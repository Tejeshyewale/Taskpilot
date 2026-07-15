"""
Email notifications — sends a "your report is ready" email via SMTP.
Same graceful-degradation pattern as llm.py/tools.py: if SMTP isn't
configured, this silently no-ops instead of breaking task completion —
a missing "nice to have" feature should never fail the core task.
"""

import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS", "").strip()


def is_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS)


def send_report_ready_email(to_email: str, goal: str, report_url: str) -> bool:
    if not is_configured() or not to_email:
        return False

    body = (
        f"Your TaskPilot research report is ready.\n\n"
        f"Goal: {goal}\n\n"
        f"View it here: {report_url}\n\n"
        f"— TaskPilot"
    )
    msg = MIMEText(body)
    msg["Subject"] = f"Your research report is ready: {goal[:60]}"
    msg["From"] = SMTP_USER
    msg["To"] = to_email

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True
    except Exception:  # noqa: BLE001
        # Notification failure must never break the task itself.
        return False
