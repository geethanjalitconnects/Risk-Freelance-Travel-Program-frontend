"""Create the first admin from ADMIN_USERNAME / ADMIN_PASSWORD (environment or .env).

    python manage.py seed_admin

Safe to run again: if the username already exists, nothing changes (the password is not reset).
The admin must choose a new password at first sign-in.
"""
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Create the first dashboard admin from ADMIN_USERNAME and ADMIN_PASSWORD (skipped if it exists)."

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME", "").strip()
        password = os.environ.get("ADMIN_PASSWORD", "")
        if not username or not password:
            raise CommandError("Set ADMIN_USERNAME and ADMIN_PASSWORD (environment or backend/.env).")

        User = get_user_model()
        with transaction.atomic():
            if User.objects.select_for_update().filter(username=username).exists():
                self.stdout.write(f"Admin '{username}' already exists; nothing changed.")
                return
            candidate = User(username=username, name=os.environ.get("ADMIN_NAME", "Administrator"))
            try:
                validate_password(password, candidate)
            except ValidationError as e:
                raise CommandError("ADMIN_PASSWORD is too weak: " + " ".join(e.messages))
            User.objects.create_admin(
                username, password, name=candidate.name, email=os.environ.get("ADMIN_EMAIL", ""), must_change_password=True
            )
        self.stdout.write(self.style.SUCCESS(f"Created admin '{username}'. They must change the password at first sign-in."))
