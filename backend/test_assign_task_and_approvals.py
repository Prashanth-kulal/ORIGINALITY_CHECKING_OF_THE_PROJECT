"""
Automated tests for Assign Task status updating and Project Stage Approvals.
Tests authorization, status transitions, database persistence, and absence of redundant notifications.
"""
import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import jwt

sys.path.insert(0, os.path.dirname(__file__))

import app
from app import app as flask_app, db

class TestAssignTaskAndApprovals(unittest.TestCase):
    def setUp(self):
        flask_app.config["TESTING"] = True
        self.client = flask_app.test_client()

        self.authorized_faculty_email = "guide_pro@college.edu"
        self.unauthorized_faculty_email = "intruder_fac@college.edu"
        self.coordinator_email = "coordinator@college.edu"

        # Generate tokens
        self.auth_token = jwt.encode(
            {"email": self.authorized_faculty_email, "role": "faculty", "name": "Dr. Guide"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )
        self.unauth_token = jwt.encode(
            {"email": self.unauthorized_faculty_email, "role": "faculty", "name": "Dr. Other"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )
        self.coord_token = jwt.encode(
            {"email": self.coordinator_email, "role": "coordinator", "name": "Prof. Coordinator"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )

        self.mock_team = {
            "_id": "mock_team_id_123",
            "team_name": "Team-Alpha",
            "leader_name": "Alice Leader",
            "leader_email": "alice@college.edu",
            "faculty_name": "Dr. Guide",
            "faculty_email": self.authorized_faculty_email,
            "tasks": [
                {
                    "name": "Design Database Schema",
                    "deadline": "2026-11-10",
                    "status": "Pending",
                    "description": "Create MongoDB collections and schemas"
                },
                {
                    "name": "Implement JWT Auth",
                    "deadline": "2026-11-15",
                    "status": "Pending"
                }
            ],
            "approvals": [
                {
                    "stage": "Project Proposal",
                    "status": "Pending"
                }
            ],
            "project_idea": {
                "title": "Autonomous Drone Pathfinding",
                "status": "Pending"
            },
            "members": [
                {"name": "Alice Leader", "email": "alice@college.edu", "usn": "4MW21CS001"},
                {"name": "Bob Builder", "email": "bob@college.edu", "usn": "4MW21CS002"}
            ]
        }

    # =========================================================================
    # 1. ASSIGN TASK STATUS UPDATE TESTS
    # =========================================================================

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_faculty_can_update_task_status_to_in_progress(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)

        payload = {
            "team_name": "Team-Alpha",
            "task_index": 0,
            "status": "In Progress"
        }
        res = self.client.post(
            "/api/faculty/update_task_status",
            json=payload,
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "In Progress")

        # Verify update in DB was called with correct field
        mock_db.teams.update_one.assert_called_once()
        args = mock_db.teams.update_one.call_args[0]
        self.assertEqual(args[0], {"_id": "mock_team_id_123"})
        self.assertEqual(args[1], {"$set": {"tasks.0.status": "In Progress"}})

        # Verify NO additional email notification was sent
        mock_send.assert_not_called()

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_faculty_can_update_task_status_to_completed(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)

        payload = {
            "team_name": "Team-Alpha",
            "task_index": 1,
            "status": "Completed"
        }
        res = self.client.post(
            "/api/faculty/update_task_status",
            json=payload,
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "Completed")

        # Verify DB update
        args = mock_db.teams.update_one.call_args[0]
        self.assertEqual(args[1], {"$set": {"tasks.1.status": "Completed"}})

        # Verify NO email notification sent
        mock_send.assert_not_called()

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_unauthorized_faculty_cannot_update_task_status(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team

        payload = {
            "team_name": "Team-Alpha",
            "task_index": 0,
            "status": "Completed"
        }
        res = self.client.post(
            "/api/faculty/update_task_status",
            json=payload,
            headers={"Authorization": f"Bearer {self.unauth_token}"}
        )
        self.assertEqual(res.status_code, 403)
        mock_db.teams.update_one.assert_not_called()
        mock_send.assert_not_called()

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_coordinator_can_update_task_status(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.teams.update_one.return_value = MagicMock(modified_count=1)

        payload = {
            "team_name": "Team-Alpha",
            "task_index": 0,
            "status": "Completed"
        }
        res = self.client.post(
            "/api/faculty/update_task_status",
            json=payload,
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        self.assertEqual(res.status_code, 200)
        mock_db.teams.update_one.assert_called_once()
        mock_send.assert_not_called()

    @patch("app.db")
    def test_update_task_status_missing_parameters(self, mock_db):
        res = self.client.post(
            "/api/faculty/update_task_status",
            json={"team_name": "Team-Alpha"},
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        self.assertEqual(res.status_code, 400)

    # =========================================================================
    # 2. APPROVAL SECTION TESTS
    # =========================================================================

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_faculty_can_approve_project_stage(self, mock_send, mock_db):
        mock_db.teams.find_one.side_effect = [
            self.mock_team,  # find_team_by_name
            {"approvals": [{"stage": "Project Proposal", "status": "Approved"}]}  # updated team
        ]
        mock_db.teams.update_one.return_value = MagicMock(matched_count=1)

        payload = {
            "team_name": "Team-Alpha",
            "new_approval": {
                "stage": "Project Proposal",
                "status": "Approved"
            }
        }
        res = self.client.post(
            "/api/faculty/update_approvals",
            json=payload,
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "Approved")
        self.assertEqual(data["stage"], "Project Proposal")

        # Verify DB update
        mock_db.teams.update_one.assert_called_once()
        args = mock_db.teams.update_one.call_args[0]
        self.assertEqual(args[1]["$set"]["approvals.$.status"], "Approved")

        # Verify email notification was sent (preserving existing workflow)
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args[1].get("trigger_name"), "FACULTY_STAGE_APPROVAL")

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_faculty_can_reject_project_stage(self, mock_send, mock_db):
        mock_db.teams.find_one.side_effect = [
            self.mock_team,
            {"approvals": [{"stage": "Synopsis & Literature Review", "status": "Rejected"}]}
        ]
        mock_db.teams.update_one.return_value = MagicMock(matched_count=0)

        payload = {
            "team_name": "Team-Alpha",
            "new_approval": {
                "stage": "Synopsis & Literature Review",
                "status": "Rejected"
            }
        }
        res = self.client.post(
            "/api/faculty/update_approvals",
            json=payload,
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "Rejected")

        # Verify it pushed new approval stage since matched_count was 0
        push_call = mock_db.teams.update_one.call_args_list[-1][0]
        self.assertIn("$push", push_call[1])
        self.assertEqual(push_call[1]["$push"]["approvals"]["status"], "Rejected")

    @patch("app.db")
    @patch("app.send_email_notification")
    def test_unauthorized_faculty_cannot_update_approvals(self, mock_send, mock_db):
        mock_db.teams.find_one.return_value = self.mock_team

        payload = {
            "team_name": "Team-Alpha",
            "new_approval": {
                "stage": "Project Proposal",
                "status": "Approved"
            }
        }
        res = self.client.post(
            "/api/faculty/update_approvals",
            json=payload,
            headers={"Authorization": f"Bearer {self.unauth_token}"}
        )
        self.assertEqual(res.status_code, 403)
        mock_db.teams.update_one.assert_not_called()
        mock_send.assert_not_called()

    @patch("app.db")
    def test_faculty_dashboard_includes_approvals_in_projection(self, mock_db):
        mock_db.faculty.find_one.return_value = {"email": self.authorized_faculty_email, "name": "Dr. Guide"}
        mock_db.teams.find.return_value = [self.mock_team]

        res = self.client.get(
            "/api/dashboard/faculty",
            headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        teams = data.get("allocated_teams", [])
        self.assertEqual(len(teams), 1)
        self.assertIn("approvals", teams[0])
        self.assertIn("tasks", teams[0])
        self.assertEqual(teams[0]["approvals"][0]["stage"], "Project Proposal")

if __name__ == "__main__":
    unittest.main()
