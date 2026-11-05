from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from .models import Company

User = get_user_model()


class EmailOrUsernameModelBackend(ModelBackend):
    """Allow authentication via username, personal email, company email (for admins), or full name."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        identifier = str(username).strip()

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

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
