from django.conf import settings
from django.core.management.base import BaseCommand


def mask_address(value):
    local, separator, domain = (value or '').partition('@')
    if not separator:
        return 'Not configured'
    return f'{local[:2]}{"*" * max(4, len(local) - 2)}@{domain}'


class Command(BaseCommand):
    help = 'Safely diagnose production email settings without printing credentials.'

    def handle(self, *args, **options):
        password = ''.join((settings.EMAIL_HOST_PASSWORD or '').split())
        values = [
            ('EMAIL_BACKEND', settings.EMAIL_BACKEND),
            ('EMAIL_HOST', settings.EMAIL_HOST),
            ('EMAIL_PORT', settings.EMAIL_PORT),
            ('EMAIL_HOST_USER configured', 'Yes' if settings.EMAIL_HOST_USER else 'No'),
            ('EMAIL_HOST_USER', mask_address(settings.EMAIL_HOST_USER)),
            ('EMAIL_HOST_PASSWORD configured', 'Yes' if password else 'No'),
            ('EMAIL_HOST_PASSWORD length', len(password)),
            ('EMAIL_USE_TLS', settings.EMAIL_USE_TLS),
            ('EMAIL_USE_SSL', settings.EMAIL_USE_SSL),
            ('DEFAULT_FROM_EMAIL', settings.DEFAULT_FROM_EMAIL or 'Not configured'),
            ('SITE_URL', settings.SITE_URL),
        ]
        for label, value in values:
            self.stdout.write(f'{label}: {value}')

        errors = []
        if settings.EMAIL_BACKEND.endswith('console.EmailBackend'): errors.append('Console backend is active.')
        if not settings.EMAIL_HOST_USER: errors.append('EMAIL_HOST_USER is missing.')
        if not password: errors.append('EMAIL_HOST_PASSWORD is missing.')
        if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL: errors.append('TLS and SSL cannot both be enabled.')
        if settings.SITE_URL.startswith(('http://127.0.0.1', 'http://localhost')) and not settings.DEBUG: errors.append('SITE_URL uses localhost in production.')
        if settings.EMAIL_HOST == 'smtp.gmail.com' and password and len(password) != 16: errors.append('Google App Password length is expected to be 16 after whitespace removal.')
        if settings.EMAIL_HOST == 'smtp.gmail.com' and settings.EMAIL_HOST_USER and settings.EMAIL_HOST_USER not in settings.DEFAULT_FROM_EMAIL: errors.append('DEFAULT_FROM_EMAIL should use the authenticated Gmail address.')
        if errors:
            self.stdout.write(self.style.ERROR('Configuration problems:'))
            for error in errors: self.stdout.write(self.style.ERROR(f'- {error}'))
        else:
            self.stdout.write(self.style.SUCCESS('Email configuration looks structurally valid. Run send_test_email to test delivery.'))
