"""
Views for the Conversational Resume Builder.

Endpoints:
  POST   /api/v1/resume-chat/start/          — Start a new session
  GET    /api/v1/resume-chat/                 — List user's sessions
  GET    /api/v1/resume-chat/<id>/            — Get session with messages
  POST   /api/v1/resume-chat/<id>/submit/     — Submit action for current step
  POST   /api/v1/resume-chat/<id>/finalize/   — Generate PDF/DOCX
  DELETE /api/v1/resume-chat/<id>/            — Delete session
  GET    /api/v1/resume-chat/resumes/         — List resumes for base selection
"""
import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.throttles import WriteThrottle, ReadOnlyThrottle
from accounts.services import (
    deduct_credits, refund_credits, check_balance,
    InsufficientCreditsError,
)
from .models import ResumeChat, GeneratedResume, ResumeTemplate
from .serializers import (
    ResumeChatSerializer,
    ResumeChatListSerializer,
    ResumeChatStartSerializer,
    ResumeChatSubmitSerializer,
    ResumeChatFinalizeSerializer,
    ResumeChatMessageSerializer,
    ResumeChatTextMessageSerializer,
)
from .services.resume_chat_service import (
    start_session,
    process_step,
    process_text_message,
    finalize_resume,
    get_user_resumes_for_selection,
)

logger = logging.getLogger('analyzer')


class ResumeChatStartView(APIView):
    """
    POST /api/v1/resume-chat/start/
    Start a new resume builder chat session.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def post(self, request):
        serializer = ResumeChatStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source = serializer.validated_data['source']
        base_resume_id = serializer.validated_data.get('base_resume_id')

        # Limit active sessions per user (max 5)
        active_count = ResumeChat.objects.filter(
            user=request.user, status=ResumeChat.STATUS_ACTIVE,
        ).count()
        if active_count >= 5:
            return Response(
                {'detail': 'Maximum 5 active resume chat sessions. Please complete or delete an existing session.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        chat = start_session(
            user=request.user,
            source=source,
            base_resume_id=str(base_resume_id) if base_resume_id else None,
        )

        data = ResumeChatSerializer(chat).data
        return Response(data, status=status.HTTP_201_CREATED)


class ResumeChatListView(APIView):
    """
    GET /api/v1/resume-chat/
    List the current user's resume chat sessions.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        chats = ResumeChat.objects.filter(user=request.user).order_by('-updated_at')

        # Optional status filter
        status_filter = request.query_params.get('status')
        if status_filter in ('active', 'completed', 'abandoned'):
            chats = chats.filter(status=status_filter)

        data = ResumeChatListSerializer(chats[:20], many=True).data
        return Response(data)


class ResumeChatDetailView(APIView):
    """
    GET    /api/v1/resume-chat/<id>/  — Get session detail with all messages
    DELETE /api/v1/resume-chat/<id>/  — Delete session
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request, pk):
        try:
            chat = ResumeChat.objects.prefetch_related('messages').get(
                id=pk, user=request.user,
            )
        except ResumeChat.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = ResumeChatSerializer(chat).data
        return Response(data)

    def delete(self, request, pk):
        try:
            chat = ResumeChat.objects.get(id=pk, user=request.user)
        except ResumeChat.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        chat.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResumeChatSubmitView(APIView):
    """
    POST /api/v1/resume-chat/<id>/submit/
    Submit an action/answer for the current step.

    Body: {"action": "continue", "payload": {...}}
    Returns the new messages created (user echo + assistant response).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def post(self, request, pk):
        try:
            chat = ResumeChat.objects.get(
                id=pk, user=request.user, status=ResumeChat.STATUS_ACTIVE,
            )
        except ResumeChat.DoesNotExist:
            return Response(
                {'detail': 'Chat session not found or not active.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ResumeChatSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data['action']
        payload = serializer.validated_data.get('payload', {})

        try:
            new_messages = process_step(chat, action, payload)
        except Exception as exc:
            logger.exception('Error processing chat step: chat=%s action=%s', pk, action)
            return Response(
                {'detail': 'An unexpected error occurred while processing your request. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Refresh chat to get updated state
        chat.refresh_from_db()

        messages_data = ResumeChatMessageSerializer(new_messages, many=True).data
        return Response({
            'messages': messages_data,
            'current_step': chat.current_step,
            'step_number': chat.step_number,
            'total_steps': chat.total_steps,
            'status': chat.status,
        })


class ResumeChatTextMessageView(APIView):
    """
    POST /api/v1/resume-chat/<id>/message/
    Send a free-text message in text chat mode.

    Body: {"text": "I'm John Doe, john@doe.com, based in Mumbai"}
    Returns the assistant's response, updated resume_data, and progress.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def post(self, request, pk):
        try:
            chat = ResumeChat.objects.get(
                id=pk, user=request.user, status=ResumeChat.STATUS_ACTIVE,
            )
        except ResumeChat.DoesNotExist:
            return Response(
                {'detail': 'Chat session not found or not active.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if chat.mode != ResumeChat.MODE_TEXT:
            return Response(
                {'detail': 'This session uses guided mode. Use the /submit/ endpoint instead.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Limit messages per session (prevent abuse)
        msg_count = chat.messages.filter(role='user').count()
        if msg_count >= 50:
            return Response(
                {'detail': 'Message limit reached for this session. Please finalize or start a new session.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ResumeChatTextMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_text = serializer.validated_data['text']

        try:
            result = process_text_message(chat, user_text)
        except Exception as exc:
            logger.exception('Error processing text message: chat=%s', pk)
            return Response(
                {'detail': 'An unexpected error occurred while processing your message. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            'user_message': ResumeChatMessageSerializer(result['user_message']).data,
            'assistant_message': ResumeChatMessageSerializer(result['assistant_message']).data,
            'resume_data': result['resume_data'],
            'progress': result['progress'],
        })


class ResumeChatFinalizeView(APIView):
    """
    POST /api/v1/resume-chat/<id>/finalize/
    Generate the final PDF/DOCX from the chat session's resume_data.

    Deducts credits and dispatches a Celery task for rendering.
    Body: {"template": "ats_classic", "format": "pdf"}
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [WriteThrottle]

    def post(self, request, pk):
        try:
            chat = ResumeChat.objects.get(
                id=pk, user=request.user, status=ResumeChat.STATUS_ACTIVE,
            )
        except ResumeChat.DoesNotExist:
            return Response(
                {'detail': 'Chat session not found or not active.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ResumeChatFinalizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        template = serializer.validated_data['template']
        fmt = serializer.validated_data['format']

        # ── Plan gating for premium templates ──
        template_obj = getattr(serializer, '_template_obj', None)
        if template_obj and template_obj.is_premium:
            profile = getattr(request.user, 'profile', None)
            has_access = (
                profile
                and profile.plan
                and profile.plan.premium_templates
                and (
                    profile.plan.billing_cycle == 'free'
                    or not profile.plan_valid_until
                    or profile.plan_valid_until >= timezone.now()
                )
            )
            if not has_access:
                return Response(
                    {
                        'detail': 'Premium template requires a paid plan with premium templates enabled.',
                        'template': template,
                        'is_premium': True,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        # ── Credit check & deduct ──
        try:
            credit_result = deduct_credits(
                request.user,
                'resume_builder',
                description=f'Resume builder (chat #{str(chat.id)[:8]})',
                reference_id=str(chat.id),
            )
        except InsufficientCreditsError as e:
            return Response(
                {
                    'detail': 'Insufficient credits.',
                    'balance': e.balance,
                    'cost': e.cost,
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        try:
            gen = finalize_resume(chat, template, fmt)

            # Dispatch Celery task for rendering
            from .tasks import render_builder_resume_task
            render_builder_resume_task.delay(str(gen.id))

            logger.info(
                'Resume builder finalized: chat=%s gen=%s template=%s format=%s',
                chat.id, gen.id, template, fmt,
            )

            from .models import UserActivity
            UserActivity.record(request.user, UserActivity.ACTION_BUILDER_FINALIZE)

            return Response(
                {
                    'id': str(gen.id),
                    'status': gen.status,
                    'template': gen.template,
                    'format': gen.format,
                    'credits_used': credit_result['cost'],
                    'balance': credit_result['balance_after'],
                },
                status=status.HTTP_202_ACCEPTED,
            )
        except ValueError as exc:
            refund_credits(
                request.user, 'resume_builder',
                description='Refund: resume builder finalize failed',
                reference_id=str(chat.id),
            )
            return Response(
                {'detail': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            refund_credits(
                request.user, 'resume_builder',
                description='Refund: resume builder finalize failed',
                reference_id=str(chat.id),
            )
            raise


class ResumeChatResumesView(APIView):
    """
    GET /api/v1/resume-chat/resumes/
    List the user's resumes available for "use as base" selection.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadOnlyThrottle]

    def get(self, request):
        resumes = get_user_resumes_for_selection(request.user)
        return Response({'resumes': resumes})
