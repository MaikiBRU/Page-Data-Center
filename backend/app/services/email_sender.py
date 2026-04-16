from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from app.core.config import settings


def send_verification_code(email: str, code: str) -> bool:
    if not settings.sendgrid_api_key:
        return False

    message = Mail(
        from_email=settings.email_from,
        to_emails=email,
        subject="Código de verificación",
        html_content=f"""
        <h2>Verificación de cuenta</h2>
        <p>Tu código es:</p>
        <h1>{code}</h1>
        <p>Este código vence en 10 minutos.</p>
        """,
    )
    try:
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        sg.send(message)
        return True
    except Exception:
        return False
