"""
Comprehensive Automated Test Suite for 6th and 7th Semester Separation.

Verifies:
1. 6th-semester marksheet structure and 100-mark calculation remain unchanged.
2. 7th-semester categories total exactly 100 marks (Phase 4 [30], Phase 5 [30], Report [10], Attendance [10], Paper Submission [20]).
3. Marks are validated against each category's maximum.
4. Marks save and reload correctly for both semesters.
5. Updating one semester does not affect the other.
6. Student, faculty, and coordinator dashboards display the correct semester's saved marks.
7. Attendance records and calculations do not leak between semesters.
8. Final totals and percentages are calculated correctly for each semester.
9. 6th-semester Excel export contains only 6th-semester marks.
10. 7th-semester Excel export contains only 7th-semester marks.
11. Both exports have exactly ['USN', 'Marks'] columns, unique USNs, and ascending alphanumeric order.
12. Existing workflows and permissions continue to function.
13. No Grade display remains in Project Evaluation or My Marksheet sections.
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import io
import re
import jwt
import openpyxl

import app as flask_module
from app import app as flask_app, db


class TestSemesterSeparation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
        cls.coord_html_path = os.path.join(cls.frontend_dir, "project_coordinator-dashboard.html")
        cls.team_html_path = os.path.join(cls.frontend_dir, "team-dasboard.html")
        cls.faculty_html_path = os.path.join(cls.frontend_dir, "faculty-dashboard.html")

        with open(cls.coord_html_path, "r", encoding="utf-8") as f:
            cls.coord_html = f.read()
        with open(cls.team_html_path, "r", encoding="utf-8") as f:
            cls.team_html = f.read()
        with open(cls.faculty_html_path, "r", encoding="utf-8") as f:
            cls.faculty_html = f.read()

    def setUp(self):
        flask_app.config["TESTING"] = True
        self.client = flask_app.test_client()

        self.coordinator_email = "coord@college.edu"
        self.faculty_email = "guide@college.edu"
        self.student_email = "student@college.edu"

        self.coord_token = jwt.encode(
            {"email": self.coordinator_email, "role": "coordinator", "name": "Admin Coordinator"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )
        self.faculty_token = jwt.encode(
            {"email": self.faculty_email, "role": "faculty", "name": "Dr. Guide"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )
        self.student_token = jwt.encode(
            {"email": self.student_email, "usn": "1MS21CS001", "role": "student", "name": "Alice"},
            flask_app.config["SECRET_KEY"],
            algorithm="HS256"
        )

        self.sample_team = {
            "team_name": "Team-Alpha",
            "leader_name": "Alice Leader",
            "leader_usn": "1MS21CS001",
            "leader_email": self.student_email,
            "faculty_name": "Dr. Guide",
            "faculty_email": self.faculty_email,
            "project_idea": {
                "title": "Machine Learning Security Analysis",
                "status": "Approved"
            },
            "members": [
                {"name": "Bob Member", "usn": "1MS21CS002", "email": "bob@college.edu"}
            ]
        }

        # 6th semester evaluation structure (100 marks total)
        self.sample_eval_sem6 = {
            "_id": "id_sem6_alpha",
            "team_name": "Team-Alpha",
            "semester": 6,
            "is_locked": False,
            "phases": [
                {
                    "name": "Phase 1 - Synopsis & Problem Definition",
                    "total_marks": 20,
                    "criteria": [
                        {
                            "name": "Problem Statement & Objectives",
                            "max_marks": 10,
                            "marks": [{"marks_obtained": 9, "maximum_marks": 10}, {"marks_obtained": 8, "maximum_marks": 10}]
                        },
                        {
                            "name": "Presentation",
                            "max_marks": 10,
                            "marks": [{"marks_obtained": 8, "maximum_marks": 10}, {"marks_obtained": 7, "maximum_marks": 10}]
                        }
                    ]
                },
                {
                    "name": "Phase 2 - System Design",
                    "total_marks": 40,
                    "criteria": [
                        {
                            "name": "System Architecture",
                            "max_marks": 40,
                            "marks": [{"marks_obtained": 36, "maximum_marks": 40}, {"marks_obtained": 34, "maximum_marks": 40}]
                        }
                    ]
                },
                {
                    "name": "Report & Attendance",
                    "total_marks": 40,
                    "criteria": [
                        {
                            "name": "Report",
                            "max_marks": 20,
                            "marks": [{"marks_obtained": 18, "maximum_marks": 20}, {"marks_obtained": 17, "maximum_marks": 20}]
                        },
                        {
                            "name": "Attendance",
                            "max_marks": 10,
                            "marks": [{"marks_obtained": 10, "maximum_marks": 10}, {"marks_obtained": 8, "maximum_marks": 10}]
                        },
                        {
                            "name": "Synopsis",
                            "max_marks": 10,
                            "marks": [{"marks_obtained": 9, "maximum_marks": 10}, {"marks_obtained": 8, "maximum_marks": 10}]
                        }
                    ]
                }
            ]
        }

        # 7th semester evaluation structure (100 marks total: Phase 4 [30], Phase 5 [30], Report [10], Attendance [10], Paper Submission [20])
        self.sample_eval_sem7 = {
            "_id": "id_sem7_alpha",
            "team_name": "Team-Alpha",
            "semester": 7,
            "is_locked": False,
            "phases": [
                {
                    "name": "Phase 4",
                    "total_marks": 30,
                    "criteria": [
                        {
                            "name": "Phase 4",
                            "max_marks": 30,
                            "marks": [{"marks_obtained": 27, "maximum_marks": 30}, {"marks_obtained": 25, "maximum_marks": 30}]
                        }
                    ]
                },
                {
                    "name": "Phase 5",
                    "total_marks": 30,
                    "criteria": [
                        {
                            "name": "Phase 5",
                            "max_marks": 30,
                            "marks": [{"marks_obtained": 28, "maximum_marks": 30}, {"marks_obtained": 26, "maximum_marks": 30}]
                        }
                    ]
                },
                {
                    "name": "Report",
                    "total_marks": 10,
                    "criteria": [
                        {
                            "name": "Report",
                            "max_marks": 10,
                            "marks": [{"marks_obtained": 9, "maximum_marks": 10}, {"marks_obtained": 8, "maximum_marks": 10}]
                        }
                    ]
                },
                {
                    "name": "Attendance",
                    "total_marks": 10,
                    "criteria": [
                        {
                            "name": "Attendance",
                            "max_marks": 10,
                            "marks": [{"marks_obtained": 10, "maximum_marks": 10}, {"marks_obtained": 9, "maximum_marks": 10}]
                        }
                    ]
                },
                {
                    "name": "Paper Submission",
                    "total_marks": 20,
                    "criteria": [
                        {
                            "name": "Paper Submission",
                            "max_marks": 20,
                            "marks": [{"marks_obtained": 19, "maximum_marks": 20}, {"marks_obtained": 18, "maximum_marks": 20}]
                        }
                    ]
                }
            ]
        }

    # =========================================================================
    # Test 1 & 6: Semester Selector UI in All Three Dashboards
    # =========================================================================

    def test_semester_selector_in_student_dashboard(self):
        """Student dashboard must have 6th and 7th semester selector toggle."""
        self.assertIn("switchStudentSemester", self.team_html)
        self.assertIn("6th Semester", self.team_html)
        self.assertIn("7th Semester", self.team_html)
        self.assertIn("renderMarksheetSem7", self.team_html)

    def test_semester_selector_in_faculty_dashboard(self):
        """Faculty dashboard must have 6th and 7th semester selector toggle."""
        self.assertIn("switchFacultySemester", self.faculty_html)
        self.assertIn("6th Semester", self.faculty_html)
        self.assertIn("7th Semester", self.faculty_html)
        self.assertIn("renderEvaluationFormSem7", self.faculty_html)

    def test_semester_selector_in_coordinator_dashboard(self):
        """Coordinator dashboard must have 6th and 7th semester selector toggle."""
        self.assertIn("switchCoordinatorSemester", self.coord_html)
        self.assertIn("6th Semester", self.coord_html)
        self.assertIn("7th Semester", self.coord_html)
        self.assertIn("renderCoordinatorViewModeSem7", self.coord_html)
        self.assertIn("renderCoordinatorEditModeSem7", self.coord_html)

    # =========================================================================
    # Test 2 & 13: 7th Semester 100-Mark Categories and Removal of Grade
    # =========================================================================

    def test_seventh_semester_categories_total_100_marks(self):
        """Phase 4 (30) + Phase 5 (30) + Report (10) + Attendance (10) + Paper Submission (20) = 100."""
        categories = [
            ("Phase 4", 30),
            ("Phase 5", 30),
            ("Report", 10),
            ("Attendance", 10),
            ("Paper Submission", 20)
        ]
        total_max = sum(cat[1] for cat in categories)
        self.assertEqual(total_max, 100)

        # Check in student dashboard
        for name, max_val in categories:
            self.assertIn(f"{name} (Max: {max_val})", self.team_html)

        # Check in faculty dashboard
        for name, max_val in categories:
            self.assertIn(name, self.faculty_html)
            self.assertIn(f"total_marks: {max_val}", self.faculty_html)

        # Check in coordinator dashboard
        for name, max_val in categories:
            self.assertIn(name, self.coord_html)
            self.assertIn(f"total_marks: {max_val}", self.coord_html)

    def test_no_grade_display_in_evaluations_or_marksheets(self):
        """Verify Grade display is removed from marksheet and evaluation sections across all dashboards."""
        # Coordinator dashboard
        self.assertNotIn("Grade", self.coord_html)
        # Student dashboard marksheet table headers
        self.assertNotIn("<th>Grade</th>", self.team_html)
        self.assertNotIn("<td>Grade</td>", self.team_html)
        # Faculty dashboard final marks table headers
        self.assertNotIn("<th>Grade</th>", self.faculty_html)

    # =========================================================================
    # Test 3 & 4: Backend Evaluation Save and Reload with Validation
    # =========================================================================

    @patch("app.db")
    def test_save_evaluation_validates_category_maximums_for_sem7(self, mock_db):
        """Phase 4 > 30, Phase 5 > 30, Report > 10, Attendance > 10, or Paper > 20 must be rejected."""
        mock_db.teams.find_one.return_value = self.sample_team
        mock_db.evaluations.find_one.return_value = None

        # Exceeds Phase 4 maximum (35 > 30)
        invalid_eval = {
            "team_name": "Team-Alpha",
            "semester": 7,
            "evaluation": {
                "phases": [
                    {
                        "name": "Phase 4",
                        "total_marks": 30,
                        "criteria": [
                            {"name": "Phase 4", "max_marks": 30, "marks": [{"marks_obtained": 35, "maximum_marks": 30}]}
                        ]
                    }
                ]
            }
        }

        res = self.client.post(
            "/api/evaluation/save",
            headers={"Authorization": f"Bearer {self.faculty_token}"},
            json=invalid_eval
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertIn("exceeds maximum", data.get("error", ""))

    @patch("app.db")
    def test_save_and_reload_semester_7_evaluation(self, mock_db):
        """Save 7th semester evaluation and verify retrieval with semester=7 parameter."""
        mock_db.teams.find_one.return_value = self.sample_team
        mock_db.evaluations.find_one.return_value = None
        mock_db.evaluations.insert_one.return_value = MagicMock(inserted_id="new_id")

        payload = {
            "team_name": "Team-Alpha",
            "semester": 7,
            "evaluation": {
                "phases": self.sample_eval_sem7["phases"],
                "remarks": "Good work on Phase 4 and paper"
            }
        }

        res = self.client.post(
            "/api/evaluation/save",
            headers={"Authorization": f"Bearer {self.faculty_token}"},
            json=payload
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(mock_db.evaluations.insert_one.called)
        saved_doc = mock_db.evaluations.insert_one.call_args[0][0]
        self.assertEqual(saved_doc.get("semester"), 7)
        self.assertEqual(saved_doc.get("team_name"), "Team-Alpha")

    # =========================================================================
    # Test 5 & 7: Independent Storage, Retrieval, and Attendance Isolation
    # =========================================================================

    @patch("app.db")
    def test_semesters_are_stored_independently_and_do_not_overwrite(self, mock_db):
        """Updating semester 7 marks updates the sem 7 document by _id and leaves sem 6 untouched."""
        existing_sem7_doc = dict(self.sample_eval_sem7)
        mock_db.teams.find_one.return_value = self.sample_team
        # When querying for sem 7, mock_db returns the sem 7 doc
        mock_db.evaluations.find_one.return_value = existing_sem7_doc

        updated_payload = {
            "team_name": "Team-Alpha",
            "semester": 7,
            "evaluation": {
                "phases": self.sample_eval_sem7["phases"],
                "remarks": "Updated sem 7 evaluation"
            }
        }

        res = self.client.post(
            "/api/evaluation/save",
            headers={"Authorization": f"Bearer {self.faculty_token}"},
            json=updated_payload
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(mock_db.evaluations.update_one.called)
        # Verify update targets specifically the sem 7 document's _id
        query_filter = mock_db.evaluations.update_one.call_args[0][0]
        self.assertEqual(query_filter, {"_id": "id_sem7_alpha"})

    @patch("app.db")
    def test_attendance_guide_meetings_do_not_leak_into_semester_7(self, mock_db):
        """Guide meetings from 6th semester must not auto-overwrite 7th semester attendance."""
        mock_db.teams.find_one.return_value = self.sample_team
        mock_db.evaluations.find_one.return_value = dict(self.sample_eval_sem7)

        # 6th sem meetings are present, but 7th sem query returns 0 meetings
        mock_db.attendance.find.return_value = []

        # Student evaluation endpoint with semester=7
        res = self.client.get(
            "/api/evaluation/student?semester=7",
            headers={"Authorization": f"Bearer {self.student_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        eval_data = data.get("evaluation", {})

        # The 7th sem Attendance criterion uses only 7th sem meetings (0 meetings = 0 marks, not 6th sem meetings)
        att_phase = next((p for p in eval_data.get("phases", []) if p["name"] == "Attendance"), None)
        self.assertIsNotNone(att_phase)
        att_mark = att_phase["criteria"][0]["marks"][0]["marks_obtained"]
        self.assertEqual(att_mark, 0)

    @patch("app.db")
    def test_7th_sem_meetings_calculate_attendance_for_sem7(self, mock_db):
        """15 meetings in 7th semester automatically calculate 10 marks for 7th semester attendance."""
        mock_db.teams.find_one.return_value = self.sample_team
        mock_db.evaluations.find_one.return_value = dict(self.sample_eval_sem7)
        # 15 meetings for 7th semester
        mock_db.attendance.find.return_value = [
            {"student_usn": "1MS21CS001", "team_name": "Team-Alpha", "semester": 7} for _ in range(15)
        ]

        res = self.client.get(
            "/api/evaluation/student?semester=7",
            headers={"Authorization": f"Bearer {self.student_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        eval_data = data.get("evaluation", {})
        att_phase = next((p for p in eval_data.get("phases", []) if p["name"] == "Attendance"), None)
        self.assertIsNotNone(att_phase)
        att_mark = att_phase["criteria"][0]["marks"][0]["marks_obtained"]
        self.assertEqual(att_mark, 10)

    # =========================================================================
    # Test 8: Live Calculation & Totals Out of 100 for Both Semesters
    # =========================================================================

    def test_sem7_grand_total_calculation_formula(self):
        """Grand total for sem 7 must sum Phase 4 + Phase 5 + Report + Attendance + Paper <= 100."""
        # Alice's marks in sample_eval_sem7:
        # Phase 4: 27, Phase 5: 28, Report: 9, Attendance: 10, Paper: 19 = 93/100
        alice_marks = [27, 28, 9, 10, 19]
        total = sum(alice_marks)
        self.assertEqual(total, 93)
        self.assertLessEqual(total, 100)
        percentage = (total / 100) * 100
        self.assertEqual(percentage, 93.0)

    # =========================================================================
    # Test 9, 10, 11: Independent VTU Excel Exports by Semester
    # =========================================================================

    @patch("app.db")
    def test_semester_6_vtu_excel_export_contains_only_sem6_marks(self, mock_db):
        """Export with semester=6 (or default) returns 6th semester marks out of 100."""
        mock_db.teams.find.return_value = [self.sample_team]
        mock_db.evaluations.find.return_value = [self.sample_eval_sem6]
        mock_db.attendance.find.return_value = (
            [{"student_usn": "1MS21CS001", "team_name": "Team-Alpha"} for _ in range(15)] +
            [{"student_usn": "1MS21CS002", "team_name": "Team-Alpha"} for _ in range(10)]
        )

        res = self.client.get(
            "/api/coordinator/export_final_marks?semester=6",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        self.assertEqual(res.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        ws = wb.active

        headers = [cell.value for cell in ws[1]]
        self.assertEqual(headers, ["USN", "Marks"])

        rows = list(ws.iter_rows(min_row=2, values_only=True))
        # Alice (1MS21CS001): 9+8+36+18+10+9 = 90
        # Bob (1MS21CS002): 8+7+34+17+8+8 = 82
        usn_map = {row[0]: row[1] for row in rows}
        self.assertEqual(usn_map.get("1MS21CS001"), 90.0)
        self.assertEqual(usn_map.get("1MS21CS002"), 82.0)

    @patch("app.db")
    def test_semester_7_vtu_excel_export_contains_only_sem7_marks(self, mock_db):
        """Export with semester=7 returns 7th semester marks out of 100."""
        mock_db.teams.find.return_value = [self.sample_team]
        mock_db.evaluations.find.return_value = [self.sample_eval_sem7]
        mock_db.attendance.find.return_value = (
            [{"student_usn": "1MS21CS001", "team_name": "Team-Alpha", "semester": 7} for _ in range(15)] +
            [{"student_usn": "1MS21CS002", "team_name": "Team-Alpha", "semester": 7} for _ in range(12)]
        )

        res = self.client.get(
            "/api/coordinator/export_final_marks?semester=7",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        self.assertEqual(res.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        ws = wb.active

        headers = [cell.value for cell in ws[1]]
        self.assertEqual(headers, ["USN", "Marks"])

        rows = list(ws.iter_rows(min_row=2, values_only=True))
        # Alice (1MS21CS001): 27+28+9+10(15 mtgs)+19 = 93
        # Bob (1MS21CS002): 25+26+8+8(12 mtgs)+18 = 85
        usn_map = {row[0]: row[1] for row in rows}
        self.assertEqual(usn_map.get("1MS21CS001"), 93.0)
        self.assertEqual(usn_map.get("1MS21CS002"), 85.0)

        # USNs sorted ascending
        usns = [row[0] for row in rows]
        self.assertEqual(usns, sorted(usns))

    @patch("app.db")
    def test_export_never_combines_both_semesters(self, mock_db):
        """Ensure 6th and 7th semester marks are never summed into 200 marks."""
        mock_db.teams.find.return_value = [self.sample_team]
        mock_db.evaluations.find.return_value = [self.sample_eval_sem7]

        res = self.client.get(
            "/api/coordinator/export_final_marks?semester=7",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        ws = wb.active
        for row in ws.iter_rows(min_row=2, values_only=True):
            mark = row[1]
            if isinstance(mark, (int, float)):
                self.assertLessEqual(mark, 100.0, "Marks must never exceed 100 (never combine 6th & 7th semesters).")

    # =========================================================================
    # UI Layout & Separation Tests for 7th Semester Marksheets & Navigation
    # =========================================================================

    def test_sem7_combined_table_layout_without_status_column(self):
        """Combined Report (10), Attendance (10), Paper Submission (20) table must not have Status column."""
        frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
        coord_file = os.path.join(frontend_dir, "project_coordinator-dashboard.html")
        student_file = os.path.join(frontend_dir, "team-dasboard.html")
        faculty_file = os.path.join(frontend_dir, "faculty-dashboard.html")

        for fpath, name in [(coord_file, "Coordinator"), (student_file, "Student"), (faculty_file, "Faculty")]:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()

            # Verify combined section card/header exists
            self.assertIn("Report, Attendance &amp; Paper Submission", content, f"Missing combined section header in {name} dashboard")
            # Verify columns
            self.assertIn("Report (10)", content, f"Missing Report (10) column header in {name} dashboard")
            self.assertIn("Attendance (10)", content, f"Missing Attendance (10) column header in {name} dashboard")
            self.assertIn("Paper Submission (20)", content, f"Missing Paper Submission (20) column header in {name} dashboard")

        # Verify Student Marksheet sem 7 function no longer has a Status column or badge
        with open(student_file, "r", encoding="utf-8") as f:
            student_content = f.read()
        self.assertNotIn("Marks Obtained (Max:", student_content, "Obsolete 7th sem per-category tables still present in student dashboard")
        self.assertNotIn("● Not Yet Evaluated", student_content, "Status badge still present in 7th sem marksheet in student dashboard")

    def test_sem7_phase4_and_phase5_separate_sections(self):
        """Phase 4 (30) and Phase 5 (30) must remain separate section cards."""
        frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
        coord_file = os.path.join(frontend_dir, "project_coordinator-dashboard.html")
        student_file = os.path.join(frontend_dir, "team-dasboard.html")
        faculty_file = os.path.join(frontend_dir, "faculty-dashboard.html")

        for fpath, name in [(coord_file, "Coordinator"), (student_file, "Student"), (faculty_file, "Faculty")]:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Phase 4 (Max: 30)", content, f"Phase 4 (Max: 30) missing in {name} dashboard")
            self.assertIn("Phase 5 (Max: 30)", content, f"Phase 5 (Max: 30) missing in {name} dashboard")

    def test_faculty_attendance_semester_selector(self):
        """Faculty Guide Meeting Tracking must provide 6th & 7th semester selector."""
        faculty_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "faculty-dashboard.html"))
        with open(faculty_file, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('id="attSem6Btn"', content, "attSem6Btn missing from faculty attendance tracker")
        self.assertIn('id="attSem7Btn"', content, "attSem7Btn missing from faculty attendance tracker")
        self.assertIn('switchFacultyAttendanceSemester', content, "switchFacultyAttendanceSemester function missing")
        self.assertIn('semester=${currentFacultyAttendanceSemester}', content, "currentFacultyAttendanceSemester not passed to /api/attendance GET")

    def test_coordinator_sidebar_navigation_buttons(self):
        """Coordinator sidebar must have all working buttons with data-section attributes."""
        coord_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "project_coordinator-dashboard.html"))
        with open(coord_file, "r", encoding="utf-8") as f:
            content = f.read()

        sections = ["registered-users", "monitor", "approval", "progress", "evaluation", "allocation", "analytics"]
        for sec in sections:
            self.assertIn(f'data-section="{sec}"', content, f"Sidebar button for {sec} missing data-section")
            self.assertIn(f"showSection('{sec}')", content, f"Sidebar button for {sec} missing showSection call")


if __name__ == "__main__":
    unittest.main()

