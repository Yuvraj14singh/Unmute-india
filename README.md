# Unmute India

A server-rendered Django platform where Indian students can share privately by text, audio or video and receive a compassionate human response.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Staff can use `/staff-dashboard/` and `/admin/`.

## Petition verification email

Local development uses Django's console email backend, so verification messages and links appear in the terminal running the server. For production, copy the keys from `.env.example` into the deployment environment and configure an authenticated SMTP provider. Set `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL`; never commit credentials. `PETITION_VERIFICATION_EXPIRY_HOURS` defaults to 48.

The database is the signature-count source of truth. A signature counts only after the single-use email link is accepted and its moderation status is `Valid`.

## Privacy and production

Development uses SQLite. Before production, configure PostgreSQL from environment variables, set `DEBUG=False`, use a strong secret, HTTPS, secure cookies, malware scanning, rate limiting, and private object storage with signed media URLs. Django's development media serving is not suitable for private production uploads.

All emotional submissions are private by default. Public stories require an explicit approved record. Verified crisis resources must be reviewed in admin before they are shown.

## Generated visual assets

- `static/images/home/accountability-hero.webp`: built-in image generation; peaceful Indian student accountability poster, editorial screen-print style, no text or politician likeness.
- `static/images/support/students-listening.webp`: built-in image generation; diverse Indian students listening in a warm campus courtyard.

Both were converted to compressed WebP for project use. The first visual replaces the unavailable supplied `/mnt/data/...` source.
