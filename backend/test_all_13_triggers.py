"""
Comprehensive Automated Test Suite for All 13 Notification Triggers
Tests mocked SMTP dispatch, recipient resolution, team-specific accuracy,
student-faculty routing, deduplication, error resilience, and structured logging.
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import smtplib
import socket

sys.path.insert(0, os.path.dirname(__file__))

import app
from app import (
    find_team_by_name,
    get_team_recipient_emails,
    get_team_assigned_faculty,
    send_email_notification,
    _send_smtp_worker,
    render_email_template,
    get_frontend_base_url,
    is_valid_email
)

class TestAll13NotificationTriggers(unittest.TestCase):
    def setUp(self):
        # Sample Team Alpha (Team 41 equivalent)
        self.team_alpha = {
            "team_name": "Team-Alpha",
            "leader_name": "Poorvik Acharya",
            "leader_email": "poorvik@college.edu",
            "faculty_name": "Ms. Mahadevi",
            "faculty_email": "mahadevi@college.edu",
            "project_idea": {
                "title": "Intelligent Water Contamination Monitoring",
                "status": "Pending Faculty Approval"
            },
            "members": [
                {"name": "Prakhyath Nayak", "email": "prakhyath@college.edu", "usn": "4MW23CS096"},
                {"name": "Prashanth", "email": "prashanth@college.edu", "usn": "4MW23CS098"},
                {"name": "Prithesh", "email": "prithesh@college.edu", "usn": "4MW23CS104"},
                {"name": "Poorvik Acharya", "email": "POORVIK@college.edu", "usn": "4MW23CS092"}  # Duplicate with case variation
            ]
        }

        # Sample Team Beta (for cross-team isolation tests)
        self.team_beta = {
            "team_name": "Team-Beta",
            "leader_name": "Bob Smith",
            "leader_email": "bob@college.edu",
            "faculty_name": "Dr. Alan Turing",
            "faculty_email": "turing@college.edu",
            "project_idea": {
                "title": "AI Autonomous Drone Navigation"
            },
            "members": [
                {"name": "Charlie", "email": "charlie@college.edu", "usn": "4MW23CS002"}
            ]
        }

    # =========================================================================
    # 1. Faculty assigns or updates tasks
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_01_faculty_assigns_tasks(self, mock_worker):
        mock_worker.return_value = True
        recipients = get_team_recipient_emails(self.team_alpha)
        task_name = "Prepare System Architecture Diagram"
        deadline = "2026-11-01"

        plain_msg = f"Task: {task_name}\nDeadline: {deadline}"
        html_msg = render_email_template(
            headline="New Task Assigned",
            badge_text="Task Assigned",
            badge_color="#7c3aed",
            team_name=self.team_alpha["team_name"],
            project_title=self.team_alpha["project_idea"]["title"],
            key_details={"Task Name": task_name, "Deadline": deadline},
            message_content="Please complete deliverables before the deadline."
        )

        send_email_notification(
            recipients,
            f"New Task Assigned: {task_name} - {self.team_alpha['team_name']}",
            plain_msg,
            html_msg,
            async_send=False,
            trigger_name="FACULTY_UPDATE_TASKS",
            team_id=self.team_alpha["team_name"]
        )

        mock_worker.assert_called_once()
        args = mock_worker.call_args[0]
        # Verify all 4 team members receive it
        self.assertEqual(len(args[0]), 4)
        self.assertIn("poorvik@college.edu", args[0])
        self.assertIn("prashanth@college.edu", args[0])
        self.assertEqual(args[4], "FACULTY_UPDATE_TASKS")
        self.assertEqual(args[5], "Team-Alpha")

    # =========================================================================
    # 2. Faculty submits or updates feedback
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_02_faculty_submits_feedback(self, mock_worker):
        mock_worker.return_value = True
        recipients = get_team_recipient_emails(self.team_alpha)
        feedback_text = "Refine the sensor calibration section in your methodology."

        send_email_notification(
            recipients,
            f"New Feedback Received: {self.team_alpha['team_name']}",
            feedback_text,
            f"<html>{feedback_text}</html>",
            async_send=False,
            trigger_name="FACULTY_SUBMIT_FEEDBACK",
            team_id=self.team_alpha["team_name"]
        )

        mock_worker.assert_called_once()
        args = mock_worker.call_args[0]
        self.assertEqual(set(args[0]), {
            "poorvik@college.edu",
            "prakhyath@college.edu",
            "prashanth@college.edu",
            "prithesh@college.edu"
        })
        self.assertEqual(args[4], "FACULTY_SUBMIT_FEEDBACK")
        self.assertEqual(args[5], "Team-Alpha")

    # =========================================================================
    # 3. Faculty publishes assessment marks
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_03_faculty_publishes_marks(self, mock_worker):
        mock_worker.return_value = True
        recipients = get_team_recipient_emails(self.team_alpha)
        assessment_name = "Phase 1 Evaluation"

        send_email_notification(
            recipients,
            f"Assessment Marks Published: {assessment_name} - {self.team_alpha['team_name']}",
            f"Marks recorded for {assessment_name}",
            f"<html>Marks for {assessment_name}</html>",
            async_send=False,
            trigger_name="FACULTY_PUBLISH_MARKS",
            team_id=self.team_alpha["team_name"]
        )

        mock_worker.assert_called_once()
        args = mock_worker.call_args[0]
        self.assertEqual(len(args[0]), 4)
        self.assertEqual(args[4], "FACULTY_PUBLISH_MARKS")
        self.assertEqual(args[5], "Team-Alpha")

    # =========================================================================
    # 4. Faculty approves or rejects a project
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_04_faculty_approves_rejects_project(self, mock_worker):
        mock_worker.return_value = True
        recipients = get_team_recipient_emails(self.team_alpha)
        status = "Approved"

        send_email_notification(
            recipients,
            f"Project Idea Status: {status} - {self.team_alpha['team_name']}",
            f"Status updated to {status}",
            f"<html>Status: {status}</html>",
            async_send=False,
            trigger_name="FACULTY_PROJECT_STATUS",
            team_id=self.team_alpha["team_name"]
        )

        mock_worker.assert_called_once()
        args = mock_worker.call_args[0]
        self.assertEqual(args[4], "FACULTY_PROJECT_STATUS")
        self.assertEqual(args[5], "Team-Alpha")

    # =========================================================================
    # 5. Faculty or coordinator updates project idea status
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_05_coordinator_updates_idea_status(self, mock_worker):
        mock_worker.return_value = True
        recipients = get_team_recipient_emails(self.team_alpha)
        new_status = "Approved"

        # Under portal policy: Coordinator -> Students is temporarily disabled (zero emails)
        res = send_email_notification(
            recipients,
            f"Project Proposal {new_status}: {self.team_alpha['team_name']}",
            f"Proposal updated to {new_status}",
            f"<html>Proposal: {new_status}</html>",
            async_send=False,
            trigger_name="COORDINATOR_IDEA_STATUS",
            team_id=self.team_alpha["team_name"]
        )

        self.assertFalse(res)
        mock_worker.assert_not_called()

    # =========================================================================
    # 6. Faculty updates stage approvals
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_06_faculty_updates_stage_approvals(self, mock_worker):
        mock_worker.return_value = True
        recipients = get_team_recipient_emails(self.team_alpha)
        stage_name = "Literature Review"
        stage_status = "Approved"

        send_email_notification(
            recipients,
            f"Project Stage Update: {stage_name} ({stage_status}) - {self.team_alpha['team_name']}",
            f"Stage {stage_name} marked as {stage_status}",
            f"<html>Stage {stage_name}: {stage_status}</html>",
            async_send=False,
            trigger_name="FACULTY_STAGE_APPROVAL",
            team_id=self.team_alpha["team_name"]
        )

        mock_worker.assert_called_once()
        args = mock_worker.call_args[0]
        self.assertEqual(args[4], "FACULTY_STAGE_APPROVAL")
        self.assertEqual(args[5], "Team-Alpha")

    # =========================================================================
    # 7. Evaluator saves evaluation results
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_07_evaluator_saves_rubric(self, mock_worker):
        mock_worker.return_value = True
        recipients = get_team_recipient_emails(self.team_alpha)

        send_email_notification(
            recipients,
            f"Evaluation Rubric Results Saved: {self.team_alpha['team_name']}",
            "Rubric scoring sheet has been updated.",
            "<html>Evaluation sheet updated</html>",
            async_send=False,
            trigger_name="EVALUATOR_SAVE_RUBRIC",
            team_id=self.team_alpha["team_name"]
        )

        mock_worker.assert_called_once()
        args = mock_worker.call_args[0]
        self.assertEqual(args[4], "EVALUATOR_SAVE_RUBRIC")
        self.assertEqual(args[5], "Team-Alpha")

    # =========================================================================
    # 8. Faculty reviews project objectives
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_08_faculty_reviews_objectives(self, mock_worker):
        mock_worker.return_value = True
        recipients = get_team_recipient_emails(self.team_alpha)
        status = "Approved"

        send_email_notification(
            recipients,
            f"Project Objectives Reviewed: {status} - {self.team_alpha['team_name']}",
            f"Objectives have been marked as '{status}'.",
            f"<html>Objectives: {status}</html>",
            async_send=False,
            trigger_name="FACULTY_REVIEW_OBJECTIVES",
            team_id=self.team_alpha["team_name"]
        )

        mock_worker.assert_called_once()
        args = mock_worker.call_args[0]
        self.assertEqual(args[4], "FACULTY_REVIEW_OBJECTIVES")
        self.assertEqual(args[5], "Team-Alpha")

    # =========================================================================
    # 9. Faculty reviews a research paper
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_09_faculty_reviews_paper(self, mock_worker):
        mock_worker.return_value = True
        recipients = get_team_recipient_emails(self.team_alpha)
        status = "Approved"

        send_email_notification(
            recipients,
            f"Research Paper Review: {status} - {self.team_alpha['team_name']}",
            f"Paper review outcome: {status}",
            f"<html>Paper review: {status}</html>",
            async_send=False,
            trigger_name="FACULTY_REVIEW_PAPER",
            team_id=self.team_alpha["team_name"]
        )

        mock_worker.assert_called_once()
        args = mock_worker.call_args[0]
        self.assertEqual(args[4], "FACULTY_REVIEW_PAPER")
        self.assertEqual(args[5], "Team-Alpha")

    # =========================================================================
    # 10. Coordinator allocates or reassigns a faculty guide
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_10_coordinator_allocates_guide(self, mock_worker):
        mock_worker.return_value = True
        team_recipients = get_team_recipient_emails(self.team_alpha)
        faculty_email = self.team_alpha["faculty_email"]

        # Under portal policy: Coordinator -> Students and Coordinator -> Faculty are disabled (zero emails)
        res_team = send_email_notification(
            team_recipients,
            f"Faculty Guide Assigned: {self.team_alpha['faculty_name']} - {self.team_alpha['team_name']}",
            "Guide assigned to your team.",
            "<html>Guide assigned</html>",
            async_send=False,
            trigger_name="COORDINATOR_ALLOCATE_GUIDE_TEAM",
            team_id=self.team_alpha["team_name"]
        )
        self.assertFalse(res_team)

        # Part 2: Notify newly assigned faculty member
        res_faculty = send_email_notification(
            [faculty_email],
            f"New Project Team Assigned: {self.team_alpha['team_name']}",
            "New team assigned to you.",
            "<html>New team assigned</html>",
            async_send=False,
            trigger_name="COORDINATOR_ALLOCATE_GUIDE_FACULTY",
            team_id=self.team_alpha["team_name"]
        )
        self.assertFalse(res_faculty)
        mock_worker.assert_not_called()

    # =========================================================================
    # 11. Student submits a project proposal
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_11_student_submits_proposal(self, mock_worker):
        mock_worker.return_value = True
        faculty_email, f_name = get_team_assigned_faculty(self.team_alpha)

        self.assertEqual(faculty_email, "mahadevi@college.edu")
        self.assertEqual(f_name, "Ms. Mahadevi")

        # Under portal policy: Student -> Faculty is disabled (zero emails)
        res = send_email_notification(
            [faculty_email],
            f"New Project Proposal Submitted: {self.team_alpha['team_name']}",
            "Students submitted project proposal.",
            "<html>Proposal submitted</html>",
            async_send=False,
            trigger_name="STUDENT_SUBMIT_PROPOSAL",
            team_id=self.team_alpha["team_name"]
        )

        self.assertFalse(res)
        mock_worker.assert_not_called()

    # =========================================================================
    # 12. Student uploads project progress or deliverables
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_12_student_uploads_progress(self, mock_worker):
        mock_worker.return_value = True
        faculty_email, f_name = get_team_assigned_faculty(self.team_alpha)

        # Under portal policy: Student -> Faculty is disabled (zero emails)
        res = send_email_notification(
            [faculty_email],
            f"New Progress Deliverable: {self.team_alpha['team_name']}",
            "Students uploaded a new deliverable.",
            "<html>Progress deliverable uploaded</html>",
            async_send=False,
            trigger_name="STUDENT_UPLOAD_PROGRESS",
            team_id=self.team_alpha["team_name"]
        )

        self.assertFalse(res)
        mock_worker.assert_not_called()

    # =========================================================================
    # 13. Student submits project objectives
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_13_student_submits_objectives(self, mock_worker):
        mock_worker.return_value = True
        faculty_email, f_name = get_team_assigned_faculty(self.team_alpha)

        # Under portal policy: Student -> Faculty is disabled (zero emails)
        res = send_email_notification(
            [faculty_email],
            f"Project Objectives Submitted for Review: {self.team_alpha['team_name']}",
            "Students submitted project objectives for review.",
            "<html>Objectives submitted</html>",
            async_send=False,
            trigger_name="STUDENT_SUBMIT_OBJECTIVES",
            team_id=self.team_alpha["team_name"]
        )

        self.assertFalse(res)
        mock_worker.assert_not_called()

    # =========================================================================
    # Edge Case: Deduplication and Case-Insensitive Matching
    # =========================================================================
    def test_deduplication_and_case_insensitivity(self):
        recipients = get_team_recipient_emails(self.team_alpha)
        # Leader is poorvik@college.edu, members also has POORVIK@college.edu
        # It must only appear once in lowercase
        self.assertEqual(recipients.count("poorvik@college.edu"), 1)
        self.assertEqual(len(recipients), 4)

    # =========================================================================
    # Edge Case: Cross-Team Isolation (Never leak emails across teams)
    # =========================================================================
    def test_cross_team_isolation(self):
        recipients_alpha = set(get_team_recipient_emails(self.team_alpha))
        recipients_beta = set(get_team_recipient_emails(self.team_beta))

        # Disjoint sets: no team B student ever appears in team A list
        self.assertEqual(recipients_alpha.intersection(recipients_beta), set())
        self.assertNotIn("bob@college.edu", recipients_alpha)
        self.assertNotIn("charlie@college.edu", recipients_alpha)

    # =========================================================================
    # Edge Case: Missing or Invalid Recipients Handling
    # =========================================================================
    @patch("app._send_smtp_worker")
    def test_missing_or_invalid_recipients(self, mock_worker):
        # Empty recipient list
        result = send_email_notification([], "Subject", "Message", async_send=False)
        self.assertFalse(result)
        mock_worker.assert_not_called()

        # Invalid recipient format
        result2 = send_email_notification(["not-an-email", "@bad.com"], "Subject", "Message", async_send=False)
        self.assertFalse(result2)
        mock_worker.assert_not_called()

        # Non-existent team
        recipients_none = get_team_recipient_emails(None)
        self.assertEqual(recipients_none, [])

    # =========================================================================
    # Edge Case: SMTP Authentication Failure Handling
    # =========================================================================
    @patch("smtplib.SMTP")
    def test_smtp_auth_failure_handling(self, mock_smtp):
        instance = MagicMock()
        mock_smtp.return_value = instance
        instance.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")

        result = _send_smtp_worker(
            ["prashanth@college.edu"],
            "Test Subject",
            "Test Body",
            trigger_name="TEST_AUTH_FAILURE",
            team_id="41"
        )
        self.assertFalse(result)

    # =========================================================================
    # Edge Case: SMTP Connection Timeout Handling
    # =========================================================================
    @patch("smtplib.SMTP")
    def test_smtp_timeout_handling(self, mock_smtp):
        instance = MagicMock()
        mock_smtp.return_value = instance
        instance.login.side_effect = socket.timeout("Connection timed out after 10s")

        result = _send_smtp_worker(
            ["prashanth@college.edu"],
            "Test Subject",
            "Test Body",
            trigger_name="TEST_TIMEOUT",
            team_id="41"
        )
        self.assertFalse(result)

    # =========================================================================
    # Edge Case: Background Worker Exception Handling
    # =========================================================================
    @patch("smtplib.SMTP")
    def test_worker_unexpected_exception(self, mock_smtp):
        instance = MagicMock()
        mock_smtp.return_value = instance
        instance.sendmail.side_effect = RuntimeError("Unexpected socket error")

        result = _send_smtp_worker(
            ["prashanth@college.edu"],
            "Test Subject",
            "Test Body",
            trigger_name="TEST_RUNTIME_ERROR",
            team_id="41"
        )
        self.assertFalse(result)

if __name__ == "__main__":
    unittest.main()
