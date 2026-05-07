"""Telegram bot service for sending earnings alerts."""

import httpx
from app.core.config import get_settings

settings = get_settings()


class TelegramService:
    """Send alerts via Telegram Bot API."""

    BASE_URL = "https://api.telegram.org/bot{token}"

    def __init__(self):
        self.token = settings.telegram_bot_token
        self.enabled = bool(self.token)
        self.base_url = self.BASE_URL.format(token=self.token)

    async def send_alert(self, chat_id: str, ticker: str, company: str,
                         earnings_date: str, recommendation: str = None,
                         confidence: float = None) -> bool:
        """Send an earnings alert message to a Telegram chat."""
        if not self.enabled:
            return False

        # Build message
        rec_label = {"buy": "[BUY]", "sell": "[SELL]", "avoid": "[AVOID]"}.get(recommendation, "")
        lines = [
            f"<b>EarningsEdge Alert: {ticker}</b>",
            f"{company} reports on <b>{earnings_date}</b>",
        ]

        if recommendation:
            lines.append(f"AI Recommendation: <b>{rec_label}</b>")
        if confidence:
            lines.append(f"Confidence: {confidence:.0%}")

        lines.append("\nCheck EarningsEdge for full analysis")

        message = "\n".join(lines)

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                },
            )
            return resp.status_code == 200

    async def verify_chat(self, chat_id: str) -> bool:
        """Verify a chat_id is reachable."""
        if not self.enabled:
            return False

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": "✅ EarningsEdge alerts connected! You'll receive earnings notifications here.",
                    "parse_mode": "HTML",
                },
            )
            return resp.status_code == 200
