from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q

from indiaApp.models import Petition, PetitionSignature


class Command(BaseCommand):
    help = 'Safely audit petition signatures and private-identity migration eligibility.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Accepted for deployment runbook clarity; this command never writes.')
        parser.add_argument('--limit', type=int)
        parser.add_argument('--petition-id', type=int)

    def handle(self, *args, **options):
        signatures = PetitionSignature.objects.all()
        if options['petition_id']:
            signatures = signatures.filter(petition_id=options['petition_id'])
        if options['limit']:
            ids = signatures.order_by('pk').values_list('pk', flat=True)[:max(options['limit'], 0)]
            signatures = signatures.filter(pk__in=ids)
        table=PetitionSignature._meta.db_table
        with connection.cursor() as cursor:
            columns={column.name for column in connection.introspection.get_table_description(cursor,table)}
        identity_schema_ready='private_identity_id' in columns
        valid = signatures.filter(
            is_verified=True,
            verified_at__isnull=False,
            moderation_status='valid',
            is_removed=False,
            removed_at__isnull=True,
        )
        google = valid.filter(verification_method='google')
        legacy = valid.filter(verification_method='email_legacy')
        petitions = Petition.objects.all()
        if options['petition_id']:
            petitions = petitions.filter(pk=options['petition_id'])
        stats = [
            ('Total rows', signatures.count()),
            ('Valid verified signatures', valid.count()),
            ('Google verified', google.count()),
            ('Legacy verified', legacy.count()),
            ('Pending', signatures.filter(moderation_status='pending').count()),
            ('Removed', signatures.filter(Q(is_removed=True)|Q(moderation_status='removed')|Q(removed_at__isnull=False)).distinct().count()),
            ('Duplicate', signatures.filter(moderation_status='duplicate').count()),
            ('Already linked', valid.filter(private_identity__isnull=False).count() if identity_schema_ready else 0),
            ('Eligible for confirmed migration', (valid.filter(private_identity__isnull=True) if identity_schema_ready else valid).exclude(google_subject='').count()),
            ('Eligible for provisional migration', (valid.filter(private_identity__isnull=True) if identity_schema_ready else valid).filter(google_subject='').exclude(Q(verified_email='')&Q(email='')).count()),
            ('Public count currently expected', sum(petition.verified_count for petition in petitions)),
        ]
        for label, value in stats:
            self.stdout.write(f'{label}: {value}')
