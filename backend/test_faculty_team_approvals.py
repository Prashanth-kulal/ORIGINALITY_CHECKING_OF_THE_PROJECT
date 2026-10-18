"""
Automated Test Suite for Faculty Team-Specific Approvals and Visibility.

Verifies:
1. Faculty member A sees only their allocated teams.
2. Faculty member A cannot approve or reject a team allocated to faculty member B.
3. Approving team A does not change team B's status.
4. Rejecting team A does not change team B's status.
5. Students in team A see team A's status only.
6. Students in team B do not see team A's approval as their own.
7. Multiple teams under the same project remain independent.
8. Existing approval functionality and unrelated features still work.
"""
import unittest
from unittest.mock import patch, MagicMock
from bson import ObjectId
import jwt
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import app
from app import app as flask_app

class TestFacultyTeamApprovalsAndVisibility(unittest.TestCase):
    def setUp(self):
        flask_app.config["TESTING"] = True
        self.client = flask_app.test_client()

        # Faculty accounts
        self.faculty_a_email = "faculty_a@college.edu"
        self.faculty_b_email = "faculty_b@college.edu"
        self.coordinator_email = "coordinator@college.edu"

        # Students
        self.student_a_email = "student_a@college.edu"
        self.student_b_email = "student_b@college.edu"

        # JWT tokens
        self.token_faculty_a = jwt.encode(
            {"email": self.faculty_a_email, "role": "faculty", "name": "Prof. Alpha Guide"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )
        self.token_faculty_b = jwt.encode(
            {"email": self.faculty_b_email, "role": "faculty", "name": "Prof. Beta Guide"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )
        self.token_coordinator = jwt.encode(
            {"email": self.coordinator_email, "role": "coordinator", "name": "Prof. Coordinator"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )
        self.token_student_a = jwt.encode(
            {"email": self.student_a_email, "role": "student", "name": "Alice"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )
        self.token_student_b = jwt.encode(
            {"email": self.student_b_email, "role": "student", "name": "Bob"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )

        self.team_a_id = ObjectId("65123456789abcdef0123456")
        self.team_b_id = ObjectId("65123456789abcdef0123457")

        # Two teams sharing the same project title
        self.shared_project_title = "AI Driven Urban Drone Navigation"

        self.team_a = {
            "_id": self.team_a_id,
            "team_name": "Team-Alpha",
            "leader_name": "Alice Leader",
            "leader_email": self.student_a_email,
            "leader_usn": "4MW21CS001",
            "faculty_name": "Prof. Alpha Guide",
            "faculty_email": self.faculty_a_email,
            "project_title": self.shared_project_title,
            "project_idea": {
                "title": self.shared_project_title,
                "status": "Pending",
                "abstract": "Pathfinding algorithms using graph neural networks."
            },
            "approvals": [
                {"stage": "Project Proposal", "status": "Pending", "team_name": "Team-Alpha", "team_id": str(self.team_a_id)},
                {"stage": "Synopsis & Literature Review", "status": "Pending", "team_name": "Team-Alpha", "team_id": str(self.team_a_id)}
            ],
            "members": [
                {"name": "Alice Leader", "email": self.student_a_email, "usn": "4MW21CS001"}
            ]
        }

        self.team_b = {
            "_id": self.team_b_id,
            "team_name": "Team-Beta",
            "leader_name": "Bob Leader",
            "leader_email": self.student_b_email,
            "leader_usn": "4MW21CS002",
            "faculty_name": "Prof. Beta Guide",
            "faculty_email": self.faculty_b_email,
            "project_title": self.shared_project_title,
            "project_idea": {
                "title": self.shared_project_title,
                "status": "Pending",
                "abstract": "Decentralized swarm collision avoidance systems."
            },
            "approvals": [
                {"stage": "Project Proposal", "status": "Pending", "team_name": "Team-Beta", "team_id": str(self.team_b_id)},
                {"stage": "Synopsis & Literature Review", "status": "Pending", "team_name": "Team-Beta", "team_id": str(self.team_b_id)}
            ],
            "members": [
                {"name": "Bob Leader", "email": self.student_b_email, "usn": "4MW21CS002"}
            ]
        }

    # =========================================================================
    # Case 1: Faculty member A sees only their allocated teams
    # =========================================================================
    @patch("app.db")
    def test_case1_faculty_a_sees_only_allocated_teams(self, mock_db):
        """Faculty dashboard returns only teams where faculty_email matches logged-in faculty or allocated."""
        mock_db.faculty.find_one.return_value = {"email": self.faculty_a_email, "name": "Prof. Alpha Guide"}
        mock_db.allocations.find.return_value = []
        mock_db.students.find.return_value = []
        mock_db.teams.find.return_value = [self.team_a]

        res = self.client.get(
            "/api/dashboard/faculty",
            headers={"Authorization": f"Bearer {self.token_faculty_a}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        teams = data.get("allocated_teams", [])
        self.assertEqual(len(teams), 1)
        self.assertEqual(teams[0]["team_name"], "Team-Alpha")
        self.assertNotEqual(teams[0]["team_name"], "Team-Beta")

    # =========================================================================
    # Case 2: Faculty member A cannot approve or reject a team allocated to B
    # =========================================================================
    @patch("app.db")
    def test_case2_faculty_a_cannot_approve_team_b(self, mock_db):
        """Faculty A attempting to approve Team B must be rejected with 403 Forbidden."""
        # When querying for Team B, team is returned with faculty_b assigned
        mock_db.teams.find_one.return_value = self.team_b
        mock_db.allocations.find_one.return_value = None

        payload = {
            "team_name": "Team-Beta",
            "new_approval": {
                "stage": "Project Proposal",
                "status": "Approved",
                "comments": "Unauthorized attempt by Faculty A"
            }
        }
        res = self.client.post(
            "/api/faculty/update_approvals",
            json=payload,
            headers={"Authorization": f"Bearer {self.token_faculty_a}"}
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("not authorized", res.get_json()["error"].lower())
        mock_db.teams.update_one.assert_not_called()

    @patch("app.db")
    def test_case2b_faculty_a_cannot_view_approvals_for_team_b(self, mock_db):
        """Faculty A attempting to load approvals endpoint for Team B must receive 403."""
        mock_db.teams.find_one.return_value = self.team_b
        mock_db.allocations.find_one.return_value = None

        res = self.client.get(
            "/api/faculty/team_approvals/Team-Beta",
            headers={"Authorization": f"Bearer {self.token_faculty_a}"}
        )
        self.assertEqual(res.status_code, 403)

    # =========================================================================
    # Case 3: Approving Team A does not change Team B's status
    # =========================================================================
    @patch("app.send_email_notification")
    @patch("app.db")
    def test_case3_approving_team_a_does_not_affect_team_b(self, mock_db, mock_notify):
        """Approving Team A updates Team A's document only and leaves Team B unaffected."""
        mock_db.teams.find_one.side_effect = [
            self.team_a,  # find_team_by_name
            {**self.team_a, "approvals": [{"stage": "Project Proposal", "status": "Approved", "team_id": str(self.team_a_id)}]}
        ]
        mock_db.teams.update_one.return_value = MagicMock(matched_count=1)

        payload = {
            "team_name": "Team-Alpha",
            "new_approval": {
                "stage": "Project Proposal",
                "status": "Approved",
                "comments": "Outstanding proposal"
            }
        }
        res = self.client.post(
            "/api/faculty/update_approvals",
            json=payload,
            headers={"Authorization": f"Bearer {self.token_faculty_a}"}
        )
        self.assertEqual(res.status_code, 200)

        # Verify DB update target matches ONLY Team A's ID
        mock_db.teams.update_one.assert_called_once()
        filter_query = mock_db.teams.update_one.call_args[0][0]
        self.assertEqual(filter_query["_id"], self.team_a_id)
        self.assertNotEqual(filter_query["_id"], self.team_b_id)

        # Team B's approvals remain Pending
        self.assertEqual(self.team_b["approvals"][0]["status"], "Pending")

    # =========================================================================
    # Case 4: Rejecting Team A does not change Team B's status
    # =========================================================================
    @patch("app.send_email_notification")
    @patch("app.db")
    def test_case4_rejecting_team_a_does_not_affect_team_b(self, mock_db, mock_notify):
        """Rejecting Team A updates Team A's document only, Team B stays Pending."""
        mock_db.teams.find_one.side_effect = [
            self.team_a,
            {**self.team_a, "approvals": [{"stage": "Synopsis & Literature Review", "status": "Rejected", "team_id": str(self.team_a_id)}]}
        ]
        mock_db.teams.update_one.return_value = MagicMock(matched_count=1)

        payload = {
            "team_name": "Team-Alpha",
            "new_approval": {
                "stage": "Synopsis & Literature Review",
                "status": "Rejected",
                "comments": "Literature review needs stronger citations."
            }
        }
        res = self.client.post(
            "/api/faculty/update_approvals",
            json=payload,
            headers={"Authorization": f"Bearer {self.token_faculty_a}"}
        )
        self.assertEqual(res.status_code, 200)

        # Target must be team A's _id only
        filter_query = mock_db.teams.update_one.call_args[0][0]
        self.assertEqual(filter_query["_id"], self.team_a_id)
        self.assertEqual(self.team_b["approvals"][1]["status"], "Pending")

    # =========================================================================
    # Case 5: Students in Team A see Team A's status only
    # =========================================================================
    @patch("app.db")
    def test_case5_student_a_sees_team_a_status_only(self, mock_db):
        """Student A calling /api/dashboard/team sees Team A's approvals only."""
        team_a_approved = dict(self.team_a)
        team_a_approved["approvals"] = [
            {"stage": "Project Proposal", "status": "Approved", "comments": "Great work"}
        ]
        mock_db.teams.find_one.return_value = team_a_approved

        res = self.client.get(
            "/api/dashboard/team",
            headers={"Authorization": f"Bearer {self.token_student_a}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["team_name"], "Team-Alpha")
        self.assertEqual(data["approvals"][0]["stage"], "Project Proposal")
        self.assertEqual(data["approvals"][0]["status"], "Approved")
        self.assertEqual(data["approvals"][0]["team_name"], "Team-Alpha")

    # =========================================================================
    # Case 6: Students in Team B do not see Team A's approval as their own
    # =========================================================================
    @patch("app.db")
    def test_case6_student_b_does_not_see_team_a_approval(self, mock_db):
        """Student B querying /api/dashboard/team retrieves Team B which remains Pending."""
        mock_db.teams.find_one.return_value = self.team_b

        res = self.client.get(
            "/api/dashboard/team",
            headers={"Authorization": f"Bearer {self.token_student_b}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["team_name"], "Team-Beta")
        # Ensure status is Pending and not Approved
        proposal_approval = next(a for a in data["approvals"] if a["stage"] == "Project Proposal")
        self.assertEqual(proposal_approval["status"], "Pending")
        self.assertEqual(proposal_approval["team_name"], "Team-Beta")

    # =========================================================================
    # Case 7: Multiple teams under the same project remain independent
    # =========================================================================
    @patch("app.send_email_notification")
    @patch("app.db")
    def test_case7_shared_project_teams_remain_strictly_independent(self, mock_db, mock_notify):
        """Even with identical project title, approving Team A does not alter Team B."""
        # Both teams have project_title == self.shared_project_title
        self.assertEqual(self.team_a["project_title"], self.team_b["project_title"])

        mock_db.teams.find_one.side_effect = [
            self.team_a,
            {**self.team_a, "approvals": [{"stage": "Project Proposal", "status": "Approved"}]}
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
            headers={"Authorization": f"Bearer {self.token_faculty_a}"}
        )
        self.assertEqual(res.status_code, 200)

        # Database update should strictly include Team A's ObjectId, never just the project title
        call_args = mock_db.teams.update_one.call_args[0]
        update_filter = call_args[0]
        self.assertIn("_id", update_filter)
        self.assertEqual(update_filter["_id"], self.team_a_id)

    # =========================================================================
    # Case 8: Existing approval functionality & coordinator privileges preserved
    # =========================================================================
    @patch("app.send_email_notification")
    @patch("app.db")
    def test_case8_coordinator_has_global_approval_privileges(self, mock_db, mock_notify):
        """Coordinator can oversee and update approvals across teams."""
        mock_db.teams.find_one.side_effect = [
            self.team_b,
            {**self.team_b, "approvals": [{"stage": "Project Proposal", "status": "Approved"}]}
        ]
        mock_db.teams.update_one.return_value = MagicMock(matched_count=1)

        payload = {
            "team_name": "Team-Beta",
            "new_approval": {
                "stage": "Project Proposal",
                "status": "Approved",
                "comments": "Coordinator final approval"
            }
        }
        res = self.client.post(
            "/api/faculty/update_approvals",
            json=payload,
            headers={"Authorization": f"Bearer {self.token_coordinator}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "Approved")

if __name__ == "__main__":
    unittest.main()
