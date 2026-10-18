"""
Unit and integration test suite for the upgraded email notification subsystem.
Tests recipient deduplication, validation, template rendering, XSS escaping,
mocked SMTP delivery, failure recovery, and background thread execution.
"""
import unittest
from unittest.mock import patch, MagicMock
import os
import re
import html
import threading
import time

# Ensure we import from app
import sys
sys.path.insert(0, os.path.dirname(__file__))

from app import (
    is_valid_email,
    get_team_recipient_emails,
    get_frontend_base_url,
    render_email_template,
    send_email_notification,
    _send_smtp_worker
)

class TestEmailValidationAndRecipients(unittest.TestCase):
    def test_is_valid_email(self):
        # Valid cases
        self.assertTrue(is_valid_email("student@example.com"))
        self.assertTrue(is_valid_email("student.123+tag@gmail.com"))
        self.assertTrue(is_valid_email("  LEADER@COLLEGE.EDU  "))

        # Invalid cases
        self.assertFalse(is_valid_email(None))
        self.assertFalse(is_valid_email(""))
        self.assertFalse(is_valid_email("notanemail"))
        self.assertFalse(is_valid_email("missing@domain"))
        self.assertFalse(is_valid_email("@missinguser.com"))
        self.assertFalse(is_valid_email(12345))

    def test_get_team_recipient_emails_deduplication(self):
        team = {
            "leader_email": "leader@college.edu",
            "members": [
                {"name": "Leader Student", "email": "LEADER@college.edu"}, # duplicate in diff case
                {"name": "Member Two", "email": "member2@college.edu"},
                {"name": "Member Three", "email": "member3@college.edu"},
                {"name": "Member Four", "email": ""} # empty
            ]
        }
        recipients = get_team_recipient_emails(team)
        self.assertEqual(len(recipients), 3)
        self.assertIn("leader@college.edu", recipients)
        self.assertIn("member2@college.edu", recipients)
        self.assertIn("member3@college.edu", recipients)

    def test_get_team_recipient_emails_missing_data(self):
        self.assertEqual(get_team_recipient_emails(None), [])
        self.assertEqual(get_team_recipient_emails({}), [])
        self.assertEqual(get_team_recipient_emails({"leader_email": "", "members": []}), [])
        self.assertEqual(get_team_recipient_emails({"leader_email": "invalid-email"}), [])

    def test_get_team_recipient_emails_string_members(self):
        # In case legacy members are list of strings
        team = {
            "leader_email": "leader@college.edu",
            "members": ["student2@college.edu", "student3@college.edu", "leader@college.edu"]
        }
        recipients = get_team_recipient_emails(team)
        self.assertEqual(len(recipients), 3)


class TestEmailTemplateRendering(unittest.TestCase):
    def test_html_template_escaping(self):
        malicious_input = "<script>alert('xss')</script>"
        rendered = render_email_template(
            headline=f"Project {malicious_input}",
            badge_text="Approved",
            badge_color="#059669",
            team_name=f"Team {malicious_input}",
            project_title=f"AI System {malicious_input}",
            key_details={"Notes": malicious_input},
            message_content=f"Feedback: {malicious_input}",
            action_url="http://localhost:5000/dashboard",
            action_text="View Dashboard"
        )
        # Ensure script tag is strictly escaped
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;", rendered)
        self.assertIn("http://localhost:5000/dashboard", rendered)

    def test_unicode_and_emojis(self):
        unicode_title = "Intelligent AI Monitoring — 🚀 [Phase 1]"
        rendered = render_email_template(
            headline="New Update 🎉",
            badge_text="Active",
            badge_color="#2563eb",
            team_name="Team Alpha 🌟",
            project_title=unicode_title,
            key_details={"Grade": "A+ 💯"},
            message_content="Great job on the demo! ✨",
            action_url="http://localhost:5000",
            action_text="Go to Portal"
        )
        self.assertIn("Intelligent AI Monitoring", rendered)
        self.assertIn("Team Alpha", rendered)


class TestMockedSMTPSending(unittest.TestCase):
    @patch("smtplib.SMTP")
    @patch.dict(os.environ, {"EMAIL_USER": "test_sender@gmail.com", "EMAIL_PASS": "test_app_pass_16c", "SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587"})
    def test_smtp_worker_success(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        recipients = ["student1@college.edu", "student2@college.edu"]
        success = _send_smtp_worker(
            recipients=recipients,
            subject="Test Subject",
            plain_text="Plain message",
            html_content="<p>HTML message</p>"
        )

        self.assertTrue(success)
        mock_smtp_class.assert_called_with("smtp.gmail.com", 587, timeout=10)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_with("test_sender@gmail.com", "test_app_pass_16c")
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()

    @patch("smtplib.SMTP")
    @patch.dict(os.environ, {"EMAIL_USER": "test_sender@gmail.com", "EMAIL_PASS": "test_app_pass_16c"})
    def test_smtp_worker_auth_failure(self, mock_smtp_class):
        import smtplib
        mock_server = MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
        mock_smtp_class.return_value = mock_server

        success = _send_smtp_worker(
            recipients=["student@college.edu"],
            subject="Test Auth Failure",
            plain_text="Plain message"
        )

        self.assertFalse(success)
        mock_server.quit.assert_called_once()

    @patch("smtplib.SMTP")
    @patch.dict(os.environ, {"EMAIL_USER": "test_sender@gmail.com", "EMAIL_PASS": "test_app_pass_16c"})
    def test_background_thread_execution(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        # Test asynchronous dispatch
        res = send_email_notification(
            to_email_or_list=["student@college.edu"],
            subject="Async Thread Test",
            message="Testing async dispatch",
            async_send=True,
            trigger_name="FACULTY_UPDATE_TASKS"
        )
        self.assertTrue(res)

        # Allow background thread a moment to finish
        time.sleep(0.3)
        mock_server.sendmail.assert_called_once()


if __name__ == "__main__":
    unittest.main()
