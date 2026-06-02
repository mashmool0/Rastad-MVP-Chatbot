import logging

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from adapters.factory import build_pipeline
from apps.api.serializers import (
    MessageRequestSerializer,
    MessageSerializer,
    UserSerializer,
)
from repositories.message_repository import MessageRepository
from repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

# Wired once at import time (app startup)
_pipeline = build_pipeline()
_user_repo = UserRepository()
_message_repo = MessageRepository()


@api_view(["POST"])
def message_view(request: Request) -> Response:
    serializer = MessageRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    result = _pipeline.process(
        user_id=data["user_id"],
        name=data["name"],
        message=data["message"],
    )

    return Response({
        "reply":               result.reply,
        "intent":              result.intent,
        "user_segment":        result.user_segment,
        "needs_human_support": result.needs_human_support,
        "confidence":          result.confidence,
        "chunks_used":         result.chunks_used,
        "llm_provider":        result.llm_provider,
        "fallback_used":       result.fallback_used,
        "latency_ms":          result.latency_ms,
    })


@api_view(["GET"])
def users_view(request: Request) -> Response:
    users = _user_repo.list_users()
    return Response(UserSerializer(users, many=True).data)


@api_view(["GET"])
def user_messages_view(request: Request, user_id: int) -> Response:
    messages = _message_repo.list_for_user(user_id)
    return Response(MessageSerializer(messages, many=True).data)
