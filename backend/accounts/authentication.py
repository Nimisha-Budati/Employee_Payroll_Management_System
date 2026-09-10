from rest_framework.authentication import SessionAuthentication


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """Use the existing session login for the separately hosted frontend.

    The leave API is explicitly CSRF-exempt and is consumed from the local
    frontend development server, so DRF must not reject the session before
    the view is reached.
    """

    def enforce_csrf(self, request):
        return
