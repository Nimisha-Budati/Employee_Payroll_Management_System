from rest_framework.authentication import SessionAuthentication


class ApiSessionAuthentication(SessionAuthentication):
    """Session authentication that answers unauthenticated requests with 401 (not 403).

    CSRF validation is inherited and stays enabled for unsafe methods. The
    ``WWW-Authenticate`` value makes DRF choose 401, which the frontend uses to
    send signed-out users back to the login page.
    """

    def authenticate_header(self, request):
        return 'Session'
