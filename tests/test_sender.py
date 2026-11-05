"""SMTP header identity and envelope routing remain separate."""
import unittest
from unittest.mock import Mock, patch
from literature_scout.daily import send_email


class SenderTests(unittest.TestCase):
    @patch.dict('os.environ', {'SCOUT_SMTP_HOST': 'smtp.example.org', 'SCOUT_SMTP_PORT': '587',
        'SCOUT_SMTP_SECURITY': 'starttls', 'SCOUT_SMTP_USER': 'sender@example.org',
        'SCOUT_SMTP_PASSWORD': 'fake-test-only', 'SCOUT_EMAIL_FROM': 'sender@example.org',
        'SCOUT_EMAIL_NAME': 'PaperBeacon', 'SCOUT_EMAIL_TO': 'researcher@example.org'}, clear=True)
    @patch('literature_scout.daily.smtplib.SMTP')
    def test_display_name_login_and_receiver(self, smtp):
        connection = smtp.return_value.__enter__.return_value
        connection.send_message.return_value = {}
        send_email({'subject': 'Test', 'body': 'Test', 'message_id': '<test@example.org>',
                    'date_header': 'Thu, 05 Nov 2026 07:30:00 +0800'})
        message = connection.send_message.call_args.args[0]
        self.assertEqual(str(message['From']), 'PaperBeacon <sender@example.org>')
        self.assertEqual(str(message['To']), 'researcher@example.org')
        connection.login.assert_called_once_with('sender@example.org', 'fake-test-only')
