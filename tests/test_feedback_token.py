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
