# Dispatch Flow — Canonical Reference

**This document describes the authoritative end-to-end flow for the WhatsApp Dispatch Agent.**
**Read this before changing any core dispatch, approval, batch, or RC-callback code.**
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
5. Generate Hebrew WhatsApp message with **per-trip RC approval links embedded**.
6. Send one WhatsApp per driver.
7. Schedule **1-hour batch timeout** (`driver_offer_timeout_seconds`).

State transitions: Trip `open` → `offered`. Offers `pending`.

### Supplier path
- One WhatsApp listing all rides + RC link per booking.
- 6-hour timeout (`supplier_offer_timeout_seconds`).

---

## Stage 5 — Driver replies on WhatsApp

Webhook → Claude parses per-ride intent.

| Driver said | Offer status | Trip status | Side effects |
|---|---|---|---|
| **YES** | `pending_approval` | stays `offered` | Schedule 1h approval-check |
| **NO** | `rejected` | `open` | **Immediately re-queue** to next-best driver |
| **Ambiguous** | unchanged | unchanged | Log only |

After parsing: send driver a Hebrew reminder to click the per-trip RC link to officially confirm.

> **Critical:** WhatsApp YES is intent, NOT binding. **Do not** call `assign_driver_to_booking` here. **Do not** mark the trip `confirmed` here.

> **Critical:** Refused trips re-queue immediately, NOT at batch timeout. Don't wait.

---

## Stage 6 — Driver clicks the RC approval link

Driver opens link from WhatsApp → Ride Control approval page → clicks Approve or Decline.

Ride Control calls back:
```
POST /api/trips/rc-status/{booking_id}
Authorization: Bearer <RC_CALLBACK_TOKEN>
{ "status": "approved" | "declined", "timestamp": "..." }
```

Validate token. Look up trip by `external_booking_id`. Find the `pending_approval` offer.

### Approved
1. Cancel the 1h approval-check job.
2. Offer → `accepted`. Trip → `confirmed`.
3. Call Ride Control API: `assign_driver_to_booking` + `update_booking_notes`.
4. Send driver: confirmation Hebrew message.

### Declined
1. Offer → `rejected`. Trip → `open`.
2. Send driver: "we saw you didn't approve, reassigning."
3. Re-queue trip to next-best driver in the region.

---

## Stage 7 — Edge cases (must remain auto-handled)

| Trigger | Result |
|---|---|
| Driver said YES, never clicked link within 1h | Offer `approval_timeout`. Trip → `open`. **Michel WhatsApp warning.** Re-queue. |
| Driver never replied within 1h batch timeout | Offer `timeout`. Each trip re-queued individually. |
| All drivers in region exhausted | Trip `unassigned`. **Michel escalation.** |
| Driver sends availability change ("בחופש מחר") mid-flow | Restriction parser updates DB. |

---

## The Two-Gate Principle

This is the design's heart. Do not collapse the gates.

1. **Gate 1 — WhatsApp YES:** signals intent. No write to Ride Control. No `confirmed` status.
2. **Gate 2 — RC link click:** official, binding. Only now does the agent write back to Ride Control.

If anyone modifies the code to mark a trip confirmed on WhatsApp YES alone, or to call `assign_driver_to_booking` before the RC callback, that change breaks the flow and must be reverted.

---

## Timeouts (current values)

| Timeout | Value | Setting |
|---|---|---|
| Driver batch reply | 1 hour | `driver_offer_timeout_seconds` |
| Supplier batch reply | 6 hours | `supplier_offer_timeout_seconds` |
| Driver RC approval (after WhatsApp YES) | 1 hour | `approval_timeout_seconds` |

`fast_timeout_seconds` overrides all three for dev/testing.

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
| 4 (message generation) | `app/services/claude.py` — `generate_batch_offer_message` |
| 5 (reply handling) | `app/services/batch_dispatch.py` — `handle_driver_batch_reply`, `_requeue_trip` |
| 6 (RC callback) | `app/api/trips.py` — `ride_control_status_callback`; `app/services/approval.py` — `handle_rc_status` |
| 7 (approval timeout) | `app/services/approval.py` — `_check_approval`, `schedule_approval_check` |
| 7 (batch timeout) | `app/services/batch_dispatch.py` — `_driver_batch_timeout` |
| 7 (Michel escalation) | `app/services/batch_dispatch.py` — `_notify_michel_unassigned`, `_notify_michel_summary` |

---

## When making changes, check:

- Does the change preserve the **manual ingest gate**? (no auto-dispatch on ingest)
- Does the change preserve the **two-gate approval**? (WhatsApp YES ≠ confirmed)
- Does it still **immediately re-queue refused trips**, not wait for batch timeout?
- Does the RC callback still **handle both approve and decline**?
- Does the RC callback still **look up by `external_booking_id`** (not internal trip_id)?
- Does the RC callback still **validate the bearer token**?
- Are timeouts still configurable via `fast_timeout_seconds`?
