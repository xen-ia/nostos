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

#: Route fragments ("MXP -> INV", "Bergamo → Edimburgo") normalized to the
#: elegant en-dash shape. The email is one-way prose: no arrows in flight names.
_ARROW_RE = re.compile(r"\s*(?:->|→)\s*")
_ROUTE_RE = re.compile(r"([^\s,]+)\s*(?:->|→)\s*([^\s,]+)")


def _humanize_flight_name(name: str) -> str:
    """Reformat flight titles to the elegant '{Airline} · {From} – {To}' shape.

    Raw data lines reflow to 'Volo {airline} · {from} – {to}'; already-human
    titles pass through with any `->`/`→` arrows normalized to `–`.
    Price stays pill-only (handled by the caller)."""
    text = name or ""
    if _RAW_FLIGHT_RE.search(text):
        first = text.split(",")[0].strip()
        route = _ROUTE_RE.search(text)
        if first and route:
            return f"Volo {first} · {route.group(1)} – {route.group(2)}"
        return f"Volo {first}" if first else "Volo"
    return _ARROW_RE.sub(" – ", text)


def _strip_duplicate_price(desc: str, price: str) -> str:
    """Drop the price pill's exact text from a flight description so the price
    renders once. Only exact-duplicate matches are removed; anything else
    (e.g. '95 EUR/notte' vs pill '95 EUR') is left untouched."""
    if desc and price and price in desc:
        desc = re.sub(r"\s{2,}", " ", desc.replace(price, "")).strip(" ,;–—-").strip()
    return desc


#: "4.3 stars" (SerpAPI English) normalized to Italian in card prose.
_STARS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s+stars?\b", re.IGNORECASE)


def _it_stars(desc: str) -> str:
    return _STARS_RE.sub(lambda m: f"{m.group(1)} stelle", desc or "")


_CARD_TEMPLATE = """
<table class="card-frame" role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-bottom:12px;">
  <tr>
    <td class="card d-card" style="background-color:#DFE9F3;border:1px solid #D0DDE9;border-radius:16px;padding:18px 20px;">
      <div class="d-cardname d-name" style="font-family:'Fraunces',Georgia,serif;font-size:16px;font-weight:600;color:#221D0F;line-height:1.35;">{name}</div>
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
    desc = _it_stars(item.get("description") or "")
    price = item.get("price") or ""
    if is_flight:
        desc = _strip_duplicate_price(desc, price)
    return _CARD_TEMPLATE.format(
        href=_e(item["link"]),
        name=_e(name),
        desc_block=_DESC_BLOCK.format(desc=_e(desc)) if desc else "",
        price_block=_PRICE_BLOCK.format(price=_e(price)) if price else "",
    )


def _render_group(label: str, items: list[dict], is_flight: bool = False) -> str:
    if not items:
        return ""
    head = f'<div style="font-family:\'IBM Plex Sans\',Arial,sans-serif;font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#4E6071;margin:16px 0 8px;">{_e(label)}</div>'
    return head + "\n".join(_render_card(item, is_flight=is_flight) for item in items)


def _is_van_trip(content: dict) -> bool:
    """Same van predicate as the research layer (Part A rental query trigger)."""
    tm = (content.get("travel_mode") or "").lower()
    acc = (content.get("accommodation_style") or "").lower()
    return tm == "van_life" or acc == "van"


#: Max rental cards in the "Dove noleggiare" section (van trips only).
RENTAL_CAP = 2
RENTAL_HEADING = "Dove noleggiare il van"


def _rental_items(content: dict) -> list[dict]:
    """Rental-tagged places, curated via the `places` allow-list (no new map key)."""
    allow = set(content.get("sections_map", {}).get("places", []))
    return [r for r in content.get("resources", [])
            if r.get("rental") and r.get("link") in allow][:RENTAL_CAP]


def _render_rental_group(content: dict) -> str:
    """'Dove noleggiare il van' cards (van trips with curated rentals only)."""
    if not _is_van_trip(content):
        return ""
    return _render_group(RENTAL_HEADING, _rental_items(content))


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
        f'<tr><td class="btn-cell" align="center">{_render_button(feedback_link, "Parliamone insieme")}</td>'
        "</tr></table></td></tr>"
    )


def _render_moments(moments: list[dict], cards_by_link: dict[str, dict]) -> str:
    blocks = []
    for moment in moments or []:
        prose = (moment.get("prose") or "").strip()
        if not prose:
            continue
        links = "".join(
            f'<div style="margin-top:6px;"><a href="{_e(link)}" target="_blank" '
            f'style="font-family:\'IBM Plex Sans\',-apple-system,\'Segoe UI\',Roboto,Helvetica,'
            f'Arial,sans-serif;font-size:13px;font-weight:600;color:#A84E28;'
            f'text-decoration:underline;">Vedi →</a></div>'
            for link in moment.get("place_links", []) if link in cards_by_link)
        blocks.append(
            f'<div class="d-desc" style="font-family:\'IBM Plex Sans\',-apple-system,\'Segoe UI\','
            f'Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.7;color:#3B4956;'
            f'margin-top:16px;">{_e(prose)}</div>' + links)
    return "".join(blocks)


def _render_places_list(places: list[dict]) -> str:
    rows = []
    for place in places or []:
        if not place.get("link"):
            continue
        line = f"{(place.get('name') or '').strip()}"
        if (place.get("price") or "").strip():
            line += f" — {place['price'].strip()}"
        rows.append(
            f'<div style="margin-top:8px;font-family:\'IBM Plex Sans\',-apple-system,\'Segoe UI\','
            f'Roboto,Helvetica,Arial,sans-serif;font-size:13px;color:#3B4956;">{_e(line)} '
            f'<a href="{_e(place["link"])}" target="_blank" style="color:#A84E28;'
            f'font-weight:600;text-decoration:underline;">vedi →</a></div>')
    if not rows:
        return ""
    return ('<div class="d-heading" style="font-family:\'Fraunces\',Georgia,serif;font-size:16px;'
            'font-weight:600;color:#221D0F;margin-top:22px;">I luoghi</div>' + "".join(rows))


_IT_MONTHS = ("gen", "feb", "mar", "apr", "mag", "giu",
              "lug", "ago", "set", "ott", "nov", "dic")


def format_trip_summary(destination: str | None, start_date: str | None,
                        end_date: str | None, travelers_count: int | None,
                        travelers_type: str | None) -> str:
    """One-line trip memory: 'Creta · 30 lug – 30 ago 2027 · coppia (2)'.
    Missing parts are skipped; empty when nothing is known."""

    def day_month(iso: str | None) -> str:
        try:
            y, m, d = (iso or "").split("-")
            return f"{int(d)} {_IT_MONTHS[int(m) - 1]}"
        except (ValueError, IndexError):
            return ""

    parts = []
    if (destination or "").strip():
        parts.append(destination.strip())
    start, end = day_month(start_date), day_month(end_date)
    year = (start_date or "")[:4] if (start_date or "")[:4].isdigit() else ""
    if start and end:
        parts.append(f"{start} – {end} {year}".strip())
    elif start:
        parts.append(f"{start} {year}".strip())
    who = " ".join(p for p in (travelers_type or "", f"({travelers_count})" if travelers_count else "") if p.strip())
    if who.strip():
        parts.append(who.strip())
    return " · ".join(parts)


def _render_trip_summary(summary: str) -> str:
    if not (summary or "").strip():
        return ""
    return (f'<div class="trip-summary d-muted" style="font-family:\'IBM Plex Sans\',-apple-system,'
            f'\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;font-size:12px;letter-spacing:0.8px;'
            f'color:#4E6071;margin-top:10px;text-align:center;">{_e(summary.strip())}</div>')


def _render_draft_note(note: str) -> str:
    """First-draft framing: this is a starting proposal, the human follow-up
    is the actual next step. Renders nothing when absent."""
    if not (note or "").strip():
        return ""
    return (f'<div class="draft-note d-muted" style="font-family:\'IBM Plex Sans\',-apple-system,'
            f'\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;font-size:13px;font-style:italic;'
            f'line-height:1.6;color:#4E6071;margin-top:14px;">{_e(note.strip())}</div>')


def build_html_email(content: dict) -> str:
    smap = content.get("sections_map", {})
    resources = content.get("resources", [])
    shown_links = {r.get("link") for r in resources if r.get("link")}
    feedback_link = content.get("feedback_link") or ""
    cards_by_link = {r.get("link"): r for r in resources if r.get("link")}
    return load_email_template().safe_substitute(
        letter_opening=_e(content.get("opening") or ""),
        trip_summary=_render_trip_summary(content.get("trip_summary") or ""),
        draft_note=_render_draft_note(content.get("draft_note") or ""),
        moments=_render_moments(content.get("moments", []), cards_by_link),
        places_list=_render_places_list(content.get("places", [])),
        rental_section=_render_rental_group(content),
        sources_section=_render_sources(content.get("appendix", {}), exclude_links=shown_links),
        cta=_e(content.get("closing") or content.get("cta") or ""),
        button_row=_render_button_row(feedback_link),
        honest_note=_e(content.get("honest_note") or ""),
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
