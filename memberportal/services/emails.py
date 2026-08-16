from django.template.loader import render_to_string
from django.utils.html import escape
from constance import config
import logging
import json
import requests

logger = logging.getLogger("emails")

# Constance default and other values that are not a real Mailgun private API key.
_UNSET_MAILGUN_KEYS = {"", "PLEASE_CHANGE_ME"}
_MAILGUN_API_HOSTS = {
    "us": "https://api.mailgun.net",
    "eu": "https://api.eu.mailgun.net",
}
_MAILGUN_TIMEOUT_SECONDS = 30


def is_mailgun_configured() -> bool:
    key = (config.MAILGUN_API_KEY or "").strip()
    domain = (config.MAILGUN_DOMAIN or "").strip()
    return key not in _UNSET_MAILGUN_KEYS and bool(domain)


def _mailgun_api_host() -> str:
    region = (config.MAILGUN_REGION or "us").strip().lower()
    host = _MAILGUN_API_HOSTS.get(region)
    if host:
        return host
    logger.warning("Unknown MAILGUN_REGION %r, defaulting to us", region)
    return _MAILGUN_API_HOSTS["us"]


def send_single_email(
    to_email: object,
    subject: object,
    template_vars: object,
    template_name=None,
    reply_to=None,
    user: object | None = None,
) -> bool:
    # TODO: move to celery

    template_to_use = template_name if template_name else "email_without_button.html"
    logger.debug("Using email template: " + template_to_use)
    logger.debug("Using template vars: " + json.dumps(template_vars))

    if template_vars.get("message"):
        template_vars["message"] = escape(template_vars["message"]).replace(
            "~br~", "<br>"
        )

    email_string = render_to_string(
        template_to_use, {"email": template_vars, "config": config}
    )

    if not is_mailgun_configured():
        logger.warning("Mailgun is not configured, not sending email")
        if user:
            user.log_event(
                "Email NOT sent due to configuration issue: " + subject,
                "email",
                "Email content: " + json.dumps(template_vars),
            )
        return False

    domain = (config.MAILGUN_DOMAIN or "").strip()
    url = f"{_mailgun_api_host()}/v3/{domain}/messages"
    try:
        response = requests.post(
            url,
            auth=("api", (config.MAILGUN_API_KEY or "").strip()),
            data={
                "from": config.EMAIL_DEFAULT_FROM,
                "to": to_email,
                "subject": subject,
                "html": email_string,
                "h:Reply-To": reply_to or config.EMAIL_DEFAULT_FROM,
            },
            timeout=_MAILGUN_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        logger.error("Error sending email: " + str(e))
        raise

    if response.status_code == 401:
        logger.warning("Email NOT sent because Mailgun API key is invalid")
        if user:
            user.log_event(
                "Email NOT sent because Mailgun API key is invalid: ",
                "email",
                "Email content: " + json.dumps(template_vars),
            )
        return False

    if not response.ok:
        logger.error("Error sending email: " + str(response.status_code))
        response.raise_for_status()

    if user:
        logger.info("Email sent to " + to_email + " with subject: " + subject)
        user.log_event(
            "Sent email with subject: " + subject,
            "email",
            "Email content: " + json.dumps(template_vars),
        )
    return True


def send_email_to_admin(
    subject: object,
    template_vars: object,
    template_name=None,
    reply_to=None,
    user: object | None = None,
) -> object:
    return send_single_email(
        config.EMAIL_ADMIN,
        subject,
        template_vars,
        template_name=template_name,
        reply_to=reply_to,
        user=user,
    )
