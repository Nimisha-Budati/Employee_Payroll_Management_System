import logging
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from .models import Company

User = get_user_model()
logger = logging.getLogger('accounts.auth')


class EmailOrUsernameModelBackend(ModelBackend):
    """Allow authentication via username, personal email, company email (for admins), or full name."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        # Normalize whitespace (handles standard and unicode spaces e.g. non-breaking spaces)
        identifier = ' '.join(str(username).split())

        user = None
        # 1. By exact username (case-insensitive)
        user = User.objects.filter(username__iexact=identifier).first()

        # 2. By user email (case-insensitive)
        if user is None:
            user = User.objects.filter(email__iexact=identifier).first()

        # 3. By company email for company admin
        if user is None:
            company = Company.objects.filter(email__iexact=identifier).first()
            if company:
                admin_profile = company.profiles.filter(role='ADMIN').first()
                if admin_profile:
                    user = admin_profile.user

        # 4. By full name if matches uniquely
        if user is None and ' ' in identifier:
            first, _, last = identifier.partition(' ')
            candidates = list(User.objects.filter(first_name__iexact=first, last_name__iexact=last))
            if len(candidates) == 1:
                user = candidates[0]

        if user and self.user_can_authenticate(user):
            # Direct password check
            if user.check_password(password):
                return user
            # Fallback for mobile clipboard artifacts (trailing/leading whitespace or trailing newlines)
            if isinstance(password, str):
                trimmed = password.strip()
                if trimmed != password and user.check_password(trimmed):
                    logger.info("User authenticated via trimmed password fallback for user id=%s", user.pk)
                    return user
                without_newline = password.rstrip('\r\n')
                if without_newline != password and user.check_password(without_newline):
                    logger.info("User authenticated via newline-stripped password fallback for user id=%s", user.pk)
                    return user
        return None
