from django.db import models

from apps.users.models import RastadUser

INTENT_CHOICES = [
    ("vip_question", "VIP Question"),
    ("exchange_registration", "Exchange Registration"),
    ("kol_collaboration", "KOL Collaboration"),
    ("support_request", "Support Request"),
    ("general_info", "General Info"),
    ("unknown", "Unknown"),
]


class Message(models.Model):
    user = models.ForeignKey(RastadUser, on_delete=models.CASCADE, related_name="messages")
    user_message = models.TextField()
    assistant_reply = models.TextField()
    intent = models.CharField(max_length=50, choices=INTENT_CHOICES)
    needs_human_support = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "messages"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user"], name="idx_message_user"),
        ]

    def __str__(self):
        return f"Message #{self.id} from user #{self.user_id}"
