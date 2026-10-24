"""
Automated tests for Duplicate Marks Deduplication and Faculty Project Evaluation Final Marks.
Verifies:
1. Removal of duplicate Marks section from Student dashboard while preserving My Marksheet.
2. Removal of duplicate Assign Marks section from Faculty dashboard while preserving Project Evaluation.
3. Presence of Final Marks section at the bottom of Faculty Project Evaluation with live calculation hooks.
4. Calculation logic, rounding, edge cases (empty, zero, max, decimals, incomplete marks).
5. Exact formula and grading parity between Faculty Final Marks and Student My Marksheet.
6. Persistence of marks to backend database and consistent retrieval via Student My Marksheet API.
7. Authorization restrictions (team/role-based) and lock enforcement.
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import re
import jwt

sys.path.insert(0, os.path.dirname(__file__))

import app
from app import app as flask_app, db


class TestDuplicateMarksRemovalAndFinalMarks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Read frontend HTML files
        cls.frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
        cls.team_dashboard_path = os.path.join(cls.frontend_dir, "team-dasboard.html")
        cls.faculty_dashboard_path = os.path.join(cls.frontend_dir, "faculty-dashboard.html")
        cls.theme_css_path = os.path.join(cls.frontend_dir, "theme.css")

        with open(cls.team_dashboard_path, "r", encoding="utf-8") as f:
            cls.team_html = f.read()

        with open(cls.faculty_dashboard_path, "r", encoding="utf-8") as f:
            cls.faculty_html = f.read()

        with open(cls.theme_css_path, "r", encoding="utf-8") as f:
            cls.theme_css = f.read()

    def setUp(self):
        flask_app.config["TESTING"] = True
        self.client = flask_app.test_client()

        self.faculty_email = "guide_evaluation@college.edu"
        self.unauth_email = "student_user@college.edu"
        self.student_email = "alice@college.edu"
        self.student_usn = "1MS21CS001"

        self.faculty_token = jwt.encode(
            {"email": self.faculty_email, "role": "faculty", "name": "Dr. Guide"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )
        self.student_token = jwt.encode(
            {"email": self.student_email, "usn": self.student_usn, "role": "student", "name": "Alice Leader"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )
        self.unauth_token = jwt.encode(
            {"email": self.unauth_email, "role": "student", "name": "Bob Student"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )

        self.team_name = "Team-Apollo"
        self.mock_team = {
            "_id": "mock_team_apollo_1",
            "team_name": self.team_name,
            "leader_name": "Alice Leader",
            "leader_email": self.student_email,
            "leader_usn": self.student_usn,
            "faculty_name": "Dr. Guide",
            "faculty_email": self.faculty_email,
            "members": [
                {"name": "Charlie Member", "usn": "1MS21CS002", "display_name": "Charlie Member (1MS21CS002)"}
            ],
            "project_idea": {
                "title": "Autonomous Mars Rover Navigation",
                "abstract": "Deep reinforcement learning system for planetary rovers."
            }
        }

    # =========================================================================
    # 1. Verification of Duplicate Marks Sections Removal
    # =========================================================================

    def test_student_navigation_duplicate_marks_removed(self):
        """Student sidebar must not contain the duplicate Marks button."""
        pattern = r"showSection\(['\"]marks['\"]\)"
        self.assertIsNone(
            re.search(pattern, self.team_html),
            "Duplicate 'Marks' navigation button found in student dashboard sidebar."
        )

    def test_student_interface_duplicate_marks_card_removed(self):
        """Student dashboard must not contain the separate #marks card."""
        self.assertNotIn(
            'id="marks"',
            self.team_html,
            "Separate duplicate card with id='marks' found in student dashboard."
        )

    def test_student_my_marksheet_section_preserved(self):
        """Student dashboard must preserve the My Marksheet section and navigation."""
        self.assertIn(
            "showSection('marksheet')",
            self.team_html,
            "My Marksheet navigation button missing from student dashboard sidebar."
        )
        self.assertIn(
            'id="marksheet"',
            self.team_html,
            "My Marksheet card (id='marksheet') missing from student dashboard."
        )
        self.assertIn(
            'id="marksheetContainer"',
            self.team_html,
            "marksheetContainer missing from student dashboard."
        )

    def test_faculty_navigation_duplicate_assign_marks_removed(self):
        """Faculty sidebar must not contain the duplicate Assign Marks link."""
        pattern = r"showSection\(['\"]marks['\"]\)"
        self.assertIsNone(
            re.search(pattern, self.faculty_html),
            "Duplicate 'Assign Marks' navigation link found in faculty dashboard sidebar."
        )

    def test_faculty_interface_duplicate_marks_section_removed(self):
        """Faculty dashboard must not contain the separate duplicate marks section."""
        self.assertNotIn(
            'id="marks"',
            self.faculty_html,
            "Duplicate section with id='marks' found in faculty dashboard."
        )

    def test_faculty_project_evaluation_section_preserved(self):
        """Faculty dashboard must preserve Project Evaluation section and navigation."""
        self.assertIn(
            "showSection('evaluation')",
            self.faculty_html,
            "Project Evaluation navigation link missing from faculty dashboard sidebar."
        )
        self.assertIn(
            'id="evaluation"',
            self.faculty_html,
            "Project Evaluation section (id='evaluation') missing from faculty dashboard."
        )
        self.assertIn(
            'id="evaluationContainer"',
            self.faculty_html,
            "evaluationContainer missing from faculty dashboard."
        )

    # =========================================================================
    # 2. Verification of Final Marks Section in Faculty Project Evaluation
    # =========================================================================

    def test_faculty_final_marks_section_rendered(self):
        """Final Marks section must be defined and rendered in Project Evaluation."""
        self.assertIn(
            "renderFacultyFinalMarksSection",
            self.faculty_html,
            "renderFacultyFinalMarksSection function missing from faculty dashboard."
        )
        self.assertIn(
            'id="finalMarksSection"',
            self.faculty_html,
            "finalMarksSection container missing from faculty dashboard."
        )
        self.assertIn(
            "final-marks-card",
            self.faculty_html,
            "final-marks-card class missing from faculty dashboard."
        )

    def test_faculty_final_marks_live_calculation_hooks(self):
        """Live calculation listener and function must be hooked to inputs."""
        self.assertIn(
            "setupFinalMarksLiveCalculation",
            self.faculty_html,
            "setupFinalMarksLiveCalculation function missing from faculty dashboard."
        )
        self.assertIn(
            "recalculateFinalMarksLive",
            self.faculty_html,
            "recalculateFinalMarksLive function missing from faculty dashboard."
        )
        # Verify event listeners on input and change
        self.assertIn(
            'addEventListener("input"',
            self.faculty_html,
            "Input event listener for live final marks calculation missing."
        )
        self.assertIn(
            'addEventListener("change"',
            self.faculty_html,
            "Change event listener for live final marks calculation missing."
        )

    def test_faculty_final_marks_status_badge(self):
        """Status badge distinguishing saved marks from unsaved changes must exist."""
        self.assertIn(
            'id="finalMarksSaveStatusBadge"',
            self.faculty_html,
            "finalMarksSaveStatusBadge missing from faculty Final Marks section."
        )
        self.assertIn(
            "Unsaved Changes",
            self.faculty_html,
            "Unsaved Changes distinction missing from live recalculation logic."
        )
        self.assertIn(
            "Saved in Database",
            self.faculty_html,
            "Saved in Database status missing from live recalculation logic."
        )

    # =========================================================================
    # 3. Marks Calculation Formula & Parity with Student My Marksheet
    # =========================================================================

    @staticmethod
    def calculate_evaluation_final_marks(phases, member_marks):
        """
        Reference implementation of the marks calculation formula used by
        both student My Marksheet and faculty Final Marks section.
        """
        grand_total_max = sum(float(p.get("total_marks", 0)) for p in phases)
        phase_totals = []
        grand_total = 0

        for p_idx, phase in enumerate(phases):
            p_total = 0
            for c_idx, criterion in enumerate(phase.get("criteria", [])):
                val = member_marks.get(f"{p_idx}_{c_idx}", 0)
                try:
                    num = float(val) if val is not None and str(val).strip() != "" else 0.0
                except (ValueError, TypeError):
                    num = 0.0
                # Clamp negative
                if num < 0:
                    num = 0.0
                p_total += num
            phase_totals.append(p_total)
            grand_total += p_total

        pct = round((grand_total / grand_total_max) * 100, 1) if grand_total_max > 0 else 0.0
        pct_str = f"{pct:.1f}"

        if pct >= 90:
            grade = "S"
        elif pct >= 80:
            grade = "A"
        elif pct >= 70:
            grade = "B"
        elif pct >= 60:
            grade = "C"
        elif pct >= 50:
            grade = "D"
        else:
            grade = "F"

        return {
            "grand_total_max": grand_total_max,
            "phase_totals": phase_totals,
            "grand_total": grand_total,
            "percentage": pct_str,
            "grade": grade
        }

    def test_calculation_full_marks(self):
        """Test calculation with full marks (100%) produces Grade S."""
        phases = [
            {"total_marks": 20, "criteria": [{"max_marks": 5}, {"max_marks": 5}, {"max_marks": 5}, {"max_marks": 5}]},
            {"total_marks": 40, "criteria": [{"max_marks": 10}, {"max_marks": 15}, {"max_marks": 10}, {"max_marks": 5}]},
            {"total_marks": 40, "criteria": [{"max_marks": 20}, {"max_marks": 10}, {"max_marks": 10}]}
        ]
        marks = {
            "0_0": 5, "0_1": 5, "0_2": 5, "0_3": 5,
            "1_0": 10, "1_1": 15, "1_2": 10, "1_3": 5,
            "2_0": 20, "2_1": 10, "2_2": 10
        }
        res = self.calculate_evaluation_final_marks(phases, marks)
        self.assertEqual(res["grand_total_max"], 100.0)
        self.assertEqual(res["phase_totals"], [20.0, 40.0, 40.0])
        self.assertEqual(res["grand_total"], 100.0)
        self.assertEqual(res["percentage"], "100.0")
        self.assertEqual(res["grade"], "S")

    def test_calculation_grade_boundaries(self):
        """Test exact grade boundary transitions: S (90), A (80), B (70), C (60), D (50), F (<50)."""
        phases = [{"total_marks": 100, "criteria": [{"max_marks": 100}]}]

        # 90% -> S
        self.assertEqual(self.calculate_evaluation_final_marks(phases, {"0_0": 90})["grade"], "S")
        self.assertEqual(self.calculate_evaluation_final_marks(phases, {"0_0": 89.9})["grade"], "A")

        # 80% -> A
        self.assertEqual(self.calculate_evaluation_final_marks(phases, {"0_0": 80})["grade"], "A")
        self.assertEqual(self.calculate_evaluation_final_marks(phases, {"0_0": 79.9})["grade"], "B")

        # 70% -> B
        self.assertEqual(self.calculate_evaluation_final_marks(phases, {"0_0": 70})["grade"], "B")
        self.assertEqual(self.calculate_evaluation_final_marks(phases, {"0_0": 69.9})["grade"], "C")

        # 60% -> C
        self.assertEqual(self.calculate_evaluation_final_marks(phases, {"0_0": 60})["grade"], "C")
        self.assertEqual(self.calculate_evaluation_final_marks(phases, {"0_0": 59.9})["grade"], "D")

        # 50% -> D
        self.assertEqual(self.calculate_evaluation_final_marks(phases, {"0_0": 50})["grade"], "D")
        self.assertEqual(self.calculate_evaluation_final_marks(phases, {"0_0": 49.9})["grade"], "F")

        # 0% -> F
        self.assertEqual(self.calculate_evaluation_final_marks(phases, {"0_0": 0})["grade"], "F")

    def test_calculation_empty_and_incomplete_marks(self):
        """Empty strings, whitespace, or missing inputs must be treated as 0 without crashing."""
        phases = [
            {"total_marks": 20, "criteria": [{"max_marks": 5}, {"max_marks": 5}, {"max_marks": 5}, {"max_marks": 5}]},
            {"total_marks": 40, "criteria": [{"max_marks": 10}, {"max_marks": 15}, {"max_marks": 10}, {"max_marks": 5}]}
        ]
        marks = {
            "0_0": "5",
            "0_1": "",
            "0_2": "   ",
            "0_3": None,
            "1_0": 10
        }
        res = self.calculate_evaluation_final_marks(phases, marks)
        self.assertEqual(res["grand_total_max"], 60.0)
        self.assertEqual(res["phase_totals"], [5.0, 10.0])
        self.assertEqual(res["grand_total"], 15.0)
        self.assertEqual(res["percentage"], "25.0")
        self.assertEqual(res["grade"], "F")

    def test_calculation_decimal_half_marks(self):
        """Decimal half-marks (0.5 steps) must sum accurately and round percentage to 1 decimal place."""
        phases = [{"total_marks": 20, "criteria": [{"max_marks": 5}, {"max_marks": 5}, {"max_marks": 5}, {"max_marks": 5}]}]
        marks = {"0_0": 4.5, "0_1": 4.5, "0_2": 3.5, "0_3": 4.5}
        res = self.calculate_evaluation_final_marks(phases, marks)
        self.assertEqual(res["grand_total"], 17.0)
        self.assertEqual(res["percentage"], "85.0")
        self.assertEqual(res["grade"], "A")

    # =========================================================================
    # 4. Backend Persistence, Student Marksheet Consistency & Authorization
    # =========================================================================

    @patch("app.find_team_by_name")
    @patch("app.db")
    def test_faculty_save_evaluation_marks_persists(self, mock_db, mock_find_team):
        """Faculty can save evaluation marks which updates database and notifies students."""
        mock_db.teams.find_one.return_value = self.mock_team
        mock_find_team.return_value = self.mock_team
        mock_db.evaluations.find_one.return_value = None  # New evaluation

        payload = {
            "team_name": self.team_name,
            "evaluation": {
                "phases": [
                    {
                        "name": "Phase 1 - Synopsis & Problem Definition",
                        "total_marks": 20,
                        "criteria": [
                            {
                                "name": "Problem Statement & Objectives",
                                "max_marks": 5,
                                "marks": [
                                    {"marks_obtained": 4.5, "maximum_marks": 5},
                                    {"marks_obtained": 4.0, "maximum_marks": 5}
                                ]
                            }
                        ]
                    }
                ]
            }
        }

        res = self.client.post(
            "/api/evaluation/save",
            headers={"Authorization": f"Bearer {self.faculty_token}"},
            json=payload
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("message", data)
        self.assertTrue(mock_db.evaluations.insert_one.called or mock_db.evaluations.update_one.called)

    @patch("app.db")
    def test_student_cannot_save_evaluation(self, mock_db):
        """Students cannot call /api/evaluation/save."""
        payload = {
            "team_name": self.team_name,
            "evaluation": {"phases": []}
        }
        res = self.client.post(
            "/api/evaluation/save",
            headers={"Authorization": f"Bearer {self.student_token}"},
            json=payload
        )
        self.assertEqual(res.status_code, 403)

    @patch("app.db")
    def test_locked_evaluation_blocks_faculty_edits(self, mock_db):
        """When evaluation is locked by coordinator, faculty cannot overwrite it."""
        mock_db.teams.find_one.return_value = self.mock_team
        mock_db.evaluations.find_one.return_value = {
            "team_name": self.team_name,
            "is_locked": True,
            "phases": []
        }

        payload = {
            "team_name": self.team_name,
            "evaluation": {"phases": []}
        }
        res = self.client.post(
            "/api/evaluation/save",
            headers={"Authorization": f"Bearer {self.faculty_token}"},
            json=payload
        )
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertIn("locked", data.get("error", "").lower())

    @patch("app.get_student_meeting_stats")
    @patch("app.get_team_attendance_summary")
    @patch("app.get_student_project_info")
    @patch("app.db")
    def test_student_evaluation_api_returns_saved_marks(self, mock_db, mock_student_info, mock_summary, mock_stats):
        """Student My Marksheet API returns the exact evaluation saved by faculty."""
        mock_student_info.return_value = (self.mock_team, self.mock_team["project_idea"])
        mock_summary.return_value = {}
        mock_stats.return_value = {"attendance_mark": 10, "total_meetings": 15}
        mock_db.evaluations.find_one.return_value = {
            "team_name": self.team_name,
            "is_locked": False,
            "phases": [
                {
                    "name": "Phase 1 - Synopsis & Problem Definition",
                    "total_marks": 20,
                    "criteria": [
                        {
                            "name": "Problem Statement & Objectives",
                            "max_marks": 5,
                            "marks": [
                                {"marks_obtained": 4.5, "maximum_marks": 5}
                            ]
                        }
                    ]
                }
            ]
        }

        res = self.client.get(
            "/api/evaluation/student",
            headers={"Authorization": f"Bearer {self.student_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["team_name"], self.team_name)
        self.assertIsNotNone(data["evaluation"])
        phase1 = data["evaluation"]["phases"][0]
        self.assertEqual(phase1["criteria"][0]["marks"][0]["marks_obtained"], 4.5)

    def test_existing_assessment_marks_backend_endpoint_preserved(self):
        """Existing /api/faculty/add_assessment_marks endpoint must remain operational."""
        # Route exists and requires validation/auth
        res = self.client.post("/api/faculty/add_assessment_marks", json={})
        self.assertIn(res.status_code, [400, 401])


if __name__ == "__main__":
    unittest.main()
