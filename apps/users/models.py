from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()

SEGMENT_CHOICES = [
    ("new_user", "New User"),
    ("vip_interest", "VIP Interest"),
    ("exchange_signup", "Exchange Signup"),
    ("kol_candidate", "KOL Candidate"),
    ("support_needed", "Support Needed"),
    ("general_question", "General Question"),
]


class RastadUser(models.Model):
    user_id = models.AutoField(primary_key=True)
    # nullable so the open API can create users without a Django auth account
    auth_user = models.OneToOneField(
        User, on_delete=models.CASCADE,
        related_name="rastad_profile",
        null=True, blank=True,
    )
    name = models.CharField(max_length=255)
    segment = models.CharField(max_length=50, choices=SEGMENT_CHOICES, default="new_user")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rastad_users"

    def __str__(self):
        return f"{self.name} (#{self.user_id})"
