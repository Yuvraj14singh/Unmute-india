import hashlib
import hmac
import uuid

from django.conf import settings


COOKIE_NAME = 'unmute_anonymous_id'
COOKIE_MAX_AGE = 60 * 60 * 24 * 365


class AnonymousReactionCookieMiddleware:
    """Provide a stable, non-identifying browser key for reaction idempotency."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw = request.COOKIES.get(COOKIE_NAME, '')
        should_set = False
        try:
            raw = str(uuid.UUID(raw))
        except (ValueError, TypeError, AttributeError):
            raw = str(uuid.uuid4())
            should_set = True
        request.anonymous_reaction_key = hmac.new(
            settings.SECRET_KEY.encode(),
            raw.encode(),
            hashlib.sha256,
        ).hexdigest()
        response = self.get_response(request)
        if should_set:
            response.set_cookie(
                COOKIE_NAME,
                raw,
                max_age=COOKIE_MAX_AGE,
                secure=not settings.DEBUG,
                httponly=True,
                samesite='Lax',
            )
        return response
