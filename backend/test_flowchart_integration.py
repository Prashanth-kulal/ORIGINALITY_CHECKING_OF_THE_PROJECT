"""
Comprehensive Flowchart Integration & Integrity Tests
Validates frontend markup, script references, CSS tokens,
backend APIs, ownership protection, and preservation of existing system behavior.
"""

import os
import re
import unittest
import jwt
from datetime import datetime, timezone, timedelta
from backend.app import app, db
from backend.flowchart_engine import (
    parse_python_code,
    parse_java_code,
    validate_diagram_data,
    calculate_hierarchical_layout
)


class TestFlowchartCompleteSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        cls.secret = app.config["SECRET_KEY"]

        # Student A
        cls.student_payload = {
            "email": "student_alpha@test.edu",
            "usn": "1MS21CS101",
            "name": "Alpha Student",
            "role": "student",
            "team_name": "Team Flow",
            "exp": datetime.now(timezone.utc) + timedelta(hours=2)
        }
        cls.student_token = jwt.encode(cls.student_payload, cls.secret, algorithm="HS256")
        cls.student_headers = {"Authorization": f"Bearer {cls.student_token}"}

        # Student B (Separate user for isolation)
        cls.student_b_payload = {
            "email": "student_beta@test.edu",
            "usn": "1MS21CS202",
            "name": "Beta Student",
            "role": "student",
            "team_name": "Team Beta",
            "exp": datetime.now(timezone.utc) + timedelta(hours=2)
        }
        cls.student_b_token = jwt.encode(cls.student_b_payload, cls.secret, algorithm="HS256")
        cls.student_b_headers = {"Authorization": f"Bearer {cls.student_b_token}"}

        # Faculty
        cls.faculty_payload = {
            "email": "faculty@test.edu",
            "name": "Prof Evaluator",
            "role": "faculty",
            "exp": datetime.now(timezone.utc) + timedelta(hours=2)
        }
        cls.faculty_token = jwt.encode(cls.faculty_payload, cls.secret, algorithm="HS256")
        cls.faculty_headers = {"Authorization": f"Bearer {cls.faculty_token}"}

    # --- 1. Dashboard Integration & Student-Only Access ---
    def test_01_dashboard_integration_and_student_only_access(self):
        # Read team-dasboard.html
        dash_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "team-dasboard.html")
        with open(dash_path, "r", encoding="utf-8") as f:
            dash_html = f.read()

        # Check sidebar item exists
        self.assertIn("flowchart-designer.html", dash_html)
        self.assertIn("Flowchart Designer", dash_html)
        self.assertIn('id="flowchart"', dash_html)

        # Endpoint authorization checks
        unauth_res = self.client.get("/api/flowchart/list")
        self.assertEqual(unauth_res.status_code, 401)

        fac_res = self.client.get("/api/flowchart/list", headers=self.faculty_headers)
        self.assertEqual(fac_res.status_code, 403)

        stud_res = self.client.get("/api/flowchart/list", headers=self.student_headers)
        self.assertEqual(stud_res.status_code, 200)

    # --- 2. Manual Node Creation & Editing Data Structures ---
    def test_02_node_creation_and_attributes(self):
        payload = {
            "title": "Manual Flowchart",
            "nodes": [
                {
                    "id": "node_1",
                    "type": "start",
                    "label": "Begin Algorithm",
                    "x": 200,
                    "y": 50,
                    "width": 160,
                    "height": 70,
                    "style": {"fill": "#ecfdf5", "stroke": "#10b981", "fontSize": 14}
                },
                {
                    "id": "node_2",
                    "type": "process",
                    "label": "Compute Hash",
                    "x": 200,
                    "y": 180,
                    "width": 160,
                    "height": 70,
                    "style": {"fill": "#ffffff", "stroke": "#3b82f6", "fontSize": 13}
                }
            ],
            "edges": [
                {
                    "id": "edge_1",
                    "source": "node_1",
                    "target": "node_2",
                    "label": "Proceed",
                    "type": "orthogonal"
                }
            ]
        }
        valid, sanitized, msg = validate_diagram_data(payload)
        self.assertTrue(valid)
        self.assertEqual(len(sanitized["nodes"]), 2)
        self.assertEqual(sanitized["nodes"][0]["style"]["fill"], "#ecfdf5")
        self.assertEqual(sanitized["nodes"][0]["style"]["stroke"], "#10b981")

    # --- 3. Connector Attachment & Graph Integrity ---
    def test_03_connector_attachment(self):
        # Broken edges targeting non-existent nodes must be sanitized
        payload = {
            "title": "Edge Test",
            "nodes": [
                {"id": "n_a", "type": "process", "label": "A"},
                {"id": "n_b", "type": "process", "label": "B"}
            ],
            "edges": [
                {"id": "e_valid", "source": "n_a", "target": "n_b", "label": "connects"},
                {"id": "e_broken", "source": "n_a", "target": "n_ghost", "label": "invalid"}
            ]
        }
        valid, sanitized, msg = validate_diagram_data(payload)
        self.assertTrue(valid)
        self.assertEqual(len(sanitized["edges"]), 1)
        self.assertEqual(sanitized["edges"][0]["id"], "e_valid")

    # --- 4. Decision Branches & Labels ---
    def test_04_decision_branches_and_labels(self):
        code = "if x > 0:\n    print('pos')\nelse:\n    print('non-pos')"
        res = parse_python_code(code)
        decision_node = next(n for n in res["nodes"] if n["type"] == "decision")
        self.assertIn("x > 0", decision_node["label"])

        out_edges = [e for e in res["edges"] if e["source"] == decision_node["id"]]
        labels = {e["label"] for e in out_edges}
        self.assertTrue("Yes" in labels or "True" in labels)
        self.assertTrue("No" in labels or "False" in labels)

    # --- 5. Valid and Invalid Code to Flowchart Input ---
    def test_05_code_to_flowchart_validation(self):
        # Empty code -> 400
        res_empty = self.client.post("/api/flowchart/code-to-flowchart", json={"language": "python", "code": ""}, headers=self.student_headers)
        self.assertEqual(res_empty.status_code, 400)

        # Invalid Python syntax -> 400 with syntax message
        res_bad = self.client.post("/api/flowchart/code-to-flowchart", json={"language": "python", "code": "def foo(:::"}, headers=self.student_headers)
        self.assertEqual(res_bad.status_code, 400)
        self.assertIn("Syntax Error", res_bad.get_json()["error"])

        # Valid Python while loop
        while_code = "i = 0\nwhile i < 10:\n    i += 1"
        res_while = self.client.post("/api/flowchart/code-to-flowchart", json={"language": "python", "code": while_code}, headers=self.student_headers)
        self.assertEqual(res_while.status_code, 200)
        edges = res_while.get_json()["edges"]
        self.assertTrue(any(e.get("label") == "Loop" for e in edges))

        # Valid Java code
        java_code = "int count = 5;\nwhile (count > 0) {\n    count--;\n}"
        res_java = self.client.post("/api/flowchart/code-to-flowchart", json={"language": "java", "code": java_code}, headers=self.student_headers)
        self.assertEqual(res_java.status_code, 200)

    # --- 6. Natural Language AI Generation & Error Handling ---
    def test_06_ai_generation_handling(self):
        # Empty prompt -> 400
        res_empty = self.client.post("/api/flowchart/generate-ai", json={"prompt": ""}, headers=self.student_headers)
        self.assertEqual(res_empty.status_code, 400)

        # Too short prompt -> 400
        res_short = self.client.post("/api/flowchart/generate-ai", json={"prompt": "abc"}, headers=self.student_headers)
        self.assertEqual(res_short.status_code, 400)

    # --- 7. Automatic Layout: TB and LR ---
    def test_07_automatic_layout_directions(self):
        nodes = [
            {"id": "1", "type": "start", "label": "1"},
            {"id": "2", "type": "process", "label": "2"},
            {"id": "3", "type": "end", "label": "3"}
        ]
        edges = [
            {"id": "e1", "source": "1", "target": "2"},
            {"id": "e2", "source": "2", "target": "3"}
        ]

        # Top to Bottom: y increases
        tb_nodes = calculate_hierarchical_layout(nodes, edges, direction="TB")
        n1 = next(n for n in tb_nodes if n["id"] == "1")
        n2 = next(n for n in tb_nodes if n["id"] == "2")
        n3 = next(n for n in tb_nodes if n["id"] == "3")
        self.assertLess(n1["y"], n2["y"])
        self.assertLess(n2["y"], n3["y"])

        # Left to Right: x increases
        lr_nodes = calculate_hierarchical_layout(nodes, edges, direction="LR")
        lr1 = next(n for n in lr_nodes if n["id"] == "1")
        lr2 = next(n for n in lr_nodes if n["id"] == "2")
        lr3 = next(n for n in lr_nodes if n["id"] == "3")
        self.assertLess(lr1["x"], lr2["x"])
        self.assertLess(lr2["x"], lr3["x"])

    # --- 8. Persistence Lifecycle & Ownership Isolation ---
    def test_08_crud_and_ownership_isolation(self):
        # Student A saves diagram
        create_payload = {
            "title": "Alpha Private Diagram",
            "nodes": [{"id": "n1", "type": "start", "label": "Start"}],
            "edges": []
        }
        res_a = self.client.post("/api/flowchart/save", json=create_payload, headers=self.student_headers)
        self.assertEqual(res_a.status_code, 201)
        diag_id = res_a.get_json()["diagram_id"]

        # Student A can view
        get_a = self.client.get(f"/api/flowchart/{diag_id}", headers=self.student_headers)
        self.assertEqual(get_a.status_code, 200)

        # Student B attempts to view -> 403 Forbidden
        get_b = self.client.get(f"/api/flowchart/{diag_id}", headers=self.student_b_headers)
        self.assertEqual(get_b.status_code, 403)

        # Student B attempts to modify -> 403 Forbidden
        mod_b = self.client.post("/api/flowchart/save", json={"id": diag_id, "title": "Tampered"}, headers=self.student_b_headers)
        self.assertEqual(mod_b.status_code, 403)

        # Student B attempts to delete -> 403 Forbidden
        del_b = self.client.delete(f"/api/flowchart/{diag_id}", headers=self.student_b_headers)
        self.assertEqual(del_b.status_code, 403)

        # Student A duplicates
        dup_a = self.client.post(f"/api/flowchart/duplicate/{diag_id}", headers=self.student_headers)
        self.assertEqual(dup_a.status_code, 201)
        dup_id = dup_a.get_json()["diagram_id"]

        # Student A deletes both
        self.assertEqual(self.client.delete(f"/api/flowchart/{diag_id}", headers=self.student_headers).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/flowchart/{dup_id}", headers=self.student_headers).status_code, 200)

    # --- 9. Frontend Files & DOM Elements Integrity ---
    def test_09_frontend_dom_elements_exist(self):
        html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "flowchart-designer.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        required_ids = [
            "fcDiagramTitleInput", "fcStatusBadge", "fcBtnSave", "fcBtnNew",
            "fcBtnUndo", "fcBtnRedo", "fcBtnAutoArrange", "fcBtnZoomIn",
            "fcBtnZoomOut", "fcBtnZoomFit", "fcBtnExport", "fcBtnFullscreen",
            "fcDiagramSvg", "fcEdgesLayer", "fcNodesLayer", "fcGuidesLayer",
            "fcTempLayer", "fcMinimap", "fcRightPanel", "fcCodeModal", "fcAiModal"
        ]
        for req_id in required_ids:
            self.assertIn(f'id="{req_id}"', html, f"Missing DOM ID: {req_id}")

    # --- 10. Existing Application Unaffected ---
    def test_10_existing_pages_and_routes_unaffected(self):
        # Serve login
        res_login = self.client.get("/")
        self.assertEqual(res_login.status_code, 200)

        # Static files route
        res_css = self.client.get("/theme.css")
        self.assertEqual(res_css.status_code, 200)

        # Serve flowchart-designer.html
        res_fc = self.client.get("/flowchart-designer.html")
        self.assertEqual(res_fc.status_code, 200)


if __name__ == "__main__":
    unittest.main()
