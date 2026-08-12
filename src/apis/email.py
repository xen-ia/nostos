import asyncio
import html as html_module
import logging
from pathlib import Path
from string import Template

import resend

logger = logging.getLogger("nostos.email")

SIGNATURE_GREETING = "Buon ritorno a casa,"
SIGNATURE_NAME = "Edoardo&Chiara"
SIGNATURE_ROLE = "CEOs@Nostos"

_EMAIL_TEMPLATE = Template(
    (Path(__file__).parent.parent / "templates" / "email.html")
    .read_text(encoding="utf-8")
    .rstrip()
)


class EmailSendError(Exception):
    ...


def _e(value: str) -> str:
    return html_module.escape(value)


_CARD_TEMPLATE = """
<table class="card-frame" role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-bottom:12px;">
  <tr>
    <td class="card d-card" style="background-color:#DFE9F3;border:1px solid #D0DDE9;border-radius:16px;padding:18px 20px;">
      <a href="{href}" target="_blank" style="display:block;text-decoration:none;">
        <div class="d-cardname d-name" style="font-family:'Fraunces',Georgia,serif;font-size:16px;font-weight:600;color:#221D0F;line-height:1.35;">{name}</div>
        {desc_block}
        {price_block}
      </a>
    </td>
  </tr>
</table>"""

_DESC_BLOCK = """
        <div class="d-carddesc d-desc" style="font-family:'IBM Plex Sans',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:13px;line-height:1.55;color:#3B4956;margin-top:5px;">{desc}</div>"""

_PRICE_BLOCK = """
        <div class="d-price" style="display:inline-block;font-family:'IBM Plex Sans',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:12px;font-weight:600;color:#B58026;background-color:#EBF2F8;border:1px solid #B58026;padding:3px 12px;border-radius:999px;margin-top:9px;">{price}</div>"""

def _render_card(item: dict) -> str:
    desc = item.get("description") or ""
    price = item.get("price") or ""
    return _CARD_TEMPLATE.format(
        href=_e(item["link"]),
        name=_e(item["name"]),
        desc_block=_DESC_BLOCK.format(desc=_e(desc)) if desc else "",
        price_block=_PRICE_BLOCK.format(price=_e(price)) if price else "",
    )


def build_html_email(content: dict) -> str:
    resource_cards = "\n".join(_render_card(item) for item in content.get("resources", []))
    return _EMAIL_TEMPLATE.safe_substitute(
        opening=_e(content["opening"]),
        understanding=_e(content["understanding"]),
        resource_cards=resource_cards,
        cta=_e(content["cta"]),
        honest_note=_e(content["honest_note"]),
        signature_greeting=_e(SIGNATURE_GREETING),
        signature_name=_e(SIGNATURE_NAME),
        signature_role=_e(SIGNATURE_ROLE),
    )


class EmailSender:
    def __init__(self, api_key: str, from_address: str):
        resend.api_key = api_key
        self._from = from_address

    async def send(self, to: str, subject: str, body: str, html: str | None = None, timeout: float = 60.0) -> None:
        payload: dict = {"from": self._from, "to": to, "subject": subject, "text": body}
        if html:
            payload["html"] = html
        try:
            response = await asyncio.wait_for(asyncio.to_thread(resend.Emails.send, payload), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise EmailSendError(f"Email send timed out after {timeout}s") from exc
        if not response or "id" not in response:
            raise EmailSendError(f"Send failed, unexpected response: {response}")
        logger.info("email sent to %s (id=%s)", to, response["id"])
