"""
Detect if a driver's WhatsApp message contains an availability restriction
and return a dict of DB fields to update.
"""
import json
from app.config import settings


async def extract_restriction_update(text: str) -> dict | None:
    """
    Returns e.g. {"works_nights": False} or {"works_shabbat": True},
    or None if the message contains no restriction update.
    """
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            system="Reply with valid JSON only.",
            messages=[{"role": "user", "content":
                f"""Does this WhatsApp message from a driver contain a change to their availability/constraints?
Message: "{text}"

Detectable fields:
- works_nights (bool): mentions not working nights / working nights again
- works_shabbat (bool): mentions not working Shabbat / working Shabbat again
- works_long_distance (bool): mentions not doing long distance / ok with long distance
- active (bool): mentions stopping work / coming back to work

If a restriction is detected, return: {{"field": "value"}} — e.g. {{"works_nights": false}}
If multiple: {{"works_nights": false, "works_shabbat": false}}
If no restriction detected: {{"none": true}}"""}],
        )
        data = json.loads(response.content[0].text.strip())
        if "none" in data:
            return None
        return data
    except Exception:
        return None
