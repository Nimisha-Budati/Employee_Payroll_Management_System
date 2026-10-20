"""Payslip PDF rendering (ReportLab)."""

import calendar
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor('#0f172a')
MUTED = colors.HexColor('#64748b')
LINE = colors.HexColor('#e2e8f0')
ACCENT = colors.HexColor('#4338ca')
SOFT = colors.HexColor('#f8fafc')


def format_inr(value):
    """Format with Indian digit grouping, e.g. 1234567.5 -> 'INR 12,34,567.50'."""
    value = Decimal(value).quantize(Decimal('0.01'))
    sign = '-' if value < 0 else ''
    whole, _, fraction = f'{abs(value):.2f}'.partition('.')
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ','.join(groups + [tail])
    return f'{sign}INR {whole}.{fraction}'


def _paragraph(text, style):
    from xml.sax.saxutils import escape
    return Paragraph(escape(str(text)), style)


def render_payslip_pdf(payslip):
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f'Payslip {payslip.employee_code} {payslip.year}-{payslip.month:02d}',
        author=settings.COMPANY_NAME,
    )
    base = getSampleStyleSheet()
    small = ParagraphStyle('small', parent=base['Normal'], fontName='Helvetica', fontSize=9, textColor=MUTED, leading=12)
    body = ParagraphStyle('body', parent=base['Normal'], fontName='Helvetica', fontSize=10, textColor=INK, leading=13)
    bold = ParagraphStyle('bold', parent=body, fontName='Helvetica-Bold')
    title = ParagraphStyle('title', parent=body, fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=INK)
    company = ParagraphStyle('company', parent=body, fontName='Helvetica-Bold', fontSize=11, textColor=ACCENT)

    period = f'{calendar.month_name[payslip.month]} {payslip.year}'
    story = [
        _paragraph(settings.COMPANY_NAME, company),
        Spacer(1, 2 * mm),
        _paragraph(f'Payslip - {period}', title),
        Spacer(1, 6 * mm),
    ]

    paid_days = max(Decimal('0'), Decimal(payslip.working_days) - payslip.lop_days)
    info = [
        [_paragraph('Employee', small), _paragraph(payslip.employee_name, bold), _paragraph('Employee ID', small), _paragraph(payslip.employee_code, bold)],
        [_paragraph('Department', small), _paragraph(payslip.department or '-', body), _paragraph('Designation', small), _paragraph(payslip.designation or '-', body)],
        [_paragraph('Working days', small), _paragraph(payslip.working_days, body), _paragraph('Paid days', small), _paragraph(f'{paid_days:g}', body)],
        [_paragraph('Loss of pay days', small), _paragraph(f'{payslip.lop_days:g}', body), _paragraph('Status', small), _paragraph(payslip.get_status_display(), body)],
    ]
    info_table = Table(info, colWidths=[32 * mm, 54 * mm, 32 * mm, 54 * mm])
    info_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.6, LINE),
        ('BACKGROUND', (0, 0), (-1, -1), SOFT),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story += [info_table, Spacer(1, 6 * mm)]

    earnings = [
        ('Basic pay', payslip.basic),
        ('House rent allowance', payslip.hra),
        ('Dearness allowance', payslip.da),
        ('Conveyance allowance', payslip.conveyance_allowance),
        ('Medical allowance', payslip.medical_allowance),
        ('Special allowance', payslip.special_allowance),
        ('Other allowance', payslip.other_allowance),
        ('Overtime pay', payslip.overtime_pay),
        ('Bonus', payslip.bonus),
    ]
    deductions = [
        (f'Provident fund ({payslip.pf_percent:g}%)', payslip.pf),
        ('Professional tax', payslip.professional_tax),
        ('Income tax (TDS)', payslip.tds),
        ('Loss of pay', payslip.lop_deduction),
        ('Other deductions', payslip.other_deduction),
    ]
    earnings = [row for row in earnings if row[1] or row[0] == 'Basic pay']
    deductions = [row for row in deductions if row[1]]
    rows = [[_paragraph('Earnings', bold), _paragraph('Amount', bold), _paragraph('Deductions', bold), _paragraph('Amount', bold)]]
    for index in range(max(len(earnings), len(deductions), 1)):
        left = earnings[index] if index < len(earnings) else ('', None)
        right = deductions[index] if index < len(deductions) else ('', None)
        rows.append([
            _paragraph(left[0], body), _paragraph(format_inr(left[1]) if left[1] is not None else '', body),
            _paragraph(right[0], body), _paragraph(format_inr(right[1]) if right[1] is not None else '', body),
        ])
    rows.append([
        _paragraph('Gross earnings', bold), _paragraph(format_inr(payslip.gross_earnings), bold),
        _paragraph('Total deductions', bold), _paragraph(format_inr(payslip.total_deductions), bold),
    ])
    table = Table(rows, colWidths=[46 * mm, 40 * mm, 46 * mm, 40 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), SOFT),
        ('LINEBELOW', (0, 0), (-1, 0), 0.8, INK),
        ('LINEBELOW', (0, 1), (-1, -2), 0.4, LINE),
        ('LINEABOVE', (0, -1), (-1, -1), 0.8, INK),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story += [table, Spacer(1, 6 * mm)]

    net = Table(
        [[_paragraph('Net salary', ParagraphStyle('netl', parent=bold, textColor=colors.white, fontSize=11)),
          _paragraph(format_inr(payslip.net_salary), ParagraphStyle('netv', parent=bold, textColor=colors.white, fontSize=14, alignment=2))]],
        colWidths=[86 * mm, 86 * mm],
    )
    net.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), ACCENT),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(net)
    if payslip.notes:
        story += [Spacer(1, 4 * mm), _paragraph(f'Note: {payslip.notes}', small)]
    story += [
        Spacer(1, 10 * mm),
        _paragraph('This is a computer-generated payslip and does not require a signature.', small),
    ]
    document.build(story)
    return buffer.getvalue()
