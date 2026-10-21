"""Team calendar: approved leave, approved work from home, shifts and holidays for a date range.

Permissions
-----------
* Administrators see every employee and can filter by employee, department and event type.
* Employees see their own schedule (leave type, WFH, shift) and, for colleagues in their own
  department, only *availability* — "On leave" or "Working from home" with dates. Leave types, reasons
  and shifts of colleagues are never returned. The employee is always taken from the session.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Employee, Holiday, LeaveRequest, WorkFromHomeRequest
from .utils import is_admin_user

MAX_DAYS = 62
TYPES = ('leave', 'wfh', 'shift', 'holiday')


def _name(user):
    return user.get_full_name() or user.username


def _clip(start, end, range_start, range_end):
    return max(start, range_start), min(end, range_end)


def _shift_ranges(user, start, end):
    """Compress the per-day shift (assignment or default) into continuous ranges."""
    from workforce.services import shift_for

    ranges, current = [], None
    day = start
    while day <= end:
        shift = shift_for(user, day)
        key = shift.pk if shift else None
        if current and current['key'] == key and current['end'] == day - timedelta(days=1):
            current['end'] = day
        else:
            current = {'key': key, 'shift': shift, 'start': day, 'end': day}
            ranges.append(current)
        day += timedelta(days=1)
    return [item for item in ranges if item['shift'] is not None]


def _shift_label(shift):
    return f'{shift.name} ({shift.start_time:%H:%M}–{shift.end_time:%H:%M})'


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def team_calendar(request):
    params = request.query_params
    today = timezone.localdate()
    start = parse_date(params.get('start', '') or '') or today.replace(day=1)
    end = parse_date(params.get('end', '') or '') or (start + timedelta(days=41))
    if end < start:
        return Response({'detail': 'The end date must be on or after the start date.'}, status=status.HTTP_400_BAD_REQUEST)
    if (end - start).days + 1 > MAX_DAYS:
        return Response({'detail': f'Choose a range of at most {MAX_DAYS} days.'}, status=status.HTTP_400_BAD_REQUEST)
    requested = [item.strip() for item in params.get('types', '').split(',') if item.strip()]
    types = [item for item in requested if item in TYPES] or list(TYPES)

    admin = is_admin_user(request.user)
    events = []
    me = request.user
    my_employee = Employee.objects.filter(user=me).first()

    if admin:
        people = Employee.objects.filter(status='ACTIVE', user__is_active=True).select_related('user')
        if params.get('department'):
            people = people.filter(department__iexact=params['department'])
        if params.get('employee'):
            people = people.filter(user_id=params['employee']) if str(params['employee']).isdigit() else people.none()
        scope = 'all'
    else:
        scope = 'team' if params.get('scope') == 'team' else 'mine'
        if my_employee is None:
            people = Employee.objects.none()
        elif scope == 'team':
            people = Employee.objects.filter(status='ACTIVE', user__is_active=True, department__iexact=my_employee.department).select_related('user')
        else:
            people = Employee.objects.filter(pk=my_employee.pk).select_related('user')
    people = list(people.order_by('employee_id'))
    by_user = {person.user_id: person for person in people}

    def private(user_id):
        """True when the viewer may only see availability (a colleague, for an employee)."""
        return not admin and user_id != me.pk

    if 'leave' in types and by_user:
        for leave in LeaveRequest.objects.filter(
            employee_id__in=by_user, status='APPROVED', start_date__lte=end, end_date__gte=start,
        ).order_by('start_date'):
            person = by_user[leave.employee_id]
            first, last = _clip(leave.start_date, leave.end_date, start, end)
            hidden = private(leave.employee_id)
            events.append({
                'type': 'leave', 'start': first, 'end': last, 'employee_user_id': person.user_id,
                'employee_name': _name(person.user), 'department': person.department,
                'title': 'On leave' if hidden else (leave.leave_type if 'leave' in leave.leave_type.lower() else f'{leave.leave_type} leave'),
                'detail': '' if hidden else f'{leave.number_of_days} day(s), {leave.start_date:%d %b} – {leave.end_date:%d %b}',
            })
    if 'wfh' in types and by_user:
        for item in WorkFromHomeRequest.objects.filter(
            employee_id__in=by_user, status='APPROVED', start_date__lte=end, end_date__gte=start,
        ).order_by('start_date'):
            person = by_user[item.employee_id]
            first, last = _clip(item.start_date, item.end_date, start, end)
            events.append({
                'type': 'wfh', 'start': first, 'end': last, 'employee_user_id': person.user_id,
                'employee_name': _name(person.user), 'department': person.department,
                'title': 'Working from home', 'detail': '',
            })
    if 'shift' in types and by_user:
        from workforce.models import ShiftAssignment

        if admin:
            # Explicit assignments only; the default shift is reported once instead of per person and day.
            assignments = ShiftAssignment.objects.select_related('shift').filter(
                employee_id__in=by_user, start_date__lte=end,
            ).filter(Q(end_date__isnull=True) | Q(end_date__gte=start)).order_by('start_date')
            for assignment in assignments:
                person = by_user[assignment.employee_id]
                first, last = _clip(assignment.start_date, assignment.end_date or end, start, end)
                events.append({
                    'type': 'shift', 'start': first, 'end': last, 'employee_user_id': person.user_id,
                    'employee_name': _name(person.user), 'department': person.department,
                    'title': _shift_label(assignment.shift), 'detail': assignment.notes,
                })
        elif my_employee is not None:
            for item in _shift_ranges(me, start, end):
                events.append({
                    'type': 'shift', 'start': item['start'], 'end': item['end'], 'employee_user_id': me.pk,
                    'employee_name': _name(me), 'department': my_employee.department,
                    'title': _shift_label(item['shift']), 'detail': 'Your shift',
                })
    if 'holiday' in types:
        for holiday in Holiday.objects.filter(date__range=(start, end)).order_by('date'):
            events.append({
                'type': 'holiday', 'start': holiday.date, 'end': holiday.date, 'employee_user_id': None,
                'employee_name': '', 'department': '', 'title': holiday.name,
                'detail': holiday.get_holiday_type_display(),
            })

    events.sort(key=lambda item: (item['start'], TYPES.index(item['type']), item['employee_name']))
    response = {
        'start': start, 'end': end, 'scope': scope, 'types': types, 'events': events,
        'people': len(people),
    }
    if admin and 'shift' in types:
        from workforce.models import Shift

        default = Shift.objects.filter(is_default=True, is_active=True).first()
        response['default_shift'] = _shift_label(default) if default else None
    if not admin and my_employee is not None:
        response['department'] = my_employee.department
    return Response(response)
