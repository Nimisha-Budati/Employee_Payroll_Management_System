"""Verified project knowledge for the AI assistants.

``knowledge/guide.md`` is split into topics (one per ``## `` heading). For each question the
best-matching topics are retrieved by keyword overlap and sent to the model, so general answers
come from documented PayrollPro behaviour instead of the model's general knowledge. Text written
by administrators in the AI knowledge base (company overview, leave policy, FAQ) is added as
separate, clearly labelled topics.
"""

import re
from functools import lru_cache
from pathlib import Path


from .models import AIKnowledgeBase

GUIDE_PATH = Path(__file__).resolve().parent / 'knowledge' / 'guide.md'
STOPWORDS = {
    'a', 'an', 'the', 'is', 'are', 'am', 'was', 'were', 'be', 'to', 'of', 'in', 'on', 'for', 'and', 'or', 'do', 'does',
    'did', 'how', 'what', 'why', 'when', 'where', 'which', 'who', 'can', 'could', 'i', 'my', 'me', 'you', 'your', 'it',
    'this', 'that', 'with', 'about', 'please', 'tell', 'show', 'explain', 'there', 'any', 'have', 'has', 'get', 'much',
    'many', 'will', 'would', 'should', 'from', 'at', 'by', 'as', 'so', 'if', 'than', 'then', 'its', 'we', 'our', 'hi',
    'hello', 'hey', 'thanks', 'thank', 'ok', 'okay',
}


def tokens(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = set()
    for word in words:
        if word in STOPWORDS or len(word) < 2:
            continue
        out.add(word)
        if len(word) > 4 and word.endswith('s'):
            out.add(word[:-1])
    return out


def _entitlements_text():
    """The current leave policy from the database (administrators change it on the Leave policy page)."""
    from accounts.leave_policy import leave_year_label, leave_year_of, policy_settings
    from accounts.models import LeaveType
    from django.utils import timezone

    rules = policy_settings()
    lines = []
    for leave_type in LeaveType.objects.filter(is_active=True):
        limit = f'{leave_type.annual_days} days per leave year' if leave_type.annual_days is not None else 'no annual limit'
        carry = f'; up to {leave_type.max_carry_forward_days} unused days can be carried forward' if leave_type.allow_carry_forward else ''
        lines.append(f'- **{leave_type.name}**: {limit}, {"paid" if leave_type.is_paid else "unpaid (loss of pay)"}{carry}.'
                     + (f' {leave_type.description}' if leave_type.description else ''))
    year = leave_year_of(timezone.localdate(), rules)
    lines.append(f'- The current leave year is {leave_year_label(year, rules)}.')
    if rules.min_notice_days:
        lines.append(f'- Apply at least {rules.min_notice_days} day(s) before the leave starts.')
    if rules.max_days_per_request:
        lines.append(f'- One request can cover at most {rules.max_days_per_request} day(s).')
    if not rules.allow_past_dates:
        lines.append('- Leave cannot be applied for dates in the past.')
    return '\n'.join(lines) or '- No leave types are configured yet.'


@lru_cache(maxsize=1)
def _guide_sections():
    raw = GUIDE_PATH.read_text(encoding='utf-8')
    raw = re.sub(r'<!--.*?-->', '', raw, flags=re.S)
    sections = []
    for block in re.split(r'^## ', raw, flags=re.M)[1:]:
        title, _, body = block.partition('\n')
        keywords = ''
        lines = []
        for line in body.strip().splitlines():
            if line.startswith('Keywords:'):
                keywords = line[len('Keywords:'):]
            else:
                lines.append(line)
        sections.append({'title': title.strip(), 'body': '\n'.join(lines).strip(), 'keywords': keywords})
    return sections


def sections():
    """All verified topics with dynamic values filled in, plus administrator-written topics."""
    result = []
    for section in _guide_sections():
        body = section['body'].replace('{leave_entitlements}', _entitlements_text())
        result.append({'title': section['title'], 'body': body, 'source': 'PayrollPro guide',
                       'tokens': tokens(f"{section['title']} {section['keywords']}"), 'body_tokens': tokens(body)})
    kb = AIKnowledgeBase.load()
    for field, title, extra in (
        ('company_overview', 'Company overview (written by administrators)', 'company organisation office timing contact hr about'),
        ('leave_policy', 'Organisation leave policy (written by administrators)', 'leave policy rule notice sick casual earned'),
        ('faq', 'Frequently asked questions (written by administrators)', 'faq question'),
    ):
        text = getattr(kb, field).strip()
        if text:
            result.append({'title': title, 'body': text, 'source': 'Administrator knowledge base', 'field': field,
                           'tokens': tokens(f'{title} {extra}'), 'body_tokens': tokens(text)})
    return result


def retrieve(question, limit=3, always=()):
    """Return (best topics, best score). ``always`` forces topics with these titles or KB fields to be included."""
    query = tokens(question)
    scored = []
    for section in sections():
        score = 3 * len(query & section['tokens']) + len(query & section['body_tokens'])
        forced = section['title'] in always or section.get('field') in always
        if score or forced:
            scored.append((score + (100 if forced else 0), section))
    scored.sort(key=lambda item: -item[0])
    picked = [section for score, section in scored[:limit + len(always)] if score >= 3 or score >= 100]
    best = max((score for score, section in scored if score < 100), default=0)
    return picked, best


def render(topics):
    return '\n\n'.join(f"### {topic['title']} ({topic['source']})\n{topic['body']}" for topic in topics)
