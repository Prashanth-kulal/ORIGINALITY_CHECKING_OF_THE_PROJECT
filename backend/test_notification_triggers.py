"""
Integration test for notification triggers in the upgraded email notification system.
Mocks the underlying _send_smtp_worker to test payload generation, recipient resolution,
and parameter dispatch without network latency.
"""
import unittest
from unittest.mock import patch, MagicMock
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import app
from app import (
    get_team_recipient_emails,
    render_email_template,
    get_frontend_base_url,
    send_email_notification
)

class TestNotificationTriggersPayloads(unittest.TestCase):
    def setUp(self):
        self.mock_team = {
            "team_name": "Autonomous Drones",
            "leader_name": "Alice Johnson",
            "leader_email": "alice@college.edu",
            "faculty_name": "Dr. Alan Turing",
            "faculty_email": "aturing@college.edu",
            "project_idea": {
                "title": "Autonomous Drone Pathfinding Using Vision Transformers"
            },
            "members": [
                {"name": "Bob Smith", "email": "bob@college.edu", "usn": "4MW21CS002"},
                {"name": "Charlie Davis", "email": "charlie@college.edu", "usn": "4MW21CS003"},
                {"name": "Alice Johnson", "email": "ALICE@college.edu", "usn": "4MW21CS001"} # duplicate
            ]
        }

    def test_recipient_resolution_for_team(self):
        recipients = get_team_recipient_emails(self.mock_team)
        self.assertEqual(len(recipients), 3)
        self.assertEqual(set(recipients), {"alice@college.edu", "bob@college.edu", "charlie@college.edu"})

    @patch("app._send_smtp_worker")
    def test_task_assigned_trigger(self, mock_worker):
        mock_worker.return_value = True
        recipients = get_team_recipient_emails(self.mock_team)
        task_name = "Implement Optical Flow"
        deadline = "2026-11-15"
        base_url = get_frontend_base_url()

        plain = f"Hello {self.mock_team['team_name']},\n\nTask: {task_name}\nDeadline: {deadline}"
        html_msg = render_email_template(
            headline="New Task Assigned",
            badge_text="Task Assigned",
            badge_color="#7c3aed",
            team_name=self.mock_team["team_name"],
            project_title=self.mock_team["project_idea"]["title"],
            key_details={"Task": task_name, "Deadline": deadline},
            message_content="Complete optical flow implementation.",
            action_url=f"{base_url}/team-dasboard.html"
        )
        send_email_notification(
            recipients, f"New Task Assigned: {task_name}", plain, html_msg,
            async_send=False, trigger_name="FACULTY_UPDATE_TASKS"
        )

        mock_worker.assert_called_once()
        call_args = mock_worker.call_args[0]
        self.assertEqual(call_args[0], recipients)
        self.assertIn("Implement Optical Flow", call_args[1])
        self.assertIn("Autonomous Drone", call_args[3])

    @patch("app._send_smtp_worker")
    def test_project_status_approved_trigger(self, mock_worker):
        mock_worker.return_value = True
        recipients = get_team_recipient_emails(self.mock_team)
        status = "Approved"
        base_url = get_frontend_base_url()

        html_msg = render_email_template(
            headline=f"Project Idea {status}",
            badge_text=status,
            badge_color="#059669",
            team_name=self.mock_team["team_name"],
            project_title=self.mock_team["project_idea"]["title"],
            key_details={"Status": status, "Reviewer": self.mock_team["faculty_name"]},
            message_content="Proposal approved without reservations.",
            action_url=f"{base_url}/team-dasboard.html"
        )
        send_email_notification(
            recipients, f"Project Idea Status: {status}", "Plain text", html_msg,
            async_send=False, trigger_name="FACULTY_PROJECT_STATUS"
        )

        mock_worker.assert_called_once()
        self.assertEqual(mock_worker.call_args[0][0], recipients)

    @patch("app._send_smtp_worker")
    def test_faculty_allocation_trigger(self, mock_worker):
        mock_worker.return_value = True
        recipients = get_team_recipient_emails(self.mock_team)
        # 1. Under policy: Coordinator -> Students is blocked (zero emails)
        res1 = send_email_notification(
            recipients,
            f"Faculty Guide Assigned: {self.mock_team['faculty_name']}",
            "Guide assigned",
            "<html>Guide assigned</html>",
            async_send=False,
            trigger_name="COORDINATOR_ALLOCATE_GUIDE_TEAM"
        )
        self.assertFalse(res1)

        # 2. Under policy: Coordinator -> Faculty is blocked (zero emails)
        res2 = send_email_notification(
            [self.mock_team["faculty_email"]],
            f"New Project Team Assigned: {self.mock_team['team_name']}",
            "Team assigned to you",
            "<html>Team assigned</html>",
            async_send=False,
            trigger_name="COORDINATOR_ALLOCATE_GUIDE_FACULTY"
        )
        self.assertFalse(res2)

        # Zero emails sent
        mock_worker.assert_not_called()

    @patch("app._send_smtp_worker")
    def test_student_submission_to_faculty_trigger(self, mock_worker):
        mock_worker.return_value = True
        faculty_email = self.mock_team["faculty_email"]
        # Under policy: Student -> Faculty is blocked (zero emails)
        res = send_email_notification(
            [faculty_email],
            f"New Project Proposal Submitted: {self.mock_team['team_name']}",
            "Students submitted proposal",
            "<html>Proposal submitted</html>",
            async_send=False,
            trigger_name="STUDENT_SUBMIT_PROPOSAL"
        )
        self.assertFalse(res)
        mock_worker.assert_not_called()

    @patch("app._send_smtp_worker")
    def test_policy_reversibility(self, mock_worker):
        # Temporarily disable policy: all directions work
        app.ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS = False
        try:
            mock_worker.return_value = True
            res = send_email_notification(
                ["faculty@college.edu"],
                "Student Proposal",
                "Proposal message",
                async_send=False,
                trigger_name="STUDENT_SUBMIT_PROPOSAL"
            )
            self.assertTrue(res)
            mock_worker.assert_called_once()
        finally:
            app.ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS = True


if __name__ == "__main__":
    unittest.main()
