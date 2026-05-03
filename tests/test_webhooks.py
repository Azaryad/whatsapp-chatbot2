from app.services.whatsapp import parse_webhook, _normalize_phone


def test_parse_inbound_message():
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "972521234567",
                        "id": "wamid.abc123",
                        "type": "text",
                        "timestamp": "1700000000",
                        "text": {"body": "כן מאשר"}
                    }]
                }
            }]
        }]
    }
    msgs = parse_webhook(payload)
    assert len(msgs) == 1
    assert msgs[0]["body"] == "כן מאשר"
    assert msgs[0]["from_phone"] == "972521234567"


def test_normalize_phone_local():
    assert _normalize_phone("0521234567") == "972521234567"

def test_normalize_phone_plus():
    assert _normalize_phone("+972521234567") == "972521234567"

def test_normalize_phone_already_normalized():
    assert _normalize_phone("972521234567") == "972521234567"


def test_parse_empty_payload():
    assert parse_webhook({}) == []
    assert parse_webhook({"entry": []}) == []
