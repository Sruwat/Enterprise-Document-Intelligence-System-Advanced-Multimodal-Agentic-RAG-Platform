from __future__ import annotations

import smtplib
from email.message import EmailMessage


class EmailSender:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.sent_messages: list[dict[str, str]] = []

    def send_auth_action(self, *, to_email: str, action: str, token: str) -> None:
        subject = "Verify your Aiwana email" if action == "email_verification" else "Reset your Aiwana password"
        body = f"Use this Aiwana {action.replace('_', ' ')} token:\n\n{token}\n"
        self.send(to_email=to_email, subject=subject, body=body)

    def send(self, *, to_email: str, subject: str, body: str) -> None:
        if self.settings.email_provider == "smtp":
            self._send_smtp(to_email=to_email, subject=subject, body=body)
            return
        self.sent_messages.append({"to_email": to_email, "subject": subject, "body": body})

    def _send_smtp(self, *, to_email: str, subject: str, body: str) -> None:
        if not self.settings.smtp_host:
            raise RuntimeError("SMTP_HOST is required when EMAIL_PROVIDER=smtp.")
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.smtp_username or "no-reply@aiwana.local"
        message["To"] = to_email
        message.set_content(body)
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if self.settings.smtp_username:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)
