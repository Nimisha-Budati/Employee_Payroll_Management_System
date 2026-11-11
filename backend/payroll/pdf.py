"""Payslip PDF — PayFlow layout (ReportLab).

Matches the web payslip exactly:
  PayFlow  (brand)
  Name · Period
  Annual package: ₹X
  Shared rates: PF X%; TDS X%; professional tax X%; other X%.

  Single table:
    Description | Amount
    Annual package
    Basic / HRA / ... (non-zero only)
    ── Gross earnings (bold) ──
    PF / TDS / Prof tax / Other / Unpaid leave (non-zero; unpaid always shown)
    ── Total deductions (bold) ──
    Net pay  (white on dark)

  Footer: employee code · designation · department · attendance summary
"""

import calendar
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Palette
INK    = colors.HexColor('#0f172a')
SUBTLE = colors.HexColor('#64748b')
LINE   = colors.HexColor('#e2e8f0')
LINE_H = colors.HexColor('#94a3b8')
DARK   = colors.HexColor('#0f172a')   # Net pay background
WHITE  = colors.white

# Two-column widths (A4 usable = ~174 mm with 18 mm margins each side)
COL_L = 128 * mm
COL_R =  46 * mm

CENT = Decimal('0.01')


def _dec(value):
    return Decimal(str(value or 0))


def format_inr(value):
    """Indian grouping, whole rupees: ₹12,34,567"""
    value = _dec(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    sign  = '-' if value < 0 else ''
    whole = str(abs(int(value)))
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ','.join(groups + [tail])
    return f'{sign}\u20b9{whole}'   # ₹


def _p(text, style):
    from xml.sax.saxutils import escape
    return Paragraph(escape(str(text)), style)


def _monthly_gross(payslip):
    fields = ('basic', 'hra', 'da', 'conveyance_allowance',
              'medical_allowance', 'special_allowance', 'other_allowance')
    return sum(_dec(getattr(payslip, f)) for f in fields)


def _rates_line(payslip, monthly_gross):
    """'Shared rates: PF X%; TDS X%; professional tax X%; other X%.'"""
    parts = []
    pf = _dec(payslip.pf_percent)
    if pf:
        parts.append(f'PF {pf:g}%')
    if monthly_gross > 0:
        def pct(amount):
            v = (_dec(amount) / monthly_gross * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            return f'{v:g}%'
        tds = _dec(payslip.tds)
        pt  = _dec(payslip.professional_tax)
        oth = _dec(payslip.other_deduction)
        if tds: parts.append(f'TDS {pct(tds)}')
        if pt:  parts.append(f'professional tax {pct(pt)}')
        if oth: parts.append(f'other {pct(oth)}')
    return ('Shared rates: ' + '; '.join(parts) + '.') if parts else ''


def render_payslip_pdf(payslip):
    company_obj  = getattr(getattr(payslip.employee, 'userprofile', None), 'company', None)
    company_name = company_obj.name if company_obj else getattr(settings, 'COMPANY_NAME', 'PayrollPro')

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm, topMargin=18*mm, bottomMargin=16*mm,
        title=f'Payslip {payslip.employee_code} {payslip.year}-{payslip.month:02d}',
        author=company_name,
    )

    base  = getSampleStyleSheet()
    small = ParagraphStyle('small', parent=base['Normal'], fontName='Helvetica',      fontSize=8,  textColor=SUBTLE, leading=11)
    body  = ParagraphStyle('body',  parent=base['Normal'], fontName='Helvetica',      fontSize=10, textColor=INK,    leading=14)
    bold  = ParagraphStyle('bold',  parent=body,           fontName='Helvetica-Bold')
    brand = ParagraphStyle('brand', parent=body,           fontName='Helvetica-Bold', fontSize=11, textColor=colors.HexColor('#4338ca'))
    hero  = ParagraphStyle('hero',  parent=body,           fontName='Helvetica-Bold', fontSize=15, leading=20)
    thlbl = ParagraphStyle('thlbl', parent=body,           fontName='Helvetica-Bold', fontSize=9,  textColor=SUBTLE)
    netl  = ParagraphStyle('netl',  parent=body,           fontName='Helvetica-Bold', fontSize=11, textColor=WHITE)
    netv  = ParagraphStyle('netv',  parent=body,           fontName='Helvetica-Bold', fontSize=14, textColor=WHITE, alignment=2)

    period       = f'{calendar.month_name[payslip.month]} {payslip.year}'
    monthly_g    = _monthly_gross(payslip)
    annual       = monthly_g * 12
    paid_days    = max(Decimal('0'), _dec(payslip.working_days) - _dec(payslip.lop_days))
    lop          = _dec(payslip.lop_days)
    rates_text   = _rates_line(payslip, monthly_g)

    story = [
        # Brand
        _p('PayFlow', brand),
        Spacer(1, 2*mm),
        # Name · Period  (single line, matches web layout)
        _p(f'{payslip.employee_name}  \u00b7  {period}', hero),
        Spacer(1, 6*mm),
    ]

    if annual:
        story.append(_p(f'Annual package: {format_inr(annual)}', bold))
        story.append(Spacer(1, 2*mm))
    if rates_text:
        story.append(_p(rates_text, small))
        story.append(Spacer(1, 6*mm))
    else:
        story.append(Spacer(1, 4*mm))

    # ── Build the table ──────────────────────────────────────────────────────
    def r(label_p, amount_p):
        return [label_p, amount_p]

    rows = [r(_p('Description', thlbl), _p('Amount', thlbl))]  # header

    # Earnings (non-zero only; Annual package always included)
    earn_defs = [
        ('Annual package',      annual),
        ('Basic',               payslip.basic),
        ('HRA',                 payslip.hra),
        ('Dearness allowance',  payslip.da),
        ('Conveyance allowance',payslip.conveyance_allowance),
        ('Medical allowance',   payslip.medical_allowance),
        ('Special allowance',   payslip.special_allowance),
        ('Other allowance',     payslip.other_allowance),
    ]
    if _dec(payslip.overtime_pay):
        earn_defs.append((f'Overtime ({payslip.overtime_hours:g} h)', payslip.overtime_pay))
    if _dec(payslip.bonus):
        earn_defs.append(('Bonus', payslip.bonus))

    for label, amount in earn_defs:
        if _dec(amount) or label == 'Annual package':
            rows.append(r(_p(label, body), _p(format_inr(amount), body)))

    # Gross earnings (bold, divider above)
    gross_idx = len(rows)   # 0-based index in `rows`
    rows.append(r(_p('Gross earnings', bold), _p(format_inr(payslip.gross_earnings), bold)))

    # Deductions
    deduct_defs = [
        ('Provident fund (PF)', payslip.pf),
        ('Income tax (TDS)',    payslip.tds),
        ('Professional tax',    payslip.professional_tax),
        ('Other deductions',    payslip.other_deduction),
        (f'Unpaid leave ({lop:g} day{"" if lop == 1 else "s"})', payslip.lop_deduction),
    ]
    for label, amount in deduct_defs:
        if _dec(amount) or label.startswith('Unpaid leave'):
            rows.append(r(_p(label, body), _p(format_inr(amount), body)))

    # Total deductions (bold, divider above)
    total_idx = len(rows)
    rows.append(r(_p('Total deductions', bold), _p(format_inr(payslip.total_deductions), bold)))

    # Net pay (white on dark, final row)
    net_idx = len(rows)
    rows.append(r(_p('Net pay', netl), _p(format_inr(payslip.net_salary), netv)))

    table = Table(rows, colWidths=[COL_L, COL_R], repeatRows=1)
    table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND',    (0, 0),  (-1, 0),  colors.HexColor('#f8fafc')),
        ('LINEBELOW',     (0, 0),  (-1, 0),  1.0, LINE_H),
        ('TOPPADDING',    (0, 0),  (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0),  (-1, -1), 6),
        ('VALIGN',        (0, 0),  (-1, -1), 'MIDDLE'),
        ('ALIGN',         (1, 0),  (1, -1),  'RIGHT'),
        # Row separator lines
        ('LINEBELOW',     (0, 1),  (-1, -4), 0.4, LINE),
        # Gross row divider
        ('LINEABOVE',     (0, gross_idx), (-1, gross_idx), 1.0, LINE_H),
        # Total row divider
        ('LINEABOVE',     (0, total_idx), (-1, total_idx), 1.0, LINE_H),
        # Net pay row: dark background, white text
        ('BACKGROUND',    (0, net_idx), (-1, net_idx), DARK),
        ('TOPPADDING',    (0, net_idx), (-1, net_idx), 10),
        ('BOTTOMPADDING', (0, net_idx), (-1, net_idx), 10),
        ('LEFTPADDING',   (0, net_idx), (-1, net_idx), 10),
        ('RIGHTPADDING',  (0, net_idx), (-1, net_idx), 10),
    ]))
    story.append(table)
    story.append(Spacer(1, 4*mm))

    # Footer: employee code · designation · department · attendance
    meta_parts = [payslip.employee_code]
    if payslip.designation: meta_parts.append(payslip.designation)
    if payslip.department:  meta_parts.append(payslip.department)
    meta_parts.append(f'{payslip.working_days} working days')
    meta_parts.append(f'{paid_days:g} paid')
    if lop: meta_parts.append(f'{lop:g} unpaid')
    story.append(_p('  \u00b7  '.join(meta_parts), small))

    if payslip.notes:
        story += [Spacer(1, 3*mm), _p(f'Note: {payslip.notes}', small)]
    story += [
        Spacer(1, 10*mm),
        _p('This is a computer-generated payslip and does not require a signature.', small),
    ]
    doc.build(story)
    return buf.getvalue()
