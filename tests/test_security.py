from fastapi import FastAPI
from starlette.requests import Request

from src.api.security import rate_limit_key
from src.settings import Settings


def _req(headers=None, host="9.9.9.9", api_token=""):
    app = FastAPI()
    app.state.settings = Settings(api_token=api_token)
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw,
        "client": (host, 5000),
        "app": app,
    }
    return Request(scope)


def test_cf_connecting_ip_wins_over_edge_ip():
    r = _req(headers={"CF-Connecting-IP": "1.2.3.4"}, host="5.6.7.8")
    assert rate_limit_key(r) == "ip:1.2.3.4"


def test_fallback_to_client_host_without_cf_header():
    assert rate_limit_key(_req(host="5.6.7.8")) == "ip:5.6.7.8"


def test_blank_cf_header_ignored():
    assert rate_limit_key(_req(headers={"CF-Connecting-IP": "  "}, host="5.6.7.8")) == "ip:5.6.7.8"


def test_auth_token_still_wins_over_cf_ip():
    r = _req(
        headers={"Authorization": "Bearer sekret", "CF-Connecting-IP": "1.2.3.4"},
        api_token="sekret",
    )
    assert rate_limit_key(r) == "token:sekret"
