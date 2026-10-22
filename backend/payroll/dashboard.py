"""Dashboard summaries computed from real database records."""

import calendar
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import (
    Announcement, AttendanceRecord, Company, Employee, EmployeeDocument, Holiday, LeaveRequest, UserProfile, WorkFromHomeRequest,
)
from accounts.permissions import IsAdminUserRole
from accounts.leave_policy import leave_year_of, policy_settings
from accounts.serializers import AnnouncementSerializer, HolidaySerializer, LeaveRequestSerializer, leave_balance_for

from workforce.models import OvertimeRecord
from workforce.serializers import ShiftSerializer
from workforce.services import shift_for

from .models import Payslip
from .serializers import PayslipSerializer


def _month_label(year, month):
    return f'{calendar.month_abbr[month]} {str(year)[2:]}'


def _company_id(user):
    return UserProfile.objects.filter(user=user).values_list('company_id', flat=True).first()


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def admin_dashboard(request):
    today = timezone.localdate()
    company_id = _company_id(request.user)
    active = Employee.objects.filter(company_id=company_id, status='ACTIVE', user__is_active=True)

    employees = {
        'total': Employee.objects.filter(company_id=company_id).count(),
        'active': active.count(),
        'inactive': Employee.objects.filter(company_id=company_id).exclude(status='ACTIVE').count(),
        'joined_this_month': Employee.objects.filter(company_id=company_id, joining_date__year=today.year, joining_date__month=today.month).count(),
        'pending_onboarding': User.objects.filter(userprofile__company_id=company_id, userprofile__role='EMPLOYEE', employee__isnull=True, is_active=True).count(),
        'onboarding_in_progress': active.filter(onboarding_status=Employee.ONBOARDING_PENDING, onboarding_ready_at__isnull=True).count(),
        'onboarding_ready': active.filter(onboarding_status=Employee.ONBOARDING_PENDING, onboarding_ready_at__isnull=False).count(),
    }
    from accounts.models import AttendanceCorrectionRequest, ReminderSettings
    from accounts.reminders import maybe_run_reminders

    maybe_run_reminders(Company.objects.filter(pk=company_id).first())
    warn_until = today + timedelta(days=ReminderSettings.load(Company.objects.filter(pk=company_id).first()).warning_window_days)
    pending = {
        'corrections': AttendanceCorrectionRequest.objects.filter(employee__userprofile__company_id=company_id, status='PENDING').count(),
        'leaves': LeaveRequest.objects.filter(employee__userprofile__company_id=company_id, status='PENDING').count(),
        'wfh': WorkFromHomeRequest.objects.filter(employee__userprofile__company_id=company_id, status='PENDING').count(),
        'documents': EmployeeDocument.objects.filter(employee__userprofile__company_id=company_id, status='PENDING').count(),
        'overtime': OvertimeRecord.objects.filter(employee__userprofile__company_id=company_id, status=OvertimeRecord.PENDING).count(),
    }
    month_start = today.replace(day=1)
    month_attendance = AttendanceRecord.objects.filter(employee__userprofile__company_id=company_id, date__range=(month_start, today), check_in_at__isnull=False)
    attendance = {
        'checked_in_today': AttendanceRecord.objects.filter(employee__userprofile__company_id=company_id, date=today, check_in_at__isnull=False).count(),
        'late_today': AttendanceRecord.objects.filter(employee__userprofile__company_id=company_id, date=today, late_minutes__gt=0).count(),
        'on_leave_today': LeaveRequest.objects.filter(employee__userprofile__company_id=company_id, status='APPROVED', start_date__lte=today, end_date__gte=today).count(),
        'working_from_home_today': WorkFromHomeRequest.objects.filter(employee__userprofile__company_id=company_id, status='APPROVED', start_date__lte=today, end_date__gte=today).count(),
        'late_this_month': month_attendance.filter(late_minutes__gt=0).count(),
        'average_late_minutes_this_month': round(month_attendance.filter(late_minutes__gt=0).aggregate(v=Avg('late_minutes'))['v'] or 0),
    }
    # Daily attendance for the last 14 days: present and late check-ins.
    window_start = today - timedelta(days=13)
    daily = {
        row['date']: row for row in AttendanceRecord.objects.filter(employee__userprofile__company_id=company_id, date__range=(window_start, today), check_in_at__isnull=False)
        .values('date').annotate(present=Count('id'), late=Count('id', filter=Q(late_minutes__gt=0)))
    }
    attendance['trend'] = [
        {'date': day, 'label': day.strftime('%d %b'), 'present': daily.get(day, {}).get('present', 0), 'late': daily.get(day, {}).get('late', 0)}
        for day in (window_start + timedelta(days=offset) for offset in range(14))
    ]

    year_leaves = LeaveRequest.objects.filter(employee__userprofile__company_id=company_id, start_date__year=today.year)
    leave = {
        'year': today.year,
        'by_status': {row['status']: row['count'] for row in year_leaves.values('status').annotate(count=Count('id'))},
        'approved_days_by_type': [
            {'leave_type': row['leave_type'], 'days': row['days'] or 0}
            for row in year_leaves.filter(status='APPROVED').values('leave_type').annotate(days=Sum('number_of_days')).order_by('-days')
        ],
        'approved_days_this_month': year_leaves.filter(status='APPROVED', start_date__month=today.month).aggregate(v=Sum('number_of_days'))['v'] or 0,
    }
    overtime = OvertimeRecord.objects.filter(employee__userprofile__company_id=company_id, date__range=(month_start, today))
    overtime_stats = {
        'pending': OvertimeRecord.objects.filter(employee__userprofile__company_id=company_id, status=OvertimeRecord.PENDING).count(),
        'approved_hours_this_month': overtime.filter(status=OvertimeRecord.APPROVED).aggregate(v=Sum('hours'))['v'] or 0,
        'approved_amount_this_month': overtime.filter(status=OvertimeRecord.APPROVED).aggregate(v=Sum('amount'))['v'] or 0,
    }

    # Latest payroll period that has any payslips, plus a six-period trend.
    periods = list(
        Payslip.objects.filter(employee__userprofile__company_id=company_id).values('year', 'month').annotate(
            count=Count('id'), gross=Sum('gross_earnings'), deductions=Sum('total_deductions'), net=Sum('net_salary'),
            drafts=Count('id', filter=Q(status=Payslip.DRAFT)),
        ).order_by('-year', '-month')[:6]
    )
    latest = periods[0] if periods else None
    payroll = {
        'latest': {
            'label': f'{calendar.month_name[latest["month"]]} {latest["year"]}',
            'year': latest['year'], 'month': latest['month'], 'count': latest['count'],
            'gross': latest['gross'], 'deductions': latest['deductions'], 'net': latest['net'],
            'drafts': latest['drafts'],
        } if latest else None,
        'trend': [
            {'label': _month_label(period['year'], period['month']), 'net': period['net'], 'gross': period['gross']}
            for period in reversed(periods)
        ],
        'employees_without_structure': active.filter(user__salary_structure__isnull=True).count(),
    }

    departments = list(
        active.values('department').annotate(headcount=Count('id')).order_by('-headcount', 'department')
    )

    recent_leaves = LeaveRequest.objects.filter(employee__userprofile__company_id=company_id, status='PENDING').select_related('employee', 'employee__employee').order_by('-applied_at')[:5]
    announcements = Announcement.objects.filter(company_id=company_id).select_related('created_by')[:3]

    return Response({
        'employees': employees,
        'pending': pending,
        'documents': {
            'expired': EmployeeDocument.objects.filter(employee__userprofile__company_id=company_id, expiry_date__lt=today, employee__is_active=True).count(),
            'expiring': EmployeeDocument.objects.filter(employee__userprofile__company_id=company_id, expiry_date__gte=today, expiry_date__lte=warn_until, employee__is_active=True).count(),
        },
        'attendance': attendance,
        'leave': leave,
        'overtime': overtime_stats,
        'payroll': payroll,
        'departments': departments,
        'recent_leaves': LeaveRequestSerializer(recent_leaves, many=True).data,
        'announcements': AnnouncementSerializer(announcements, many=True).data,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def employee_dashboard(request):
    user = request.user
    company_id = _company_id(user)
    today = timezone.localdate()
    employee = Employee.objects.filter(user=user, company_id=company_id).first()

    month_records = AttendanceRecord.objects.filter(
        employee=user, date__year=today.year, date__month=today.month, check_in_at__isnull=False,
    )
    today_record = month_records.filter(date=today).first()

    shift = shift_for(user, today)
    month_overtime = OvertimeRecord.objects.filter(employee=user, date__year=today.year, date__month=today.month)
    payslips = list(Payslip.objects.filter(employee=user, status=Payslip.PAID).order_by('-year', '-month')[:6])
    latest = payslips[0] if payslips else None

    upcoming_holidays = Holiday.objects.filter(company_id=company_id, date__gte=today).order_by('date')[:3]

    from accounts.models import AttendanceCorrectionRequest, ReminderSettings
    from accounts.onboarding import summary as onboarding_summary
    from accounts.reminders import maybe_run_reminders

    company = Company.objects.filter(pk=company_id).first()
    maybe_run_reminders(company)
    warn_until = today + timedelta(days=ReminderSettings.load(company).warning_window_days)
    onboarding = None
    if employee is not None and employee.onboarding_status != Employee.ONBOARDING_COMPLETED:
        onboarding = onboarding_summary(employee)
        onboarding.pop('note', None)

    return Response({
        'employee': {
            'employee_id': employee.employee_id,
            'department': employee.department,
            'designation': employee.designation,
            'joining_date': employee.joining_date,
            'status': employee.status,
        } if employee else None,
        'leave_balance': leave_balance_for(user, leave_year_of(today, policy_settings(company))),
        'leave_year': leave_year_of(today, policy_settings(company)),
        'requests': {
            'pending_leaves': LeaveRequest.objects.filter(employee=user, status='PENDING').count(),
            'pending_wfh': WorkFromHomeRequest.objects.filter(employee=user, status='PENDING').count(),
            'pending_documents': EmployeeDocument.objects.filter(employee=user, status='PENDING').count(),
            'pending_overtime': month_overtime.filter(status=OvertimeRecord.PENDING).count(),
            'pending_corrections': AttendanceCorrectionRequest.objects.filter(employee=user, status='PENDING').count(),
        },
        'onboarding': onboarding,
        'documents': {
            'expired': EmployeeDocument.objects.filter(employee=user, expiry_date__lt=today).count(),
            'expiring': EmployeeDocument.objects.filter(employee=user, expiry_date__gte=today, expiry_date__lte=warn_until).count(),
        },
        'attendance': {
            'days_present_this_month': month_records.count(),
            'checked_in_today': bool(today_record and today_record.check_in_at),
            'checked_out_today': bool(today_record and today_record.check_out_at),
            'late_minutes_today': today_record.late_minutes if today_record else None,
            'late_days_this_month': month_records.filter(late_minutes__gt=0).count(),
            'late_minutes_this_month': month_records.aggregate(v=Sum('late_minutes'))['v'] or 0,
        },
        'shift': ShiftSerializer(shift).data if shift else None,
        'overtime': {
            'approved_hours_this_month': month_overtime.filter(status=OvertimeRecord.APPROVED).aggregate(v=Sum('hours'))['v'] or 0,
            'approved_amount_this_month': month_overtime.filter(status=OvertimeRecord.APPROVED).aggregate(v=Sum('amount'))['v'] or 0,
        },
        'latest_payslip': PayslipSerializer(latest).data if latest else None,
        'salary_trend': [
            {'label': _month_label(slip.year, slip.month), 'net': slip.net_salary} for slip in reversed(payslips)
        ],
        'upcoming_holidays': HolidaySerializer(upcoming_holidays, many=True).data,
        'announcements': AnnouncementSerializer(Announcement.objects.filter(company_id=company_id).select_related('created_by')[:3], many=True).data,
    })
