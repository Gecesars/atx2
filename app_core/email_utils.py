from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Optional

from flask import current_app, render_template
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


def _serializer() -> URLSafeTimedSerializer:
    secret_key = current_app.config["SECRET_KEY"]
    salt = current_app.config.get("SECURITY_EMAIL_SALT", "email-token")
    return URLSafeTimedSerializer(secret_key, salt=salt)


def generate_token(email: str, purpose: str) -> str:
    serializer = _serializer()
    return serializer.dumps({"email": email, "purpose": purpose})


def load_token(token: str, max_age: int, expected_purpose: str) -> Optional[str]:
    serializer = _serializer()
    try:
        data = serializer.loads(token, max_age=max_age)
    except SignatureExpired:
        return None
    except BadSignature:
        return None
    if data.get("purpose") != expected_purpose:
        return None
    return data.get("email")


def send_email(
    subject: str,
    recipient: str,
    html_template: str,
    text_template: Optional[str] = None,
    **context,
) -> None:
    suppress = current_app.config.get("MAIL_SUPPRESS_SEND", True)
    html_body = render_template(html_template, **context)
    text_body = (
        render_template(text_template, **context) if text_template else None
    )

    current_app.logger.info(
        "Sending email to %s | subject=%s | suppress=%s",
        recipient,
        subject,
        suppress,
    )

    if suppress:
        current_app.logger.debug("Email HTML body:\n%s", html_body)
        if text_body:
            current_app.logger.debug("Email TEXT body:\n%s", text_body)
        return

    config = current_app.config
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.get("MAIL_DEFAULT_SENDER", config.get("MAIL_USERNAME"))
    message["To"] = recipient
    if text_body:
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")
    else:
        message.set_content(html_body, subtype="html")

    host = config.get("MAIL_SERVER", "localhost")
    port = config.get("MAIL_PORT", 25)
    use_ssl = config.get("MAIL_USE_SSL", False)
    use_tls = config.get("MAIL_USE_TLS", False)

    if use_ssl:
        smtp = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        smtp = smtplib.SMTP(host, port, timeout=30)

    try:
        if not use_ssl and use_tls:
            smtp.starttls()
        username = config.get("MAIL_USERNAME")
        password = config.get("MAIL_PASSWORD")
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)
    finally:
        smtp.quit()
