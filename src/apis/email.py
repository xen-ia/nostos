import asyncio
import html as html_module
import logging

import resend

logger = logging.getLogger("nostos.email")


class EmailSendError(Exception):
    pass


def _e(value: str) -> str:
    return html_module.escape(value)


def build_html_email(content: dict) -> str:
    resources = content.get("resources", [])
    resource_cards = "\n".join(
        f"""<a href="{_e(item['link'])}" target="_blank"
             style="display:block;text-decoration:none;border:1px solid #e4dfd5;border-radius:8px;padding:14px 16px;margin-bottom:10px;background:#fbfaf7;">
          <div style="font-size:15px;font-weight:bold;color:#1f2a24;">{_e(item['name'])}</div>
          <div style="font-size:13px;color:#7a7362;margin-top:4px;">{_e(item.get('description') or '')}</div>
          <div style="font-size:14px;color:#b3933a;font-weight:bold;margin-top:6px;">{_e(item.get('price') or '')}</div>
        </a>"""
        for item in resources
    )
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#f4f2ec;font-family:Georgia,serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
    <tr><td align="center" style="padding:24px 16px;">
      <table role="presentation" width="560" cellspacing="0" cellpadding="0" border="0"
             style="background:#fff;border:1px solid #e4dfd5;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
        <tr>
          <td style="padding:28px 32px;border-bottom:1px solid #ece6da;">
            <div style="font-size:26px;letter-spacing:4px;color:#1f2a24;font-weight:bold;">Νόστος-Ξενία</div>
            <div style="font-size:13px;letter-spacing:1px;color:#8a8372;margin-top:2px;">viaggi autentici, lontano dal turismo di massa</div>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 32px 8px;">
            <div style="font-size:17px;line-height:1.6;color:#33302a;">{_e(content['opening'])}</div>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 32px 8px;">
            <div style="font-size:15px;line-height:1.6;color:#4c463a;">{_e(content['understanding'])}</div>
          </td>
        </tr>
        <tr>
          <td style="padding:24px 32px;">
            <div style="font-size:18px;font-weight:bold;color:#1f2a24;margin-bottom:12px;">Ecco tre punti di partenza concreti</div>
            {resource_cards}
          </td>
        </tr>
        <tr>
          <td style="padding:0 32px 8px;">
            <div style="background:#f6f3eb;border-left:3px solid #c8b89a;border-radius:6px;padding:16px 18px;font-size:13px;line-height:1.6;color:#5c5648;">
              {_e(content['honest_note'])}
            </div>
          </td>
        </tr>
        <tr>
          <td style="padding:24px 32px 28px;">
            <div style="font-size:15px;color:#33302a;">Buon ritorno a casa,</div>
            <div style="font-size:16px;font-weight:bold;color:#1f2a24;margin-top:8px;">Edoardo &amp; Chiara</div>
            <div style="font-size:13px;letter-spacing:2px;color:#8a8372;margin-top:2px;">CEOs@Nostos</div>
          </td>
        </tr>
        <tr>
          <td style="padding:14px 32px;background:#1f2a24;color:#cfd6cf;font-size:11px;letter-spacing:1px;">
            Nostos &middot; viaggi su misura &middot; <a href="https://xen-ia.github.io/nostos" style="color:#cfd6cf;text-decoration:underline;">xen-ia.github.io/nostos</a>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


class EmailSender:
    def __init__(self, api_key: str, from_address: str):
        resend.api_key = api_key
        self._from = from_address

    async def send(self, to: str, subject: str, body: str, html: str | None = None) -> None:
        payload: dict = {"from": self._from, "to": to, "subject": subject, "text": body}
        if html:
            payload["html"] = html
        response = await asyncio.to_thread(resend.Emails.send, payload)
        if not response or "id" not in response:
            raise EmailSendError(f"Invio fallito, risposta inattesa: {response}")
        logger.info("email inviata a %s (id=%s)", to, response["id"])