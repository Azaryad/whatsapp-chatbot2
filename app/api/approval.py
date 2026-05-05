"""
Driver-facing approval pages.

When a driver clicks any HMAC-signed link from WhatsApp, they land on /approve.
The page shows ALL still-pending rides in that same batch so the driver doesn't
miss any. Each ride has its own Approve / Decline form, signed independently.

All security is HMAC + per-offer status: no auth/login required, but the link
cannot be forged or replayed against a different offer.
"""
from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.utils.hmac_token import verify_approval_params, sign_approval_params
from app.models.offer import Offer, OfferStatus
from app.models.trip import Trip
from app.models.driver import Driver
from app.services.approval import handle_driver_approval

router = APIRouter(tags=["approval"])


# ─── Page chrome ──────────────────────────────────────────────────────────────

def _page(title: str, body: str, color: str = "#2E4057") -> str:
    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    margin: 0; padding: 16px;
    background: #f5f7fa; color: #1a1a1a;
    min-height: 100vh;
  }}
  .wrap {{ max-width: 560px; margin: 0 auto; }}
  h1 {{ margin: 12px 0 8px; color: {color}; font-size: 22px; }}
  .subtitle {{ color: #666; margin-bottom: 20px; font-size: 15px; }}
  .ride {{
    background: white; padding: 18px; border-radius: 14px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    margin-bottom: 14px;
  }}
  .ride-head {{ font-size: 16px; font-weight: 600; color: #2E4057; margin-bottom: 10px; }}
  .ride-row {{ font-size: 15px; line-height: 1.7; color: #333; }}
  .ride-row strong {{ color: #2E4057; margin-left: 6px; }}
  .badge {{
    display: inline-block; padding: 6px 14px; border-radius: 999px;
    font-size: 14px; font-weight: 600; margin-top: 8px;
  }}
  .badge-yes {{ background: #d4edda; color: #155724; }}
  .badge-no  {{ background: #f8d7da; color: #721c24; }}
  .badge-wait {{ background: #fff3cd; color: #856404; }}
  .buttons {{ display: flex; gap: 10px; margin-top: 14px; }}
  button {{
    flex: 1; padding: 14px; font-size: 17px; font-weight: 600;
    border: none; border-radius: 10px; cursor: pointer;
    transition: transform 0.1s;
    font-family: inherit;
  }}
  button:active {{ transform: scale(0.97); }}
  .yes {{ background: #2ecc71; color: white; }}
  .no  {{ background: #e74c3c; color: white; }}
  form {{ flex: 1; margin: 0; }}
  form button {{ width: 100%; }}
  .msg {{ font-size: 17px; line-height: 1.6; }}
  .err-card {{
    background: white; padding: 24px; border-radius: 14px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
  }}
  .back-link {{
    display: inline-block; margin-top: 18px;
    background: #2E4057; color: white; padding: 12px 20px;
    border-radius: 10px; text-decoration: none; font-weight: 600;
  }}
</style>
</head>
<body>
  <div class="wrap">
    {body}
  </div>
</body>
</html>"""


def _error_page(reason: str) -> HTMLResponse:
    messages = {
        "expired": ("הלינק פג תוקף", "הזמן לאישור הנסיעה הסתיים. אם הנסיעה עדיין רלוונטית, פנה למוקד."),
        "invalid_signature": ("לינק לא תקין", "הלינק נראה פגום. וודא שלחצת על הלינק המלא מההודעה."),
        "secret_not_configured": ("שגיאת מערכת", "הגדרות השרת לא הושלמו. פנה לתמיכה."),
        "not_found": ("הנסיעה לא נמצאה", "ייתכן שההצעה כבר לא בתוקף."),
        "wrong_status": ("כבר ניתנה תשובה", "הנסיעה הזו כבר טופלה — לא ניתן להגיב שוב."),
        "bad_action": ("פעולה לא חוקית", "פנה לתמיכה."),
    }
    title, body_text = messages.get(reason, ("שגיאה", "אירעה שגיאה לא צפויה."))
    body = f'<div class="err-card"><h1 style="color:#e74c3c">{title}</h1><p class="msg">{body_text}</p></div>'
    return HTMLResponse(_page(title, body, color="#e74c3c"), status_code=400)


# ─── Page rendering ───────────────────────────────────────────────────────────

def _ride_card(trip: Trip, offer: Offer, exp: int, sig: str) -> str:
    pickup_str = trip.pickup_time.strftime("%a %d/%m %H:%M")
    head = f"{trip.pickup_city} → {trip.dropoff_city}"
    rows = (
        f'<div class="ride-row"><strong>איסוף:</strong>{trip.pickup_address or trip.pickup_city}</div>'
        f'<div class="ride-row"><strong>יעד:</strong>{trip.dropoff_address or trip.dropoff_city}</div>'
        f'<div class="ride-row"><strong>מועד:</strong>{pickup_str}</div>'
        f'<div class="ride-row"><strong>נוסעים:</strong>{trip.num_passengers}</div>'
    )

    if offer.status == OfferStatus.accepted:
        badge = '<div class="badge badge-yes">✓ אושר</div>'
        return f'<div class="ride"><div class="ride-head">{head}</div>{rows}{badge}</div>'
    if offer.status in (OfferStatus.rejected, OfferStatus.approval_timeout, OfferStatus.timeout, OfferStatus.cancelled):
        badge = '<div class="badge badge-no">✗ נדחה</div>'
        return f'<div class="ride"><div class="ride-head">{head}</div>{rows}{badge}</div>'

    forms = f"""
<div class="buttons">
  <form method="post" action="/approve/yes">
    <input type="hidden" name="offer" value="{offer.id}">
    <input type="hidden" name="exp" value="{exp}">
    <input type="hidden" name="sig" value="{sig}">
    <button class="yes" type="submit">מאשר</button>
  </form>
  <form method="post" action="/approve/no">
    <input type="hidden" name="offer" value="{offer.id}">
    <input type="hidden" name="exp" value="{exp}">
    <input type="hidden" name="sig" value="{sig}">
    <button class="no" type="submit">לא יכול</button>
  </form>
</div>"""
    return f'<div class="ride"><div class="ride-head">{head}</div>{rows}{forms}</div>'


async def _gather_sibling_offers(anchor_offer: Offer, db: AsyncSession) -> list[Offer]:
    """
    Return all offers visible to the same driver in this view.
    If the anchor offer is part of a batch, returns all offers in that batch.
    Otherwise returns only the anchor offer itself.
    """
    if anchor_offer.batch_offer_id:
        result = await db.execute(
            select(Offer)
            .where(Offer.batch_offer_id == anchor_offer.batch_offer_id)
            .order_by(Offer.id)
        )
        return list(result.scalars().all())
    return [anchor_offer]


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/approve", response_class=HTMLResponse)
async def show_approval_page(offer: int, exp: int, sig: str, db: AsyncSession = Depends(get_db)):
    """Render all still-relevant rides for the driver who clicked this link."""
    valid, reason = verify_approval_params(offer, exp, sig)
    if not valid:
        return _error_page(reason)

    anchor = await db.get(Offer, offer)
    if not anchor:
        return _error_page("not_found")

    siblings = await _gather_sibling_offers(anchor, db)

    driver_name = ""
    if anchor.driver_id:
        driver = await db.get(Driver, anchor.driver_id)
        if driver:
            driver_name = driver.name.split()[0]

    pending = [o for o in siblings if o.status in (OfferStatus.pending, OfferStatus.pending_approval)]
    resolved = [o for o in siblings if o not in pending]

    if not pending and not resolved:
        return _error_page("not_found")

    # Build cards
    cards_html: list[str] = []
    for o in siblings:
        trip = await db.get(Trip, o.trip_id)
        if not trip:
            continue
        if o.status in (OfferStatus.pending, OfferStatus.pending_approval):
            o_exp, o_sig = sign_approval_params(o.id)
        else:
            o_exp, o_sig = 0, ""
        cards_html.append(_ride_card(trip, o, o_exp, o_sig))

    if pending:
        n_pending = len(pending)
        if n_pending > 1:
            heading = f"שלום{' ' + driver_name if driver_name else ''}, יש לך {n_pending} נסיעות לאישור"
            sub = "אשר או דחה כל נסיעה בנפרד למטה."
        else:
            heading = f"שלום{' ' + driver_name if driver_name else ''}, האם לאשר את הנסיעה?"
            sub = ""
    else:
        heading = f"תודה{' ' + driver_name if driver_name else ''}!"
        sub = "כל הנסיעות בקבוצה זו כבר טופלו."

    body = f'<h1>{heading}</h1>'
    if sub:
        body += f'<div class="subtitle">{sub}</div>'
    body += "".join(cards_html)
    return HTMLResponse(_page("אישור נסיעות", body))


async def _handle_action(
    offer: int, exp: int, sig: str, action: str, db: AsyncSession
) -> HTMLResponse:
    valid, reason = verify_approval_params(offer, exp, sig)
    if not valid:
        return _error_page(reason)

    db_offer = await db.get(Offer, offer)
    if not db_offer:
        return _error_page("not_found")

    ok, err = await handle_driver_approval(offer, action, db)
    if not ok:
        return _error_page(err or "wrong_status")

    # Render confirmation + link back to the multi-ride view if there are others pending
    siblings = await _gather_sibling_offers(db_offer, db)
    others_pending = [
        o for o in siblings
        if o.id != offer and o.status in (OfferStatus.pending, OfferStatus.pending_approval)
    ]

    driver_name = ""
    if db_offer.driver_id:
        driver = await db.get(Driver, db_offer.driver_id)
        if driver:
            driver_name = driver.name.split()[0]

    if action == "approved":
        title = "אושר"
        color = "#2ecc71"
        head = f'<h1 style="color:#2ecc71">תודה{" " + driver_name if driver_name else ""}!</h1>'
        msg = '<p class="msg">הנסיעה אושרה. נשלח לך אישור בוואטסאפ עם פרטי הנסיעה.</p>'
    else:
        title = "נדחה"
        color = "#666"
        head = f'<h1 style="color:#666">קיבלנו{" " + driver_name if driver_name else ""}</h1>'
        msg = '<p class="msg">הנסיעה לא אושרה. אנחנו מעבירים אותה לנהג אחר. תודה על התשובה המהירה!</p>'

    body = f'<div class="err-card">{head}{msg}'
    if others_pending:
        n = len(others_pending)
        word = "נסיעה" if n == 1 else "נסיעות"
        # Use the original signed link to return to the full view
        body += (
            f'<p class="msg" style="margin-top:16px">יש לך עוד {n} {word} לאישור.</p>'
            f'<a class="back-link" href="/approve?offer={offer}&exp={exp}&sig={sig}">חזרה לכל הנסיעות</a>'
        )
    body += "</div>"
    return HTMLResponse(_page(title, body, color=color))


@router.post("/approve/yes", response_class=HTMLResponse)
async def approve_yes(
    offer: int = Form(...),
    exp: int = Form(...),
    sig: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    return await _handle_action(offer, exp, sig, "approved", db)


@router.post("/approve/no", response_class=HTMLResponse)
async def approve_no(
    offer: int = Form(...),
    exp: int = Form(...),
    sig: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    return await _handle_action(offer, exp, sig, "declined", db)
