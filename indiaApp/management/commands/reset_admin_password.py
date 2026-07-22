import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Update an existing user's admin access and password from environment variables."

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME")
        password = os.environ.get("ADMIN_PASSWORD")

        if not username or not password:
            raise CommandError(
                "Admin was not updated: ADMIN_USERNAME and ADMIN_PASSWORD are required."
            )

        User = get_user_model()

        try:
            user = User._default_manager.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError("Admin was not updated: user does not exist.") from exc

        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save(
            update_fields=["password", "is_staff", "is_superuser", "is_active"]
        )

        self.stdout.write(self.style.SUCCESS("Admin successfully updated."))
