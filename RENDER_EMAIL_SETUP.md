# Render email setup

Configure these values in the Render web service's **Environment** page. Do not commit real credentials.

```text
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=<Gmail address that created the App Password>
EMAIL_HOST_PASSWORD=<16-character Google App Password without spaces>
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL=Unmute India <same Gmail address>
SITE_URL=https://<actual-service>.onrender.com
```

`EMAIL_HOST_USER`, the App Password owner, and the address inside `DEFAULT_FROM_EMAIL` must match. Never use the normal Google password. Save the environment changes and redeploy the service.

Run these commands from Render Shell:

```bash
python manage.py diagnose_email
python manage.py send_test_email recipient@example.com
```

The diagnostic command masks the username and prints only whether a password exists and its length. It never prints the password.
