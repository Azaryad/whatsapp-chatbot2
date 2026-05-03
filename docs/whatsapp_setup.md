# WhatsApp Cloud API Setup

## Step 1 — Get test credentials (instant, no business verification)

1. Go to https://developers.facebook.com and create/log in with a Meta account.
2. Create a new App → choose **Business** type.
3. Add the **WhatsApp** product.
4. In **WhatsApp → Getting Started** you'll see:
   - A **Phone Number ID** (copy → `WA_PHONE_NUMBER_ID` in `.env`)
   - A **Temporary Access Token** (copy → `WA_ACCESS_TOKEN`)
   - A pre-configured test number you can use to send messages immediately.
5. Add your personal WhatsApp number as a test recipient.

## Step 2 — Configure webhook

1. Start ngrok: `ngrok http 8000`
2. Copy the HTTPS URL (e.g. `https://abc123.ngrok.io`)
3. In Meta dashboard → WhatsApp → Configuration → Webhook:
   - URL: `https://abc123.ngrok.io/webhook`
   - Verify Token: any string you choose → set as `WA_VERIFY_TOKEN` in `.env`
4. Subscribe to the **messages** webhook field.

## Step 3 — Run locally

```bash
cp .env.example .env   # fill in your keys
make install
make dev               # starts on :8000
```

Open http://localhost:8000 for the dashboard.

## Step 4 — Fast timeout mode (dev/testing)

```bash
make fast-timeout      # 30-second offer timeout instead of 3 hours
```

## Path to production

1. Submit your Meta app for Business Verification (requires company documents).
2. Apply for a permanent WhatsApp Business phone number.
3. Replace the temporary access token with a permanent System User token.
4. Deploy to Render/Railway:
   - Set all env vars in the platform dashboard.
   - Point your webhook URL to the production domain (no ngrok needed).
   - Change `DATABASE_URL` to a Postgres URL for production persistence.
