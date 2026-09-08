import asyncio
import html as html_module
import logging
import re
from pathlib import Path
from string import Template

import resend

logger = logging.getLogger("nostos.email")

SIGNATURE_GREETING = "Buon ritorno a casa,"
SIGNATURE_NAME = "Edoardo&Chiara"
SIGNATURE_ROLE = "CEOs@Nostos"

SITE_URL = "https://xen-ia.github.io/nostos"

#: Max links shown in the sources section (plain list, no collapsible).
SOURCES_CAP = 3

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


#: Raw flight data line echoed by the LLM as a card title, e.g.
#: "easyJet, MXP -> INV, departure 2026-12-21 10:35, 196 EUR".
#: The email prompt is the primary fix (human-shaped titles); this pattern is
#: defensive renderer hardening only.
_RAW_FLIGHT_RE = re.compile(r"departure \d{4}-\d{2}-\d{2}")


def _humanize_flight_name(name: str) -> str:
    """Reformat a raw flight data line to 'Volo {airline}'; pass through otherwise."""
    if _RAW_FLIGHT_RE.search(name or ""):
        first = (name or "").split(",")[0].strip()
        return f"Volo {first}" if first else "Volo"
    return name


def _strip_duplicate_price(desc: str, price: str) -> str:
    """Drop the price pill's exact text from a flight description so the price
    renders once. Only exact-duplicate matches are removed; anything else
    (e.g. '95 EUR/notte' vs pill '95 EUR') is left untouched."""
    if desc and price and price in desc:
        desc = re.sub(r"\s{2,}", " ", desc.replace(price, "")).strip(" ,;–—-").strip()
    return desc


_CARD_TEMPLATE = """
<table class="card-frame" role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-bottom:12px;">
  <tr>
    <td class="card d-card" style="background-color:#DFE9F3;border:1px solid #D0DDE9;border-radius:16px;padding:18px 20px;">
      <div class="d-cardname d-name" style="font-family:'Fraunces',Georgia,serif;font-size:16px;font-weight:600;color:#221D0F;line-height:1.35;"><a href="{href}" target="_blank" style="color:inherit;text-decoration:underline;">{name}</a></div>
      {desc_block}
      {price_block}
      <div style="margin-top:10px;"><a href="{href}" target="_blank" style="font-family:'IBM Plex Sans',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:14px;font-weight:600;color:#A84E28;text-decoration:underline;">Apri &rarr;</a></div>
    </td>
  </tr>
</table>"""

_DESC_BLOCK = """
        <div class="d-carddesc d-desc" style="font-family:'IBM Plex Sans',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:13px;line-height:1.55;color:#3B4956;margin-top:5px;">{desc}</div>"""

_PRICE_BLOCK = """
        <div class="d-price" style="display:inline-block;font-family:'IBM Plex Sans',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:12px;font-weight:600;color:#B58026;background-color:#EBF2F8;border:1px solid #B58026;padding:3px 12px;border-radius:999px;margin-top:9px;">{price}</div>"""

def _render_card(item: dict, is_flight: bool = False) -> str:
    name = _humanize_flight_name(item.get("name") or "")
    desc = item.get("description") or ""
    price = item.get("price") or ""
    if is_flight:
        desc = _strip_duplicate_price(desc, price)
    return _CARD_TEMPLATE.format(
        href=_e(item["link"]),
        name=_e(name),
        desc_block=_DESC_BLOCK.format(desc=_e(desc)) if desc else "",
        price_block=_PRICE_BLOCK.format(price=_e(price)) if price else "",
    )


_GROUP_HEADINGS = {"flights": "Voli", "places": "Dove stare", "maps": "Cosa fare"}


def _render_group(label: str, items: list[dict], is_flight: bool = False) -> str:
    if not items:
        return ""
    head = f'<div style="font-family:\'IBM Plex Sans\',Arial,sans-serif;font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#4E6071;margin:16px 0 8px;">{_e(label)}</div>'
    return head + "\n".join(_render_card(item, is_flight=is_flight) for item in items)


def _grouped_cards(content: dict, exclude_links: set[str] | None = None) -> str:
    """Group resources under Voli/Dove stare/Cosa fare headings.

    Links in `exclude_links` (the hero flight) never render here — neither as
    grouped cards nor as leftover singles."""
    excluded = set(exclude_links or ())
    smap = content.get("sections_map", {})
    flight_links = set(smap.get("flights", []))
    used: set[str] = set(excluded)
    out = []
    for kind, label in _GROUP_HEADINGS.items():
        allow = set(smap.get(kind, [])) - excluded
        items = [r for r in content.get("resources", []) if r.get("link") in allow and r["link"] not in used]
        for r in items:
            used.add(r["link"])
        out.append(_render_group(label, items, is_flight=(kind == "flights")))
    leftovers = [r for r in content.get("resources", []) if r.get("link") not in used]
    if leftovers:
        out.append("\n".join(
            _render_card(r, is_flight=(r.get("link") in flight_links)) for r in leftovers
        ))  # unmatched singles render flat
    return "\n".join(o for o in out if o)


def _render_sources(
    appendix: dict, cap: int = SOURCES_CAP, exclude_links: set[str] | None = None
) -> str:
    """Plain <ul> of at most `cap` links (group order preserved), no collapsible.

    Links already shown in the email (hero, cards, footer) never reappear here."""
    excluded = set(exclude_links or ()) | {SITE_URL}
    pairs: list[tuple[str, str]] = []
    for _label, items in appendix.get("groups", []):
        for i in items or []:
            if i.get("link") and i["link"] not in excluded:
                pairs.append((i.get("name") or i["link"], i["link"]))
    for u in appendix.get("source_links", []):
        if u.get("link") and u["link"] not in excluded:
            pairs.append((u.get("name") or "ricerca", u["link"]))
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for name, link in pairs:
        if link not in seen:
            seen.add(link)
            unique.append((name, link))
    unique = unique[:cap]
    if not unique:
        return ""
    lis = "\n".join(
        f'<li style="margin:4px 0;"><a href="{_e(link)}" target="_blank" style="color:#4E6071;text-decoration:underline;">{_e(name)}</a></li>'
        for name, link in unique
    )
    head = '<div style="font-family:\'IBM Plex Sans\',Arial,sans-serif;font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#4E6071;margin:16px 0 8px;">Fonti</div>'
    return f"{head}<ul style=\"margin:4px 0 0;padding-left:18px;\">{lis}</ul>"


def _render_arrival_block(items: list[dict]) -> str:
    """Hero card for the first flight plus a bulletproof 'Vedi il volo' button."""
    flight = next((i for i in items if i.get("link")), None)
    if flight is None:
        return ""
    name = _humanize_flight_name(flight.get("name") or "Volo")
    price = flight.get("price") or ""
    desc = _strip_duplicate_price(flight.get("description") or "", price)
    desc_block = f'<div class="d-desc" style="font-family:\'IBM Plex Sans\',-apple-system,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.6;color:#3B4956;margin-top:6px;">{_e(desc)}</div>' if desc else ""
    price_block = f'<div class="d-price" style="display:inline-block;font-family:\'IBM Plex Sans\',-apple-system,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;font-size:13px;font-weight:600;color:#B58026;background-color:#EBF2F8;border:1px solid #B58026;padding:6px 14px;border-radius:999px;margin-top:10px;">{_e(price)}</div>' if price else ""
    return (
        '<div style="margin-top:24px;padding:20px 22px;background-color:#DFE9F3;border:1px solid #B58026;border-radius:14px;">'
        '<div style="font-family:\'IBM Plex Sans\',Arial,sans-serif;font-size:12px;font-weight:600;'
        'letter-spacing:1px;text-transform:uppercase;color:#4E6071;margin-bottom:8px;">Come arrivare</div>'
        f'<div class="d-name" style="font-family:\'Fraunces\',Georgia,serif;font-size:18px;font-weight:600;color:#221D0F;line-height:1.4;"><a href="{_e(flight["link"])}" target="_blank" style="color:inherit;text-decoration:underline;">{_e(name)}</a></div>'
        f"{desc_block}{price_block}"
        '<table class="btn-frame" role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin-top:14px;">'
        "<tr>"
        f'<td bgcolor="#A84E28" style="border-radius:999px;background-color:#A84E28;">'
        f'<a href="{_e(flight["link"])}" target="_blank" style="display:inline-block;padding:14px 26px;font-size:16px;font-weight:600;color:#FFFFFF;text-decoration:none;">Vedi il volo</a>'
        "</td></tr></table></div>"
    )


_TRAVEL_MODE_BLOCKS = {
    "road_trip": (
        "Come muoversi in loco",
        "Il viaggio è pensato come road trip: ti suggeriamo tappe giornaliere con distanze gestibili, "
        "soste per il pranzo e pernottamenti lungo il percorso. L'auto (o moto) ti dà libertà totale "
        "di deviare verso i luoghi che scoprirai strada facendo."
    ),
    "van_life": (
        "Vita in van",
        "Dormi nel veicolo: le soste notturne sono aree attrezzate, campeggi liberi o parcheggi sicuri "
        "selezionati lungo il percorso. Ti segnaliamo dove rifornire acqua, scaricare e ricaricare."
    ),
    "sailing": (
        "Navigazione",
        "Il viaggio si svolge in barca: ti indichiamo porti di imbarco, marine per il noleggio, "
        "rotte costiere con ancoraggi sicuri e tappe a terra per rifornimenti ed esplorazioni."
    ),
}


def _render_travel_mode_block(travel_mode: str | None, mobility: list[str] | None = None) -> str:
    """Single travel box: mode heading + body prose. There is deliberately no
    'Mezzi' line — a bare vehicle list ("Mezzi: auto, van") makes no sense;
    mobility info lives in the LLM prose instead. Unknown modes (incl. 'fixed')
    render no box at all.
    """
    del mobility  # accepted for caller compatibility; never rendered
    tm = (travel_mode or "").lower()
    if tm not in _TRAVEL_MODE_BLOCKS:
        return ""
    heading, body = _TRAVEL_MODE_BLOCKS[tm]
    return (
        f'<div style="margin-top:24px;padding:18px 20px;background-color:#EBF2F8;border:1px solid #B58026;'
        f'border-radius:12px;">'
        f'<div style="font-family:\'Fraunces\',Georgia,serif;font-size:16px;font-weight:600;color:#B58026;'
        f'margin-bottom:8px;">{_e(heading)}</div>'
        f'<div class="d-bodytext" style="font-family:\'Fraunces\',Georgia,serif;font-size:15px;line-height:1.6;color:#221D0F;">'
        f'{_e(body)}</div></div>'
    )


def _render_button(href: str, label: str) -> str:
    """Table-based bulletproof button: 14px vertical padding + 16px text ≈ 44px target."""
    return (
        '<table class="btn-frame" role="presentation" cellspacing="0" cellpadding="0" border="0">'
        "<tr>"
        '<td bgcolor="#A84E28" style="border-radius:999px;background-color:#A84E28;">'
        f'<a href="{_e(href)}" target="_blank" style="display:inline-block;padding:14px 26px;font-size:16px;'
        f'font-weight:600;font-family:\'IBM Plex Sans\',-apple-system,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;'
        f'color:#FFFFFF;text-decoration:none;white-space:nowrap;">{_e(label)}</a>'
        "</td></tr></table>"
    )


def _render_button_row(feedback_link: str) -> str:
    """Actions row: single centered feedback button (email is one-way, no reply).
    Renders no row at all when the feedback link is absent."""
    if not feedback_link:
        return ""
    return (
        '<tr><td class="gutter" style="padding:24px 36px 0;">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">'
        f'<tr><td class="btn-cell" align="center">{_render_button(feedback_link, "Lascia un feedback")}</td>'
        "</tr></table></td></tr>"
    )


def build_html_email(content: dict) -> str:
    smap = content.get("sections_map", {})
    flight_links = set(smap.get("flights", []))
    arrival_items = [r for r in content.get("resources", []) if r.get("link") in flight_links]
    hero_link = next((r["link"] for r in arrival_items if r.get("link")), None)
    exclude_links = {hero_link} if hero_link else set()
    shown_links = {r.get("link") for r in content.get("resources", []) if r.get("link")}
    shown_links |= exclude_links
    feedback_link = content.get("feedback_link") or ""
    return load_email_template().safe_substitute(
        opening=_e(content["opening"]),
        understanding=_e(content["understanding"]),
        arrival_section=_render_arrival_block(arrival_items),
        resource_groups=_grouped_cards(content, exclude_links=exclude_links),
        travel_box=_render_travel_mode_block(content.get("travel_mode"), content.get("mobility")),
        sources_section=_render_sources(content.get("appendix", {}), exclude_links=shown_links),
        cta=_e(content["cta"]),
        button_row=_render_button_row(feedback_link),
        honest_note=_e(content["honest_note"]),
        signature_greeting=_e(SIGNATURE_GREETING),
        signature_name=_e(SIGNATURE_NAME),
        signature_role=_e(SIGNATURE_ROLE),
        footer_url=_e(SITE_URL),
        footer_url_visible=_e(SITE_URL.removeprefix("https://")),
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
