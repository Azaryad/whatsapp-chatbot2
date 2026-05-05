"""
Driver-facing approval pages.

Driver clicks an HMAC-signed link from WhatsApp → lands on /approve
→ presses Approve / Decline → POST /approve/yes or /approve/no.

All security is HMAC + offer-status: no auth/login required, but the link
cannot be forged or replayed against a different offer.
"""
from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.utils.hmac_token import verify_approval_params
from app.models.offer import Offer, OfferStatus
from app.models.trip import Trip
from app.models.driver import Driver
from app.services.approval import handle_driver_approval

router = APIRouter(tags=["approval"])


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
    margin: 0; padding: 24px;
    background: #f5f7fa; color: #1a1a1a;
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
  }}
  .card {{
    background: white; padding: 32px 24px; border-radius: 16px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.08);
    max-width: 480px; width: 100%;
  }}
  h1 {{ margin: 0 0 16px; color: {color}; font-size: 24px; }}
  .details {{ background: #f0f4f8; padding: 16px; border-radius: 12px; margin: 20px 0;
              line-height: 1.7; font-size: 16px; }}
  .details strong {{ color: #2E4057; }}
  .buttons {{ display: flex; gap: 12px; margin-top: 24px; }}
  button {{
    flex: 1; padding: 16px; font-size: 18px; font-weight: 600;
    border: none; border-radius: 12px; cursor: pointer;
    transition: transform 0.1s, opacity 0.1s;
  }}
  button:active {{ transform: scale(0.97); }}
  .yes {{ background: #2ecc71; color: white; }}
  .no  {{ background: #e74c3c; color: white; }}
  .msg {{ font-size: 18px; line-height: 1.6; }}
  form {{ flex: 1; margin: 0; }}
  form button {{ width: 100%; }}
</style>
</head>
<body>
  <div class="card">
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
        "wrong_status": ("כבר ניתנה תשובה", "הנסיעה כבר טופלה — לא ניתן להגיב שוב."),
    }
    title, body_text = messages.get(reason, ("שגיאה", "אירעה שגיאה לא צפויה."))
    body = f'<h1 style="color:#e74c3c">{title}</h1><p class="msg">{body_text}</p>'
    return HTMLResponse(_page(title, body, color="#e74c3c"), status_code=400)


def _confirmation_page(action: str, driver_first_name: str = "") -> HTMLResponse:
    if action == "approved":
        body = (
            f'<h1 style="color:#2ecc71">תודה{" " + driver_first_name if driver_first_name else ""}!</h1>'
            '<p class="msg">הנסיעה אושרה. נשלח לך אישור בוואטסאפ עם פרטי הנסיעה.</p>'
        )
        return HTMLResponse(_page("אושר", body, color="#2ecc71"))
    body = (
        f'<h1 style="color:#666">קיבלנו{" " + driver_first_name if driver_first_name else ""}</h1>'
        '<p class="msg">הנסיעה לא אושרה. אנחנו מעבירים אותה לנהג אחר. תודה על התשובה המהירה!</p>'
    )
    return HTMLResponse(_page("נדחה", body, color="#666"))


@router.get("/approve", response_class=HTMLResponse)
async def show_approval_page(offer: int, exp: int, sig: str, db: AsyncSession = Depends(get_db)):
    """Render the Hebrew approval page if the signed link is valid."""
    valid, reason = verify_approval_params(offer, exp, sig)
    if not valid:
        return _error_page(reason)

    db_offer = await db.get(Offer, offer)
    if not db_offer:
        return _error_page("not_found")

    if db_offer.status not in (OfferStatus.pending, OfferStatus.pending_approval):
        return _error_page("wrong_status")

    trip = await db.get(Trip, db_offer.trip_id)
    if not trip:
        return _error_page("not_found")

    driver_name = ""
    if db_offer.driver_id:
        driver = await db.get(Driver, db_offer.driver_id)
        if driver:
            driver_name = driver.name.split()[0]

    pickup_str = trip.pickup_time.strftime("%d/%m/%Y %H:%M")
    body = f"""
<h1>שלום{" " + driver_name if driver_name else ""}, האם לאשר את הנסיעה?</h1>
<div class="details">
  <div><strong>איסוף:</strong> {trip.pickup_address or trip.pickup_city}</div>
  <div><strong>יעד:</strong> {trip.dropoff_address or trip.dropoff_city}</div>
  <div><strong>מועד:</strong> {pickup_str}</div>
  <div><strong>נוסעים:</strong> {trip.num_passengers}</div>
</div>
<div class="buttons">
  <form method="post" action="/approve/yes">
    <input type="hidden" name="offer" value="{offer}">
    <input type="hidden" name="exp" value="{exp}">
    <input type="hidden" name="sig" value="{sig}">
    <button class="yes" type="submit">מאשר</button>
  </form>
  <form method="post" action="/approve/no">
    <input type="hidden" name="offer" value="{offer}">
    <input type="hidden" name="exp" value="{exp}">
    <input type="hidden" name="sig" value="{sig}">
    <button class="no" type="submit">לא יכול</button>
  </form>
</div>
"""
    return HTMLResponse(_page("אישור נסיעה", body))


async def _handle_action(offer: int, exp: int, sig: str, action: str, db: AsyncSession) -> HTMLResponse:
    valid, reason = verify_approval_params(offer, exp, sig)
    if not valid:
        return _error_page(reason)

    ok, err = await handle_driver_approval(offer, action, db)
    if not ok:
        return _error_page(err or "wrong_status")

    db_offer = await db.get(Offer, offer)
    driver_name = ""
    if db_offer and db_offer.driver_id:
        driver = await db.get(Driver, db_offer.driver_id)
        if driver:
            driver_name = driver.name.split()[0]
    return _confirmation_page(action, driver_name)


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
