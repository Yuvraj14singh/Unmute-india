# Google and Turnstile petition verification

## Google setup

1. Create or select a Google Cloud project.
2. Configure the OAuth consent screen for the site.
3. Under Credentials, create an OAuth 2.0 Client ID with application type **Web application**.
4. Add these authorised JavaScript origins:
   - `https://unmute-india.onrender.com`
   - `http://localhost:8000`
   - `http://127.0.0.1:8000`
5. Copy the web client ID into Render as `GOOGLE_CLIENT_ID`.

Use an OAuth client whose application type is **Web application**. For production, the authorised JavaScript origin must be exactly `https://unmute-india.onrender.com` with no trailing path. Popup mode does not require a redirect URI.

No Google client secret is needed for this Google Identity Services ID-token flow.

## Cloudflare Turnstile setup

1. In Cloudflare, create a Turnstile site.
2. Add the production hostname `unmute-india.onrender.com`.
3. Copy the site key into Render as `TURNSTILE_SITE_KEY`.
4. Copy the secret key into Render as `TURNSTILE_SECRET_KEY`.

For localhost, set `TURNSTILE_USE_TEST_KEYS=True` while `DEBUG=True`. The project then uses Cloudflare's official dummy keys, which work on `localhost` and `127.0.0.1`. Production ignores this mode because it is disabled whenever `DEBUG=False`.

## Render environment variables

```text
GOOGLE_CLIENT_ID
TURNSTILE_SITE_KEY
TURNSTILE_SECRET_KEY
SITE_URL=https://unmute-india.onrender.com
```

Save the variables and redeploy. Never put the Turnstile secret or a Google credential token in source control, templates, logs, or browser code.
