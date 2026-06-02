import logging

from apps.users.models import RastadUser

logger = logging.getLogger(__name__)


class UserRepository:
    def get_or_create(self, user_id: int | None, name: str) -> RastadUser:
        if user_id:
            user, created = RastadUser.objects.get_or_create(
                user_id=user_id,
                defaults={"name": name},
            )
            if created:
                logger.info("REQUEST | new user created user_id=%s name=%s", user_id, name)
            return user

        user = RastadUser.objects.create(name=name)
        logger.info("REQUEST | new user created user_id=%s name=%s", user.user_id, name)
        return user

    def update_last_seen_and_segment(self, user: RastadUser, segment: str) -> None:
        # auto_now=True on last_seen_at means save() updates it automatically
        user.segment = segment
        user.save(update_fields=["segment", "last_seen_at"])
