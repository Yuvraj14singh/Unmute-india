from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


class Command(BaseCommand):
    help = 'Send one safe SMTP test email.'

    def add_arguments(self, parser):
        parser.add_argument('recipient')

    def handle(self, *args, **options):
        recipient = options['recipient'].strip().casefold()
        try:
            validate_email(recipient)
        except ValidationError:
            raise CommandError('Enter a valid recipient email address.')
        message = EmailMessage(
            'Unmute India Email Test',
            'This is a test email from the Unmute India production deployment.',
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
        )
        try:
            sent = message.send(fail_silently=False)
        except Exception as exc:
            raise CommandError(f'Email failed ({type(exc).__name__}). Check SMTP credentials, TLS/SSL settings, and provider access.')
        if sent != 1:
            raise CommandError('The configured email backend did not accept the test email.')
        self.stdout.write(self.style.SUCCESS('Test email accepted by the configured email backend. Check the recipient inbox and spam folder.'))
