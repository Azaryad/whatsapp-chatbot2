# App Integration Spec

This document describes the three endpoints the driver app team needs to build
so the dispatch system can integrate fully. Until these exist, all three are
stubbed behind `AppIntegration` in `app/services/app_integration.py`.

---

## 1. Deep-link into a specific trip

**What we need:** A URL that, when tapped on a mobile device with the app installed,
opens that specific trip inside the app.

**Preferred form:** Universal link
```
https://app.tlv-transfers.com/trips/{booking_id}
```
Or a custom scheme:
```
tlvtransfers://trips/{booking_id}
```

**Action required:** Confirm the scheme with the app team and update `APP_DEEPLINK_BASE` in `.env`.

---

## 2. Push a pending trip to a driver's app view

When the dispatch system offers a trip to a driver, we push the trip into their
app so it appears immediately when they tap the WhatsApp link.

**Endpoint:** `POST /api/app/pending-trip`

**Auth:** Bearer token (same `SUPPLIER_API_TOKEN`)

**Request body:**
```json
{
  "booking_id": "string",
  "driver_code": "string"
}
```

**Response:**
```json
{ "success": true }
```

**Behaviour:** Creates a "pending" trip card in the driver's app home screen.
Does not constitute acceptance — the driver still confirms via WhatsApp.

---

## 3. Cancel a pending trip from a driver's app view

Called when:
- Another driver accepts first.
- The offer times out.
- The dispatcher manually cancels.

**Endpoint:** `DELETE /api/app/pending-trip`

**Auth:** Bearer token

**Request body:**
```json
{
  "booking_id": "string",
  "driver_code": "string"
}
```

**Response:**
```json
{ "success": true }
```

---

## 4. (Optional) Driver accepts/declines via app webhook

If the driver taps Accept/Decline inside the app instead of replying on WhatsApp,
the app should notify us so we can keep state in sync.

**Endpoint on our side (we expose):** `POST /api/app-events/driver-response`

**App should call:**
```
POST https://<our-host>/api/app-events/driver-response
Authorization: Bearer <shared-secret>

{
  "booking_id": "string",
  "driver_code": "string",
  "action": "accept" | "decline"
}
```

**Note:** Until this is implemented, WhatsApp remains the single response channel.
