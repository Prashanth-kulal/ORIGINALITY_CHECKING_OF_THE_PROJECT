"""
Automated Test Suite for:
1. Faculty Dashboard Navigation & Section Mapping
2. Single Notification Bell in Faculty Dashboard (No Duplicates)
3. Coordinator Faculty Selection Dropdown & API Integration
"""

import unittest
import os
import re
import subprocess
import json
from app import app, db


class TestFacultyNavAndCoordinatorDropdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        cls.frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
        cls.faculty_html_path = os.path.join(cls.frontend_dir, "faculty-dashboard.html")
        cls.coord_html_path = os.path.join(cls.frontend_dir, "project_coordinator-dashboard.html")

        with open(cls.faculty_html_path, "r", encoding="utf-8") as f:
            cls.faculty_html = f.read()

        with open(cls.coord_html_path, "r", encoding="utf-8") as f:
            cls.coord_html = f.read()

    # =========================================================================
    # ISSUE 1: FACULTY DASHBOARD NAVIGATION & SYNTAX
    # =========================================================================

    def test_faculty_dashboard_javascript_syntax_clean(self):
        """The inline faculty dashboard JavaScript must parse with 0 syntax errors."""
        script_pattern = re.compile(r'<script\b[^>]*>([\s\S]*?)</script>', re.IGNORECASE)
        scripts = script_pattern.findall(self.faculty_html)
        main_script = None
        for s in scripts:
            if "function showSection" in s:
                main_script = s
                break

        self.assertIsNotNone(main_script, "Inline script containing showSection not found in faculty-dashboard.html.")

        p = subprocess.Popen(["node", "-c"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate(main_script.encode("utf-8"))
        self.assertEqual(
            p.returncode,
            0,
            f"JavaScript syntax error in faculty-dashboard.html: {err.decode('utf-8', errors='ignore')}"
        )

    def test_faculty_sidebar_items_and_sections_exist(self):
        """Every faculty sidebar navigation item must map to an existing <div id='...' class='section'>."""
        expected_sections = [
            "teams",
            "progress_history",
            "tasks",
            "approvals",
            "feedback",
            "attendance",
            "chat",
            "panel-evaluations",
            "evaluation",
            "novelty",
            "projectIdeas",
            "research-papers"
        ]

        # Verify sidebar contains showSection for all sections
        for sec in expected_sections:
            self.assertTrue(
                f"showSection('{sec}')" in self.faculty_html or f'showSection("{sec}")' in self.faculty_html,
                f"Sidebar missing navigation call for section: {sec}"
            )
            # Verify target section element exists
            pattern = rf'<div[^>]*id="{sec}"[^>]*class="[^"]*section[^"]*"|<div[^>]*class="[^"]*section[^"]*"[^>]*id="{sec}"'
            self.assertIsNotNone(
                re.search(pattern, self.faculty_html),
                f"Target DOM section <div id='{sec}' class='section'> not found in faculty-dashboard.html."
            )

    def test_faculty_show_section_prevents_substring_collisions(self):
        """showSection must not collide between 'evaluation' and 'panel-evaluations'."""
        self.assertIn("function showSection(id)", self.faculty_html)
        # Should not use a[onclick*="${id}"] which causes collision
        self.assertNotIn('a[onclick*="${id}"]', self.faculty_html)
        # Should check exact showSection call
        self.assertIn("showSection('${id}')", self.faculty_html)

    # =========================================================================
    # ISSUE 2: COORDINATOR FACULTY SELECTION DROPDOWN & API
    # =========================================================================

    def test_get_all_faculty_endpoint(self):
        """Backend endpoint /api/faculty/all returns full faculty details with names, emails, IDs, and depts."""
        res = self.client.get('/api/faculty/all')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("faculties", data)
        self.assertIn("faculty", data)
        faculties = data["faculties"]
        self.assertIsInstance(faculties, list)
        self.assertGreater(len(faculties), 0, "No faculty returned from /api/faculty/all")

        seen_emails = set()
        for f in faculties:
            self.assertIn("name", f)
            self.assertIn("email", f)
            self.assertIn("faculty_id", f)
            self.assertIn("department", f)
            # Name must not be blank or undefined
            self.assertTrue(bool(f["name"] and str(f["name"]).strip()), "Faculty name cannot be blank")
            self.assertNotEqual(f["name"], "undefined")
            # Email must not be empty or duplicate
            email = f["email"].lower()
            self.assertNotIn(email, seen_emails, f"Duplicate faculty email found: {email}")
            seen_emails.add(email)

    def test_coordinator_dashboard_dropdown_population_logic(self):
        """Coordinator dashboard must handle object response with .faculties or .faculty."""
        self.assertIn("populateCoordinatorPanelFacultyDropdowns", self.coord_html)
        # Must check Array.isArray(data) ? data : (data.faculties || data.faculty || [])
        self.assertIn("data.faculties || data.faculty", self.coord_html)
        # Must populate member 1, 2, 3, and replace dropdown
        self.assertIn("panelAllocMember1", self.coord_html)
        self.assertIn("panelAllocMember2", self.coord_html)
        self.assertIn("panelAllocMember3", self.coord_html)
        self.assertIn("replaceNewMemberSelect", self.coord_html)
        # Must format option display with name, email, and ID/department
        self.assertIn("f.faculty_id", self.coord_html)
        # Team dropdown must fetch from /api/evaluation/coordinator/all
        self.assertIn("/api/evaluation/coordinator/all", self.coord_html)

    # =========================================================================
    # ISSUE 3: REMOVE DUPLICATE NOTIFICATION SYMBOL
    # =========================================================================

    def test_single_notification_bell_in_faculty_dashboard(self):
        """Faculty dashboard must not hardcode a duplicate notification bell in .topbar."""
        # Check that topbar in faculty-dashboard.html does NOT contain a hardcoded headerNotifBtn
        topbar_match = re.search(r'<div class="topbar">([\s\S]*?)</div>\s*<!--\s*Dedicated Panel Evaluations', self.faculty_html)
        self.assertIsNotNone(topbar_match, "Topbar container not found.")
        topbar_content = topbar_match.group(1)
        self.assertNotIn('id="headerNotifBtn"', topbar_content, "Duplicate hardcoded #headerNotifBtn found in .topbar HTML.")
        self.assertNotIn('id="headerNotifPopover"', topbar_content, "Duplicate hardcoded #headerNotifPopover found in .topbar HTML.")

        # Sidebar Panel Evaluations must not use the bell emoji
        sidebar_match = re.search(r'<div class="sidebar">([\s\S]*?)</div>', self.faculty_html)
        self.assertIsNotNone(sidebar_match)
        sidebar_content = sidebar_match.group(1)
        self.assertNotIn("🔔 Panel Evaluations", sidebar_content, "Bell emoji still present in sidebar Panel Evaluations.")
        self.assertIn("👥 Panel Evaluations", sidebar_content, "Sidebar Panel Evaluations missing 👥 icon.")

    # =========================================================================
    # ISSUE 4: PHASE ALLOCATION VALIDATION FOR 6TH & 7TH SEMESTER
    # =========================================================================

    def test_allocate_panel_handles_all_semesters_and_phase_keys(self):
        """Coordinator panel allocation must accept Phase 1/Phase 2 (Sem 6) and Phase 4/Phase 5 (Sem 7) seamlessly."""
        import jwt
        token = jwt.encode({'email': 'coord@test.edu', 'role': 'coordinator'}, app.config['SECRET_KEY'], algorithm='HS256')

        # Find or create a test team with guide
        team = db.teams.find_one() or {'team_name': 'Test Team 101'}
        t_name = team.get('team_name')
        db.allocations.update_one(
            {'team_name': t_name},
            {'$set': {'faculty_email': 'guide@test.edu', 'faculty_name': 'Prof Guide'}},
            upsert=True
        )

        test_cases = [
            (6, 'Phase 1'),
            (6, 'Phase 2'),
            (7, 'Phase 4'),
            (7, 'Phase 5'),
            (6, 'Phase 1 (20 Marks)'),
            (7, 'Phase 4 (30 Marks)')
        ]

        for sem, phase_val in test_cases:
            # Test payload with presentation_phase (coordinator frontend format)
            payload = {
                'team_name': t_name,
                'semester': sem,
                'presentation_phase': phase_val,
                'panel_member_emails': ['p1@test.edu', 'p2@test.edu', 'p3@test.edu'],
                'evaluation_deadline': '2026-11-30T18:00'
            }
            res = self.client.post(
                '/api/panel/allocate',
                headers={'Authorization': f'Bearer {token}'},
                json=payload
            )
            data = res.get_json()
            self.assertIn(
                res.status_code,
                [200, 201],
                f"Failed to allocate panel for sem {sem}, phase '{phase_val}': {data}"
            )
            self.assertTrue(data.get("success"), f"Expected success: True for sem {sem}, phase '{phase_val}'")


if __name__ == "__main__":
    unittest.main()

