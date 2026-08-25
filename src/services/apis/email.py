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

_EMAIL_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "email.html"

_EMAIL_TEMPLATE: Template | None = None


def load_email_template() -> Template:
    global _EMAIL_TEMPLATE
    if _EMAIL_TEMPLATE is None:
        if not _EMAIL_TEMPLATE_PATH.exists():
            raise FileNotFoundError(f"email template not found: {_EMAIL_TEMPLATE_PATH}")
        _EMAIL_TEMPLATE = Template(_EMAIL_TEMPLATE_PATH.read_text(encoding="utf-8").rstrip())
    return _EMAIL_TEMPLATE


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


_GROUP_HEADINGS = {"flights": "Voli", "places": "Dove stare", "maps": "Cosa fare"}


def _render_group(label: str, items: list[dict]) -> str:
    if not items:
        return ""
    head = f'<div style="font-family:\'IBM Plex Sans\',Arial,sans-serif;font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#4E6071;margin:16px 0 8px;">{_e(label)}</div>'
    return head + "\n".join(_render_card(item) for item in items)


def _grouped_cards(content: dict) -> str:
    smap = content.get("sections_map", {})
    used: set[str] = set()
    out = []
    for kind, label in _GROUP_HEADINGS.items():
        allow = set(smap.get(kind, []))
        items = [r for r in content.get("resources", []) if r.get("link") in allow and r["link"] not in used]
        for r in items:
            used.add(r["link"])
        out.append(_render_group(label, items))
    leftovers = [r for r in content.get("resources", []) if r.get("link") not in used]
    if leftovers:
        out.append("\n".join(_render_card(r) for r in leftovers))  # unmatched singles render flat
    return "\n".join(o for o in out if o)


def _render_appendix(appendix: dict) -> str:
    rows = []
    for label, items in appendix.get("groups", []):
        if not items:
            continue
        lis = "\n".join(
            f'<li style="margin:2px 0;"><a href="{_e(i["link"])}" target="_blank" style="color:#4E6071;">{_e(i.get("name") or i["link"])}</a></li>'
            for i in items if i.get("link")
        )
        rows.append(f'<div style="font-size:12px;color:#4E6071;margin-top:6px;">{_e(label)}</div><ul style="margin:4px 0 0;padding-left:18px;">{lis}</ul>')
    src = "".join(f' <a href="{_e(u)}" target="_blank" style="color:#7A8895;">ricerca</a>' for u in appendix.get("source_links", []) if u)
    if not rows and not src:
        return ""
    inner = "".join(rows) + (f'<div style="font-size:11px;color:#7A8895;margin-top:10px;">Ricerche effettuate:{src}</div>' if src else "")
    return (
        '<details style="margin-top:8px;"><summary style="cursor:pointer;font-family:\'IBM Plex Sans\',Arial,sans-serif;'
        'font-size:12px;font-weight:600;color:#4E6071;">Tutto quello che abbiamo esplorato</summary>'
        f'<div style="font-family:\'IBM Plex Sans\',Arial,sans-serif;">{inner}</div></details>'
    )


def build_html_email(content: dict) -> str:
    return load_email_template().safe_substitute(
        opening=_e(content["opening"]),
        understanding=_e(content["understanding"]),
        resource_groups=_grouped_cards(content),
        appendix=_render_appendix(content.get("appendix", {})),
        cta=_e(content["cta"]),
        honest_note=_e(content["honest_note"]),
        signature_greeting=_e(SIGNATURE_GREETING),
        signature_name=_e(SIGNATURE_NAME),
        signature_role=_e(SIGNATURE_ROLE),
    )


class EmailSender:
    def __init__(self, api_key: str, from_address: str, sender=None):
        resend.api_key = api_key
        self._from = from_address
        self._sender = sender or _resend_send

    async def send(self, to: str, subject: str, body: str, html: str | None = None, timeout: float = 60.0) -> None:
        payload: dict = {"from": self._from, "to": to, "subject": subject, "text": body}
        if html:
            payload["html"] = html
        try:
            response = await asyncio.wait_for(self._sender(payload), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise EmailSendError(f"Email send timed out after {timeout}s") from exc
        if not response or "id" not in response:
            raise EmailSendError(f"Send failed, unexpected response: {response}")
        logger.info("email sent to %s (id=%s)", to, response["id"])


async def _resend_send(payload: dict) -> dict:
    return await asyncio.to_thread(resend.Emails.send, payload)
