import asyncio
import resend


class EmailSendError(Exception):
    pass


class EmailSender:
    def __init__(self, api_key: str, from_address: str):
        resend.api_key = api_key
        self._from = from_address

    async def send(self, to: str, subject: str, body: str) -> None:
        response = await asyncio.to_thread(
            resend.Emails.send,
            {"from": self._from, "to": to, "subject": subject, "text": body},
        )
        print(f"[DEBUG] Risposta Resend: {response}")
        if not response or "id" not in response:
            raise EmailSendError(f"Invio fallito, risposta inattesa: {response}")