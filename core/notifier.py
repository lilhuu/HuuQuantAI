"""Trade event notifications via SMTP."""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any


class TradeNotifier:
    """Send optional local trade alerts.

    The notifier is inert unless SMTP host/user credentials are configured.
    It never blocks trading paths with an exception; failures return False.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.smtp = self.config.get("smtp", {}) or {}
        self.enabled = bool(self.smtp.get("host") and self.smtp.get("user") and self.smtp.get("pass"))

    def send_trade_alert(self, subject: str, body: str) -> bool:
        if not self.enabled:
            return False
        try:
            message = MIMEMultipart()
            message["Subject"] = f"[HuuQuantAI] {subject}"
            message["From"] = str(self.smtp["user"])
            message["To"] = str(self.smtp.get("recipient") or self.smtp["user"])
            message.attach(MIMEText(body, "html", "utf-8"))

            with smtplib.SMTP_SSL(str(self.smtp["host"]), int(self.smtp.get("port", 465) or 465), timeout=10) as server:
                server.login(str(self.smtp["user"]), str(self.smtp["pass"]))
                server.send_message(message)
            return True
        except Exception:
            return False

    def send_daily_summary(self, account: dict[str, Any], trades: list[dict[str, Any]]) -> bool:
        total_pnl = sum(float(item.get("realized_pnl", 0) or 0) for item in trades or [])
        equity = float(account.get("equity", account.get("cash", 0)) or 0)
        html = f"""
        <h2>每日交易汇总</h2>
        <p>总盈亏: <b>{total_pnl:+.2f} USDT</b></p>
        <p>成交笔数: {len(trades or [])}</p>
        <p>账户权益: {equity:.2f} USDT</p>
        """
        return self.send_trade_alert("每日交易汇总", html)
