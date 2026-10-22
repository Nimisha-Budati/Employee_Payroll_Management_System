from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import asin, cos, radians, sin, sqrt

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .audit import record_audit
from .models import Company, LeaveType, AuditLog, Announcement, AttendanceRecord, AttendanceSettings, ChatConversation, ChatMessage, Notification, NotificationBroadcast, UserProfile, LeaveRequest, Employee, EmployeeDocument, Holiday, WorkFromHomeRequest
from .onboarding import refresh_for_user as _refresh_onboarding
from .notifications import optional_kinds as _optional_kinds, notify_admins as _notify_admins, notify_role as _notify_role, notify_user as _notify_user
from .pagination import maybe_paginate
from .permissions import IsAdminUserRole
from .leave_policy import carry_forward as _carry_forward, leave_year_bounds as _leave_year_bounds, leave_year_label as _leave_year_label, leave_year_of as _leave_year_of, policy_settings as _leave_rules
from .serializers import LeavePolicySettingsSerializer, LeaveTypeSerializer, AuditLogSerializer, AnnouncementSerializer, NotificationBroadcastSerializer, AttendanceRecordSerializer, AttendanceSettingsSerializer, ChatConversationSerializer, ChatEmployeeSerializer, ChatMessageSerializer, EmployeeSerializer, EmployeeWriteSerializer, EmployeeDocumentSerializer, HolidaySerializer, LeaveRequestSerializer, NotificationSerializer, leave_balance_for, ProfileSerializer, WorkFromHomeSerializer
from .utils import is_admin_user as _is_admin
from workforce.services import late_minutes as _late_minutes, scheduled_start as _scheduled_start, shift_for as _shift_for


# --- LEAVE MANAGEMENT APIs ---

def _company_id(user):
    return UserProfile.objects.filter(user=user).values_list('company_id', flat=True).first()


def _company_users(company_id):
    return User.objects.filter(userprofile__company_id=company_id)


def _company_employees(company_id):
    return Employee.objects.filter(company_id=company_id)


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def company_profile(request):
    profile = UserProfile.objects.select_related('company').filter(user=request.user).first()
    if profile is None or profile.company_id is None:
        return Response({'detail': 'This account is not assigned to a company.'}, status=status.HTTP_403_FORBIDDEN)
    company = profile.company
    if request.method == 'GET':
        return Response({'name': company.name, 'email': company.email, 'phone': company.phone, 'address': company.address})
    if not _is_admin(request.user):
        return Response({'detail': 'Only company administrators can update company details.'}, status=status.HTTP_403_FORBIDDEN)
    name = str(request.data.get('name', company.name)).strip()
    email = str(request.data.get('email', company.email)).strip().lower()
    phone = str(request.data.get('phone', company.phone)).strip()
    address = str(request.data.get('address', company.address)).strip()
    if not name or len(name) > 160 or len(phone) > 20:
        return Response({'detail': 'Enter a valid company name and contact number.'}, status=status.HTTP_400_BAD_REQUEST)
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError
    try:
        validate_email(email)
    except ValidationError:
        return Response({'email': ['Enter a valid email address.']}, status=status.HTTP_400_BAD_REQUEST)
    if Company.objects.filter(email__iexact=email).exclude(pk=company.pk).exists():
        return Response({'email': ['A company with this email already exists.']}, status=status.HTTP_400_BAD_REQUEST)
    company.name, company.email, company.phone, company.address = name, email, phone, address
    company.save(update_fields=['name', 'email', 'phone', 'address'])
    return Response({'name': company.name, 'email': company.email, 'phone': company.phone, 'address': company.address})

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def leave_list_create(request):
    user = request.user
    is_admin = _is_admin(user)

    if request.method == 'GET':
        leaves = LeaveRequest.objects.select_related('employee', 'employee__employee').filter(employee__userprofile__company_id=_company_id(user))
        if not is_admin:
            leaves = leaves.filter(employee=user)
        params = request.query_params
        if params.get('status') in ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED'):
            leaves = leaves.filter(status=params['status'])
        if params.get('leave_type'):
            value = str(params['leave_type'])
            leaves = leaves.filter(policy_id=int(value)) if value.isdigit() else leaves.filter(leave_type__iexact=value)
        search = params.get('search', '').strip()
        if search and is_admin:
            leaves = leaves.filter(
                Q(employee__username__icontains=search)
                | Q(employee__employee__employee_id__icontains=search)
                | Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search)
            )
        return maybe_paginate(request, leaves.order_by('-applied_at', '-id'), LeaveRequestSerializer)

    serializer = LeaveRequestSerializer(data=request.data, context={'request': request, 'company_id': _company_id(user)})
    if serializer.is_valid():
        leave_request = serializer.save(employee=user)
        _notify_admins(
            'LEAVE',
            'New leave request',
            f'{user.username} requested {leave_request.leave_type}.',
            'admin-leave.html',
            actor=user,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def leave_balance(request):
    """Leave balance per configured leave type for the signed-in user (administrators may pass ?employee_id=<user id>)."""
    target = request.user
    requested = request.query_params.get('employee_id')
    if requested:
        if not _is_admin(request.user):
            return Response({'detail': 'You can only view your own leave balance.'}, status=status.HTTP_403_FORBIDDEN)
        target = _company_users(_company_id(request.user)).filter(pk=requested, userprofile__role='EMPLOYEE').first() if str(requested).isdigit() else None
        if target is None:
            return Response({'detail': 'Employee not found.'}, status=status.HTTP_404_NOT_FOUND)
    rules = _leave_rules(Company.objects.filter(pk=_company_id(request.user)).first())
    try:
        year = int(request.query_params.get('year') or _leave_year_of(timezone.localdate(), rules))
    except ValueError:
        return Response({'detail': 'Invalid year.'}, status=status.HTTP_400_BAD_REQUEST)
    start, end = _leave_year_bounds(year, rules)
    return Response({'year': year, 'label': _leave_year_label(year, rules), 'starts': start, 'ends': end,
                     'balances': leave_balance_for(target, year)})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def leave_cancel(request, pk):
    """An employee cancels their own pending leave request; it then no longer counts towards any balance."""
    with transaction.atomic():
        leave_req = LeaveRequest.objects.select_for_update().filter(pk=pk, employee=request.user, employee__userprofile__company_id=_company_id(request.user)).first()
        if leave_req is None:
            return Response({'detail': 'Leave request not found.'}, status=status.HTTP_404_NOT_FOUND)
        if leave_req.status != 'PENDING':
            return Response({'detail': 'Only pending leave requests can be cancelled. Contact an administrator about approved leave.'},
                            status=status.HTTP_409_CONFLICT)
        leave_req.status = 'CANCELLED'
        leave_req.save(update_fields=['status', 'updated_at'])
    _notify_admins('LEAVE', 'Leave request cancelled',
                   f'{request.user.username} cancelled a {leave_req.leave_type} request ({leave_req.start_date} to {leave_req.end_date}).',
                   'admin-leave.html', actor=request.user)
    return Response(LeaveRequestSerializer(leave_req).data)


# --- LEAVE POLICY (administrators manage; everyone can read the active types) ---

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def leave_type_list_create(request):
    from django.db.models import Count

    if request.method == 'GET':
        types = LeaveType.objects.filter(company_id=_company_id(request.user))
        if not (_is_admin(request.user) and request.query_params.get('all') == 'true'):
            types = types.filter(is_active=True)
        if _is_admin(request.user):
            types = types.annotate(request_count=Count('requests'))
        return Response(LeaveTypeSerializer(types.order_by('sort_order', 'name'), many=True).data)
    if not _is_admin(request.user):
        return Response({'detail': 'Only administrators can manage leave types.'}, status=status.HTTP_403_FORBIDDEN)
    serializer = LeaveTypeSerializer(data=request.data, context={'company_id': _company_id(request.user)})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    leave_type = serializer.save(company_id=_company_id(request.user))
    record_audit(request, 'CREATE', 'LeaveType', leave_type.pk, f'Created leave type {_describe_leave_type(leave_type)}.')
    return Response(LeaveTypeSerializer(leave_type).data, status=status.HTTP_201_CREATED)


def _describe_leave_type(leave_type):
    limit = f'{leave_type.annual_days} days/year' if leave_type.annual_days is not None else 'no limit'
    carry = f', carry forward up to {leave_type.max_carry_forward_days}' if leave_type.allow_carry_forward else ''
    return f'"{leave_type.name}" ({limit}, {"paid" if leave_type.is_paid else "unpaid"}{carry}, {"active" if leave_type.is_active else "inactive"})'


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def leave_type_detail(request, pk):
    leave_type = LeaveType.objects.filter(pk=pk, company_id=_company_id(request.user)).first()
    if leave_type is None:
        return Response({'detail': 'Leave type not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response(LeaveTypeSerializer(leave_type).data)
    if request.method == 'DELETE':
        if leave_type.requests.exists():
            return Response({'detail': 'This leave type has leave requests, so it is kept for their history. Deactivate it instead.'},
                            status=status.HTTP_409_CONFLICT)
        summary = f'Deleted leave type {_describe_leave_type(leave_type)}.'
        leave_type.delete()
        record_audit(request, 'DELETE', 'LeaveType', pk, summary)
        return Response(status=status.HTTP_204_NO_CONTENT)
    before = _describe_leave_type(leave_type)
    old_name = leave_type.name
    serializer = LeaveTypeSerializer(leave_type, data=request.data, partial=request.method == 'PATCH', context={'company_id': _company_id(request.user)})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        leave_type = serializer.save()
        if leave_type.name != old_name:   # keep the label on its requests in step with the renamed type
            LeaveRequest.objects.filter(policy=leave_type).update(leave_type=leave_type.name)
        record_audit(request, 'UPDATE', 'LeaveType', pk, f'Changed leave type {before} to {_describe_leave_type(leave_type)}.')
    return Response(LeaveTypeSerializer(leave_type).data)


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def leave_policy_settings(request):
    rules = _leave_rules(Company.objects.filter(pk=_company_id(request.user)).first())
    if request.method == 'GET':
        data = LeavePolicySettingsSerializer(rules).data
        current = _leave_year_of(timezone.localdate(), rules)
        data.update({'current_leave_year': current, 'current_leave_year_label': _leave_year_label(current, rules)})
        return Response(data)
    if not _is_admin(request.user):
        return Response({'detail': 'Only administrators can change the leave policy.'}, status=status.HTTP_403_FORBIDDEN)
    serializer = LeavePolicySettingsSerializer(rules, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    rules = serializer.save(updated_by=request.user)
    record_audit(request, 'UPDATE', 'LeavePolicy', 1,
                 f'Leave policy: year starts in month {rules.leave_year_start_month}, notice {rules.min_notice_days} day(s), '
                 f'max {rules.max_days_per_request or "no limit"} day(s) per request, past dates {"allowed" if rules.allow_past_dates else "not allowed"}.')
    return Response(LeavePolicySettingsSerializer(rules).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def leave_carry_forward(request):
    try:
        year = int(request.data.get('year'))
    except (TypeError, ValueError):
        return Response({'year': ['Enter the leave year to carry days into.']}, status=status.HTTP_400_BAD_REQUEST)
    if not 2000 <= year <= 2100:
        return Response({'year': ['Enter a valid year.']}, status=status.HTTP_400_BAD_REQUEST)
    company_id = _company_id(request.user)
    if not LeaveType.objects.filter(company_id=company_id, allow_carry_forward=True, annual_days__isnull=False).exists():
        return Response({'detail': 'No leave type allows carrying days forward. Enable it on a leave type first.'},
                        status=status.HTTP_400_BAD_REQUEST)
    written = _carry_forward(year, actor=request.user, employees=_company_users(company_id).filter(userprofile__role='EMPLOYEE', employee__isnull=False))
    record_audit(request, 'CARRY_FORWARD', 'LeavePolicy', year, f'Carried unused leave from {year - 1} into {year} ({written} balance(s)).')
    return Response({'year': year, 'balances_written': written})


@api_view(['PUT'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def leave_balance_adjust(request):
    """Administrators can add or remove days for one employee, leave type and leave year (with a note)."""
    from .models import EmployeeLeaveBalance

    company_id = _company_id(request.user)
    user = User.objects.filter(pk=request.data.get('employee_id'), userprofile__role='EMPLOYEE', userprofile__company_id=company_id).first() \
        if str(request.data.get('employee_id', '')).isdigit() else None
    leave_type = LeaveType.objects.filter(pk=request.data.get('leave_type_id'), company_id=company_id).first() \
        if str(request.data.get('leave_type_id', '')).isdigit() else None
    if user is None or leave_type is None:
        return Response({'detail': 'Employee or leave type not found.'}, status=status.HTTP_404_NOT_FOUND)
    if leave_type.annual_days is None:
        return Response({'detail': f'{leave_type.name} has no annual limit, so it has no balance to adjust.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        year = int(request.data.get('year'))
        adjustment = int(request.data.get('adjustment'))
    except (TypeError, ValueError):
        return Response({'detail': 'Enter a whole number of days and a leave year.'}, status=status.HTTP_400_BAD_REQUEST)
    if not -366 <= adjustment <= 366:
        return Response({'adjustment': ['Use between -366 and 366 days.']}, status=status.HTTP_400_BAD_REQUEST)
    note = str(request.data.get('note', '')).strip()[:255]
    if adjustment and not note:
        return Response({'note': ['Add a short reason for the adjustment.']}, status=status.HTTP_400_BAD_REQUEST)
    row, _ = EmployeeLeaveBalance.objects.get_or_create(employee=user, leave_type=leave_type, year=year)
    row.adjustment, row.note, row.updated_by = adjustment, note, request.user
    row.save()
    record_audit(request, 'ADJUST', 'LeavePolicy', row.pk,
                 f'Set {leave_type.name} adjustment for {user.username} in {year} to {adjustment:+d} day(s): {note or "no note"}.',
                 subject=user)
    return Response({'year': year, 'balances': leave_balance_for(user, year)})


@api_view(['PUT'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def leave_update_status(request, pk):
    with transaction.atomic():
        leave_req = LeaveRequest.objects.select_for_update().select_related('employee').filter(pk=pk, employee__userprofile__company_id=_company_id(request.user)).first()
        if leave_req is None:
            return Response({'detail': 'Leave request not found.'}, status=status.HTTP_404_NOT_FOUND)
        if leave_req.status != 'PENDING':
            return Response({'detail': 'This leave request has already been processed.'}, status=status.HTTP_400_BAD_REQUEST)

        new_status = request.data.get('status')
        if new_status not in ['APPROVED', 'REJECTED']:
            return Response({'detail': 'Status must be APPROVED or REJECTED.'}, status=status.HTTP_400_BAD_REQUEST)

        leave_req.status = new_status
        if new_status == 'REJECTED':
            leave_req.rejection_reason = str(request.data.get('rejection_reason', '')).strip()
        else:
            leave_req.rejection_reason = ''
        leave_req.save()
        record_audit(request, 'APPROVE' if new_status == 'APPROVED' else 'REJECT', 'Leave', leave_req.pk,
                     f'{new_status.title()} {leave_req.leave_type} for {leave_req.employee.username} '
                     f'({leave_req.start_date} to {leave_req.end_date}, {leave_req.number_of_days} day(s)).',
                     subject=leave_req.employee)

    decision = 'approved' if new_status == 'APPROVED' else 'rejected'
    detail = f' Reason: {leave_req.rejection_reason}' if leave_req.rejection_reason else ''
    _notify_user(
        leave_req.employee,
        'LEAVE',
        f'Leave request {decision}',
        f'Your {leave_req.leave_type} request was {decision}.{detail}',
        'employee-leave.html',
        actor=request.user,
    )
    return Response(LeaveRequestSerializer(leave_req).data, status=status.HTTP_200_OK)


# --- EMPLOYEE MANAGEMENT APIs ---

def _employee_queryset(user=None):
    employees = Employee.objects.select_related('user', 'user__salary_structure')
    return employees.filter(company_id=_company_id(user)) if user is not None else employees.none()


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def employee_list_create(request):
    if request.method == 'GET':
        employees = _employee_queryset(request.user).order_by('employee_id')
        params = request.query_params
        if params.get('status') in ('ACTIVE', 'INACTIVE'):
            employees = employees.filter(status=params['status'])
        if params.get('department'):
            employees = employees.filter(department__iexact=params['department'])
        search = params.get('search', '').strip()
        if search:
            employees = employees.filter(
                Q(employee_id__icontains=search)
                | Q(user__username__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__email__icontains=search)
                | Q(department__icontains=search)
                | Q(designation__icontains=search)
            )
        ordering = params.get('ordering', 'employee_id')
        allowed = {'employee_id': 'employee_id', 'name': 'user__first_name', 'department': 'department',
                   'joining_date': 'joining_date', 'status': 'status'}
        key = allowed.get(ordering.lstrip('-'))
        if key:
            employees = employees.order_by(('-' if ordering.startswith('-') else '') + key, 'employee_id')
        return maybe_paginate(request, employees, EmployeeSerializer)

    company_id = _company_id(request.user)
    if company_id is None:
        return Response({'detail': 'Assign the administrator to a company before adding employees.'}, status=status.HTTP_403_FORBIDDEN)
    serializer = EmployeeWriteSerializer(data=request.data, context={'company_id': company_id})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data

    with transaction.atomic():
        user = data.get('existing_user')
        if user is None:
            user = User.objects.create_user(
                username=data['username'],
                email=data['email'],
                password=data['password'],
                first_name=data.get('first_name', ''),
                last_name=data.get('last_name', ''),
            )
            UserProfile.objects.create(user=user, role='EMPLOYEE', phone=data['phone'], company_id=company_id)
        else:
            updates = []
            for field in ('first_name', 'last_name'):
                if field in data:
                    setattr(user, field, data[field])
                    updates.append(field)
            if updates:
                user.save(update_fields=updates)
            UserProfile.objects.filter(user=user).update(phone=data['phone'], company_id=company_id)
        employee = Employee.objects.create(
            user=user,
            company_id=company_id,
            employee_id=data['employee_id'],
            phone=data['phone'],
            department=data['department'],
            designation=data['designation'],
            joining_date=data['joining_date'],
        )
        record_audit(request, 'CREATE', 'Employee', employee.pk, f'Added employee {employee.employee_id} ({user.username}).', subject=user)

    _notify_user(
        user,
        'EMPLOYEE',
        'Welcome to PayrollPro',
        'Your employee record is ready. Your dashboard shows the onboarding checklist of details and documents to provide.',
        'employee-dashboard.html',
        actor=request.user,
    )
    employee = _employee_queryset(request.user).get(pk=employee.pk)
    return Response(EmployeeSerializer(employee).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def employee_meta(request):
    """Departments in use and self-registered accounts still waiting for an employee record."""
    company_id = _company_id(request.user)
    departments = list(_company_employees(company_id).order_by('department').values_list('department', flat=True).distinct())
    pending = User.objects.filter(
        userprofile__role='EMPLOYEE', employee__isnull=True, is_active=True,
    ).filter(
        Q(userprofile__company_id=company_id) | Q(userprofile__company__isnull=True)
    ).order_by('username')
    return Response({
        'departments': departments,
        'pending_accounts': [
            {'user_id': user.pk, 'username': user.username, 'email': user.email,
             'full_name': user.get_full_name() or user.username, 'date_joined': user.date_joined}
            for user in pending
        ],
    })


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def employee_detail(request, pk):
    employee = _employee_queryset(request.user).filter(pk=pk).first()
    if employee is None:
        return Response({'detail': 'Employee not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(EmployeeSerializer(employee).data)

    if request.method == 'DELETE':
        if employee.user_id == request.user.pk:
            return Response({'detail': 'You cannot deactivate your own account.'}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            employee.user.is_active = False
            employee.user.save(update_fields=['is_active'])
            employee.status = 'INACTIVE'
            employee.deactivated_at = timezone.localdate()
            employee.save(update_fields=['status', 'deactivated_at'])
            record_audit(request, 'DEACTIVATE', 'Employee', employee.pk, f'Deactivated employee {employee.employee_id}.', subject=employee.user)
        return Response({'detail': 'Employee deactivated.'})

    serializer = EmployeeWriteSerializer(employee, data=request.data, partial=True, context={'company_id': _company_id(request.user)})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    if employee.user_id == request.user.pk and data.get('status') == 'INACTIVE':
        return Response({'status': ['You cannot deactivate your own account.']}, status=status.HTTP_400_BAD_REQUEST)

    changed = []
    with transaction.atomic():
        user = employee.user
        for field in ('first_name', 'last_name', 'email'):
            if field in data and getattr(user, field) != data[field]:
                setattr(user, field, data[field])
                changed.append(field)
        for field in ('employee_id', 'phone', 'department', 'designation', 'joining_date', 'status'):
            if field in data and getattr(employee, field) != data[field]:
                setattr(employee, field, data[field])
                changed.append(field)
        if 'status' in data:
            user.is_active = data['status'] == 'ACTIVE'
            if 'status' in changed:
                employee.deactivated_at = None if data['status'] == 'ACTIVE' else timezone.localdate()
        user.save()
        employee.save()
        if 'phone' in data:
            UserProfile.objects.filter(user=user).update(phone=data['phone'])
        if changed:
            action = 'UPDATE'
            if 'status' in changed:
                action = 'REACTIVATE' if data['status'] == 'ACTIVE' else 'DEACTIVATE'
            record_audit(request, action, 'Employee', employee.pk,
                         f'Updated {employee.employee_id}: {", ".join(sorted(set(changed)))}.', subject=user)
    _refresh_onboarding(employee.user)
    return Response(EmployeeSerializer(_employee_queryset(request.user).get(pk=pk)).data)


# --- DOCUMENT MANAGEMENT APIs ---

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def document_list_create(request):
    if request.method == 'GET':
        documents = EmployeeDocument.objects.select_related('employee').filter(employee__userprofile__company_id=_company_id(request.user))
        params = request.query_params
        if not _is_admin(request.user):
            documents = documents.filter(employee=request.user)
        else:
            search = params.get('search', '').strip()
            if search:
                documents = documents.filter(
                    Q(title__icontains=search) | Q(custom_document_type__icontains=search)
                    | Q(employee__username__icontains=search) | Q(employee__first_name__icontains=search)
                    | Q(employee__last_name__icontains=search) | Q(employee__employee__employee_id__icontains=search)
                )
        if params.get('status') in ('PENDING', 'VERIFIED', 'REJECTED'):
            documents = documents.filter(status=params['status'])
        if params.get('document_type') in dict(EmployeeDocument.DOCUMENT_TYPES):
            documents = documents.filter(document_type=params['document_type'])
        expiry = params.get('expiry')
        ordering = ('-uploaded_at',)
        if expiry in ('EXPIRED', 'EXPIRING', 'VALID', 'NONE', 'TRACKED'):
            today = timezone.localdate()
            soon = today + timedelta(days=_reminder_settings(request.user).warning_window_days)
            documents = {
                'EXPIRED': documents.filter(expiry_date__lt=today),
                'EXPIRING': documents.filter(expiry_date__gte=today, expiry_date__lte=soon),
                'VALID': documents.filter(expiry_date__gt=soon),
                'NONE': documents.filter(expiry_date__isnull=True),
                'TRACKED': documents.filter(expiry_date__isnull=False),
            }[expiry]
            if expiry != 'NONE':
                ordering = ('expiry_date', '-uploaded_at')
        serializer = EmployeeDocumentSerializer(documents.order_by(*ordering), many=True, context={'request': request})
        return Response(serializer.data)

    if _is_admin(request.user):
        return Response({'detail': 'Administrators review employee documents; they cannot upload them here.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = EmployeeDocumentSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        document = serializer.save(employee=request.user)
        _notify_admins(
            'DOCUMENT',
            'Document awaiting review',
            f'{request.user.username} uploaded {document.title}.',
            'admin-documents.html',
            actor=request.user,
        )
        _refresh_onboarding(request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def document_file(request, pk):
    """Stream a private document to its owner or an administrator."""
    document = EmployeeDocument.objects.filter(pk=pk, employee__userprofile__company_id=_company_id(request.user)).first()
    if document is None or not (_is_admin(request.user) or document.employee_id == request.user.pk):
        raise Http404
    try:
        handle = document.file.open('rb')
    except FileNotFoundError:
        raise Http404
    response = FileResponse(handle, as_attachment=False)
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def document_delete(request, pk):
    try:
        document = EmployeeDocument.objects.get(pk=pk, employee=request.user, employee__userprofile__company_id=_company_id(request.user))
    except EmployeeDocument.DoesNotExist:
        return Response({'detail': 'Document not found.'}, status=status.HTTP_404_NOT_FOUND)

    if document.status != 'PENDING':
        return Response({'detail': 'Only documents awaiting review can be deleted.'}, status=status.HTTP_400_BAD_REQUEST)
    document.file.delete(save=False)
    document.delete()
    _refresh_onboarding(request.user)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['PUT'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def document_review(request, pk):
    try:
        document = EmployeeDocument.objects.select_related('employee').get(pk=pk, employee__userprofile__company_id=_company_id(request.user))
    except EmployeeDocument.DoesNotExist:
        return Response({'detail': 'Document not found.'}, status=status.HTTP_404_NOT_FOUND)

    new_status = request.data.get('status')
    if new_status not in ['VERIFIED', 'REJECTED']:
        return Response({'detail': 'Status must be VERIFIED or REJECTED.'}, status=status.HTTP_400_BAD_REQUEST)
    if new_status == 'REJECTED' and not str(request.data.get('review_note', '')).strip():
        return Response({'detail': 'A rejection reason is required.'}, status=status.HTTP_400_BAD_REQUEST)

    if 'expiry_date' in request.data:
        expiry, error = _parse_expiry(request.data.get('expiry_date'))
        if error:
            return Response({'expiry_date': [error]}, status=status.HTTP_400_BAD_REQUEST)
        document.expiry_date = expiry
    document.status = new_status
    document.review_note = str(request.data.get('review_note', '')).strip()
    document.save()
    record_audit(request, 'VERIFY' if new_status == 'VERIFIED' else 'REJECT', 'Document', document.pk,
                 f'{new_status.title()} document "{document.title}" of {document.employee.username}'
                 f'{f" (expires {document.expiry_date})" if document.expiry_date else ""}.', subject=document.employee)
    _refresh_onboarding(document.employee)
    review_message = f'Your document “{document.title}” was {new_status.lower()}.'
    if document.review_note:
        review_message += f' Note: {document.review_note}'
    _notify_user(
        document.employee,
        'DOCUMENT',
        'Document review complete',
        review_message,
        'employee-documents.html',
        actor=request.user,
    )
    return Response(EmployeeDocumentSerializer(document, context={'request': request}).data)


def _reminder_settings(user=None):
    from .models import ReminderSettings

    return ReminderSettings.load(Company.objects.filter(pk=_company_id(user)).first() if user else None)


def _parse_expiry(value):
    """(date or None, error message or None) for an expiry date sent by an administrator."""
    if value in (None, ''):
        return None, None
    parsed = parse_date(str(value))
    if parsed is None:
        return None, 'Use YYYY-MM-DD.'
    return parsed, None


@api_view(['PUT'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def document_expiry(request, pk):
    """Set, change or clear a document's expiry date (the review status is not affected)."""
    document = EmployeeDocument.objects.select_related('employee').filter(pk=pk, employee__userprofile__company_id=_company_id(request.user)).first()
    if document is None:
        return Response({'detail': 'Document not found.'}, status=status.HTTP_404_NOT_FOUND)
    expiry, error = _parse_expiry(request.data.get('expiry_date'))
    if error:
        return Response({'expiry_date': [error]}, status=status.HTTP_400_BAD_REQUEST)
    before = document.expiry_date
    document.expiry_date = expiry
    document.save(update_fields=['expiry_date', 'updated_at'])
    record_audit(request, 'UPDATE', 'Document', document.pk,
                 f'Changed expiry of "{document.title}" ({document.employee.username}) from {before or "none"} to {expiry or "none"}.',
                 subject=document.employee)
    _refresh_onboarding(document.employee)
    return Response(EmployeeDocumentSerializer(document, context={'request': request}).data)


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def my_profile(request):
    profile, _ = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={'role': 'ADMIN' if request.user.is_staff or request.user.is_superuser else 'EMPLOYEE'},
    )
    if request.method == 'GET':
        return Response(ProfileSerializer(profile, context={'request': request}).data)

    serializer = ProfileSerializer(profile, data=request.data, partial=True, context={'request': request})
    if serializer.is_valid():
        serializer.save()
        _refresh_onboarding(request.user)
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# --- HOLIDAY CALENDAR APIs ---

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def holiday_list_create(request):
    if request.method == 'GET':
        return Response(HolidaySerializer(Holiday.objects.filter(company_id=_company_id(request.user)), many=True).data)

    if not _is_admin(request.user):
        return Response({'detail': 'Only administrators can manage holidays.'}, status=status.HTTP_403_FORBIDDEN)
    serializer = HolidaySerializer(data=request.data)
    if serializer.is_valid():
        holiday = serializer.save(company_id=_company_id(request.user))
        record_audit(request, 'CREATE', 'Holiday', holiday.pk, f'Added holiday {holiday.name} on {holiday.date}.')
        _notify_role(
            'EMPLOYEE',
            'HOLIDAY',
            'Holiday added',
            f'{holiday.name} is scheduled for {holiday.date}.',
            'employee-holidays.html',
            actor=request.user,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def holiday_detail(request, pk):
    try:
        holiday = Holiday.objects.get(pk=pk, company_id=_company_id(request.user))
    except Holiday.DoesNotExist:
        return Response({'detail': 'Holiday not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'DELETE':
        record_audit(request, 'DELETE', 'Holiday', holiday.pk, f'Removed holiday {holiday.name} on {holiday.date}.')
        _notify_role(
            'EMPLOYEE',
            'HOLIDAY',
            'Holiday removed',
            f'{holiday.name} on {holiday.date} was removed from the calendar.',
            'employee-holidays.html',
            actor=request.user,
        )
        holiday.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = HolidaySerializer(holiday, data=request.data)
    if serializer.is_valid():
        holiday = serializer.save()
        record_audit(request, 'UPDATE', 'Holiday', holiday.pk, f'Updated holiday {holiday.name} on {holiday.date}.')
        _notify_role(
            'EMPLOYEE',
            'HOLIDAY',
            'Holiday updated',
            f'{holiday.name} is scheduled for {holiday.date}.',
            'employee-holidays.html',
            actor=request.user,
        )
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# --- LOCATION-BASED ATTENDANCE APIs ---

def _attendance_settings(user):
    company_id = _company_id(user)
    settings, _ = AttendanceSettings.objects.get_or_create(company_id=company_id)
    return settings


def _distance_in_meters(latitude_one, longitude_one, latitude_two, longitude_two):
    earth_radius = 6371000
    latitude_delta = radians(float(latitude_two) - float(latitude_one))
    longitude_delta = radians(float(longitude_two) - float(longitude_one))
    a = sin(latitude_delta / 2) ** 2 + cos(radians(float(latitude_one))) * cos(radians(float(latitude_two))) * sin(longitude_delta / 2) ** 2
    return round(2 * earth_radius * asin(sqrt(a)))


def _provided_location(data):
    try:
        latitude = float(data.get('latitude'))
        longitude = float(data.get('longitude'))
    except (TypeError, ValueError):
        return None, None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None, None
    return latitude, longitude


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def attendance_settings(request):
    settings = _attendance_settings(request.user)
    if request.method == 'GET':
        return Response(AttendanceSettingsSerializer(settings).data)
    serializer = AttendanceSettingsSerializer(settings, data=request.data)
    if serializer.is_valid():
        saved = serializer.save()
        record_audit(request, 'UPDATE', 'AttendanceSettings', 1,
                     f'Office location set to {saved.latitude}, {saved.longitude} (radius {saved.radius_meters} m, '
                     f'{"enabled" if saved.is_enabled else "disabled"}).')
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def attendance_status(request):
    settings = _attendance_settings(request.user)
    today = timezone.localdate()
    record = AttendanceRecord.objects.filter(employee=request.user, date=today).first()
    return Response({
        'date': today,
        'attendance_enabled': settings.is_enabled and settings.latitude is not None and settings.longitude is not None,
        'radius_meters': settings.radius_meters,
        'record': AttendanceRecordSerializer(record).data if record else None,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def attendance_mark(request, action):
    if _is_admin(request.user):
        return Response({'detail': 'Administrators cannot mark employee attendance.'}, status=status.HTTP_403_FORBIDDEN)
    if action not in ('check-in', 'check-out'):
        return Response({'detail': 'Unsupported attendance action.'}, status=status.HTTP_400_BAD_REQUEST)
    settings = _attendance_settings(request.user)
    if not settings.is_enabled or settings.latitude is None or settings.longitude is None:
        return Response({'detail': 'Attendance has not been configured by an administrator.'}, status=status.HTTP_409_CONFLICT)

    latitude, longitude = _provided_location(request.data)
    if latitude is None:
        return Response({'detail': 'A valid GPS location is required.'}, status=status.HTTP_400_BAD_REQUEST)
    distance = _distance_in_meters(settings.latitude, settings.longitude, latitude, longitude)
    if distance > settings.radius_meters:
        return Response({'detail': f'You are {distance} m from the office. You must be within {settings.radius_meters} m to mark attendance.'}, status=status.HTTP_403_FORBIDDEN)

    today = timezone.localdate()
    record, created = AttendanceRecord.objects.get_or_create(employee=request.user, date=today)
    now = timezone.now()
    if action == 'check-in':
        if record.check_in_at:
            return Response({'detail': 'You have already checked in today.'}, status=status.HTTP_409_CONFLICT)
        record.check_in_at = now
        record.check_in_latitude = latitude
        record.check_in_longitude = longitude
        record.check_in_distance_meters = distance
        shift = _shift_for(request.user, today)
        if shift is not None:
            record.shift = shift
            record.shift_name = shift.name
            record.scheduled_start = _scheduled_start(shift, today)
            record.late_minutes = _late_minutes(shift, today, now)
    else:
        if not record.check_in_at:
            if created:
                record.delete()
            return Response({'detail': 'Check in before checking out.'}, status=status.HTTP_409_CONFLICT)
        if record.check_out_at:
            return Response({'detail': 'You have already checked out today.'}, status=status.HTTP_409_CONFLICT)
        record.check_out_at = now
        record.check_out_latitude = latitude
        record.check_out_longitude = longitude
        record.check_out_distance_meters = distance
    record.save()
    action_name = 'checked in' if action == 'check-in' else 'checked out'
    late_note = f' ({record.late_minutes} min late)' if action == 'check-in' and record.late_minutes else ''
    _notify_admins(
        'ATTENDANCE',
        'Employee attendance updated',
        f'{request.user.username} {action_name}{late_note}.',
        'admin-attendance.html',
        actor=request.user,
    )
    return Response(AttendanceRecordSerializer(record).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def attendance_list(request):
    records = AttendanceRecord.objects.select_related('employee', 'employee__employee').filter(employee__userprofile__company_id=_company_id(request.user))
    params = request.query_params
    for param, lookup in (('date', 'date'), ('from', 'date__gte'), ('to', 'date__lte')):
        if params.get(param):
            parsed = parse_date(params[param])
            if parsed is None:
                return Response({'detail': f'Invalid {param} date. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
            records = records.filter(**{lookup: parsed})
    search = params.get('search', '').strip()
    if search:
        records = records.filter(
            Q(employee__username__icontains=search)
            | Q(employee__first_name__icontains=search)
            | Q(employee__last_name__icontains=search)
            | Q(employee__employee__employee_id__icontains=search)
        )
    if params.get('department'):
        records = records.filter(employee__employee__department__iexact=params['department'])
    if params.get('employee'):
        records = records.filter(employee_id=params['employee']) if str(params['employee']).isdigit() else records.none()
    if params.get('late') == 'true':
        records = records.filter(late_minutes__gt=0)
    elif params.get('late') == 'false':
        records = records.filter(Q(late_minutes=0) | Q(late_minutes__isnull=True))
    if params.get('summary') == 'true':
        return Response(attendance_summary_rows(records))
    return maybe_paginate(request, records, AttendanceRecordSerializer)


def attendance_summary_rows(records):
    """Per-employee totals for filtered records: days present, late days, late minutes and time worked."""
    from django.db.models import Avg, Count, Sum

    rows = (
        records.order_by()
        .values('employee_id', 'employee__username', 'employee__first_name', 'employee__last_name',
                'employee__employee__employee_id', 'employee__employee__department')
        .annotate(
            days_present=Count('id', filter=Q(check_in_at__isnull=False)),
            late_days=Count('id', filter=Q(late_minutes__gt=0)),
            total_late=Sum('late_minutes'),
            average_late=Avg('late_minutes', filter=Q(late_minutes__gt=0)),
        )
        .order_by('employee__employee__employee_id', 'employee__username')
    )
    worked = {}
    for employee_id, check_in, check_out in records.filter(
        check_in_at__isnull=False, check_out_at__isnull=False,
    ).values_list('employee_id', 'check_in_at', 'check_out_at'):
        worked[employee_id] = worked.get(employee_id, 0) + max(0, (check_out - check_in).total_seconds() / 60)
    result = []
    for row in rows:
        name = f"{row['employee__first_name']} {row['employee__last_name']}".strip() or row['employee__username']
        result.append({
            'employee_user_id': row['employee_id'],
            'employee_code': row['employee__employee__employee_id'] or '',
            'employee_name': name,
            'department': row['employee__employee__department'] or '',
            'days_present': row['days_present'],
            'late_days': row['late_days'],
            'late_minutes': row['total_late'] or 0,
            'average_late_minutes': int(Decimal(str(row['average_late'] or 0)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)),
            'worked_minutes': round(worked.get(row['employee_id'], 0)),
        })
    totals = {
        'employees': len(result),
        'records': sum(item['days_present'] for item in result),
        'late_days': sum(item['late_days'] for item in result),
        'late_minutes': sum(item['late_minutes'] for item in result),
        'worked_minutes': sum(item['worked_minutes'] for item in result),
    }
    return {'employees': result, 'totals': totals}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def attendance_history(request):
    try:
        limit = min(max(int(request.query_params.get('limit', 14)), 1), 90)
    except ValueError:
        limit = 14
    records = AttendanceRecord.objects.filter(employee=request.user, employee__userprofile__company_id=_company_id(request.user)).select_related('employee')[:limit]
    return Response(AttendanceRecordSerializer(records, many=True).data)


# --- WORK FROM HOME APIs ---

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def wfh_list_create(request):
    if request.method == 'GET':
        admin = _is_admin(request.user)
        requests = WorkFromHomeRequest.objects.select_related('employee').filter(employee__userprofile__company_id=_company_id(request.user)) if admin else WorkFromHomeRequest.objects.filter(employee=request.user)
        selected_status = request.query_params.get('status')
        if selected_status:
            requests = requests.filter(status=selected_status)
        search = request.query_params.get('search', '').strip()
        if admin and search:
            requests = requests.filter(
                Q(employee__username__icontains=search) | Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search) | Q(employee__employee__employee_id__icontains=search)
            )
        return Response(WorkFromHomeSerializer(requests, many=True).data)
    if _is_admin(request.user):
        return Response({'detail': 'Administrators can review WFH requests but cannot create them.'}, status=status.HTTP_403_FORBIDDEN)
    serializer = WorkFromHomeSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        work_request = serializer.save(employee=request.user)
        _notify_admins(
            'WFH',
            'New work-from-home request',
            f'{request.user.username} requested remote work from {work_request.start_date} to {work_request.end_date}.',
            'admin-wfh.html',
            actor=request.user,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def wfh_detail(request, pk):
    try:
        item = WorkFromHomeRequest.objects.get(pk=pk, employee__userprofile__company_id=_company_id(request.user))
    except WorkFromHomeRequest.DoesNotExist:
        return Response({'detail': 'WFH request not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'DELETE':
        if item.employee != request.user or item.status != 'PENDING':
            return Response({'detail': 'Only your pending WFH requests can be cancelled.'}, status=status.HTTP_403_FORBIDDEN)
        item.status = 'CANCELLED'; item.save(update_fields=['status', 'updated_at'])
        _notify_admins(
            'WFH',
            'Work-from-home request cancelled',
            f'{request.user.username} cancelled a request for {item.start_date} to {item.end_date}.',
            'admin-wfh.html',
            actor=request.user,
        )
        return Response(WorkFromHomeSerializer(item).data)
    if not _is_admin(request.user):
        return Response({'detail': 'Only administrators can review WFH requests.'}, status=status.HTTP_403_FORBIDDEN)
    if item.status != 'PENDING':
        return Response({'detail': 'This WFH request has already been processed.'}, status=status.HTTP_400_BAD_REQUEST)
    new_status = request.data.get('status')
    if new_status not in ['APPROVED', 'REJECTED']:
        return Response({'detail': 'Status must be APPROVED or REJECTED.'}, status=status.HTTP_400_BAD_REQUEST)
    note = str(request.data.get('admin_note', '')).strip()
    if new_status == 'REJECTED' and not note:
        return Response({'detail': 'A note is required when rejecting a WFH request.'}, status=status.HTTP_400_BAD_REQUEST)
    item.status, item.admin_note = new_status, note
    item.save()
    record_audit(request, 'APPROVE' if new_status == 'APPROVED' else 'REJECT', 'WFH', item.pk,
                 f'{new_status.title()} WFH for {item.employee.username} ({item.start_date} to {item.end_date}).',
                 subject=item.employee)
    _notify_user(
        item.employee,
        'WFH',
        f'Work-from-home request {new_status.lower()}',
        f'Your request for {item.start_date} to {item.end_date} was {new_status.lower()}.{f" Note: {note}" if note else ""}',
        'employee-wfh.html',
        actor=request.user,
    )
    return Response(WorkFromHomeSerializer(item).data)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def announcement_list_create(request):
    if request.method == 'GET':
        announcements = Announcement.objects.select_related('created_by').filter(company_id=_company_id(request.user))
        return Response(AnnouncementSerializer(announcements, many=True).data)

    if not _is_admin(request.user):
        return Response({'detail': 'Only administrators can publish announcements.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = AnnouncementSerializer(data=request.data)
    if serializer.is_valid():
        announcement = serializer.save(created_by=request.user, company_id=_company_id(request.user))
        record_audit(request, 'CREATE', 'Announcement', announcement.pk, f'Published announcement "{announcement.title}".')
        _notify_role(
            'EMPLOYEE',
            'ANNOUNCEMENT',
            'New company announcement',
            f'{announcement.title}: {announcement.message[:200]}',
            'announcements.html',
            actor=request.user,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def announcement_detail(request, pk):
    try:
        announcement = Announcement.objects.get(pk=pk, company_id=_company_id(request.user))
    except Announcement.DoesNotExist:
        return Response({'detail': 'Announcement not found.'}, status=status.HTTP_404_NOT_FOUND)

    record_audit(request, 'DELETE', 'Announcement', announcement.pk, f'Deleted announcement "{announcement.title}".')
    announcement.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def chat_employee_list(request):
    employees = UserProfile.objects.select_related('user', 'user__employee').filter(
        role='EMPLOYEE',
        company_id=_company_id(request.user),
        user__is_active=True,
    ).order_by('user__username')
    return Response(ChatEmployeeSerializer(employees, many=True).data)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def chat_conversation_list_create(request):
    if request.method == 'GET':
        if _is_admin(request.user):
            conversations = ChatConversation.objects.filter(administrator=request.user, employee__userprofile__company_id=_company_id(request.user))
        elif UserProfile.objects.filter(user=request.user, role='EMPLOYEE').exists():
            conversations = ChatConversation.objects.filter(employee=request.user)
        else:
            return Response({'detail': 'Chat is available to employees and administrators.'}, status=status.HTTP_403_FORBIDDEN)
        conversations = conversations.select_related('administrator', 'employee')
        return Response(ChatConversationSerializer(conversations, many=True, context={'request': request}).data)

    if not _is_admin(request.user):
        return Response({'detail': 'Only administrators can start conversations.'}, status=status.HTTP_403_FORBIDDEN)
    try:
        employee_user_id = int(request.data.get('employee_id'))
    except (ValueError, TypeError):
        return Response({'detail': 'Active employee not found.'}, status=status.HTTP_404_NOT_FOUND)
    employee_profile = UserProfile.objects.select_related('user').filter(
        user_id=employee_user_id, company_id=_company_id(request.user),
        role='EMPLOYEE',
        user__is_active=True,
    ).first()
    if employee_profile is None:
        return Response({'detail': 'Active employee not found.'}, status=status.HTTP_404_NOT_FOUND)

    conversation, created = ChatConversation.objects.get_or_create(
        administrator=request.user,
        employee=employee_profile.user,
    )
    if created:
        _notify_user(
            employee_profile.user,
            'CHAT',
            'New private conversation',
            f'{request.user.get_full_name() or request.user.username} started a conversation with you.',
            f'chat.html?conversation={conversation.id}',
            actor=request.user,
        )
    response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return Response(
        ChatConversationSerializer(conversation, context={'request': request}).data,
        status=response_status,
    )


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def chat_message_list_create(request, conversation_id):
    try:
        conversation = ChatConversation.objects.select_related('administrator', 'employee').get(pk=conversation_id, employee__userprofile__company_id=_company_id(request.user))
    except ChatConversation.DoesNotExist:
        return Response({'detail': 'Conversation not found.'}, status=status.HTTP_404_NOT_FOUND)

    is_admin_participant = _is_admin(request.user) and conversation.administrator_id == request.user.id
    is_employee_participant = (
        UserProfile.objects.filter(user=request.user, role='EMPLOYEE').exists()
        and conversation.employee_id == request.user.id
    )
    if not (is_admin_participant or is_employee_participant):
        return Response({'detail': 'Conversation not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        conversation.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True)
        messages = conversation.messages.select_related('sender').all()
        return Response(ChatMessageSerializer(messages, many=True, context={'request': request}).data)

    body = request.data.get('body', '')
    if not isinstance(body, str) or not body.strip():
        return Response({'body': ['Message cannot be empty.']}, status=status.HTTP_400_BAD_REQUEST)
    if len(body.strip()) > 4000:
        return Response({'body': ['Message must be 4000 characters or fewer.']}, status=status.HTTP_400_BAD_REQUEST)

    message = ChatMessage.objects.create(
        conversation=conversation,
        sender=request.user,
        body=body.strip(),
    )
    conversation.save(update_fields=['updated_at'])
    recipient = conversation.employee if is_admin_participant else conversation.administrator
    sender_name = request.user.get_full_name() or request.user.username
    _notify_user(
        recipient,
        'CHAT',
        f'New message from {sender_name}',
        body.strip()[:240],
        f'chat.html?conversation={conversation.id}',
        actor=request.user,
    )
    return Response(
        ChatMessageSerializer(message, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )


def _visible_notifications(user):
    return Notification.objects.filter(recipient=user).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()),
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_list(request):
    visible = _visible_notifications(request.user)
    notifications = visible.select_related('actor')
    if request.query_params.get('unread') == 'true':
        notifications = notifications.filter(read_at__isnull=True)
    if request.query_params.get('kind') in dict(Notification.KIND_CHOICES):
        notifications = notifications.filter(kind=request.query_params['kind'])
    unread = visible.filter(read_at__isnull=True)
    return Response({
        'unread_count': unread.count(),
        'unread_by_kind': {row['kind']: row['n'] for row in unread.order_by().values('kind').annotate(n=Count('id'))},
        'notifications': NotificationSerializer(notifications[:100], many=True).data,
    })


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def notification_preferences(request):
    """Optional notification kinds a user can switch off. Security and other mandatory kinds are always on."""
    from .models import NotificationPreference

    optional = dict(_optional_kinds())
    if request.method == 'PUT':
        values = request.data.get('preferences')
        if not isinstance(values, dict) or not values:
            return Response({'preferences': ['Send {kind: true|false} pairs.']}, status=status.HTTP_400_BAD_REQUEST)
        mandatory = [kind for kind in values if kind in Notification.MANDATORY_KINDS]
        if mandatory:
            return Response({'preferences': [f'{", ".join(mandatory)} notifications cannot be switched off.']}, status=status.HTTP_400_BAD_REQUEST)
        unknown = [kind for kind in values if kind not in optional]
        if unknown or not all(isinstance(value, bool) for value in values.values()):
            return Response({'preferences': ['Unknown notification type or a value that is not true/false.']}, status=status.HTTP_400_BAD_REQUEST)
        for kind, enabled in values.items():
            NotificationPreference.objects.update_or_create(user=request.user, kind=kind, defaults={'enabled': enabled})
    saved = dict(NotificationPreference.objects.filter(user=request.user).values_list('kind', 'enabled'))
    return Response({
        'optional': [{'kind': kind, 'label': label, 'enabled': saved.get(kind, True)} for kind, label in optional.items()],
        'mandatory': [{'kind': kind, 'label': dict(Notification.KIND_CHOICES)[kind]} for kind in Notification.MANDATORY_KINDS],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notification_mark_read(request, pk):
    notification = Notification.objects.filter(recipient=request.user, pk=pk).first()
    if notification is None:
        return Response({'detail': 'Notification not found.'}, status=status.HTTP_404_NOT_FOUND)
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=['read_at'])
    return Response(NotificationSerializer(notification).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notification_mark_all_read(request):
    updated = _visible_notifications(request.user).filter(read_at__isnull=True).update(read_at=timezone.now())
    return Response({'updated': updated})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def notification_broadcast_list_create(request):
    """Notifications an administrator sends to all employees, a department or chosen employees, with an optional expiry."""
    from django.db.models import Count

    if request.method == 'GET':
        broadcasts = NotificationBroadcast.objects.filter(company_id=_company_id(request.user)).select_related('created_by').annotate(
            read_count=Count('notifications', filter=Q(notifications__read_at__isnull=False)),
        )
        return maybe_paginate(request, broadcasts, NotificationBroadcastSerializer)

    serializer = NotificationBroadcastSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    recipients = User.objects.filter(is_active=True, userprofile__role='EMPLOYEE', userprofile__company_id=_company_id(request.user))
    if data['target_type'] == 'DEPARTMENT':
        recipients = recipients.filter(employee__department__iexact=data['department'], employee__status='ACTIVE')
        label = data['department']
    elif data['target_type'] == 'EMPLOYEES':
        recipients = recipients.filter(pk__in=data['employee_ids'])
        label = ', '.join(recipients.order_by('username').values_list('username', flat=True)[:10])
    else:
        label = 'All active employees'
    recipients = list(recipients.exclude(pk=request.user.pk).distinct())
    if not recipients:
        return Response({'detail': 'No active employees match this target.'}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        broadcast = NotificationBroadcast.objects.create(
            title=data['title'], message=data['message'], target_type=data['target_type'], target_label=label[:255],
            expires_at=data.get('expires_at'), recipient_count=len(recipients), created_by=request.user, company_id=_company_id(request.user),
        )
        Notification.objects.bulk_create([
            Notification(recipient=user, actor=request.user, kind='GENERAL', title=broadcast.title,
                         message=broadcast.message, target_url='notifications.html',
                         expires_at=broadcast.expires_at, broadcast=broadcast)
            for user in recipients
        ])
        record_audit(request, 'SEND', 'Notification', broadcast.pk,
                     f'Sent "{broadcast.title}" to {len(recipients)} employee(s) ({broadcast.get_target_type_display()}: {label[:80]})'
                     f'{f", expires {broadcast.expires_at:%Y-%m-%d %H:%M}" if broadcast.expires_at else ""}.')
    broadcast.read_count = 0
    return Response(NotificationBroadcastSerializer(broadcast).data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def notification_broadcast_detail(request, pk):
    broadcast = NotificationBroadcast.objects.filter(pk=pk, company_id=_company_id(request.user)).first()
    if broadcast is None:
        return Response({'detail': 'Notification not found.'}, status=status.HTTP_404_NOT_FOUND)
    record_audit(request, 'WITHDRAW', 'Notification', pk, f'Withdrew "{broadcast.title}" from {broadcast.recipient_count} employee(s).')
    broadcast.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# --- DEPARTMENTS AND DESIGNATIONS ---

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def department_list(request):
    from django.db.models import Count

    rows = Employee.objects.filter(company_id=_company_id(request.user)).values('department', 'designation').annotate(
        total=Count('id'), active=Count('id', filter=Q(status='ACTIVE')),
    ).order_by('department', 'designation')
    departments = {}
    for row in rows:
        item = departments.setdefault(row['department'], {'name': row['department'], 'headcount': 0, 'active': 0, 'designations': []})
        item['headcount'] += row['total']
        item['active'] += row['active']
        item['designations'].append({'name': row['designation'], 'headcount': row['total']})
    return Response(list(departments.values()))


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def department_rename(request):
    """Rename (or merge) a department or designation across every employee record."""
    kind = request.data.get('kind')
    old = str(request.data.get('old', '')).strip()
    new = str(request.data.get('new', '')).strip()
    if kind not in ('department', 'designation'):
        return Response({'kind': ['Choose department or designation.']}, status=status.HTTP_400_BAD_REQUEST)
    if not old or not new:
        return Response({'new': ['Enter the new name.']}, status=status.HTTP_400_BAD_REQUEST)
    if len(new) > 100:
        return Response({'new': ['Use 100 characters or fewer.']}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        updated = Employee.objects.filter(company_id=_company_id(request.user), **{f'{kind}__iexact': old}).update(**{kind: new})
        if not updated:
            return Response({'detail': f'No employees have the {kind} "{old}".'}, status=status.HTTP_404_NOT_FOUND)
        record_audit(request, 'RENAME', 'Department', '', f'Renamed {kind} "{old}" to "{new}" for {updated} employee(s).')
    return Response({'updated': updated})


# --- AUDIT LOG ---

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def audit_log_list(request):
    company_id = _company_id(request.user)
    logs = AuditLog.objects.filter(Q(actor__userprofile__company_id=company_id) | Q(subject__userprofile__company_id=company_id)).distinct()
    params = request.query_params
    if params.get('entity_type'):
        logs = logs.filter(entity_type=params['entity_type'])
    if params.get('action'):
        logs = logs.filter(action=params['action'])
    if params.get('module'):
        logs = logs.filter(module=params['module'])
    if params.get('employee'):
        value = str(params['employee'])
        logs = logs.filter(Q(subject_id=value) | Q(actor_id=value)) if value.isdigit() else logs.none()
    if params.get('actor'):
        logs = logs.filter(actor_id=params['actor']) if str(params['actor']).isdigit() else logs.none()
    for param, lookup in (('from', 'created_at__date__gte'), ('to', 'created_at__date__lte')):
        parsed = parse_date(params.get(param, '') or '')
        if parsed:
            logs = logs.filter(**{lookup: parsed})
    search = params.get('search', '').strip()
    if search:
        logs = logs.filter(Q(summary__icontains=search) | Q(actor_name__icontains=search) | Q(subject_name__icontains=search)
                           | Q(ip_address__icontains=search))
    return maybe_paginate(request, logs, AuditLogSerializer)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def audit_log_meta(request):
    """Distinct modules and actions recorded so far, for the audit filters."""
    return Response({
        'modules': sorted(filter(None, AuditLog.objects.filter(Q(actor__userprofile__company_id=_company_id(request.user)) | Q(subject__userprofile__company_id=_company_id(request.user))).order_by().values_list('module', flat=True).distinct())),
        'actions': sorted(filter(None, AuditLog.objects.filter(Q(actor__userprofile__company_id=_company_id(request.user)) | Q(subject__userprofile__company_id=_company_id(request.user))).order_by().values_list('action', flat=True).distinct())),
    })
