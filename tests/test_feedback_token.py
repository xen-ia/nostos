import base64
import hashlib
import hmac
import json
import time

from src.core.feedback_token import make_token, verify_token


def test_token_roundtrip():
    tok = make_token("trip-123", "secret", ttl_days=7)
    assert verify_token(tok, "trip-123", "secret")
    assert not verify_token(tok, "trip-999", "secret")

    # expired fails
    tok_expired = make_token("trip-123", "secret", ttl_days=-1)
    assert not verify_token(tok_expired, "trip-123", "secret")

    # tampered fails
    padded = tok + "=" * (-len(tok) % 4)
    raw = base64.urlsafe_b64decode(padded).decode()
    payload, sig = raw.rsplit(".", 1)
    data = json.loads(payload)
    data["tid"] = "trip-999"
    tampered_payload = json.dumps(data, separators=(",", ":"))
    tampered_raw = f"{tampered_payload}.{sig}"
    tampered_tok = base64.urlsafe_b64encode(tampered_raw.encode()).decode().rstrip("=")
    assert not verify_token(tampered_tok, "trip-123", "secret")
    assert not verify_token(tampered_tok, "trip-999", "secret")

    # wrong secret fails
    assert not verify_token(tok, "trip-123", "wrong-secret")

    # malformed token fails
    assert not verify_token("not-a-valid-token", "trip-123", "secret")


def test_continent_helper_and_intercontinental():
    from src.core.orchestrator import _continent

    # cover required keys
    assert _continent("Italy") == "europe"
    assert _continent("Patagonia") == "south_america"
    assert _continent("Italia") == "europe"
    assert _continent("Argentina") == "south_america"
    assert _continent("Cile") == "south_america"
    assert _continent("Chile") == "south_america"
    assert _continent("Brasile") == "south_america"
    assert _continent("Peru") == "south_america"
    assert _continent("USA") == "north_america"
    assert _continent("Giappone") == "asia"
    assert _continent("Japan") == "asia"
    assert _continent("Thailand") == "asia"
    assert _continent("Australia") == "oceania"
    # intercontinental detection
    dep = _continent("Italy")
    dest = _continent("Patagonia")
    is_intercontinental = dep and dest and dep != dest
    assert is_intercontinental is True
    # same continent not intercontinental
    assert _continent("Italy") == _continent("Francia")
    dep2 = _continent("Italy")
    dest2 = _continent("Francia")
    assert not (dep2 and dest2 and dep2 != dest2)
