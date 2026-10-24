"""
Automated Test Suite for Coordinator Evaluation Cleanup and VTU Final Marks Excel Export.

Verifies:
1. Removal of separate coordinator marks section and its navigation entry.
2. Preservation and full functionality of the Project Evaluation section.
3. Placement and prominent styling of the Excel download button at the top of Project Evaluation.
4. Exported Excel workbook columns contain exactly ['USN', 'Marks'].
5. Each student appears exactly once (normalized USN deduplication without merging distinct students).
6. Exported marks match the authoritative final marks saved through faculty Project Evaluation.
7. Updated faculty marks appear in subsequent Excel downloads.
8. Missing or incomplete evaluations are handled safely (e.g. 'N/A' for unevaluated students, not silently 0).
9. Existing Excel downloading, CSV fallback, and coordinator workflows remain functional.
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import io
import re
import csv
import jwt
import openpyxl

import app as flask_module
from app import app as flask_app, db


class TestCoordinatorEvaluationAndVTUExport(unittest.TestCase):
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
            "leader_email": "alice@college.edu",
            "faculty_name": "Dr. Guide",
            "faculty_email": self.faculty_email,
            "members": [
                {"name": "Bob Member", "usn": "1MS21CS002", "email": "bob@college.edu"}
            ]
        }

        self.sample_evaluation = {
            "team_name": "Team-Alpha",
            "is_locked": False,
            "phases": [
                {
                    "name": "Phase 1 - Synopsis & Problem Definition",
                    "total_marks": 20,
                    "criteria": [
                        {
                            "name": "Problem Statement & Objectives",
                            "max_marks": 10,
                            "marks": [
                                {"marks_obtained": 9.5, "maximum_marks": 10},
                                {"marks_obtained": 8.0, "maximum_marks": 10}
                            ]
                        },
                        {
                            "name": "Social & Technical Impact",
                            "max_marks": 10,
                            "marks": [
                                {"marks_obtained": 9.0, "maximum_marks": 10},
                                {"marks_obtained": 7.5, "maximum_marks": 10}
                            ]
                        }
                    ]
                },
                {
                    "name": "Phase 2 - System Design",
                    "total_marks": 40,
                    "criteria": [
                        {
                            "name": "Technical Clarity",
                            "max_marks": 20,
                            "marks": [
                                {"marks_obtained": 18.0, "maximum_marks": 20},
                                {"marks_obtained": 16.5, "maximum_marks": 20}
                            ]
                        },
                        {
                            "name": "Novelty",
                            "max_marks": 20,
                            "marks": [
                                {"marks_obtained": 19.0, "maximum_marks": 20},
                                {"marks_obtained": 17.0, "maximum_marks": 20}
                            ]
                        }
                    ]
                }
            ]
        }

    # =========================================================================
    # 1. UI: Removal of Separate Coordinator Marks Section
    # =========================================================================

    def test_sidebar_marks_navigation_button_removed(self):
        """The separate Marks navigation button must be removed from coordinator sidebar."""
        pattern = r"showSection\(['\"]marks['\"]\)"
        self.assertIsNone(
            re.search(pattern, self.coord_html),
            "Redundant showSection('marks') navigation button still present in coordinator sidebar."
        )

    def test_standalone_marks_card_removed(self):
        """The standalone card (id='marks') must be removed from coordinator dashboard."""
        self.assertNotIn(
            'id="marks"',
            self.coord_html,
            "Standalone card with id='marks' still present in coordinator dashboard."
        )

    def test_show_section_does_not_route_to_marks(self):
        """The showSection JavaScript function must not route to 'marks'."""
        self.assertNotIn(
            'id === "marks"',
            self.coord_html,
            "showSection still contains branch for 'marks'."
        )

    # =========================================================================
    # 2. UI: Project Evaluation Section Preserved
    # =========================================================================

    def test_project_evaluation_section_intact(self):
        """Project Evaluation section (id='evaluation') must be preserved and functional."""
        self.assertIn(
            'id="evaluation"',
            self.coord_html,
            "Project Evaluation section (id='evaluation') missing from coordinator dashboard."
        )
        self.assertIn(
            "showSection('evaluation')",
            self.coord_html,
            "Project Evaluation navigation button missing from coordinator sidebar."
        )
        self.assertIn(
            'id="evaluationsContainer"',
            self.coord_html,
            "evaluationsContainer missing from coordinator dashboard."
        )
        self.assertIn(
            'id="evaluationTeamSelect"',
            self.coord_html,
            "evaluationTeamSelect dropdown missing from coordinator dashboard."
        )

    # =========================================================================
    # 3. UI: Download Final Marks Button at Top of Project Evaluation
    # =========================================================================

    def test_download_button_prominently_at_top_of_project_evaluation(self):
        """Download Final Marks button must appear inside or at the top of Project Evaluation."""
        eval_start = self.coord_html.find('id="evaluation"')
        eval_container = self.coord_html.find('id="evaluationsContainer"')
        btn_pos = self.coord_html.find('downloadFinalMarks()')

        self.assertNotEqual(eval_start, -1, "Evaluation section not found.")
        self.assertNotEqual(btn_pos, -1, "downloadFinalMarks() button not found.")
        self.assertNotEqual(eval_container, -1, "evaluationsContainer not found.")

        # Button must be located inside #evaluation and before #evaluationsContainer
        self.assertTrue(
            eval_start < btn_pos < eval_container,
            "Download button is not located prominently at the top of Project Evaluation section."
        )

    def test_download_button_appearance_and_handler_preserved(self):
        """Button text, appearance styling, and onclick handler must be preserved."""
        self.assertIn("downloadFinalMarks()", self.coord_html)
        self.assertIn("⬇️ Download Final Marks (VTU Excel)", self.coord_html)
        self.assertIn("linear-gradient(135deg, #10b981, #059669)", self.coord_html)

    # =========================================================================
    # 4. Backend: Exactly Two Columns ['USN', 'Marks'] in Excel Export
    # =========================================================================

    @patch("app.db")
    def test_export_workbook_has_exactly_two_columns(self, mock_db):
        """Exported Excel workbook must contain exactly 'USN' and 'Marks' columns."""
        mock_db.teams.find.return_value = [self.sample_team]
        mock_db.evaluations.find.return_value = [self.sample_evaluation]

        res = self.client.get(
            "/api/coordinator/export_final_marks",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.mimetype,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        ws = wb.active
        self.assertEqual(ws.title, "VTU Final Marks")

        headers = [cell.value for cell in ws[1]]
        self.assertEqual(headers, ["USN", "Marks"], "Headers must be exactly ['USN', 'Marks'].")
        self.assertEqual(len(headers), 2)

        # Verify rows have length 2 and no extraneous metadata
        for row in ws.iter_rows(min_row=2, values_only=True):
            self.assertEqual(len(row), 2)

    # =========================================================================
    # 5. Backend: Deduplication - Each Student Appears Exactly Once
    # =========================================================================

    @patch("app.db")
    def test_each_student_appears_only_once_even_with_duplicate_records(self, mock_db):
        """Normalized USN deduplication ensures each student appears only once."""
        # Setup duplicate team records sharing a member with different casing/whitespace in USN
        team1 = {
            "team_name": "Team-1",
            "leader_name": "Alice Leader",
            "leader_usn": "1ms21cs001 ",
            "members": [{"name": "Bob Member", "usn": "1MS21CS002"}]
        }
        team2 = {
            "team_name": "Team-2",
            "leader_name": "Alice Dupe",
            "leader_usn": "1MS21CS001",
            "members": [{"name": "Charlie Unique", "usn": "1MS21CS003"}]
        }

        mock_db.teams.find.return_value = [team1, team2]
        mock_db.evaluations.find.return_value = []

        res = self.client.get(
            "/api/coordinator/export_final_marks",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        self.assertEqual(res.status_code, 200)

        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        ws = wb.active

        usns = [row[0] for row in ws.iter_rows(min_row=2, values_only=True)]
        self.assertEqual(len(usns), 3, "Expected exactly 3 unique students (Alice, Bob, Charlie).")
        self.assertEqual(len(usns), len(set(usns)), "Duplicates detected in exported USNs.")
        self.assertIn("1MS21CS001", usns)
        self.assertIn("1MS21CS002", usns)
        self.assertIn("1MS21CS003", usns)

    @patch("app.db")
    def test_usns_sorted_in_ascending_natural_order(self, mock_db):
        """Exported students must be sorted in natural ascending USN order (e.g. 2 before 10)."""
        teams = [
            {
                "team_name": "Team-Sort-1",
                "leader_name": "S1",
                "leader_usn": "1MS21CS10",
                "members": [{"name": "S2", "usn": "1MS21CS2"}]
            },
            {
                "team_name": "Team-Sort-2",
                "leader_name": "S3",
                "leader_usn": "1MS20CS001",
                "members": [
                    {"name": "S4", "usn": "2TG22EC01"},
                    {"name": "S5", "usn": "1MS21CS001"}
                ]
            }
        ]
        mock_db.teams.find.return_value = teams
        mock_db.evaluations.find.return_value = []

        res = self.client.get(
            "/api/coordinator/export_final_marks",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        self.assertEqual(res.status_code, 200)

        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        ws = wb.active

        usns = [row[0] for row in ws.iter_rows(min_row=2, values_only=True)]
        expected_order = ["1MS20CS001", "1MS21CS001", "1MS21CS2", "1MS21CS10", "2TG22EC01"]
        self.assertEqual(usns, expected_order, f"USNs not sorted naturally: {usns}")

    @patch("app.db")
    def test_no_extra_rows_columns_or_metadata(self, mock_db):
        """Sheet must have only row 1 as headers ['USN', 'Marks'] followed directly by data rows."""
        mock_db.teams.find.return_value = [self.sample_team]
        mock_db.evaluations.find.return_value = [self.sample_evaluation]

        res = self.client.get(
            "/api/coordinator/export_final_marks",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        ws = wb.active

        all_rows = list(ws.iter_rows(values_only=True))
        # Total rows: 1 header row + 2 student rows = 3 rows total
        self.assertEqual(len(all_rows), 3, "Sheet must contain exactly 1 header row + student rows.")
        self.assertEqual(all_rows[0], ("USN", "Marks"), "First row must be exactly ('USN', 'Marks').")
        for row_idx, row in enumerate(all_rows[1:], start=2):
            self.assertEqual(len(row), 2, f"Row {row_idx} must have exactly 2 columns.")
            self.assertIsNotNone(row[0], f"Row {row_idx} USN must not be None.")
            self.assertIsNotNone(row[1], f"Row {row_idx} Marks must not be None.")

    @patch("app.db")
    def test_distinct_students_without_usn_not_accidentally_merged(self, mock_db):
        """Students without USNs must not be merged into a single row."""
        team = {
            "team_name": "Team-NoUSN",
            "leader_name": "Student Leader",
            "leader_usn": "",
            "members": [
                {"name": "Member One", "usn": ""},
                {"name": "Member Two", "usn": ""}
            ]
        }
        mock_db.teams.find.return_value = [team]
        mock_db.evaluations.find.return_value = []

        res = self.client.get(
            "/api/coordinator/export_final_marks",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        self.assertEqual(res.status_code, 200)

        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        ws = wb.active

        rows = list(ws.iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(rows), 3, "All 3 distinct students must be included.")
        for r in rows:
            self.assertEqual(r[0], "N/A")

    # =========================================================================
    # 6. Backend: Authoritative Marks Calculation from Faculty Project Evaluation
    # =========================================================================

    @patch("app.db")
    def test_exported_marks_match_faculty_evaluation(self, mock_db):
        """Exported marks must exactly match authoritative sum of marks from faculty Project Evaluation."""
        mock_db.teams.find.return_value = [self.sample_team]
        mock_db.evaluations.find.return_value = [self.sample_evaluation]

        res = self.client.get(
            "/api/coordinator/export_final_marks",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        self.assertEqual(res.status_code, 200)

        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        ws = wb.active

        data = {row[0]: row[1] for row in ws.iter_rows(min_row=2, values_only=True)}

        # Alice: 9.5 + 9.0 + 18.0 + 19.0 = 55.5
        # Bob: 8.0 + 7.5 + 16.5 + 17.0 = 49.0 -> integer 49
        self.assertEqual(data["1MS21CS001"], 55.5)
        self.assertEqual(data["1MS21CS002"], 49)

    # =========================================================================
    # 7. Backend: Updated Marks Reflect in Subsequent Exports
    # =========================================================================

    @patch("app.db")
    def test_updated_faculty_marks_appear_in_subsequent_export(self, mock_db):
        """Changes saved to faculty evaluation must immediately reflect in subsequent export."""
        mock_db.teams.find.return_value = [self.sample_team]

        # Initial evaluation
        mock_db.evaluations.find.return_value = [self.sample_evaluation]
        res1 = self.client.get(
            "/api/coordinator/export_final_marks",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        wb1 = openpyxl.load_workbook(io.BytesIO(res1.data))
        data1 = {row[0]: row[1] for row in wb1.active.iter_rows(min_row=2, values_only=True)}
        self.assertEqual(data1["1MS21CS001"], 55.5)

        # Faculty updates marks: Alice gets +5 marks in Phase 2 Novelty (19 -> 24? or +2: 19 -> 20, total 56.5)
        import copy
        updated_eval = copy.deepcopy(self.sample_evaluation)
        updated_eval["phases"][1]["criteria"][1]["marks"][0]["marks_obtained"] = 20.0
        # Total now: 9.5 + 9.0 + 18.0 + 20.0 = 56.5

        mock_db.evaluations.find.return_value = [updated_eval]
        res2 = self.client.get(
            "/api/coordinator/export_final_marks",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        wb2 = openpyxl.load_workbook(io.BytesIO(res2.data))
        data2 = {row[0]: row[1] for row in wb2.active.iter_rows(min_row=2, values_only=True)}
        self.assertEqual(data2["1MS21CS001"], 56.5)

    # =========================================================================
    # 8. Backend: Missing and Incomplete Evaluations Handled Consistently
    # =========================================================================

    @patch("app.db")
    def test_unevaluated_student_not_silently_zero(self, mock_db):
        """Unevaluated team/student must report 'N/A' marks, NOT silently 0."""
        mock_db.teams.find.return_value = [self.sample_team]
        mock_db.evaluations.find.return_value = []  # No evaluation saved

        res = self.client.get(
            "/api/coordinator/export_final_marks",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        self.assertEqual(res.status_code, 200)

        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        data = {row[0]: row[1] for row in wb.active.iter_rows(min_row=2, values_only=True)}
        self.assertEqual(data["1MS21CS001"], "N/A")
        self.assertEqual(data["1MS21CS002"], "N/A")

    @patch("app.db")
    def test_incomplete_evaluation_treats_empty_criteria_as_zero(self, mock_db):
        """In an existing evaluation, empty/missing criteria marks treat as 0 per authoritative logic."""
        incomplete_eval = {
            "team_name": "Team-Alpha",
            "phases": [
                {
                    "name": "Phase 1",
                    "total_marks": 20,
                    "criteria": [
                        {
                            "name": "Criterion A",
                            "max_marks": 10,
                            "marks": [{"marks_obtained": 8.0}, {"marks_obtained": ""}]
                        },
                        {
                            "name": "Criterion B",
                            "max_marks": 10,
                            "marks": [{"marks_obtained": None}, {"marks_obtained": "  "}]
                        }
                    ]
                }
            ]
        }
        mock_db.teams.find.return_value = [self.sample_team]
        mock_db.evaluations.find.return_value = [incomplete_eval]

        res = self.client.get(
            "/api/coordinator/export_final_marks",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        self.assertEqual(res.status_code, 200)

        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        data = {row[0]: row[1] for row in wb.active.iter_rows(min_row=2, values_only=True)}
        # Alice has 8.0 + 0 = 8
        self.assertEqual(data["1MS21CS001"], 8)
        # Bob has 0 + 0 = 0
        self.assertEqual(data["1MS21CS002"], 0)

    # =========================================================================
    # 9. Backend: CSV Fallback & Authorization Enforcement
    # =========================================================================

    @patch("openpyxl.Workbook", side_effect=Exception("Simulated openpyxl failure"))
    @patch("app.db")
    def test_csv_fallback_preserves_two_columns(self, mock_db, mock_wb):
        """CSV fallback when openpyxl fails must contain exactly USN and Marks."""
        mock_db.teams.find.return_value = [self.sample_team]
        mock_db.evaluations.find.return_value = [self.sample_evaluation]

        res = self.client.get(
            "/api/coordinator/export_final_marks",
            headers={"Authorization": f"Bearer {self.coord_token}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "text/csv")
        self.assertIn("vtu_final_marks.csv", res.headers.get("Content-Disposition", ""))

        csv_text = res.data.decode("utf-8")
        reader = list(csv.reader(io.StringIO(csv_text)))
        self.assertEqual(reader[0], ["USN", "Marks"])
        self.assertEqual(len(reader), 3)  # Header + 2 students

    def test_authorization_protection(self):
        """Unauthorized requests are blocked (401 missing token, 403 student role)."""
        # Missing token
        res_no_tok = self.client.get("/api/coordinator/export_final_marks")
        self.assertEqual(res_no_tok.status_code, 401)

        # Student token
        res_student = self.client.get(
            "/api/coordinator/export_final_marks",
            headers={"Authorization": f"Bearer {self.student_token}"}
        )
        self.assertEqual(res_student.status_code, 403)

    # =========================================================================
    # 10. Verification of Grade Display Removal Across All Dashboards
    # =========================================================================

    def test_faculty_final_marks_grade_display_removed(self):
        """Faculty Project Evaluation -> Final Marks table must not display Grade."""
        # No Grade column header in faculty final marks
        self.assertNotIn(
            ">Grade</th>",
            self.faculty_html,
            "Visible 'Grade' table header found in Faculty Dashboard Final Marks table."
        )
        # No grade cell ID or grade column in final marks row
        self.assertNotIn(
            "finalMarks_m${memberIdx}_grade",
            self.faculty_html,
            "Grade cell ID 'finalMarks_m${memberIdx}_grade' found in Faculty Dashboard."
        )
        # Key marks information preserved
        self.assertIn("Total Marks", self.faculty_html)
        self.assertIn("Percentage", self.faculty_html)
        self.assertIn("finalMarks_m${memberIdx}_total", self.faculty_html)
        self.assertIn("finalMarks_m${memberIdx}_pct", self.faculty_html)

    def test_student_my_marksheet_grade_display_removed(self):
        """Student Dashboard -> My Marksheet table must not display Grade."""
        # No Grade column header in student marksheet
        self.assertNotIn(
            ">Grade</th>",
            self.team_html,
            "Visible 'Grade' table header found in Student Dashboard My Marksheet."
        )
        # Key marks information preserved
        self.assertIn("Member", self.team_html)
        self.assertIn("Total Marks", self.team_html)
        self.assertIn("Percentage", self.team_html)
        self.assertIn("Grand Total & Performance", self.team_html)

    def test_coordinator_evaluation_grade_display_removed(self):
        """Coordinator Dashboard -> Project Evaluation (View & Edit) must not display Grade."""
        # No Grade column header anywhere in coordinator evaluation tables
        self.assertNotIn(
            ">Grade</th>",
            self.coord_html,
            "Visible 'Grade' table header found in Coordinator Dashboard evaluation tables."
        )
        # No grand_grade element in edit mode or recalculation
        self.assertNotIn(
            "grand_grade_",
            self.coord_html,
            "Grade element 'grand_grade_' found in Coordinator Dashboard."
        )
        # Key marks information preserved
        self.assertIn("Total Marks", self.coord_html)
        self.assertIn("Percentage", self.coord_html)
        self.assertIn("grand_total_", self.coord_html)
        self.assertIn("grand_percentage_", self.coord_html)


if __name__ == "__main__":
    unittest.main()
