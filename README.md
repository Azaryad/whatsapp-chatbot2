# WhatsApp AI Dispatch Agent

Automated driver dispatch over WhatsApp for a small Israeli tourism transport company.
Communicates in casual Hebrew. Powered by Claude (`claude-sonnet-4-6`).

## How it works

1. The main operating system pushes a trip via `POST /api/trips/ingest`.
2. The agent filters eligible drivers (vehicle type, capacity, Shabbat, night, distance, conflicts).
3. Claude ranks the eligible drivers by proximity + fairness.
4. A Hebrew WhatsApp message is sent to the top driver with trip details and a deep-link.
5. The driver's reply is interpreted by Claude (yes / no / ambiguous).
6. On acceptance → driver is assigned in the supplier API, trip confirmed.
7. On rejection or 3-hour timeout → next driver in the ranked list is tried.
8. When the regional list is exhausted → Michel (`0526084230`) receives a WhatsApp report.

> **Note:** Deep-link push/pull into the driver app is currently stubbed.
> See [docs/app_integration_spec.md](docs/app_integration_spec.md) for what the app team needs to build.

## Vehicle types

| Type | Max passengers | Upgrade allowed? |
|---|---|---|
| sedan | 4 | Yes (to any higher type) |
| executive_minivan | 6 | Only to executive — never substituted with non-executive |
| minivan | 7 | Yes |
| minibus_15 | 15 | Yes |
| minibus_18 | 18 | No (top of hierarchy) |

## Quick start

```bash
git clone git@github.com:Azaryad/whatsapp-chatbot2.git
cd whatsapp-chatbot2
cp .env.example .env        # fill in all keys (see below)
make install
make dev                    # runs on http://localhost:8000
```

Open http://localhost:8000 for the dispatcher dashboard.

### Required environment variables

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com |
| `WA_PHONE_NUMBER_ID` | Meta Developer dashboard → WhatsApp |
| `WA_ACCESS_TOKEN` | Meta Developer dashboard → WhatsApp |
| `WA_VERIFY_TOKEN` | Any string you choose |
| `GOOGLE_MAPS_API_KEY` | Google Cloud Console → Distance Matrix API |
| `SUPPLIER_API_KEY` | 64-char hex API key issued by Ride Control admin |
| `SUPPLIER_API_SECRET` | HMAC signing secret issued alongside the API key |
| `APPROVAL_LINK_SECRET` | Random 32-byte string for signing driver approval URLs |
| `APPROVAL_BASE_URL` | Public URL of this server (e.g. https://dispatch.tlv-transfers.com) |

### Dev mode with fast timeout (30 seconds instead of 3 hours)

```bash
make fast-timeout
```

### Docker

```bash
docker compose up --build
```

## Loading drivers

1. Download [driver_template.xlsx](driver_template.xlsx)
2. Fill in your drivers (one row each)
3. Upload via the dashboard → **Import Drivers** tab, or `POST /api/drivers/import`

## Webhook setup (local dev)

See [docs/whatsapp_setup.md](docs/whatsapp_setup.md) for full instructions including ngrok tunneling.

## Project structure

```
app/
  main.py              FastAPI entry point
  config.py            Settings from .env
  database.py          SQLAlchemy async engine
  models/              SQLAlchemy ORM models
  schemas/             Pydantic schemas
  api/                 Route handlers (webhooks, trips, drivers, dashboard)
  services/
    whatsapp.py        WhatsApp Cloud API send/receive
    claude.py          rank_drivers(), interpret_reply(), generate messages
    maps.py            Google Maps drive time
    dispatch.py        Offer state machine + escalation
    scheduler.py       APScheduler timeout jobs
    supplier.py        Supplier API client (assigndriver, updatefields)
    app_integration.py AppIntegration ABC + stub
  utils/
    constraints.py     Driver eligibility filter
    shabbat.py         Shabbat / night time checks
    excel_import.py    Driver Excel import
  static/
    index.html         Dispatcher dashboard
docs/
  whatsapp_setup.md    WhatsApp Cloud API setup guide
  app_integration_spec.md  Spec for app team (deep-link + push/pull)
  ideas.md             Future feature ideas
```
