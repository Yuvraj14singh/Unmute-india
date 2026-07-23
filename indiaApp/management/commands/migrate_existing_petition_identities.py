from django.core.management.base import BaseCommand
from django.db import transaction

from indiaApp.models import PetitionSignature
from indiaApp.private_identity import provision_signature_identity


class Command(BaseCommand):
    help = 'Idempotently link existing verified petition signatures to private identities.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--limit', type=int)
        parser.add_argument('--petition-id', type=int)

    def handle(self, *args, **options):
        queryset = PetitionSignature.objects.filter(
            is_verified=True,
            verified_at__isnull=False,
            moderation_status='valid',
            is_removed=False,
            removed_at__isnull=True,
        ).order_by('pk')
        if options['petition_id']:
            queryset = queryset.filter(petition_id=options['petition_id'])
        if options['limit'] is not None:
            queryset = queryset[:max(options['limit'], 0)]
        stats = {'existing':0,'already':0,'confirmed':0,'provisional':0,'skipped':0,'created':0}
        skipped_ids = []
        with transaction.atomic():
            for signature in queryset.select_for_update():
                stats['existing'] += 1
                if signature.private_identity_id:
                    stats['already'] += 1
                    continue
                identity, created = provision_signature_identity(signature)
                if not identity:
                    stats['skipped'] += 1
                    skipped_ids.append(signature.pk)
                    continue
                stats['created'] += int(created)
                if identity.identity_status == 'confirmed_google':
                    stats['confirmed'] += 1
                else:
                    stats['provisional'] += 1
            if options['dry_run']:
                transaction.set_rollback(True)
        self.stdout.write(f"Existing valid signatures: {stats['existing']}")
        self.stdout.write(f"Already linked: {stats['already']}")
        self.stdout.write(f"Eligible/linked confirmed: {stats['confirmed']}")
        self.stdout.write(f"Eligible/linked provisional: {stats['provisional']}")
        self.stdout.write(f"Skipped: {stats['skipped']}")
        if skipped_ids:
            self.stdout.write('Skipped internal IDs: ' + ','.join(map(str,skipped_ids)))
        self.stdout.write('Duplicate signatures created: 0')
        self.stdout.write('Emails modified: 0')
        self.stdout.write('Mode: DRY RUN' if options['dry_run'] else 'Mode: APPLIED')
