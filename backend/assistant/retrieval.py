"""Question routing and authorised data retrieval for the AI assistants.

For every question PayrollPro decides *in backend code* which of the signed-in user's records are
relevant, fetches only those, and does all money arithmetic itself (re-using the stored payslip
values and the payroll rules in ``payroll.calculator``). The model only receives the resulting
facts to explain; it never queries the database and never produces authoritative figures.

Identity always comes from the authenticated conversation owner (``conversation.user``). Names,
IDs or numbers typed in a question are never used to look up records. An administrator's chosen
employee (``conversation.subject``) is validated when the conversation is created.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from accounts.models import AttendanceRecord, EmployeeDocument, Holiday, LeaveRequest, WorkFromHomeRequest
from accounts.serializers import leave_balance_for
from accounts.utils import is_admin_user
from payroll.calculator import EARNING_FIELDS, money
from payroll.models import Payslip, SalaryStructure
from workforce.models import OvertimeRecord
from workforce.services import shift_for

from .models import AIConversation

# --- intents ---------------------------------------------------------------------

PAYSLIP, COMPARE, STRUCTURE, LEAVE, WFH, OVERTIME, ATTENDANCE, SHIFT, DOCUMENTS, HOLIDAYS = (
    'payslip', 'compare', 'structure', 'leave', 'wfh', 'overtime', 'attendance', 'shift', 'documents', 'holidays')

# "How do I apply…" is a general question; "my…", "was I…", "do I have…" are about the user's own records.
PERSONAL = re.compile(r"\b(my|me|mine|i'm|i've|am i|was i|were i|did i|have i|do i have|i have|i got|i get|i was|i am)\b")
PATTERNS = {
    PAYSLIP: re.compile(r'pay ?slip|salary slip|\bsalary\b|\bpay\b|\bpaid\b|net\b|gross|take[- ]?home|deduct|breakdown|break down'
                        r'|\bpf\b|provident|\btds\b|income tax|professional tax|\btax\b|\blop\b|loss of pay|bonus|allowance'
                        r'|\bda\b|\bhra\b|\bbasic\b|earning|wage|ctc|overtime pay'),
    COMPARE: re.compile(r'\bless\b|\bmore\b|lower|higher|decrease|increase|differ|change|compar|previous|last month|dropp?ed'
                        r'|reduc|went (up|down)|why (was|is|did|has)'),
    STRUCTURE: re.compile(r'salary structure|\bctc\b|monthly (salary|gross)|fixed (pay|gross)|overtime rate|pf (percent|%|rate)'),
    LEAVE: re.compile(r'\bleaves?\b|casual|sick|earned leave|time off|day off|days off|absence|vacation'),
    WFH: re.compile(r'\bwfh\b|work(ing)? from home|remote'),
    OVERTIME: re.compile(r'overtime|\bot\b|extra hours'),
    ATTENDANCE: re.compile(r'attendance|\blate\b|late minutes|check[- ]?in|check[- ]?out|\babsent|present|punctual|hours worked'),
    SHIFT: re.compile(r'\bshift'),
    DOCUMENTS: re.compile(r'document|certificate|id proof|address proof|resume'),
    HOLIDAYS: re.compile(r'holiday'),
}
STATUS_WORDS = re.compile(r'status|approved|rejected|pending|cancel|my request|requests|applied|submitted|history|did .* get')
OTHER_PERSON = re.compile(
    r"\b(emp[- ]?\d+|employee (id|code|number)|user ?id|staff id|someone else|somebody else|another employee|other employees?"
    r"|other people|colleague|co-?workers?|team ?mates?|my (manager|boss|friend)'?s?|every(one|body)'?s?|all employees)\b"
)
POSSESSIVE = re.compile(r"\b([a-z][a-z.]+)'s\s+(pay ?slip|salary|pay|leave|wfh|attendance|overtime|bonus|deductions?|documents?)")
OF_PERSON = re.compile(r'\b(?:[Pp]ay ?slip|[Ss]alary|[Pp]ay|WFH|[Aa]ttendance|[Oo]vertime)\s+(?:of|for)\s+([A-Z][a-z]+)')
SENSITIVE = re.compile(r'pay ?slip|salary|\bpay\b|\bpaid\b|leave|wfh|work from home|attendance|overtime|deduction|bonus|document|late')
NOT_NAMES = set(m.lower() for m in calendar.month_name if m) | set(m.lower() for m in calendar.month_abbr if m) | {
    'this', 'last', 'the', 'a', 'my', 'me', 'current', 'previous', 'next', 'month', 'year', 'today', 'all', 'each', 'every',
    'one', 'that', 'it', 'him', 'her', 'them', 'days', 'day', 'week', 'overtime', 'leave', 'wfh', 'work', 'sick', 'casual', 'earned',
}


COMMON_WORDS = {
    'admin', 'administrator', 'hr', 'manager', 'payroll', 'payslip', 'salary', 'leave', 'leaves', 'wfh', 'work', 'home', 'from',
    'attendance', 'overtime', 'deduction', 'deductions', 'bonus', 'document', 'documents', 'late', 'pay', 'paid', 'net', 'gross',
    'status', 'request', 'requests', 'balance', 'left', 'days', 'approved', 'pending', 'rejected', 'why', 'less', 'more', 'will',
    'apply', 'latest', 'breakdown', 'explain', 'show', 'casual', 'sick', 'earned', 'other', 'month', 'year', 'last', 'tax',
}


@dataclass
class Retrieval:
    intents: set = field(default_factory=set)
    blocks: list = field(default_factory=list)      # text sent to the model, already authorised
    fallback: list = field(default_factory=list)    # markdown shown when the model is unavailable
    sources: list = field(default_factory=list)     # short labels shown under the answer
    refusal: str = ''
    personal: bool = False


def detect_intents(text):
    lowered = text.lower()
    return {intent for intent, pattern in PATTERNS.items() if pattern.search(lowered)}


def asks_about_someone_else(text, user):
    """Best-effort check that a question targets another person's records (records are never fetched for them anyway)."""
    from django.contrib.auth.models import User

    lowered = text.lower()
    if OTHER_PERSON.search(lowered):
        return True
    own = {part.lower() for part in (user.username, user.first_name, user.last_name) if part}
    for match in POSSESSIVE.finditer(lowered):
        if match.group(1) not in own and match.group(1) not in NOT_NAMES:
            return True
    for match in OF_PERSON.finditer(text):
        if match.group(1).lower() not in own and match.group(1).lower() not in NOT_NAMES:
            return True
    if SENSITIVE.search(lowered):
        from .knowledge import STOPWORDS

        words = set(re.findall(r'[a-z0-9_.@+-]{3,}', lowered)) - own - NOT_NAMES - STOPWORDS - COMMON_WORDS
        if words:
            others = User.objects.exclude(pk=user.pk).filter(userprofile__role='EMPLOYEE').filter(
                Q(username__in=words) | Q(first_name__iregex=r'^(' + '|'.join(re.escape(w) for w in words) + r')$')
                | Q(employee__employee_id__in=[w.upper() for w in words]))
            if others.exists():
                return True
    return False


# --- formatting helpers -------------------------------------------------------------

def rs(value):
    return f'Rs {Decimal(value):,.2f}'


def num(value):
    """2.00 -> 2, 1.50 -> 1.5, 12.00 -> 12 (for days, hours and percentages)."""
    text = f'{Decimal(value).normalize():f}'
    return text


def period(slip):
    return f'{calendar.month_name[slip.month]} {slip.year}'


def name_of(user):
    return user.get_full_name() or user.username


EARNING_LABELS = {
    'basic': ('Basic pay', 'the core fixed part of your salary; PF is calculated on Basic + DA'),
    'hra': ('House rent allowance (HRA)', 'a fixed monthly allowance for housing'),
    'da': ('Dearness allowance (DA)', 'a fixed monthly allowance; part of fixed gross and of the PF wage'),
    'conveyance_allowance': ('Conveyance allowance', 'a fixed monthly travel allowance'),
    'medical_allowance': ('Medical allowance', 'a fixed monthly medical allowance'),
    'special_allowance': ('Special allowance', 'a fixed monthly allowance set in your salary structure'),
    'other_allowance': ('Other allowance', 'any other fixed monthly allowance in your salary structure'),
}


# --- payslip retrieval and calculation explanation -------------------------------------

def payslip_queryset(person, include_drafts):
    payslips = Payslip.objects.filter(employee=person)
    return payslips if include_drafts else payslips.filter(status=Payslip.PAID)


def explain_payslip(slip):
    """Components, calculation steps and consistency checks for one stored payslip (Decimal arithmetic)."""
    fixed = {field: Decimal(getattr(slip, field)) for field in EARNING_FIELDS}
    fixed_gross = sum(fixed.values(), Decimal('0'))
    working = Decimal(slip.working_days)
    lop = Decimal(slip.lop_days)
    lop_ratio = min(Decimal(1), lop / working) if working else Decimal(0)
    paid_ratio = Decimal(1) - lop_ratio
    paid_days = max(Decimal('0'), working - lop)

    earnings = []
    missing = []
    for field_name in EARNING_FIELDS:
        label, meaning = EARNING_LABELS[field_name]
        if fixed[field_name]:
            earnings.append((label, fixed[field_name], meaning))
        else:
            missing.append(label)
    if slip.overtime_pay:
        earnings.append((f'Overtime pay ({num(slip.overtime_hours)} approved hours)', slip.overtime_pay, 'approved overtime hours × your overtime rate'))
    if slip.bonus:
        earnings.append(('Bonus', slip.bonus, 'paid in full, not reduced for loss of pay'))

    deductions = []
    if slip.pf:
        deductions.append((f'Provident fund (PF, {num(slip.pf_percent)}%)', slip.pf, 'retirement savings: PF % of (Basic + DA), reduced for LOP days'))
    if slip.professional_tax:
        deductions.append(('Professional tax', slip.professional_tax, 'monthly state tax from your salary structure, reduced for LOP days'))
    if slip.tds:
        deductions.append(('Income tax (TDS)', slip.tds, 'monthly income tax set by an administrator, reduced for LOP days'))
    if slip.other_deduction:
        deductions.append(('Other deductions', slip.other_deduction, 'for example a loan instalment; taken in full'))
    if slip.lop_deduction:
        deductions.append((f'Loss of pay ({num(lop)} day{"s" if lop != 1 else ""})', slip.lop_deduction, 'salary reduction for unpaid working days'))

    steps = [
        f'Working days {slip.working_days}, loss-of-pay (LOP) days {num(lop)}, paid days {num(paid_days)}.',
        'Fixed gross = ' + ' + '.join(rs(v) for v in fixed.values() if v) + f' = {rs(fixed_gross)}.',
        f'Gross earnings = fixed gross {rs(fixed_gross)}'
        + (f' + overtime {rs(slip.overtime_pay)}' if slip.overtime_pay else '')
        + (f' + bonus {rs(slip.bonus)}' if slip.bonus else '') + f' = {rs(slip.gross_earnings)}.',
    ]
    checks = []
    expected_gross = money(fixed_gross + slip.overtime_pay + slip.bonus)
    if expected_gross != slip.gross_earnings:
        checks.append(f'The stored gross ({rs(slip.gross_earnings)}) differs from the sum of components ({rs(expected_gross)}).')
    if lop and working:
        steps.append(f'LOP deduction = fixed gross {rs(fixed_gross)} × {num(lop)} ÷ {slip.working_days} = {rs(money(fixed_gross * lop_ratio))}'
                     f' (stored {rs(slip.lop_deduction)}).')
    if slip.pf:
        pf_wage = fixed['basic'] + fixed['da']
        steps.append(f'PF = {num(slip.pf_percent)}% × (Basic {rs(fixed["basic"])} + DA {rs(fixed["da"])}) × paid share {num(paid_days)}/{slip.working_days}'
                     f' = {rs(money(pf_wage * paid_ratio * slip.pf_percent / 100))} (stored {rs(slip.pf)}).')
    if slip.professional_tax_base and (slip.professional_tax != slip.professional_tax_base):
        steps.append(f'Professional tax = {rs(slip.professional_tax_base)} × paid share = {rs(slip.professional_tax)}.')
    if slip.tds_base and (slip.tds != slip.tds_base):
        steps.append(f'TDS = {rs(slip.tds_base)} × paid share = {rs(slip.tds)}.')
    deduction_sum = money(slip.pf + slip.professional_tax + slip.tds + slip.other_deduction + slip.lop_deduction)
    steps.append('Total deductions = ' + (' + '.join(rs(v) for _, v, _ in deductions) or 'Rs 0.00') + f' = {rs(slip.total_deductions)}.')
    steps.append(f'Net salary = gross {rs(slip.gross_earnings)} − deductions {rs(slip.total_deductions)} = {rs(slip.net_salary)}.')
    if deduction_sum != slip.total_deductions:
        checks.append(f'The stored total deductions ({rs(slip.total_deductions)}) differ from the sum of deductions ({rs(deduction_sum)}).')
    if money(slip.gross_earnings - slip.total_deductions) != slip.net_salary:
        checks.append('The stored net salary does not equal gross minus deductions.')
    return {'earnings': earnings, 'deductions': deductions, 'missing': missing, 'steps': steps, 'checks': checks,
            'fixed_gross': fixed_gross}


COMPARE_FIELDS = [
    ('basic', 'Basic pay'), ('hra', 'HRA'), ('da', 'DA'), ('conveyance_allowance', 'Conveyance allowance'),
    ('medical_allowance', 'Medical allowance'), ('special_allowance', 'Special allowance'), ('other_allowance', 'Other allowance'),
    ('overtime_pay', 'Overtime pay'), ('bonus', 'Bonus'), ('pf', 'PF'), ('professional_tax', 'Professional tax'), ('tds', 'TDS'),
    ('other_deduction', 'Other deductions'), ('lop_deduction', 'LOP deduction'),
]


def compare_payslips(latest, previous):
    """Differences between two stored payslips, with reasons derived from the stored inputs."""
    changes = []
    for field_name, label in COMPARE_FIELDS:
        before, after = Decimal(getattr(previous, field_name)), Decimal(getattr(latest, field_name))
        if before != after:
            changes.append((label, before, after, after - before))
    changes.sort(key=lambda item: -abs(item[3]))
    reasons = []
    if latest.lop_days != previous.lop_days:
        reasons.append(f'Loss-of-pay days changed from {num(previous.lop_days)} to {num(latest.lop_days)} '
                       f'(LOP deduction {rs(previous.lop_deduction)} → {rs(latest.lop_deduction)}).')
    if latest.working_days != previous.working_days:
        reasons.append(f'The month had {latest.working_days} working days instead of {previous.working_days}.')
    if latest.overtime_pay != previous.overtime_pay:
        reasons.append(f'Approved overtime changed from {num(previous.overtime_hours)} h ({rs(previous.overtime_pay)}) to '
                       f'{num(latest.overtime_hours)} h ({rs(latest.overtime_pay)}).')
    if latest.bonus != previous.bonus:
        reasons.append(f'Bonus changed from {rs(previous.bonus)} to {rs(latest.bonus)}.')
    fixed_before = sum((Decimal(getattr(previous, f)) for f in EARNING_FIELDS), Decimal('0'))
    fixed_after = sum((Decimal(getattr(latest, f)) for f in EARNING_FIELDS), Decimal('0'))
    if fixed_before != fixed_after:
        reasons.append(f'Your fixed monthly salary components changed from {rs(fixed_before)} to {rs(fixed_after)} '
                       '(a salary structure revision).')
    if latest.other_deduction != previous.other_deduction:
        reasons.append(f'Other deductions changed from {rs(previous.other_deduction)} to {rs(latest.other_deduction)}.')
    return {
        'net_before': previous.net_salary, 'net_after': latest.net_salary, 'net_change': latest.net_salary - previous.net_salary,
        'gross_before': previous.gross_earnings, 'gross_after': latest.gross_earnings,
        'deductions_before': previous.total_deductions, 'deductions_after': latest.total_deductions,
        'changes': changes, 'reasons': reasons,
    }


def payslip_retrieval(result, person, include_drafts, chosen, want_compare):
    payslips = payslip_queryset(person, include_drafts)
    latest = chosen or payslips.order_by('-year', '-month').first()
    label = 'payslip' if include_drafts else 'finalised (paid) payslip'
    if latest is None:
        note = (f'No {label} is available for {name_of(person)} yet. Payslips appear on the Payslips page only after an '
                'administrator runs payroll for a finished month and finalises it.')
        result.blocks.append(f'PAYSLIP DATA: {note}')
        result.fallback.append(f'**Payslip:** {note}')
        result.sources.append('Payslips: none finalised')
        return
    info = explain_payslip(latest)
    status = latest.get_status_display()
    block = [f'PAYSLIP DATA ({label} for {period(latest)}, status {status}, '
             f'{"paid on " + timezone.localtime(latest.paid_at).strftime("%d %b %Y") if latest.paid_at else "not yet paid"}):',
             'Earnings:']
    block += [f'- {label_}: {rs(amount)} — {meaning}' for label_, amount, meaning in info['earnings']]
    block.append(f'Gross earnings: {rs(latest.gross_earnings)}')
    block.append('Deductions:')
    block += [f'- {label_}: {rs(amount)} — {meaning}' for label_, amount, meaning in info['deductions']] or ['- none']
    block.append(f'Total deductions: {rs(latest.total_deductions)}')
    block.append(f'Net salary: {rs(latest.net_salary)}')
    if info['missing']:
        block.append('Components that are zero / not part of this payslip: ' + ', '.join(info['missing']) + '.')
    block.append('Calculation (computed by PayrollPro from the stored values):')
    block += [f'- {step}' for step in info['steps']]
    if latest.notes:
        block.append(f'Administrator note on this payslip: {latest.notes}')
    if info['checks']:
        block.append('Consistency warnings: ' + ' '.join(info['checks']) + ' Ask an administrator to review this payslip.')
    result.blocks.append('\n'.join(block))
    result.sources.append(f'Payslip {period(latest)} ({status.lower()})')

    fallback = [f'**Your payslip for {period(latest)}** ({status.lower()})', '', '**Earnings**']
    fallback += [f'- {label_}: **{rs(amount)}**' for label_, amount, _ in info['earnings']]
    fallback.append(f'- Gross earnings: **{rs(latest.gross_earnings)}**')
    fallback += ['', '**Deductions**'] + ([f'- {label_}: **{rs(amount)}**' for label_, amount, _ in info['deductions']] or ['- none'])
    fallback += [f'- Total deductions: **{rs(latest.total_deductions)}**', '', f'**Net salary: {rs(latest.net_salary)}**', '', '**How it adds up**']
    fallback += [f'- {step}' for step in info['steps']]
    if info['checks']:
        fallback.append('- ' + ' '.join(info['checks']))

    previous = payslips.filter(Q(year__lt=latest.year) | Q(year=latest.year, month__lt=latest.month)).order_by('-year', '-month').first()
    if previous is None:
        note = f'There is no earlier {label} to compare with {period(latest)}.'
        result.blocks.append(f'COMPARISON: {note}')
        if want_compare:
            result.fallback.append(note)
    else:
        diff = compare_payslips(latest, previous)
        direction = 'lower' if diff['net_change'] < 0 else 'higher' if diff['net_change'] > 0 else 'the same as'
        summary = (f'Net salary for {period(latest)} ({rs(diff["net_after"])}) is {rs(abs(diff["net_change"]))} {direction} '
                   f'than {period(previous)} ({rs(diff["net_before"])}).' if diff['net_change'] else
                   f'Net salary for {period(latest)} is the same as {period(previous)} ({rs(diff["net_after"])}).')
        block = [f'COMPARISON with the previous {label} ({period(previous)}), computed by PayrollPro:', summary,
                 f'Gross {rs(diff["gross_before"])} → {rs(diff["gross_after"])}; total deductions {rs(diff["deductions_before"])} → {rs(diff["deductions_after"])}.']
        block += [f'- {label_}: {rs(before)} → {rs(after)} ({"+" if delta > 0 else "−"}{rs(abs(delta))})' for label_, before, after, delta in diff['changes']]
        block += ['Reasons found in the records:'] + ([f'- {reason}' for reason in diff['reasons']] or ['- No component changed.'])
        result.blocks.append('\n'.join(block))
        result.sources.append(f'Payslip {period(previous)} (comparison)')
        if want_compare:
            fallback += ['', f'**Compared with {period(previous)}**', summary]
            fallback += [f'- {reason}' for reason in diff['reasons']]
    result.fallback.append('\n'.join(fallback))


def structure_retrieval(result, person):
    structure = SalaryStructure.objects.filter(employee=person).first()
    if structure is None:
        note = 'No salary structure has been set up yet; an administrator must set it before payroll can include you.'
        result.blocks.append(f'SALARY STRUCTURE: {note}')
        result.fallback.append(f'**Salary structure:** {note}')
        return
    parts = [(EARNING_LABELS[f][0], getattr(structure, f)) for f in EARNING_FIELDS]
    present = [f'{label}: {rs(value)}' for label, value in parts if value]
    absent = [label for label, value in parts if not value]
    text = (f'SALARY STRUCTURE (effective {structure.effective_from:%d %b %Y}): ' + '; '.join(present)
            + f'. Fixed monthly gross {rs(structure.gross_monthly)}. Monthly bonus {rs(structure.bonus)}. '
            f'PF {num(structure.pf_percent)}% of Basic + DA. Professional tax {rs(structure.professional_tax)}/month. '
            f'TDS {rs(structure.tds)}/month. Other deductions {rs(structure.other_deduction)}/month. '
            f'Overtime rate {rs(structure.overtime_rate)} per approved hour.'
            + (f' Not part of the structure (zero): {", ".join(absent)}.' if absent else ''))
    result.blocks.append(text)
    result.sources.append('Salary structure')
    result.fallback.append('**Your salary structure**\n' + '\n'.join(f'- {item}' for item in present)
                           + f'\n- Fixed monthly gross: **{rs(structure.gross_monthly)}**')


def _balance_line(name, b):
    paid = 'paid' if b['is_paid'] else 'unpaid'
    if b['unlimited']:
        return f'- {name} ({paid}): no annual limit; approved {b["approved"]}, pending {b["pending"]}'
    extra = f', carried forward {b["carried_forward"]}' if b['carried_forward'] else ''
    extra += f', adjustment {b["adjustment"]:+d}' if b['adjustment'] else ''
    return (f'- {name}: entitled {b["entitled"]}, approved {b["approved"]}, pending {b["pending"]}, remaining {b["remaining"]}'
            f' (available {b["available"]} of {b["total"]}{extra}; {paid})')


def leave_retrieval(result, person, want_status):
    from accounts.leave_policy import leave_year_bounds, leave_year_label, leave_year_of, policy_settings

    rules = policy_settings()
    year = leave_year_of(timezone.localdate(), rules)
    start, end = leave_year_bounds(year, rules)
    label = leave_year_label(year, rules)
    balance = leave_balance_for(person, year)
    lines = [f'LEAVE BALANCE for leave year {label} (configured by administrators; "remaining" = what can still be requested '
             'after pending requests):']
    lines += [_balance_line(name, b) for name, b in balance.items()] or ['- No leave types are configured.']
    requests = list(LeaveRequest.objects.filter(employee=person).filter(Q(start_date__range=(start, end)) | Q(status='PENDING'))
                    .order_by('-start_date')[:15])
    lines.append(f'LEAVE REQUESTS (leave year {label} and any pending):')
    lines += [f'- {r.leave_type}, {r.start_date:%d %b %Y} to {r.end_date:%d %b %Y} ({r.number_of_days} day(s)), status {r.get_status_display()}'
              f', applied {timezone.localtime(r.applied_at):%d %b %Y}' + (f', administrator reason: {r.rejection_reason}' if r.rejection_reason else '')
              for r in requests] or ['- No leave requests found.']
    result.blocks.append('\n'.join(lines))
    result.sources.append(f'Leave balance {label}')
    fallback = [f'**Your leave balance for {label}**'] + [
        (f'- {name}: no annual limit ({"paid" if b["is_paid"] else "unpaid"}); {b["approved"]} used, {b["pending"]} pending' if b['unlimited'] else
         f'- {name}: **{b["available"]}** of {b["total"]} days available ({b["approved"]} used, {b["pending"]} pending)')
        for name, b in balance.items()]
    if want_status or requests:
        result.sources.append('Leave requests')
        fallback += ['', '**Your leave requests**'] + ([f'- {r.leave_type}: {r.start_date:%d %b} – {r.end_date:%d %b %Y} — {r.get_status_display()}'
                                                        + (f' (reason: {r.rejection_reason})' if r.rejection_reason else '') for r in requests[:8]]
                                                       or ['- You have no leave requests this year.'])
    result.fallback.append('\n'.join(fallback))


def wfh_retrieval(result, person):
    requests = list(WorkFromHomeRequest.objects.filter(employee=person).order_by('-applied_at')[:10])
    lines = ['WORK-FROM-HOME REQUESTS (latest 10, from PayrollPro records):']
    lines += [f'- {r.start_date:%d %b %Y} to {r.end_date:%d %b %Y} ({(r.end_date - r.start_date).days + 1} day(s)), status {r.get_status_display()}, '
              f'applied {timezone.localtime(r.applied_at):%d %b %Y}, reason "{r.reason[:150]}"'
              + (f', administrator note: {r.admin_note}' if r.admin_note else '') for r in requests] or [
        '- No work-from-home requests have been submitted by this user.']
    result.blocks.append('\n'.join(lines))
    result.sources.append('Work-from-home requests')
    result.fallback.append('**Your work-from-home requests**\n' + ('\n'.join(
        f'- {r.start_date:%d %b} – {r.end_date:%d %b %Y}: **{r.get_status_display()}**' + (f' (note: {r.admin_note})' if r.admin_note else '')
        for r in requests) or '- You have not submitted any work-from-home requests.'))


def overtime_retrieval(result, person):
    today = timezone.localdate()
    records = list(OvertimeRecord.objects.filter(employee=person).filter(
        Q(date__gte=today.replace(day=1) - timedelta(days=62)) | Q(status=OvertimeRecord.PENDING)).order_by('-date')[:12])
    lines = ['OVERTIME RECORDS (recent and pending):']
    lines += [f'- {r.date:%d %b %Y}: {num(r.hours)} h × {rs(r.rate)} = {rs(r.amount)}, status {r.get_status_display()}'
              + (f', note: {r.review_note}' if r.review_note else '') for r in records] or ['- No overtime records.']
    result.blocks.append('\n'.join(lines))
    result.sources.append('Overtime records')
    result.fallback.append('**Your overtime**\n' + ('\n'.join(f'- {r.date:%d %b %Y}: {num(r.hours)} h, {rs(r.amount)} — {r.get_status_display()}'
                                                              for r in records) or '- No overtime records.'))


def attendance_retrieval(result, person):
    today = timezone.localdate()
    start = today.replace(day=1)
    records = AttendanceRecord.objects.filter(employee=person, date__range=(start, today), check_in_at__isnull=False)
    late = [r.late_minutes for r in records if r.late_minutes]
    worked = [(r.check_out_at - r.check_in_at).total_seconds() / 3600 for r in records if r.check_out_at]
    today_record = records.filter(date=today).first()
    text = (f'ATTENDANCE this month ({start:%d %b} – {today:%d %b %Y}): {records.count()} day(s) checked in; '
            f'{len(late)} late day(s) totalling {sum(late)} late minutes; {round(sum(worked), 2)} hours worked on days with a check-out. '
            + (f'Today: checked in {timezone.localtime(today_record.check_in_at):%H:%M}'
               + (f', {today_record.late_minutes} min late' if today_record.late_minutes else '')
               + (f', checked out {timezone.localtime(today_record.check_out_at):%H:%M}' if today_record.check_out_at else ', not checked out')
               if today_record else 'Today: not checked in yet.'))
    result.blocks.append(text)
    result.sources.append('Attendance this month')
    result.fallback.append(f'**Attendance this month:** {records.count()} days checked in, {len(late)} late days ({sum(late)} late minutes).')


def shift_retrieval(result, person):
    shift = shift_for(person, timezone.localdate())
    text = (f'SHIFT today: {shift.name}, {shift.start_time:%H:%M}–{shift.end_time:%H:%M}, grace {shift.grace_minutes} min, '
            f'unpaid break {shift.break_minutes} min.' if shift else 'SHIFT: no shift is assigned and there is no default shift.')
    result.blocks.append(text)
    result.sources.append('Shift')
    result.fallback.append(f'**Shift:** {text.split(": ", 1)[1]}')


def document_retrieval(result, person):
    docs = list(EmployeeDocument.objects.filter(employee=person).order_by('-uploaded_at')[:10])
    lines = ['DOCUMENTS (latest 10):'] + ([f'- {d.title} ({d.get_document_type_display()}), {d.get_status_display()}'
                                          + (f', note: {d.review_note}' if d.review_note else '') for d in docs] or ['- No documents uploaded.'])
    result.blocks.append('\n'.join(lines))
    result.sources.append('Documents')
    result.fallback.append('**Your documents**\n' + '\n'.join(lines[1:]))


def holiday_retrieval(result):
    holidays = Holiday.objects.filter(date__gte=timezone.localdate()).order_by('date')[:6]
    lines = ['UPCOMING HOLIDAYS:'] + ([f'- {h.date:%a %d %b %Y}: {h.name} ({h.get_holiday_type_display()})' for h in holidays] or ['- None scheduled.'])
    result.blocks.append('\n'.join(lines))
    result.sources.append('Holiday calendar')
    result.fallback.append('**Upcoming holidays**\n' + '\n'.join(lines[1:]))


# --- router ------------------------------------------------------------------------------

def previous_question(conversation):
    message = conversation.messages.filter(role='user').order_by('-created_at', '-id').first() if conversation.pk else None
    return message.content if message else ''


def retrieve(conversation, question):
    """Decide what the question needs and fetch only the authorised records for it."""
    user = conversation.user
    admin = is_admin_user(user)
    person = conversation.subject if (admin and conversation.subject_id) else user
    result = Retrieval()
    lowered = question.lower()

    if not conversation.subject_id and asks_about_someone_else(lowered, user):
        result.refusal = ('I can only use your own records here. I can’t look up another person’s payslip, salary, leave, '
                          'work-from-home or attendance details, and names or IDs typed in a question are not used to fetch records.'
                          + (' As an administrator, use the Salary breakdown tab and choose the employee there, or open the '
                             'relevant admin page.' if admin else ' If you need information about someone else, please contact an administrator.'))
        return result

    intents = detect_intents(lowered)
    topical = intents - {COMPARE}
    if not topical:   # follow-up such as "and last month?" or "explain more": reuse the previous question's topic
        intents |= detect_intents(previous_question(conversation).lower()) - {COMPARE}
    feature = conversation.feature
    if feature == AIConversation.SALARY:
        intents.add(PAYSLIP)
    elif feature == AIConversation.LEAVE:
        intents.add(LEAVE)
    personal = bool(PERSONAL.search(lowered)) or feature in (AIConversation.SALARY, AIConversation.LEAVE) or bool(conversation.subject_id)
    if not topical and intents:
        personal = personal or bool(PERSONAL.search(previous_question(conversation).lower()))
    result.intents = intents
    result.personal = personal

    want_status = bool(STATUS_WORDS.search(lowered))
    if personal or conversation.payslip_id:
        if PAYSLIP in intents or COMPARE in intents and PAYSLIP in detect_intents(previous_question(conversation).lower()):
            payslip_retrieval(result, person, include_drafts=admin and bool(conversation.subject_id),
                              chosen=conversation.payslip, want_compare=COMPARE in intents)
        if STRUCTURE in intents:
            structure_retrieval(result, person)
        if LEAVE in intents:
            leave_retrieval(result, person, want_status)
        if WFH in intents:
            wfh_retrieval(result, person)
        if OVERTIME in intents:
            overtime_retrieval(result, person)
        if ATTENDANCE in intents:
            attendance_retrieval(result, person)
        if SHIFT in intents or (ATTENDANCE in intents and 'late' in lowered):
            shift_retrieval(result, person)
        if DOCUMENTS in intents:
            document_retrieval(result, person)
    if HOLIDAYS in intents:
        holiday_retrieval(result)
    return result
