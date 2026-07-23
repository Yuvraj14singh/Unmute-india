import hashlib
import hmac

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import CommentReaction, ListeningRequest, PetitionSignature, PrivateIdentity, StoryReaction


def _purpose_hash(value, purpose):
    key = settings.PRIVATE_IDENTITY_HMAC_KEY.encode()
    return hmac.new(key, f'{purpose}:{value}'.encode(), hashlib.sha256).hexdigest()


def google_subject_hash(subject):
    return _purpose_hash(str(subject), 'google-sub')


def legacy_email_hash(email):
    return _purpose_hash((email or '').strip().casefold(), 'verified-email')


def provision_signature_identity(signature):
    """Link a verified signature without changing any of its original fields."""
    if signature.private_identity_id:
        return signature.private_identity, False
    if signature.google_subject:
        lookup = {'google_sub_hash': google_subject_hash(signature.google_subject)}
        defaults = {
            'legacy_email_hash': legacy_email_hash(signature.verified_email or signature.email),
            'identity_status': 'confirmed_google',
            'source': 'petition_migration',
        }
    elif signature.is_verified and (signature.verified_email or signature.email):
        lookup = {'legacy_email_hash': legacy_email_hash(signature.verified_email or signature.email)}
        defaults = {
            'identity_status': 'provisional_legacy',
            'source': 'petition_migration',
        }
    else:
        return None, False
    identity, created = PrivateIdentity.objects.get_or_create(**lookup, defaults=defaults)
    PetitionSignature.objects.filter(pk=signature.pk, private_identity__isnull=True).update(private_identity=identity)
    return identity, created


@transaction.atomic
def resolve_google_identity(subject, verified_email, consent=False):
    """Resolve Google proof, safely upgrading an email-only provisional identity."""
    subject_digest = google_subject_hash(subject)
    email_digest = legacy_email_hash(verified_email)
    confirmed = PrivateIdentity.objects.select_for_update().filter(
        google_sub_hash=subject_digest, is_active=True
    ).first()
    provisional = PrivateIdentity.objects.select_for_update().filter(
        legacy_email_hash=email_digest,
        identity_status='provisional_legacy',
        is_active=True,
    ).first()
    if confirmed:
        identity = confirmed
        if provisional and provisional.pk != confirmed.pk:
            _merge_identity_rows(provisional, confirmed)
    elif provisional:
        provisional.google_sub_hash = subject_digest
        provisional.identity_status = 'confirmed_google'
        provisional.source = 'google_sync'
        identity = provisional
    else:
        identity = PrivateIdentity(
            google_sub_hash=subject_digest,
            legacy_email_hash=email_digest,
            identity_status='confirmed_google',
            source='google_sync',
        )
    identity.last_seen_at = timezone.now()
    if consent and not identity.sync_consent_at:
        identity.sync_consent_at = timezone.now()
    identity.save()

    # Linking is identity restoration only. It never creates or modifies a signature.
    signatures = PetitionSignature.objects.select_for_update().filter(
        private_identity__isnull=True,
        is_verified=True,
        moderation_status='valid',
        is_removed=False,
        removed_at__isnull=True,
    ).filter(
        models_q_for_existing_signer(subject, verified_email)
    )
    signatures.update(private_identity=identity)
    return identity


def models_q_for_existing_signer(subject, verified_email):
    from django.db.models import Q
    email = (verified_email or '').strip().casefold()
    return Q(google_subject=subject) | Q(normalized_email=email) | Q(verified_email__iexact=email)


def _merge_identity_rows(source, target):
    for reaction in StoryReaction.objects.select_for_update().filter(private_identity=source):
        duplicate = StoryReaction.objects.filter(
            story=reaction.story,
            private_identity=target,
            reaction=reaction.reaction,
        ).exclude(pk=reaction.pk).exists()
        if duplicate:
            reaction.delete()
        else:
            reaction.private_identity = target
            reaction.save(update_fields=['private_identity'])
    for reaction in CommentReaction.objects.select_for_update().filter(private_identity=source):
        duplicate = CommentReaction.objects.filter(
            comment=reaction.comment,
            private_identity=target,
        ).exclude(pk=reaction.pk).exists()
        if duplicate:
            reaction.delete()
        else:
            reaction.private_identity = target
            reaction.save(update_fields=['private_identity'])
    ListeningRequest.objects.filter(private_identity=source).update(private_identity=target)
    PetitionSignature.objects.filter(private_identity=source).update(private_identity=target)
    source.identity_status = 'merged'
    source.is_active = False
    source.merged_into = target
    source.save(update_fields=['identity_status', 'is_active', 'merged_into', 'updated_at'])


@transaction.atomic
def merge_guest_activity(identity, guest_key):
    """Idempotently move one browser's private activity to a consented identity."""
    if not guest_key:
        return
    for reaction in StoryReaction.objects.select_for_update().filter(
        anonymous_key=guest_key, private_identity__isnull=True
    ):
        duplicate = StoryReaction.objects.filter(
            story=reaction.story,
            reaction=reaction.reaction,
            private_identity=identity,
        ).exists()
        if duplicate:
            reaction.delete()
        else:
            reaction.private_identity = identity
            reaction.anonymous_key = ''
            reaction.save(update_fields=['private_identity', 'anonymous_key'])
    for reaction in CommentReaction.objects.select_for_update().filter(
        session_key_hash=guest_key, private_identity__isnull=True
    ):
        duplicate = CommentReaction.objects.filter(
            comment=reaction.comment,
            private_identity=identity,
        ).exists()
        if duplicate:
            reaction.delete()
        else:
            reaction.private_identity = identity
            reaction.save(update_fields=['private_identity'])
    ListeningRequest.objects.filter(
        guest_key=guest_key, private_identity__isnull=True
    ).update(private_identity=identity, guest_key='')
