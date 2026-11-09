import unittest
import os
import sys

# Ensure backend directory is in python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import app

class TestLandingPage(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_01_root_route_serves_login(self):
        """Verifies that the root URL / serves login.html with 200 OK without regressions."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Login', response.data)
        self.assertIn(b'Back to PROJECTVERSE', response.data)

    def test_02_landing_route_serves_landing_page(self):
        """Verifies that /landing serves the ultra-premium landing page with 200 OK."""
        response = self.client.get('/landing')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        
        # Verify Product Branding & Core Narrative
        self.assertIn('PROJECTVERSE', html)
        self.assertIn('AI-POWERED ACADEMIC PROJECT ECOSYSTEM', html)
        self.assertIn('WHERE IDEAS BECOME', html)
        self.assertIn('ORIGINAL INNOVATIONS.', html)

    def test_03_landing_html_static_route(self):
        """Verifies that /landing.html is directly accessible."""
        response = self.client.get('/landing.html')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn('PROJECTVERSE', html)

    def test_04_split_hero_section_elements(self):
        """Verifies hero content, description, CTAs, and telemetry metrics."""
        response = self.client.get('/landing')
        html = response.data.decode('utf-8')
        
        # Subtitle
        self.assertIn('An intelligent academic ecosystem connecting students, faculty and project management', html)
        self.assertIn('AI-powered originality analysis and seamless collaboration', html)
        
        # CTAs
        self.assertIn('Enter Platform', html)
        self.assertIn('Explore Experience', html)
        self.assertIn('href="login.html"', html)
        self.assertIn('href="#network"', html)

        # Telemetry metrics
        self.assertIn('all-MiniLM-L6-v2', html)
        self.assertIn('13 Triggers', html)
        self.assertIn('3 Phases', html)

    def test_05_interactive_node_network_section(self):
        """Verifies the 60fps Interactive Concept Node Network and its 8 core platform nodes."""
        response = self.client.get('/landing')
        html = response.data.decode('utf-8')

        self.assertIn('nodeNetworkCanvas', html)
        self.assertIn('INTERCONNECTED INTELLIGENCE', html)
        self.assertIn('Explore the Academic Neural Network', html)
        
        # 8 Platform Concept Nodes
        nodes = ['Students', 'Projects', 'Faculty', 'AI Analysis', 'Originality', 'Evaluation', 'Research', 'Collaboration']
        for node in nodes:
            self.assertIn(f"'{node}'", html)

    def test_06_real_feature_showcase_cards(self):
        """Verifies 8 bespoke glass cards mapping directly to real backend capabilities."""
        response = self.client.get('/landing')
        html = response.data.decode('utf-8')

        features = [
            'AI-Based Originality Checking',
            'Student Project Management',
            'Team Collaboration & Flowcharts',
            'Faculty Guidance & Approvals',
            'Project Progress Tracking',
            'Phase-Wise Evaluation',
            'Attendance & Performance',
            'Research & Documentation'
        ]
        for feat in features:
            self.assertIn(feat, html)

    def test_07_connected_workflow_pipeline_seven_steps(self):
        """Verifies the 7-step connected workflow pipeline from Project Creation to Final Submission."""
        response = self.client.get('/landing')
        html = response.data.decode('utf-8')

        expected_steps = [
            "Project Creation",
            "Team Collaboration",
            "Faculty Guidance",
            "Originality Analysis",
            "Progress Monitoring",
            "Phase Evaluation",
            "Final Submission"
        ]
        for step in expected_steps:
            self.assertIn(step, html)

    def test_08_three_role_portals_present(self):
        """Verifies tailored stakeholder cards for Student, Faculty, and Coordinator with prefilled role query params."""
        response = self.client.get('/landing')
        html = response.data.decode('utf-8')

        self.assertIn("STUDENT PORTAL", html)
        self.assertIn("FACULTY PORTAL", html)
        self.assertIn("COORDINATOR PORTAL", html)
        self.assertIn("For Students & Teams", html)
        self.assertIn("For Guides & Mentors", html)
        self.assertIn("For Project Coordinators", html)
        
        self.assertIn("Launch Student Portal", html)
        self.assertIn("Launch Faculty Portal", html)
        self.assertIn("Launch Coordinator Portal", html)
        
        self.assertIn("login.html?role=team", html)
        self.assertIn("login.html?role=faculty", html)
        self.assertIn("login.html?role=coordinator", html)

    def test_09_closing_cta_and_registration_link(self):
        """Verifies the closing CTA and registration links."""
        response = self.client.get('/landing')
        html = response.data.decode('utf-8')

        self.assertIn("WHERE IDEAS BECOME ORIGINAL INNOVATIONS.", html)
        self.assertIn("Enter Platform", html)
        self.assertIn("Register Your Team", html)
        self.assertIn('href="index.html"', html)

    def test_10_landing_page_folder_assets_exist(self):
        """Verifies that landing_page/ directory has index.html, style.css, and main.js."""
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'landing_page'))
        index_file = os.path.join(base_dir, 'index.html')
        css_file = os.path.join(base_dir, 'css', 'style.css')
        js_file = os.path.join(base_dir, 'js', 'main.js')

        self.assertTrue(os.path.exists(index_file), "landing_page/index.html must exist")
        self.assertTrue(os.path.exists(css_file), "landing_page/css/style.css must exist")
        self.assertTrue(os.path.exists(js_file), "landing_page/js/main.js must exist")

        with open(index_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn('PROJECTVERSE', content)
            self.assertIn('WHERE IDEAS BECOME', content)
            self.assertIn('ORIGINAL INNOVATIONS.', content)

    def test_11_theme_controller_and_toggle_button(self):
        """Verifies that theme controller script is referenced and toggle button is properly set up."""
        response = self.client.get('/landing')
        html = response.data.decode('utf-8')

        # Core theme controller script referenced
        self.assertIn('src="theme.js"', html)

        # Toggle button with class theme-toggle-btn and id landingThemeToggle
        self.assertIn('id="landingThemeToggle"', html)
        self.assertIn('class="theme-toggle-btn"', html)
        self.assertIn('type="button"', html)

        # Standalone landing_page/index.html also references theme.js
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'landing_page'))
        with open(os.path.join(base_dir, 'index.html'), 'r', encoding='utf-8') as f:
            index_content = f.read()
            self.assertIn('js/theme.js', index_content)
            self.assertIn('id="landingThemeToggle"', index_content)

    def test_12_theme_css_tokens_dark_and_light(self):
        """Verifies semantic CSS design tokens for both Dark Mode and Light Mode."""
        response = self.client.get('/landing')
        html = response.data.decode('utf-8')

        # Check selectors
        self.assertIn('[data-theme="dark"]', html)
        self.assertIn('[data-theme="light"]', html)
        self.assertIn('.dark-theme', html)
        self.assertIn('.light-theme', html)

        # Check crucial semantic variables
        self.assertIn('--bg-page:', html)
        self.assertIn('--bg-card:', html)
        self.assertIn('--text-primary:', html)
        self.assertIn('--text-secondary:', html)
        self.assertIn('--text-muted:', html)
        self.assertIn('--border-subtle:', html)
        self.assertIn('--border-glass:', html)
        self.assertIn('--crystal-blend: screen', html)
        self.assertIn('--crystal-blend: multiply', html)

    def test_13_no_duplicate_toggle_listeners(self):
        """Verifies that main.js and landing.html do not attach conflicting duplicate click listeners."""
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'landing_page'))
        with open(os.path.join(base_dir, 'js', 'main.js'), 'r', encoding='utf-8') as f:
            main_js = f.read()
            # Must check if window.toggleTheme is NOT defined before adding click listener
            self.assertIn("typeof window.toggleTheme !== 'function'", main_js)

        # In landing.html as well
        response = self.client.get('/landing')
        html = response.data.decode('utf-8')
        self.assertIn("typeof window.toggleTheme !== 'function'", html)


if __name__ == '__main__':
    unittest.main()
