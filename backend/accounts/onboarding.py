"""Employee onboarding checklist.

The checklist is computed from data PayrollPro already stores (name, email, phone, department and
designation, address, profile photo, uploaded documents and the salary structure), so no extra personal
information is collected. Administrators choose which items are required (``OnboardingSettings``).

States: IN_PROGRESS (items missing) → READY (everything provided; administrators are notified once)
→ COMPLETED (an administrator reviewed and marked it complete). Completing is refused while items are missing.
"""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .audit import record_audit
from .models import Employee, EmployeeDocument, OnboardingSettings, UserProfile
from .notifications import notify_admins, notify_user
from .permissions import IsAdminUserRole

DOCUMENT_LABELS = dict(EmployeeDocument.DOCUMENT_TYPES)


def _item(key, label, owner, done, state, hint=''):
    return {'key': key, 'label': label, 'owner': owner, 'done': bool(done), 'state': state, 'hint': '' if done else hint}


def checklist(employee, settings=None, today=None):
    settings = settings or OnboardingSettings.load()
    today = today or timezone.localdate()
    user = employee.user
    profile = UserProfile.objects.filter(user=user).first()
    items = [
        _item('name', 'First and last name', 'EMPLOYEE', user.first_name.strip() and user.last_name.strip(),
              'Provided' if user.first_name and user.last_name else 'Missing', 'Add your first and last name in My profile.'),
        _item('email', 'Email address', 'EMPLOYEE', user.email, 'Provided' if user.email else 'Missing', 'Add your email address in My profile.'),
        _item('phone', 'Phone number', 'EMPLOYEE', employee.phone or (profile and profile.phone),
              'Provided' if employee.phone or (profile and profile.phone) else 'Missing', 'Add your phone number in My profile.'),
        _item('job', 'Department and designation', 'ADMIN', employee.department and employee.designation,
              'Set' if employee.department and employee.designation else 'Missing', 'An administrator sets these on the employee record.'),
    ]
    if settings.require_address:
        has_address = bool(profile and profile.address.strip())
        items.append(_item('address', 'Postal address', 'EMPLOYEE', has_address, 'Provided' if has_address else 'Missing',
                           'Add your address in My profile.'))
    if settings.require_profile_photo:
        has_photo = bool(profile and profile.profile_photo)
        items.append(_item('photo', 'Profile photo', 'EMPLOYEE', has_photo, 'Uploaded' if has_photo else 'Missing',
                           'Upload a photo in My profile.'))
    documents = list(EmployeeDocument.objects.filter(employee=user).order_by('-uploaded_at'))
    for code in settings.required_document_types:
        label = DOCUMENT_LABELS.get(code, code.title())
        of_type = [doc for doc in documents if doc.document_type == code]
        verified = [doc for doc in of_type if doc.status == 'VERIFIED' and not (doc.expiry_date and doc.expiry_date < today)]
        if verified:
            items.append(_item(f'doc:{code}', label, 'EMPLOYEE', True, 'Verified'))
        elif any(doc.status == 'PENDING' for doc in of_type):
            items.append(_item(f'doc:{code}', label, 'ADMIN', False, 'Uploaded, awaiting review', 'An administrator needs to verify the uploaded document.'))
        elif any(doc.status == 'VERIFIED' for doc in of_type):
            items.append(_item(f'doc:{code}', label, 'EMPLOYEE', False, 'Expired', f'Upload a current {label.lower()} in Documents.'))
        elif of_type:
            items.append(_item(f'doc:{code}', label, 'EMPLOYEE', False, 'Rejected', f'Upload a new {label.lower()} in Documents.'))
        else:
            items.append(_item(f'doc:{code}', label, 'EMPLOYEE', False, 'Not uploaded', f'Upload your {label.lower()} in Documents.'))
    if settings.require_salary_structure:
        from payroll.models import SalaryStructure

        has_structure = SalaryStructure.objects.filter(employee=user).exists()
        items.append(_item('salary', 'Salary structure', 'ADMIN', has_structure, 'Configured' if has_structure else 'Not set',
                           'An administrator sets the salary structure.'))
    return items


def summary(employee, settings=None):
    items = checklist(employee, settings)
    done = sum(1 for item in items if item['done'])
    complete = done == len(items)
    if employee.onboarding_status == Employee.ONBOARDING_COMPLETED:
        state = 'COMPLETED'
    else:
        state = 'READY' if complete else 'IN_PROGRESS'
    return {
        'employee_pk': employee.pk,
        'employee_user_id': employee.user_id,
        'employee_code': employee.employee_id,
        'employee_name': employee.user.get_full_name() or employee.user.username,
        'department': employee.department,
        'designation': employee.designation,
        'joining_date': employee.joining_date,
        'is_active': employee.status == 'ACTIVE' and employee.user.is_active,
        'state': state,
        'items': items,
        'done': done,
        'total': len(items),
        'missing': [item['label'] for item in items if not item['done']],
        'ready_at': employee.onboarding_ready_at,
        'completed_at': employee.onboarding_completed_at,
        'completed_by': (employee.onboarding_completed_by.get_full_name() or employee.onboarding_completed_by.username)
        if employee.onboarding_completed_by else '',
        'note': employee.onboarding_note,
    }


def refresh(employee, settings=None):
    """Record (and announce once) that an in-progress checklist became complete, or clear that state."""
    if employee is None or employee.onboarding_status != Employee.ONBOARDING_PENDING:
        return
    complete = all(item['done'] for item in checklist(employee, settings))
    if complete and employee.onboarding_ready_at is None:
        Employee.objects.filter(pk=employee.pk).update(onboarding_ready_at=timezone.now())
        notify_admins('ONBOARDING', 'Onboarding ready for review',
                      f'{employee.employee_id} ({employee.user.username}) has completed every onboarding item.',
                      'admin-onboarding.html')
    elif not complete and employee.onboarding_ready_at is not None:
        Employee.objects.filter(pk=employee.pk).update(onboarding_ready_at=None)


def refresh_for_user(user):
    refresh(Employee.objects.select_related('user').filter(user=user).first())


class OnboardingSettingsSerializer(serializers.ModelSerializer):
    required_document_types = serializers.ListField(
        child=serializers.ChoiceField(choices=[code for code, _ in EmployeeDocument.DOCUMENT_TYPES if code != 'OTHER']),
        allow_empty=True,
    )

    class Meta:
        model = OnboardingSettings
        fields = ['required_document_types', 'require_address', 'require_profile_photo', 'require_salary_structure', 'updated_at']
        read_only_fields = ['updated_at']

    def validate_required_document_types(self, value):
        return sorted(set(value))


def _employees():
    return Employee.objects.select_related('user', 'onboarding_completed_by')


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def onboarding_list(request):
    params = request.query_params
    settings = OnboardingSettings.load()
    employees = _employees().order_by('-joining_date', 'employee_id')
    if params.get('include_inactive') != 'true':
        employees = employees.filter(status='ACTIVE', user__is_active=True)
    if params.get('department'):
        employees = employees.filter(department__iexact=params['department'])
    search = params.get('search', '').strip()
    if search:
        employees = employees.filter(
            Q(employee_id__icontains=search) | Q(user__username__icontains=search)
            | Q(user__first_name__icontains=search) | Q(user__last_name__icontains=search)
        )
    rows = [summary(employee, settings) for employee in employees]
    counts = {state: sum(1 for row in rows if row['state'] == state) for state in ('IN_PROGRESS', 'READY', 'COMPLETED')}
    wanted = params.get('state', 'OPEN')
    if wanted == 'OPEN':
        rows = [row for row in rows if row['state'] != 'COMPLETED']
    elif wanted in counts:
        rows = [row for row in rows if row['state'] == wanted]
    return Response({'counts': counts, 'results': rows, 'settings': OnboardingSettingsSerializer(settings).data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def onboarding_me(request):
    employee = _employees().filter(user=request.user).first()
    if employee is None:
        return Response({'detail': 'You do not have an employee record yet.'}, status=status.HTTP_404_NOT_FOUND)
    data = summary(employee)
    data.pop('note', None)
    return Response(data)


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def onboarding_settings(request):
    settings = OnboardingSettings.load()
    if request.method == 'GET':
        return Response(OnboardingSettingsSerializer(settings).data)
    serializer = OnboardingSettingsSerializer(settings, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    settings = serializer.save(updated_by=request.user)
    labels = ', '.join(DOCUMENT_LABELS[code] for code in settings.required_document_types) or 'no documents'
    record_audit(request, 'UPDATE', 'OnboardingSettings', 1,
                 f'Onboarding requires {labels}; address {"required" if settings.require_address else "optional"}, '
                 f'photo {"required" if settings.require_profile_photo else "optional"}, salary structure '
                 f'{"required" if settings.require_salary_structure else "optional"}.')
    for employee in _employees().filter(onboarding_status=Employee.ONBOARDING_PENDING):
        refresh(employee, settings)
    return Response(OnboardingSettingsSerializer(settings).data)


def _get(pk):
    return _employees().filter(pk=pk).first()


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def onboarding_complete(request, pk):
    note = str(request.data.get('note', '')).strip()[:255]
    with transaction.atomic():
        employee = Employee.objects.select_for_update().filter(pk=pk).first()
        if employee is None:
            return Response({'detail': 'Employee not found.'}, status=status.HTTP_404_NOT_FOUND)
        if employee.onboarding_status == Employee.ONBOARDING_COMPLETED:
            return Response({'detail': 'Onboarding is already complete for this employee.'}, status=status.HTTP_409_CONFLICT)
        employee = _get(pk)
        missing = [item['label'] for item in checklist(employee) if not item['done']]
        if missing:
            return Response({'detail': f'Onboarding cannot be completed yet. Missing: {", ".join(missing)}.', 'missing': missing},
                            status=status.HTTP_409_CONFLICT)
        Employee.objects.filter(pk=pk).update(
            onboarding_status=Employee.ONBOARDING_COMPLETED, onboarding_completed_at=timezone.now(),
            onboarding_completed_by=request.user, onboarding_note=note,
        )
        record_audit(request, 'COMPLETE', 'Onboarding', pk,
                     f'Marked onboarding complete for {employee.employee_id}{f": {note}" if note else ""}.', subject=employee)
    notify_user(employee.user, 'ONBOARDING', 'Onboarding complete',
                'An administrator reviewed your details and documents and completed your onboarding.',
                'employee-dashboard.html', actor=request.user)
    return Response(summary(_get(pk)))


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def onboarding_reopen(request, pk):
    note = str(request.data.get('note', '')).strip()[:255]
    if not note:
        return Response({'note': ['Say why onboarding is being reopened.']}, status=status.HTTP_400_BAD_REQUEST)
    employee = _get(pk)
    if employee is None:
        return Response({'detail': 'Employee not found.'}, status=status.HTTP_404_NOT_FOUND)
    if employee.onboarding_status != Employee.ONBOARDING_COMPLETED:
        return Response({'detail': 'Onboarding is not complete for this employee.'}, status=status.HTTP_409_CONFLICT)
    Employee.objects.filter(pk=pk).update(
        onboarding_status=Employee.ONBOARDING_PENDING, onboarding_completed_at=None, onboarding_completed_by=None,
        onboarding_ready_at=None, onboarding_note=note,
    )
    record_audit(request, 'REOPEN', 'Onboarding', pk, f'Reopened onboarding for {employee.employee_id}: {note}.', subject=employee)
    notify_user(employee.user, 'ONBOARDING', 'Onboarding reopened', f'Please review your onboarding checklist. {note}',
                'employee-dashboard.html', actor=request.user)
    refresh(_get(pk))
    return Response(summary(_get(pk)))


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def onboarding_remind(request, pk):
    employee = _get(pk)
    if employee is None:
        return Response({'detail': 'Employee not found.'}, status=status.HTTP_404_NOT_FOUND)
    missing = [item['label'] for item in checklist(employee) if not item['done'] and item['owner'] == 'EMPLOYEE']
    if not missing:
        return Response({'detail': 'Nothing is waiting on the employee; the remaining items are for an administrator.'},
                        status=status.HTTP_409_CONFLICT)
    notify_user(employee.user, 'ONBOARDING', 'Onboarding items still needed',
                f'Please complete: {", ".join(missing)}.', 'employee-dashboard.html', actor=request.user)
    record_audit(request, 'REMIND', 'Onboarding', pk, f'Sent an onboarding reminder to {employee.employee_id} ({len(missing)} item(s)).',
                 subject=employee)
    return Response({'sent': True, 'missing': missing})
