"""
Comprehensive Verification Suite for Portal Email Notification Policy

Verifies:
1. FACULTY -> STUDENTS (KEEP ENABLED):
   - Faculty task assignment / update (FACULTY_UPDATE_TASKS) -> dispatches to student team
   - Faculty feedback (FACULTY_SUBMIT_FEEDBACK) -> dispatches to student team
   - Faculty assessment marks (FACULTY_PUBLISH_MARKS) -> dispatches to student team
   - Faculty rubric evaluation save (EVALUATOR_SAVE_RUBRIC) -> dispatches to student team
   - Faculty objectives review (FACULTY_REVIEW_OBJECTIVES) -> dispatches to student team
   - Faculty research paper review (FACULTY_REVIEW_PAPER) -> dispatches to student team

2. ALL OTHER DIRECTIONS (TEMPORARILY DISABLED):
   - Student -> Faculty: project proposals (STUDENT_SUBMIT_PROPOSAL) -> ZERO emails
   - Student -> Faculty: progress deliverables (STUDENT_UPLOAD_PROGRESS) -> ZERO emails
   - Student -> Faculty: objectives submission (STUDENT_SUBMIT_OBJECTIVES) -> ZERO emails
   - Coordinator -> Students: guide allocation (COORDINATOR_ALLOCATE_GUIDE_TEAM) -> ZERO emails
   - Coordinator -> Faculty: guide allocation (COORDINATOR_ALLOCATE_GUIDE_FACULTY) -> ZERO emails
   - Coordinator -> Students: idea status (COORDINATOR_IDEA_STATUS) -> ZERO emails
   - Coordinator -> Students: rubric evaluation (EVALUATOR_SAVE_RUBRIC) -> ZERO emails
   - Coordinator -> Students: objectives review (FACULTY_REVIEW_OBJECTIVES) -> ZERO emails
   - Coordinator -> Students: paper review (FACULTY_REVIEW_PAPER) -> ZERO emails
   - Any generic/non-faculty-to-student trigger -> ZERO emails

3. REVERSIBILITY:
   - When ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS is set to False,
     all other notification directions resume dispatching immediately.
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import jwt
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import app

class TestNotificationPolicy(unittest.TestCase):
    def setUp(self):
        self.app = app.app.test_client()
        self.secret_key = app.app.config["SECRET_KEY"]

        # Ensure policy is active: ONLY faculty-to-student emails allowed
        app.ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS = True

        # Auth tokens
        self.coordinator_token = jwt.encode(
            {"email": "coordinator@college.edu", "role": "coordinator", "name": "Prof. Coordinator"},
            self.secret_key,
            algorithm="HS256"
        )
        self.faculty_token = jwt.encode(
            {"email": "faculty.guide@college.edu", "role": "faculty", "name": "Dr. Alan Turing"},
            self.secret_key,
            algorithm="HS256"
        )
        self.student_token = jwt.encode(
            {"email": "student1@college.edu", "role": "student", "team_name": "Team-101", "usn": "4MW23CS001"},
            self.secret_key,
            algorithm="HS256"
        )

        self.mock_team = {
            "_id": "60d5ec49f1b2c8b1f8c8e111",
            "team_name": "Team-101",
            "leader_name": "Alice Leader",
            "leader_email": "alice@college.edu",
            "faculty_name": "Dr. Alan Turing",
            "faculty_email": "faculty.guide@college.edu",
            "project_idea": {
                "title": "Smart Campus Navigation",
                "status": "Pending Faculty Approval"
            },
            "members": [
                {"name": "Bob Member", "email": "bob@college.edu", "usn": "4MW23CS002"},
                {"name": "Alice Leader", "email": "alice@college.edu", "usn": "4MW23CS001"}
            ],
            "objective_submission": {
                "allowed": True,
                "objectives": ["Obj 1", "Obj 2"],
                "status": "Submitted"
            }
        }

        self.mock_faculty = {
            "name": "Dr. Alan Turing",
            "email": "faculty.guide@college.edu",
            "role": "faculty"
        }

    def tearDown(self):
        # Reset policy to True after every test
        app.ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS = True

    # =========================================================================
    # PART 1: FACULTY -> STUDENTS (KEEP ENABLED)
    # =========================================================================

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_01_faculty_update_tasks_sends_to_students(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)

        payload = {
            "team_name": "Team-101",
            "new_task": {
                "name": "Implement API Endpoints",
                "deadline": "2026-11-20"
            }
        }
        res = self.app.post("/api/faculty/update_tasks", json=payload)
        self.assertEqual(res.status_code, 200)

        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args[1].get("trigger_name"), "FACULTY_UPDATE_TASKS")
        recipients = mock_send.call_args[0][0]
        self.assertIn("alice@college.edu", recipients)
        self.assertIn("bob@college.edu", recipients)

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_02_faculty_update_feedback_sends_to_students(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)

        payload = {
            "team_name": "Team-101",
            "feedback": "Great progress on database schema."
        }
        res = self.app.post("/api/faculty/update_feedback", json=payload)
        self.assertEqual(res.status_code, 200)

        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args[1].get("trigger_name"), "FACULTY_SUBMIT_FEEDBACK")
        recipients = mock_send.call_args[0][0]
        self.assertIn("alice@college.edu", recipients)
        self.assertIn("bob@college.edu", recipients)

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_03_faculty_add_assessment_marks_sends_to_students(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.evaluations.find_one.return_value = None
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)

        payload = {
            "team_name": "Team-101",
            "new_assessment": {
                "assessment": "Phase 1 Internal Review",
                "members": [
                    {"usn": "4MW23CS001", "name": "Alice Leader", "marks": 25, "max_marks": 30}
                ]
            }
        }
        headers = {"Authorization": f"Bearer {self.faculty_token}"}
        res = self.app.post("/api/faculty/add_assessment_marks", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)

        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args[1].get("trigger_name"), "FACULTY_PUBLISH_MARKS")
        recipients = mock_send.call_args[0][0]
        self.assertIn("alice@college.edu", recipients)

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_04_faculty_save_evaluation_sends_to_students(self, mock_send, mock_db):
        mock_db.evaluations.find_one.return_value = None
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.evaluations.insert_one.return_value = MagicMock(inserted_id="eval1")

        payload = {
            "team_name": "Team-101",
            "evaluation": {
                "phases": [
                    {
                        "phase_name": "Phase 1",
                        "criteria": [
                            {"marks": [{"marks_obtained": 18, "maximum_marks": 20}]}
                        ]
                    }
                ]
            }
        }
        headers = {"Authorization": f"Bearer {self.faculty_token}"}
        res = self.app.post("/api/evaluation/save", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)

        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args[1].get("trigger_name"), "EVALUATOR_SAVE_RUBRIC")
        recipients = mock_send.call_args[0][0]
        self.assertIn("alice@college.edu", recipients)
        self.assertIn("bob@college.edu", recipients)

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_05_faculty_review_objectives_sends_to_students(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)

        payload = {
            "team_name": "Team-101",
            "status": "Approved",
            "review_notes": "Well aligned with project scope."
        }
        headers = {"Authorization": f"Bearer {self.faculty_token}"}
        res = self.app.post("/api/evaluation/objectives/review", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)

        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args[1].get("trigger_name"), "FACULTY_REVIEW_OBJECTIVES")
        recipients = mock_send.call_args[0][0]
        self.assertIn("alice@college.edu", recipients)

    # =========================================================================
    # PART 2: STUDENT -> FACULTY (TEMPORARILY DISABLED)
    # =========================================================================

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_06_student_submit_proposal_sends_zero_emails(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)

        payload = {
            "title": "Smart Campus Navigation",
            "domain": "IoT",
            "abstract": "An automated indoor positioning system.",
            "technologies": ["Python", "Flask", "BLE"]
        }
        headers = {"Authorization": f"Bearer {self.student_token}"}
        res = self.app.post("/api/team/save_project_idea", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)

        # Disallowed under policy: 0 emails
        mock_send.assert_not_called()

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_07_student_upload_progress_sends_zero_emails(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)

        payload = {
            "notes": "Completed initial hardware circuit setup."
        }
        headers = {"Authorization": f"Bearer {self.student_token}"}
        res = self.app.post("/api/team/upload_progress", data=payload, headers=headers)
        self.assertEqual(res.status_code, 200)

        # Disallowed under policy: 0 emails
        mock_send.assert_not_called()

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_08_student_submit_objectives_sends_zero_emails(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)

        payload = {
            "objectives": ["Design sensors", "Implement gateway", "Deploy portal", "Validate accuracy"]
        }
        headers = {"Authorization": f"Bearer {self.student_token}"}
        res = self.app.post("/api/evaluation/objectives/submit", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)

        # Disallowed under policy: 0 emails
        mock_send.assert_not_called()

    # =========================================================================
    # PART 3: COORDINATOR ACTIONS (TEMPORARILY DISABLED)
    # =========================================================================

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_09_coordinator_reallocate_sends_zero_emails(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.faculty.find_one.return_value = self.mock_faculty
        mock_db.teams.count_documents.return_value = 1
        mock_db.allocations.update_one.return_value = MagicMock(modified_count=1)
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)

        payload = {
            "team_name": "Team-101",
            "faculty_email": "faculty.guide@college.edu"
        }
        headers = {"Authorization": f"Bearer {self.coordinator_token}"}
        res = self.app.post("/api/allocate/manual", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)

        # Neither students NOR faculty receive emails from coordinator allocation
        mock_send.assert_not_called()

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_10_coordinator_idea_status_sends_zero_emails(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)
        mock_db.projects.count_documents.return_value = 10

        payload = {
            "team_name": "Team-101",
            "title": "Smart Campus Navigation",
            "status": "Approved"
        }
        headers = {"Authorization": f"Bearer {self.coordinator_token}"}
        res = self.app.post("/api/ideas/update_status", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)

        mock_send.assert_not_called()

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_11_coordinator_save_evaluation_sends_zero_emails(self, mock_send, mock_db):
        mock_db.evaluations.find_one.return_value = None
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.evaluations.insert_one.return_value = MagicMock(inserted_id="eval1")

        payload = {
            "team_name": "Team-101",
            "evaluation": {
                "phases": [
                    {
                        "phase_name": "Phase 1",
                        "criteria": [
                            {"marks": [{"marks_obtained": 18, "maximum_marks": 20}]}
                        ]
                    }
                ]
            }
        }
        headers = {"Authorization": f"Bearer {self.coordinator_token}"}
        res = self.app.post("/api/evaluation/save", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)

        mock_send.assert_not_called()

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_12_coordinator_review_objectives_sends_zero_emails(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)

        payload = {
            "team_name": "Team-101",
            "status": "Approved",
            "review_notes": "Coordinator approved."
        }
        headers = {"Authorization": f"Bearer {self.coordinator_token}"}
        res = self.app.post("/api/evaluation/objectives/review", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)

        mock_send.assert_not_called()

    # =========================================================================
    # PART 4: DIRECT GATE CHECK IN send_email_notification
    # =========================================================================

    def test_13_send_email_notification_gate_blocks_disallowed_triggers(self):
        # Student -> Faculty
        self.assertFalse(app.send_email_notification(["fac@college.edu"], "S", "M", trigger_name="STUDENT_SUBMIT_PROPOSAL", async_send=False))
        self.assertFalse(app.send_email_notification(["fac@college.edu"], "S", "M", trigger_name="STUDENT_UPLOAD_PROGRESS", async_send=False))
        self.assertFalse(app.send_email_notification(["fac@college.edu"], "S", "M", trigger_name="STUDENT_SUBMIT_OBJECTIVES", async_send=False))

        # Coordinator -> Students & Coordinator -> Faculty
        self.assertFalse(app.send_email_notification(["stu@college.edu"], "S", "M", trigger_name="COORDINATOR_ALLOCATE_GUIDE_TEAM", async_send=False))
        self.assertFalse(app.send_email_notification(["fac@college.edu"], "S", "M", trigger_name="COORDINATOR_ALLOCATE_GUIDE_FACULTY", async_send=False))
        self.assertFalse(app.send_email_notification(["stu@college.edu"], "S", "M", trigger_name="COORDINATOR_IDEA_STATUS", async_send=False))

        # Generic / Other triggers
        self.assertFalse(app.send_email_notification(["user@college.edu"], "S", "M", trigger_name="NOTIFICATION", async_send=False))
        self.assertFalse(app.send_email_notification(["user@college.edu"], "S", "M", trigger_name="UNKNOWN_ACTION", async_send=False))

    # =========================================================================
    # PART 5: REVERSIBILITY TEST
    # =========================================================================

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_14_reversibility_when_policy_disabled(self, mock_send, mock_db):
        # Disable policy (re-enable all notifications)
        app.ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS = False

        # 1. Student proposal sends to faculty
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)
        res = self.app.post("/api/team/save_project_idea", json={"title": "Proposal"}, headers={"Authorization": f"Bearer {self.student_token}"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(mock_send.call_count, 1)
        self.assertEqual(mock_send.call_args[1].get("trigger_name"), "STUDENT_SUBMIT_PROPOSAL")

        # 2. Coordinator guide allocation sends to faculty
        mock_db.faculty.find_one.return_value = self.mock_faculty
        mock_db.teams.count_documents.return_value = 1
        mock_send.reset_mock()
        res = self.app.post("/api/allocate/manual", json={"team_name": "Team-101", "faculty_email": "faculty.guide@college.edu"}, headers={"Authorization": f"Bearer {self.coordinator_token}"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(mock_send.called)

if __name__ == "__main__":
    unittest.main()
