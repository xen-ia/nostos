import base64
import hashlib
import hmac
import json
import time


def make_token(trip_id: str, secret: str, ttl_days: int = 7) -> str:
    exp = int(time.time()) + ttl_days * 86400
    payload = json.dumps({"tid": trip_id, "exp": exp}, separators=(",", ":"))
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode().rstrip("=")


def verify_token(token: str, trip_id: str, secret: str) -> bool:
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded).decode()
        payload, sig = raw.rsplit(".", 1)
        exp_sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, exp_sig):
            return False
        data = json.loads(payload)
        if data.get("tid") != trip_id:
            return False
        if int(data.get("exp", 0)) < time.time():
            return False
        return True
    except Exception:
        return False
