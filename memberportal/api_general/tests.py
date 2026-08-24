from unittest.mock import Mock, patch

from constance.test import override_config
from django.test import TestCase
from requests import HTTPError

from services.emails import send_single_email


class SendSingleEmailTests(TestCase):
    @patch("services.emails.requests.post")
    def test_unset_key_does_not_call_mailgun(self, mock_post):
        sent = send_single_email(
            "member@example.com",
            "Hello",
            {"title": "Hello", "message": "Body"},
        )

        self.assertFalse(sent)
        mock_post.assert_not_called()

    @override_config(
        MAILGUN_API_KEY="key-123",
        MAILGUN_DOMAIN="mg.example.org",
        MAILGUN_REGION="us",
        EMAIL_DEFAULT_FROM='"Portal" <noreply@example.org>',
    )
    @patch("services.emails.requests.post")
    def test_configured_send_posts_to_mailgun(self, mock_post):
        mock_post.return_value = Mock(status_code=200, ok=True)

        sent = send_single_email(
            "member@example.com",
            "Hello",
            {"title": "Hello", "message": "Body"},
            reply_to="reply@example.org",
        )

        self.assertTrue(sent)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.mailgun.net/v3/mg.example.org/messages")
        self.assertEqual(kwargs["auth"], ("api", "key-123"))
        self.assertEqual(kwargs["timeout"], 30)
        data = kwargs["data"]
        self.assertEqual(data["from"], '"Portal" <noreply@example.org>')
        self.assertEqual(data["to"], "member@example.com")
        self.assertEqual(data["subject"], "Hello")
        self.assertEqual(data["h:Reply-To"], "reply@example.org")
        self.assertIn("Body", data["html"])

    @override_config(
        MAILGUN_API_KEY="key-123",
        MAILGUN_DOMAIN="mg.example.org",
        MAILGUN_REGION="eu",
    )
    @patch("services.emails.requests.post")
    def test_401_returns_false_without_raising(self, mock_post):
        mock_post.return_value = Mock(status_code=401, ok=False)

        sent = send_single_email(
            "member@example.com",
            "Hello",
            {"title": "Hello", "message": "Body"},
        )

        self.assertFalse(sent)
        args, _kwargs = mock_post.call_args
        self.assertEqual(
            args[0], "https://api.eu.mailgun.net/v3/mg.example.org/messages"
        )

    @override_config(
        MAILGUN_API_KEY="key-123",
        MAILGUN_DOMAIN="mg.example.org",
    )
    @patch("services.emails.requests.post")
    def test_other_http_errors_raise(self, mock_post):
        response = Mock(status_code=500, ok=False)
        response.raise_for_status.side_effect = HTTPError("500 Server Error")
        mock_post.return_value = response

        with self.assertRaises(HTTPError):
            send_single_email(
                "member@example.com",
                "Hello",
                {"title": "Hello", "message": "Body"},
            )
