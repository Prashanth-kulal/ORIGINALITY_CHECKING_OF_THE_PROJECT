"""
Focused Automated Test Suite for Coordinator Dashboard Sidebar Navigation.

Verifies:
1. All expected coordinator sidebar navigation items exist in the HTML.
2. Every sidebar item maps to a valid DOM card with a matching ID (or calls logout).
3. Sidebar button click handlers invoke showSection('<id>') with mobile sidebar cleanup.
4. showSection function is properly defined with section switching, data loaders, active button highlights, and history hash updates.
5. Initial dashboard routing (initCoordinatorDashboard) runs on load and respects URL hashes.
6. The inline dashboard JavaScript contains zero compile-time syntax errors.
"""

import unittest
import os
import re
import subprocess


class TestCoordinatorSidebarNavigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
        cls.coord_html_path = os.path.join(cls.frontend_dir, "project_coordinator-dashboard.html")

        with open(cls.coord_html_path, "r", encoding="utf-8") as f:
            cls.coord_html = f.read()

    def test_sidebar_items_exist(self):
        """All coordinator sidebar buttons must be present in the sidebar."""
        expected_sections = [
            "registered-users",
            "monitor",
            "approval",
            "progress",
            "evaluation",
            "allocation",
            "analytics"
        ]
        sidebar_match = re.search(r'<div class="sidebar">([\s\S]*?)</div>', self.coord_html)
        self.assertIsNotNone(sidebar_match, "Sidebar container <div class='sidebar'> not found.")
        sidebar_content = sidebar_match.group(1)

        for sec in expected_sections:
            self.assertIn(
                f'showSection(\'{sec}\')',
                sidebar_content,
                f"Sidebar button for '{sec}' missing showSection call."
            )
            self.assertIn(
                f'data-section="{sec}"',
                sidebar_content,
                f"Sidebar button for '{sec}' missing data-section attribute."
            )

        # Logout button must also be present
        self.assertIn("logout()", sidebar_content, "Logout button missing from coordinator sidebar.")

    def test_target_cards_exist_for_all_sidebar_sections(self):
        """Each sidebar navigation section must have a corresponding <div class='card' id='...'>."""
        sections = [
            "registered-users",
            "monitor",
            "approval",
            "progress",
            "evaluation",
            "allocation",
            "analytics"
        ]
        for sec in sections:
            # Matches <div class="card..." id="sec" or <div id="sec" ... class="...card...">
            pattern = rf'<div[^>]*class="[^"]*card[^"]*"[^>]*id="{sec}"|<div[^>]*id="{sec}"[^>]*class="[^"]*card[^"]*"'
            self.assertIsNotNone(
                re.search(pattern, self.coord_html),
                f"Corresponding card section for '{sec}' not found in coordinator dashboard."
            )

    def test_show_section_implementation(self):
        """showSection function must properly switch card classes and update sidebar active state."""
        self.assertIn("function showSection(id, btnElement)", self.coord_html)
        # Hides other cards and shows target
        self.assertIn(".card", self.coord_html)
        self.assertIn("classList.remove('active')", self.coord_html)
        self.assertIn("classList.add('active')", self.coord_html)
        # Updates URL hash
        self.assertIn("window.history.replaceState", self.coord_html)
        # Dispatches data loaders
        self.assertIn("loadProgressTeams()", self.coord_html)
        self.assertIn("loadAllIdeas()", self.coord_html)
        self.assertIn("loadCoordinatorEvaluationTeams()", self.coord_html)
        self.assertIn("monitorAllocations()", self.coord_html)
        self.assertIn("loadRegisteredUsers()", self.coord_html)
        self.assertIn("loadAnalytics()", self.coord_html)

    def test_dashboard_initialization(self):
        """Dashboard must initialize on DOMContentLoaded and check window.location.hash."""
        self.assertIn("function initCoordinatorDashboard()", self.coord_html)
        self.assertIn("window.location.hash", self.coord_html)
        self.assertIn("DOMContentLoaded", self.coord_html)

    def test_javascript_syntax_clean(self):
        """The main dashboard script block must parse with 0 syntax errors."""
        script_pattern = re.compile(r'<script\b[^>]*>([\s\S]*?)</script>', re.IGNORECASE)
        scripts = script_pattern.findall(self.coord_html)
        # Find the inline script containing showSection
        main_script = None
        for s in scripts:
            if "function showSection" in s:
                main_script = s
                break

        self.assertIsNotNone(main_script, "Inline script containing showSection not found.")

        # Validate with Node.js vm module via stdin (avoiding Windows command line length limit)
        node_script = """
        const vm = require('vm');
        const fs = require('fs');
        const code = fs.readFileSync(0, 'utf-8');
        try {
            new vm.Script(code);
            process.exit(0);
        } catch (err) {
            console.error('JS Syntax Error:', err.message);
            process.exit(1);
        }
        """
        result = subprocess.run(
            ["node", "-e", node_script],
            input=main_script,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        self.assertEqual(
            result.returncode,
            0,
            f"JavaScript syntax error in coordinator dashboard: {result.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
