import logging

from apps.messages.models import Message
from apps.users.models import RastadUser  # needed for type hint on save()

logger = logging.getLogger(__name__)


class MessageRepository:
    def save(
        self,
        user: RastadUser,
        user_message: str,
        assistant_reply: str,
        intent: str,
        needs_human_support: bool,
    ) -> Message:
        return Message.objects.create(
            user=user,
            user_message=user_message,
            assistant_reply=assistant_reply,
            intent=intent,
            needs_human_support=needs_human_support,
        )

    def list_for_user(self, user_id: int) -> list[Message]:
        return list(
            Message.objects.filter(user_id=user_id).order_by("-created_at")
        )
