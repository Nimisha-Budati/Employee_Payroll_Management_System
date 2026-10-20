import re
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.audit import record_audit
from accounts.permissions import IsAdminUserRole
from accounts.utils import is_admin_user
from payroll.models import Payslip

from . import gemini
from . import knowledge as guide
from .context import attendance_stats, build_prompt, company_attendance_stats
from .models import AIConversation, AIKnowledgeBase, AIMessage
from .retrieval import Retrieval, retrieve

HISTORY_LIMIT = 20
MAX_MESSAGE_LENGTH = 2000
DEFAULT_TITLES = dict(AIConversation.FEATURE_CHOICES)


class AIMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIMessage
        fields = ['id', 'role', 'content', 'mode', 'sources', 'created_at']


class AIConversationSerializer(serializers.ModelSerializer):
    subject_name = serializers.SerializerMethodField()
    payslip_label = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = AIConversation
        fields = ['id', 'feature', 'title', 'pinned', 'pinned_at', 'scope', 'subject_name', 'payslip', 'payslip_label', 'period_start',
                  'period_end', 'last_message', 'created_at', 'updated_at']

    def get_subject_name(self, obj):
        return (obj.subject.get_full_name() or obj.subject.username) if obj.subject_id else ''

    def get_payslip_label(self, obj):
        return f'{obj.payslip.year}-{obj.payslip.month:02d}' if obj.payslip_id else ''

    def get_last_message(self, obj):
        message = obj.messages.order_by('-created_at', '-id').first()
        return message.content[:140] if message else ''


class KnowledgeSerializer(serializers.ModelSerializer):
    updated_by_username = serializers.ReadOnlyField(source='updated_by.username')

    class Meta:
        model = AIKnowledgeBase
        fields = ['company_overview', 'leave_policy', 'faq', 'updated_by_username', 'updated_at']
        read_only_fields = ['updated_by_username', 'updated_at']
        extra_kwargs = {name: {'max_length': 8000} for name in ('company_overview', 'leave_policy', 'faq')}


def _throttled(user):
    """Simple per-user hourly cap on calls to the AI service."""
    key = f'ai-requests:{user.pk}:{int(time.time() // 3600)}'
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, 3700)
        count = 1
    return count > settings.AI_MAX_REQUESTS_PER_HOUR


def _ai_error(error):
    code = status.HTTP_429_TOO_MANY_REQUESTS if error.code in ('quota', 'rate_limited') else status.HTTP_503_SERVICE_UNAVAILABLE
    return Response({'detail': error.message, 'code': error.code}, status=code)


def _resolve_subject(request, feature, data):
    """Admins may choose an employee for salary/attendance; everyone else uses their own records."""
    raw = data.get('subject_id')
    if raw in (None, ''):
        return None
    if not is_admin_user(request.user) or feature not in (AIConversation.SALARY, AIConversation.ATTENDANCE):
        raise PermissionError('You can only ask about your own records.')
    subject = User.objects.filter(pk=raw, userprofile__role='EMPLOYEE').first() if str(raw).isdigit() else None
    if subject is None:
        raise LookupError('Employee not found.')
    return subject


def _period(data):
    today = timezone.localdate()
    start = parse_date(str(data.get('from') or '')) or (today - timedelta(days=29))
    end = parse_date(str(data.get('to') or '')) or today
    end = min(end, today)
    if start > end:
        raise ValueError('The start date must be on or before the end date.')
    if (end - start).days > 186:
        raise ValueError('Choose a period of six months or less.')
    return start, end


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ai_status(request):
    return Response({
        'enabled': gemini.is_configured(),
        'model': settings.GEMINI_MODEL if gemini.is_configured() else None,
        'features': [{'id': key, 'label': label} for key, label in AIConversation.FEATURE_CHOICES],
        'is_admin': is_admin_user(request.user),
        'hourly_limit': settings.AI_MAX_REQUESTS_PER_HOUR,
    })


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def conversation_list_create(request):
    if request.method == 'GET':
        # Always limited to the signed-in user's own conversations.
        conversations = AIConversation.objects.filter(user=request.user).select_related('subject', 'payslip')
        if request.query_params.get('feature') in DEFAULT_TITLES:
            conversations = conversations.filter(feature=request.query_params['feature'])
        if 'search' in request.query_params:
            query = ' '.join(str(request.query_params.get('search', '')).split())
            if len(query) < SEARCH_MIN:
                return Response({'search': [f'Type at least {SEARCH_MIN} characters.']}, status=status.HTTP_400_BAD_REQUEST)
            if len(query) > SEARCH_MAX:
                return Response({'search': [f'Use {SEARCH_MAX} characters or fewer.']}, status=status.HTTP_400_BAD_REQUEST)
            return Response(_search_conversations(request, conversations, query))
        return Response(AIConversationSerializer(conversations[:50], many=True).data)

    feature = request.data.get('feature')
    if feature not in DEFAULT_TITLES or feature == AIConversation.ATTENDANCE:
        return Response({'feature': ['Choose the chatbot, leave policy or salary assistant (attendance insights have their own endpoint).']},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        subject = _resolve_subject(request, feature, request.data)
    except PermissionError as error:
        return Response({'detail': str(error)}, status=status.HTTP_403_FORBIDDEN)
    except LookupError as error:
        return Response({'detail': str(error)}, status=status.HTTP_404_NOT_FOUND)

    payslip = None
    if feature == AIConversation.SALARY and request.data.get('payslip_id'):
        owner = subject or request.user
        payslip = Payslip.objects.filter(pk=request.data['payslip_id'], employee=owner).first() if str(request.data['payslip_id']).isdigit() else None
        if payslip is None or (subject is None and payslip.status != Payslip.PAID):
            return Response({'detail': 'Payslip not found.'}, status=status.HTTP_404_NOT_FOUND)

    conversation = AIConversation.objects.create(
        user=request.user, feature=feature, title=DEFAULT_TITLES[feature], scope='EMPLOYEE' if subject else 'SELF',
        subject=subject, payslip=payslip,
    )
    return Response(AIConversationSerializer(conversation).data, status=status.HTTP_201_CREATED)


TITLE_MAX = 120


def _update_conversation(request, conversation):
    """Rename and/or pin/unpin one of the user's conversations. Messages are never touched."""
    changes = {}
    if 'title' in request.data:
        title = request.data.get('title')
        if not isinstance(title, str) or not title.strip():
            return Response({'title': ['Enter a name for the conversation.']}, status=status.HTTP_400_BAD_REQUEST)
        title = ' '.join(title.split())   # trim and collapse repeated spaces
        if len(title) > TITLE_MAX:
            return Response({'title': [f'Use {TITLE_MAX} characters or fewer.']}, status=status.HTTP_400_BAD_REQUEST)
        changes['title'] = title
    wants_pin = None
    if 'pinned' in request.data:
        wants_pin = request.data.get('pinned')
        if not isinstance(wants_pin, bool):
            return Response({'pinned': ['Must be true or false.']}, status=status.HTTP_400_BAD_REQUEST)
    if not changes and wants_pin is None:
        return Response({'detail': 'Nothing to change. Send "title" and/or "pinned".'}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        # Lock the row so two quick clicks cannot pin (or unpin) the same conversation twice.
        locked = AIConversation.objects.select_for_update().get(pk=conversation.pk, user=request.user)
        if wants_pin is not None:
            if wants_pin == locked.pinned:
                return Response({'detail': 'This conversation is already pinned.' if wants_pin else 'This conversation is not pinned.',
                                 'code': 'already_pinned' if wants_pin else 'not_pinned'}, status=status.HTTP_409_CONFLICT)
            changes['pinned'] = wants_pin
            changes['pinned_at'] = timezone.now() if wants_pin else None
        # update() leaves updated_at alone, so renaming or pinning does not change the "recent activity" order.
        AIConversation.objects.filter(pk=locked.pk).update(**changes)
    conversation.refresh_from_db()
    return Response(AIConversationSerializer(conversation).data)


SEARCH_MIN, SEARCH_MAX, SEARCH_LIMIT = 2, 100, 30


def _snippet(text, query, radius=60):
    """A short plain-text excerpt of ``text`` around the first match of ``query``."""
    plain = ' '.join(re.sub(r'[*_#`>]+', '', text).split())
    index = plain.lower().find(query.lower())
    if index < 0:
        return plain[:radius * 2] + ('…' if len(plain) > radius * 2 else '')
    start, end = max(0, index - radius), min(len(plain), index + len(query) + radius)
    return ('…' if start else '') + plain[start:end] + ('…' if end < len(plain) else '')


def _search_conversations(request, conversations, query):
    """Conversations whose title or any message contains ``query`` (case-insensitive), newest activity first."""
    matching = AIMessage.objects.filter(conversation=OuterRef('pk'), content__icontains=query)
    results = list(
        conversations.filter(Q(title__icontains=query) | Exists(matching))
        .annotate(match_count=Count('messages', filter=Q(messages__content__icontains=query)))
        .order_by('-updated_at', '-id')[:SEARCH_LIMIT]
    )
    data = []
    for conversation in results:
        item = AIConversationSerializer(conversation).data
        message = conversation.messages.filter(content__icontains=query).order_by('-created_at', '-id').first()
        item['match'] = {
            'in_title': query.lower() in conversation.title.lower(),
            'message_count': conversation.match_count,
            'message_id': message.pk if message else None,
            'role': message.role if message else None,
            'snippet': _snippet(message.content, query) if message else '',
        }
        data.append(item)
    return data


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def conversation_detail(request, pk):
    # Only the owner can see, rename, pin or delete a conversation.
    conversation = AIConversation.objects.filter(pk=pk, user=request.user).select_related('subject', 'payslip').first()
    if conversation is None:
        return Response({'detail': 'Conversation not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'DELETE':
        conversation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == 'PATCH':
        return _update_conversation(request, conversation)
    return Response({
        'conversation': AIConversationSerializer(conversation).data,
        'messages': AIMessageSerializer(conversation.messages.all(), many=True).data,
    })


FALLBACK_NOTE = '_The AI service is not available right now, so here is the information straight from your PayrollPro records._'
GENERAL_FALLBACK_SCORE = 6   # minimum knowledge-match score before a guide topic is shown without the AI


def _store(conversation, question, answer, mode, sources):
    with transaction.atomic():
        user_message = AIMessage.objects.create(conversation=conversation, role='user', content=question)
        reply = AIMessage.objects.create(conversation=conversation, role='assistant', content=answer, mode=mode, sources=sources)
        if conversation.title == DEFAULT_TITLES[conversation.feature] and conversation.feature != AIConversation.ATTENDANCE:
            conversation.title = question[:80] + ('…' if len(question) > 80 else '')
        conversation.save(update_fields=['title', 'updated_at'])
    return user_message, reply


def _generate(conversation, question, retrieval):
    """Ask Gemini to explain the retrieved facts. Returns (answer text, knowledge topics used)."""
    history = list(conversation.messages.order_by('-created_at', '-id')[:HISTORY_LIMIT])[::-1]
    turns = [(message.role, message.content) for message in history] + [('user', question)]
    while turns and turns[0][0] != 'user':   # Gemini expects the conversation to start with the user
        turns.pop(0)
    instruction, topics = build_prompt(conversation, question, retrieval)
    return gemini.generate(instruction, turns), topics


def _fallback(question, retrieval):
    """A data-only answer built by PayrollPro itself, or None when there is nothing reliable to show."""
    if retrieval.fallback:
        return '\n\n'.join([FALLBACK_NOTE] + retrieval.fallback), list(retrieval.sources)
    topics, score = guide.retrieve(question, limit=1)
    if topics and score >= GENERAL_FALLBACK_SCORE:
        topic = topics[0]
        note = '_The AI service is not available right now, so here is the matching section of the PayrollPro guide._'
        return f"{note}\n\n**{topic['title']}**\n\n{topic['body']}", [f"Guide: {topic['title']}"]
    return None


def answer_question(request, conversation, question):
    """Route a question: refuse other people's data, otherwise retrieve authorised records and ask Gemini,
    falling back to PayrollPro's own data-only answer when Gemini is unavailable.
    Returns (user_message, reply, notice) or raises AIServiceError when no safe answer exists."""
    retrieval = retrieve(conversation, question)
    if retrieval.refusal:
        user_message, reply = _store(conversation, question, retrieval.refusal, 'REFUSAL', [])
        return user_message, reply, ''
    error = None
    if not gemini.is_configured():
        error = gemini.AIServiceError('not_configured')
    elif _throttled(request.user):
        error = gemini.AIServiceError('rate_limited')
    else:
        try:
            answer, topics = _generate(conversation, question, retrieval)
            sources = list(retrieval.sources) + [f"Guide: {topic['title']}" for topic in topics if topic['source'] == 'PayrollPro guide'][:2]
            user_message, reply = _store(conversation, question, answer, 'AI', sources)
            return user_message, reply, ''
        except gemini.AIServiceError as exc:
            error = exc
    fallback = _fallback(question, retrieval)
    if fallback is None:
        raise error
    user_message, reply = _store(conversation, question, fallback[0], 'DATA', fallback[1])
    return user_message, reply, error.message


def _ask(conversation, question):
    """Used by attendance insights: Gemini must produce the narrative, so there is no data-only fallback here."""
    answer, _ = _generate(conversation, question, Retrieval())
    return _store(conversation, question, answer, 'AI', ['Attendance statistics'])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def message_create(request, pk):
    # The conversation must belong to the signed-in user; identity never comes from the message text.
    conversation = AIConversation.objects.filter(pk=pk, user=request.user).select_related('subject', 'payslip', 'user').first()
    if conversation is None:
        return Response({'detail': 'Conversation not found.'}, status=status.HTTP_404_NOT_FOUND)
    question = request.data.get('message', '')
    if not isinstance(question, str) or not question.strip():
        return Response({'message': ['Type a question first.']}, status=status.HTTP_400_BAD_REQUEST)
    question = question.strip()
    if len(question) > MAX_MESSAGE_LENGTH:
        return Response({'message': [f'Use {MAX_MESSAGE_LENGTH} characters or fewer.']}, status=status.HTTP_400_BAD_REQUEST)
    try:
        user_message, reply, notice = answer_question(request, conversation, question)
    except gemini.AIServiceError as error:
        return _ai_error(error)
    payload = {
        'conversation': AIConversationSerializer(conversation).data,
        'messages': AIMessageSerializer([user_message, reply], many=True).data,
    }
    if notice:
        payload['notice'] = notice
    return Response(payload, status=status.HTTP_201_CREATED)


def _insight_target(request, data):
    scope = data.get('scope') or 'SELF'
    if scope not in ('SELF', 'EMPLOYEE', 'COMPANY'):
        raise ValueError('Unknown scope.')
    if scope != 'SELF' and not is_admin_user(request.user):
        raise PermissionError('You can only view your own attendance insights.')
    subject = None
    if scope == 'EMPLOYEE':
        subject = _resolve_subject(request, AIConversation.ATTENDANCE, {'subject_id': data.get('subject_id')})
        if subject is None:
            raise LookupError('Choose an employee.')
    return scope, subject


def _stats_for(request, scope, subject, start, end):
    if scope == 'COMPANY':
        return company_attendance_stats(start, end)
    return attendance_stats(subject or request.user, start, end)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def attendance_insight_stats(request):
    """The computed attendance figures only (works without an AI key)."""
    try:
        scope, subject = _insight_target(request, request.query_params)
        start, end = _period(request.query_params)
    except PermissionError as error:
        return Response({'detail': str(error)}, status=status.HTTP_403_FORBIDDEN)
    except LookupError as error:
        return Response({'detail': str(error)}, status=status.HTTP_404_NOT_FOUND)
    except ValueError as error:
        return Response({'detail': str(error)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'scope': scope, 'stats': _stats_for(request, scope, subject, start, end)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def attendance_insights(request):
    """Compute attendance statistics for a period and ask Gemini to turn them into insights."""
    try:
        scope, subject = _insight_target(request, request.data)
        start, end = _period(request.data)
    except PermissionError as error:
        return Response({'detail': str(error)}, status=status.HTTP_403_FORBIDDEN)
    except LookupError as error:
        return Response({'detail': str(error)}, status=status.HTTP_404_NOT_FOUND)
    except ValueError as error:
        return Response({'detail': str(error)}, status=status.HTTP_400_BAD_REQUEST)

    stats = _stats_for(request, scope, subject, start, end)
    if not gemini.is_configured():
        error = gemini.AIServiceError('not_configured')
        return Response({'stats': stats, 'detail': error.message, 'code': error.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if _throttled(request.user):
        return Response({'stats': stats, 'detail': 'You have reached the hourly limit for AI questions. Please try again later.'},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)

    who = 'the whole company' if scope == 'COMPANY' else (subject.get_full_name() or subject.username) if subject else 'me'
    conversation = AIConversation(
        user=request.user, feature=AIConversation.ATTENDANCE, scope=scope, subject=subject,
        period_start=start, period_end=end, title=f'Attendance {start:%d %b} – {end:%d %b %Y} ({who})',
    )
    prompt = (f'Generate attendance insights for {who} from {start:%d %b %Y} to {end:%d %b %Y}. Structure the answer with these '
              'headings: Summary, Patterns, Punctuality, Working hours, Suggestions. Quote the figures from the CONTEXT.')
    try:
        conversation.save()
        try:
            user_message, reply = _ask(conversation, prompt)
        except gemini.AIServiceError:
            conversation.delete()
            raise
    except gemini.AIServiceError as error:
        response = _ai_error(error)
        response.data['stats'] = stats
        return response
    if scope != 'SELF':
        record_audit(request, 'AI_INSIGHTS', 'AIKnowledge', conversation.pk,
                     f'Generated AI attendance insights for {who} ({start} to {end}).', module='AI assistance')
    return Response({
        'conversation': AIConversationSerializer(conversation).data,
        'messages': AIMessageSerializer([user_message, reply], many=True).data,
        'stats': stats,
    }, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def knowledge(request):
    kb = AIKnowledgeBase.load()
    if request.method == 'GET':
        return Response(KnowledgeSerializer(kb).data)
    serializer = KnowledgeSerializer(kb, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    kb = serializer.save(updated_by=request.user)
    record_audit(request, 'UPDATE', 'AIKnowledge', 1, f'Updated the AI knowledge base ({", ".join(sorted(serializer.validated_data)) or "no fields"}).')
    return Response(KnowledgeSerializer(kb).data)
