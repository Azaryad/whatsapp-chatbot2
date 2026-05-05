# Dispatch Flow — Canonical Reference

**This document describes the authoritative end-to-end flow for the WhatsApp Dispatch Agent.**
**Read this before changing any core dispatch, approval, batch, or approval-link code.**
**If a change would alter or break any stage below, flag it explicitly before proceeding.**

---

## Stage 1 — Ride sits in Ride Control, unassigned

A booking exists in Ride Control with no driver. The agent has zero awareness of it.
**Nothing automatic happens.**

---

## Stage 2 — Dispatcher manually pushes the ride to the agent

The dispatcher decides this ride should go through the WhatsApp agent (rather than to an internal driver). They push it to our system.

- **Endpoint:** `POST /api/trips/ingest`
- **Result:** Trip stored with `status = open`. No dispatch yet.
- **Why manual:** some bookings are handled by internal drivers and must never enter the agent queue.

> **Do NOT** add auto-dispatch on ingest. The manual gate is intentional.

---

## Stage 3 — Trip appears in the dashboard queue

The dispatcher sees the trip in the Pending Rides panel. They drag one or more trips onto a driver region or a supplier.

- **Endpoint:** `POST /api/trips/batch-dispatch`
- **Body:** `{trip_ids, target_type: "driver"|"supplier", region or supplier_id}`

---

## Stage 4 — Agent sends WhatsApp offers

### Driver-region path
1. Load active drivers in the region.
2. Claude ranks drivers (proximity, fairness, cool-off).
3. Greedy packing: assign non-conflicting trips per driver, top-ranked first.
4. Create `BatchOffer` + per-trip `Offer` rows (status `pending`).
5. **Generate one HMAC-signed approval URL per offer** via `sign_approval_url(offer.id)`.
6. Send one WhatsApp per driver — message body includes one signed link per ride.
7. Schedule **1-hour batch timeout** (`driver_offer_timeout_seconds`).

State transitions: Trip `open` → `offered`. Offers `pending`.

### Supplier path
- One WhatsApp listing all rides + signed approval link per offer.
- 6-hour timeout (`supplier_offer_timeout_seconds`).

---

## Stage 5 — Driver replies on WhatsApp (optional path)

The driver may reply YES/NO on WhatsApp before clicking the link, or may skip the WhatsApp reply entirely and click the link directly. Both paths are supported.

If the driver does reply:

| Driver said | Offer status | Trip status | Side effects |
|---|---|---|---|
| **YES** | `pending_approval` | stays `offered` | Schedule 1h approval-check |
| **NO** | `rejected` | `open` | **Immediately re-queue** to next-best driver |
| **Ambiguous** | unchanged | unchanged | Log only |

After parsing: send driver a Hebrew reminder to click the per-trip approval link.

> **Critical:** WhatsApp YES is intent, NOT binding. **Do not** call `assign_driver_to_booking` here. **Do not** mark the trip `confirmed` here.
> **Critical:** Refused trips re-queue immediately, NOT at batch timeout. Don't wait.

---

## Stage 6 — Driver clicks the approval link (the binding step)

Driver opens the link from WhatsApp. The link points to **our server**, not Ride Control:

```
https://dispatch.tlv-transfers.com/approve?offer=42&exp=1715000000&sig=a3f7c9...
```

`GET /approve` (handled by `app/api/approval.py`):
1. Verify the HMAC signature against `APPROVAL_LINK_SECRET`.
2. Verify `exp` is in the future.
3. Look up offer by `offer` id. Verify status is `pending` or `pending_approval`.
4. If any check fails → render Hebrew error page (expired / invalid / already responded).
5. Otherwise → render Hebrew approval page with ride details and two buttons (Approve / Decline).

Driver presses Approve or Decline. The form POSTs to `/approve/yes` or `/approve/no` with the same signed params. We re-validate HMAC and offer status, then call `handle_driver_approval(offer_id, action, db)`.

### Approved
1. Cancel the 1h approval-check job.
2. Offer → `accepted`. Trip → `confirmed`.
3. Call Ride Control's existing API: `assign_driver_to_booking` + `update_booking_notes`.
4. Send driver a confirmation Hebrew WhatsApp.
5. Render confirmation page in browser.

### Declined
1. Offer → `rejected`. Trip → `open`.
2. Send driver "moving on" Hebrew WhatsApp.
3. Re-queue trip to next-best driver in the region.
4. Render confirmation page in browser.

---

## Stage 7 — Edge cases (must remain auto-handled)

| Trigger | Result |
|---|---|
| Driver said YES, never clicked link within 1h | Offer `approval_timeout`. Trip → `open`. **Michel WhatsApp warning.** Re-queue. |
| Driver never replied AND never clicked within 1h batch timeout | Offer `timeout`. Each trip re-queued individually. |
| All drivers in region exhausted | Trip `unassigned`. **Michel escalation.** |
| Driver sends availability change ("בחופש מחר") mid-flow | Restriction parser updates DB. |
| Driver clicks link after offer already resolved | Friendly "already responded" page; no state change. |

---

## The Two-Gate Principle

Even though the new flow allows a single click to confirm, the design still distinguishes:

1. **Soft signal — WhatsApp YES:** signals intent. No write to Ride Control. No `confirmed` status. Triggers a 1h timer.
2. **Binding signal — Approval link click:** official, binding. Only here does the agent write back to Ride Control.

Anyone modifying the code to mark a trip confirmed on WhatsApp YES alone, or to call `assign_driver_to_booking` before the link click, breaks the flow and must be reverted.

---

## Security Model — Approval Links

- Each link carries `offer`, `exp`, `sig` query params.
- `sig = HMAC-SHA256(f"offer={offer}&exp={exp}", APPROVAL_LINK_SECRET)`.
- The secret is configured server-side only; never appears in URLs or logs.
- Tampering with `offer` or `exp` invalidates the signature → request rejected.
- Replay protection comes from two layers: (a) `exp` enforces a TTL; (b) offer status check rejects clicks against already-resolved offers.
- Driver login is **not** required — the unguessable signed token is the auth.

---

## Timeouts (current values)

| Timeout | Value | Setting |
|---|---|---|
| Driver batch reply | 1 hour | `driver_offer_timeout_seconds` |
| Supplier batch reply | 6 hours | `supplier_offer_timeout_seconds` |
| Driver approval (after WhatsApp YES) | 1 hour | `approval_timeout_seconds` |
| Approval URL TTL | batch + approval + 30min buffer | `approval_link_ttl_seconds` |

`fast_timeout_seconds` overrides all four for dev/testing.

---

## Status enums (do not rename without migration)

**TripStatus:** `open`, `offered`, `confirmed`, `completed`, `cancelled`, `unassigned`
**OfferStatus:** `pending`, `pending_approval`, `accepted`, `rejected`, `timeout`, `approval_timeout`, `cancelled`
**BatchStatus:** `pending`, `partial`, `completed`, `timeout`

---

## Files that implement this flow

| Stage | File |
|---|---|
| 2 (ingest) | `app/api/trips.py` |
| 3 (batch-dispatch endpoint) | `app/api/trips.py` |
| 4 (driver path) | `app/services/batch_dispatch.py` — `dispatch_driver_batch`, `_send_driver_batch` |
| 4 (supplier path) | `app/services/batch_dispatch.py` — `dispatch_supplier_batch`, `_build_supplier_message` |
| 4 (link signing) | `app/utils/hmac_token.py` — `sign_approval_url` |
| 4 (message generation) | `app/services/claude.py` — `generate_batch_offer_message`, `generate_offer_message` |
| 5 (reply handling) | `app/services/batch_dispatch.py` — `handle_driver_batch_reply`, `_requeue_trip` |
| 6 (approval page + actions) | `app/api/approval.py` — `show_approval_page`, `approve_yes`, `approve_no` |
| 6 (binding logic) | `app/services/approval.py` — `handle_driver_approval` |
| 7 (approval timeout) | `app/services/approval.py` — `_check_approval`, `schedule_approval_check` |
| 7 (batch timeout) | `app/services/batch_dispatch.py` — `_driver_batch_timeout` |
| 7 (Michel escalation) | `app/services/batch_dispatch.py` — `_notify_michel_unassigned`, `_notify_michel_summary` |

---

## When making changes, check:

- Does the change preserve the **manual ingest gate**? (no auto-dispatch on ingest)
- Does the change preserve the **two-gate approval**? (WhatsApp YES ≠ confirmed; only the link click writes to Ride Control)
- Does it still **immediately re-queue refused trips**, not wait for batch timeout?
- Does the approval page still **validate HMAC + expiry + offer status** on both GET and POST?
- Are timeouts still configurable via `fast_timeout_seconds`?
- Are approval URLs always generated via `sign_approval_url` (never hand-built)?
- Is `APPROVAL_LINK_SECRET` set in production? (without it, all links are rejected)
