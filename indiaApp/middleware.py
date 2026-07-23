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
        request.private_identity = None
        identity_id = request.session.get('private_identity_id')
        if identity_id:
            from .models import PrivateIdentity
            request.private_identity = PrivateIdentity.objects.filter(
                pk=identity_id,
                is_active=True,
                sync_consent_at__isnull=False,
            ).first()
            if request.private_identity is None:
                request.session.pop('private_identity_id', None)
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
