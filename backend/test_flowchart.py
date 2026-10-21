import unittest
from backend.flowchart_engine import (
    parse_python_code,
    parse_java_code,
    validate_diagram_data,
    calculate_hierarchical_layout
)


class TestFlowchartEngine(unittest.TestCase):

    def test_python_sequential(self):
        code = "x = 10\ny = 20\nprint(x + y)"
        res = parse_python_code(code)
        self.assertIn("nodes", res)
        self.assertIn("edges", res)
        # Check start and end nodes exist
        types = [n["type"] for n in res["nodes"]]
        self.assertIn("start", types)
        self.assertIn("end", types)
        self.assertIn("inputoutput", types)

    def test_python_if_else(self):
        code = """
score = 85
if score >= 50:
    print("Passed")
else:
    print("Failed")
"""
        res = parse_python_code(code)
        types = [n["type"] for n in res["nodes"]]
        self.assertIn("decision", types)
        # Decision must have outgoing Yes and No edges
        labels = [e["label"] for e in res["edges"]]
        self.assertIn("Yes", labels)
        self.assertIn("No", labels)

    def test_python_while_loop(self):
        code = """
count = 0
while count < 5:
    count += 1
print("Done")
"""
        res = parse_python_code(code)
        types = [n["type"] for n in res["nodes"]]
        self.assertIn("decision", types)
        labels = [e["label"] for e in res["edges"]]
        self.assertIn("Loop", labels)

    def test_python_for_loop(self):
        code = """
total = 0
for i in [1, 2, 3]:
    total += i
"""
        res = parse_python_code(code)
        types = [n["type"] for n in res["nodes"]]
        self.assertIn("decision", types)
        labels = [e["label"] for e in res["edges"]]
        self.assertIn("Next item", labels)

    def test_python_invalid_syntax(self):
        code = "if x > : print('bad')"
        with self.assertRaises(ValueError) as ctx:
            parse_python_code(code)
        self.assertIn("Syntax Error", str(ctx.exception))

    def test_java_parsing(self):
        code = """
public class Check {
    public static void main(String[] args) {
        int x = 10;
        if (x > 5) {
            System.out.println("Greater");
        } else {
            System.out.println("Lesser");
        }
    }
}
"""
        res = parse_java_code(code)
        types = [n["type"] for n in res["nodes"]]
        self.assertIn("start", types)
        self.assertIn("decision", types)
        self.assertIn("inputoutput", types)
        labels = [e["label"] for e in res["edges"]]
        self.assertIn("Yes", labels)
        self.assertIn("No", labels)

    def test_diagram_validation(self):
        valid_payload = {
            "title": "My Flowchart",
            "nodes": [
                {"id": "n1", "type": "start", "label": "Start", "x": 100, "y": 100},
                {"id": "n2", "type": "end", "label": "End", "x": 100, "y": 250}
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "label": ""}
            ]
        }
        is_valid, sanitized, msg = validate_diagram_data(valid_payload)
        self.assertTrue(is_valid)
        self.assertEqual(len(sanitized["nodes"]), 2)
        self.assertEqual(len(sanitized["edges"]), 1)

    def test_diagram_validation_rejects_broken_edges(self):
        broken_payload = {
            "title": "Broken",
            "nodes": [
                {"id": "n1", "type": "start", "label": "Start", "x": 100, "y": 100}
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "non_existent_node", "label": ""}
            ]
        }
        is_valid, sanitized, msg = validate_diagram_data(broken_payload)
        self.assertTrue(is_valid)
        # Edge to non_existent_node must be dropped for graph safety
        self.assertEqual(len(sanitized["edges"]), 0)

    def test_diagram_validation_with_bend_points_and_ports(self):
        payload = {
            "title": "Bend Points Test",
            "nodes": [
                {"id": "n1", "type": "start", "label": "Start", "x": 100, "y": 100},
                {"id": "n2", "type": "process", "label": "Step 1", "x": 300, "y": 200}
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "n1",
                    "target": "n2",
                    "label": "Flow",
                    "type": "orthogonal",
                    "sourcePort": "right",
                    "targetPort": "top",
                    "points": [
                        {"x": 200, "y": 100},
                        {"x": 200, "y": 160},
                        {"x": 300, "y": 160}
                    ]
                }
            ]
        }
        is_valid, sanitized, msg = validate_diagram_data(payload)
        self.assertTrue(is_valid)
        edge = sanitized["edges"][0]
        self.assertEqual(edge["sourcePort"], "right")
        self.assertEqual(edge["targetPort"], "top")
        self.assertEqual(len(edge["points"]), 3)
        self.assertEqual(edge["points"][0], {"x": 200.0, "y": 100.0})
        self.assertEqual(edge["points"][1], {"x": 200.0, "y": 160.0})
        self.assertEqual(edge["points"][2], {"x": 300.0, "y": 160.0})

    def test_diagram_validation_backward_compatibility_without_bend_points(self):
        # Legacy payload without points, sourcePort, or targetPort
        legacy_payload = {
            "title": "Legacy Diagram",
            "nodes": [
                {"id": "n1", "type": "start", "label": "Start", "x": 100, "y": 100},
                {"id": "n2", "type": "end", "label": "End", "x": 100, "y": 300}
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "label": ""}
            ]
        }
        is_valid, sanitized, msg = validate_diagram_data(legacy_payload)
        self.assertTrue(is_valid)
        edge = sanitized["edges"][0]
        self.assertIn("points", edge)
        self.assertEqual(edge["points"], [])
        self.assertIsNone(edge["sourcePort"])
        self.assertIsNone(edge["targetPort"])

    def test_diagram_validation_sanitizes_invalid_bend_points(self):
        payload = {
            "title": "Sanitize Test",
            "nodes": [
                {"id": "n1", "type": "start", "label": "Start", "x": 100, "y": 100},
                {"id": "n2", "type": "end", "label": "End", "x": 100, "y": 300}
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "n1",
                    "target": "n2",
                    "points": [
                        {"x": "150.5", "y": "220"},
                        {"bad": "format"},
                        None,
                        "string",
                        {"x": 99999999, "y": 100}  # out of bounds
                    ]
                }
            ]
        }
        is_valid, sanitized, msg = validate_diagram_data(payload)
        self.assertTrue(is_valid)
        edge = sanitized["edges"][0]
        # Only the valid float-convertible coordinate should be kept
        self.assertEqual(len(edge["points"]), 1)
        self.assertEqual(edge["points"][0], {"x": 150.5, "y": 220.0})

    def test_hierarchical_layout(self):
        nodes = [
            {"id": "n1", "type": "start", "label": "Start"},
            {"id": "n2", "type": "process", "label": "Step 1"},
            {"id": "n3", "type": "end", "label": "End"}
        ]
        edges = [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"}
        ]
        laid_out = calculate_hierarchical_layout(nodes, edges, direction="TB")
        n1 = next(n for n in laid_out if n["id"] == "n1")
        n2 = next(n for n in laid_out if n["id"] == "n2")
        n3 = next(n for n in laid_out if n["id"] == "n3")
        self.assertLess(n1["y"], n2["y"])
        self.assertLess(n2["y"], n3["y"])


import jwt
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from backend.app import app, db


class TestFlowchartAPI(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = app.test_client()
        self.secret = app.config["SECRET_KEY"]

        # Student token
        student_payload = {
            "email": "student_flow@test.edu",
            "usn": "1MS21CS001",
            "name": "Flowchart Tester",
            "role": "student",
            "team_name": "Alpha Flow",
            "exp": datetime.now(timezone.utc) + timedelta(hours=2)
        }
        self.student_token = jwt.encode(student_payload, self.secret, algorithm="HS256")
        self.student_headers = {"Authorization": f"Bearer {self.student_token}"}

        # Another student token (for ownership isolation test)
        other_payload = {
            "email": "intruder@test.edu",
            "usn": "1MS21CS999",
            "name": "Intruder",
            "role": "student",
            "team_name": "Other Team",
            "exp": datetime.now(timezone.utc) + timedelta(hours=2)
        }
        self.other_token = jwt.encode(other_payload, self.secret, algorithm="HS256")
        self.other_headers = {"Authorization": f"Bearer {self.other_token}"}

        # Faculty token (should be blocked)
        faculty_payload = {
            "email": "prof@test.edu",
            "name": "Dr. Smith",
            "role": "faculty",
            "exp": datetime.now(timezone.utc) + timedelta(hours=2)
        }
        self.faculty_token = jwt.encode(faculty_payload, self.secret, algorithm="HS256")
        self.faculty_headers = {"Authorization": f"Bearer {self.faculty_token}"}

    def test_student_only_access(self):
        # Missing token -> 401
        res = self.client.get("/api/flowchart/list")
        self.assertEqual(res.status_code, 401)

        # Faculty token -> 403 Forbidden
        res = self.client.get("/api/flowchart/list", headers=self.faculty_headers)
        self.assertEqual(res.status_code, 403)

        # Student token -> 200 OK
        res = self.client.get("/api/flowchart/list", headers=self.student_headers)
        self.assertEqual(res.status_code, 200)

    def test_save_list_get_update_duplicate_delete_workflow(self):
        # 1. Save new diagram
        payload = {
            "title": "Sorting Algorithm Flowchart",
            "description": "Visualizing bubble sort",
            "nodes": [
                {"id": "n1", "type": "start", "label": "Start", "x": 100, "y": 50},
                {"id": "n2", "type": "process", "label": "Init array", "x": 100, "y": 150},
                {"id": "n3", "type": "end", "label": "End", "x": 100, "y": 250}
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "label": ""},
                {"id": "e2", "source": "n2", "target": "n3", "label": ""}
            ]
        }
        save_res = self.client.post("/api/flowchart/save", json=payload, headers=self.student_headers)
        self.assertEqual(save_res.status_code, 201)
        save_data = save_res.get_json()
        diagram_id = save_data["diagram_id"]
        self.assertTrue(diagram_id)

        # 2. List diagrams
        list_res = self.client.get("/api/flowchart/list", headers=self.student_headers)
        self.assertEqual(list_res.status_code, 200)
        items = list_res.get_json()["diagrams"]
        found = any(d["id"] == diagram_id for d in items)
        self.assertTrue(found)

        # 3. Get diagram
        get_res = self.client.get(f"/api/flowchart/{diagram_id}", headers=self.student_headers)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.get_json()["diagram"]["title"], "Sorting Algorithm Flowchart")

        # 4. Ownership protection: other student cannot read or modify
        other_get = self.client.get(f"/api/flowchart/{diagram_id}", headers=self.other_headers)
        self.assertEqual(other_get.status_code, 403)

        other_update = self.client.post("/api/flowchart/save", json={"id": diagram_id, "title": "Hacked"}, headers=self.other_headers)
        self.assertEqual(other_update.status_code, 403)

        other_del = self.client.delete(f"/api/flowchart/{diagram_id}", headers=self.other_headers)
        self.assertEqual(other_del.status_code, 403)

        # 5. Update diagram
        update_payload = dict(payload)
        update_payload["id"] = diagram_id
        update_payload["title"] = "Updated Bubble Sort"
        update_res = self.client.post("/api/flowchart/save", json=update_payload, headers=self.student_headers)
        self.assertEqual(update_res.status_code, 200)

        # 6. Duplicate diagram
        dup_res = self.client.post(f"/api/flowchart/duplicate/{diagram_id}", headers=self.student_headers)
        self.assertEqual(dup_res.status_code, 201)
        dup_id = dup_res.get_json()["diagram_id"]
        self.assertNotEqual(dup_id, diagram_id)

        # 7. Delete original and duplicate
        del_res = self.client.delete(f"/api/flowchart/{diagram_id}", headers=self.student_headers)
        self.assertEqual(del_res.status_code, 200)
        del_dup = self.client.delete(f"/api/flowchart/{dup_id}", headers=self.student_headers)
        self.assertEqual(del_dup.status_code, 200)

    def test_code_to_flowchart_python(self):
        py_code = """
total = 0
for i in range(10):
    total += i
print(total)
"""
        res = self.client.post("/api/flowchart/code-to-flowchart", json={"language": "python", "code": py_code}, headers=self.student_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertGreater(len(data["nodes"]), 0)

    def test_code_to_flowchart_invalid_syntax(self):
        bad_code = "def foo( invalid"
        res = self.client.post("/api/flowchart/code-to-flowchart", json={"language": "python", "code": bad_code}, headers=self.student_headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.get_json())

    def test_code_to_flowchart_java(self):
        java_code = """
int val = 42;
if (val > 10) {
    System.out.println("Greater");
} else {
    System.out.println("Smaller");
}
"""
        res = self.client.post("/api/flowchart/code-to-flowchart", json={"language": "java", "code": java_code}, headers=self.student_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])

    def test_auto_layout_endpoint(self):
        nodes = [
            {"id": "a", "type": "start", "label": "Start"},
            {"id": "b", "type": "process", "label": "Process"},
            {"id": "c", "type": "end", "label": "End"}
        ]
        edges = [
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "c"}
        ]
        res = self.client.post("/api/flowchart/auto-layout", json={"nodes": nodes, "edges": edges, "direction": "LR"}, headers=self.student_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["direction"], "LR")
        self.assertEqual(len(data["nodes"]), 3)

    @patch("backend.app.call_gemini_generic_prompt")
    def test_ai_generation_valid(self, mock_gemini):
        mock_gemini.return_value = """
{
  "title": "Online Order Process",
  "nodes": [
    {"id": "n1", "type": "start", "label": "Start"},
    {"id": "n2", "type": "process", "label": "Select Items"},
    {"id": "n3", "type": "decision", "label": "In Stock?"},
    {"id": "n4", "type": "process", "label": "Checkout"},
    {"id": "n5", "type": "end", "label": "End"}
  ],
  "edges": [
    {"id": "e1", "source": "n1", "target": "n2", "label": ""},
    {"id": "e2", "source": "n2", "target": "n3", "label": ""},
    {"id": "e3", "source": "n3", "target": "n4", "label": "Yes"},
    {"id": "e4", "source": "n4", "target": "n5", "label": ""},
    {"id": "e5", "source": "n3", "target": "n5", "label": "No"}
  ]
}
"""
        res = self.client.post("/api/flowchart/generate-ai", json={"prompt": "User selects items, checks stock, and checks out"}, headers=self.student_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["diagram"]["title"], "Online Order Process")
        self.assertEqual(len(data["diagram"]["nodes"]), 5)

    @patch("backend.app.call_gemini_generic_prompt")
    def test_ai_generation_handles_malformed_gracefully(self, mock_gemini):
        mock_gemini.return_value = "Sorry, I cannot answer this request."
        res = self.client.post("/api/flowchart/generate-ai", json={"prompt": "Some flow"}, headers=self.student_headers)
        self.assertEqual(res.status_code, 422)
        self.assertIn("error", res.get_json())

    def test_save_and_retrieve_diagram_with_bend_points(self):
        payload = {
            "title": "Diagram with Custom Turns",
            "description": "Multi-segment connector test",
            "nodes": [
                {"id": "n1", "type": "start", "label": "Start", "x": 120, "y": 80},
                {"id": "n2", "type": "process", "label": "Execute", "x": 400, "y": 280}
            ],
            "edges": [
                {
                    "id": "e_bend",
                    "source": "n1",
                    "target": "n2",
                    "sourcePort": "right",
                    "targetPort": "top",
                    "type": "orthogonal",
                    "label": "Process Flow",
                    "points": [
                        {"x": 280, "y": 80},
                        {"x": 280, "y": 200},
                        {"x": 400, "y": 200}
                    ]
                }
            ]
        }

        # 1. Save diagram
        save_res = self.client.post("/api/flowchart/save", json=payload, headers=self.student_headers)
        self.assertEqual(save_res.status_code, 201)
        diag_id = save_res.get_json()["diagram_id"]

        # 2. Re-fetch diagram and check points and ports are preserved
        get_res = self.client.get(f"/api/flowchart/{diag_id}", headers=self.student_headers)
        self.assertEqual(get_res.status_code, 200)
        diag = get_res.get_json()["diagram"]
        self.assertEqual(len(diag["edges"]), 1)
        saved_edge = diag["edges"][0]
        self.assertEqual(saved_edge["sourcePort"], "right")
        self.assertEqual(saved_edge["targetPort"], "top")
        self.assertEqual(len(saved_edge["points"]), 3)
        self.assertEqual(saved_edge["points"][0], {"x": 280.0, "y": 80.0})
        self.assertEqual(saved_edge["points"][1], {"x": 280.0, "y": 200.0})
        self.assertEqual(saved_edge["points"][2], {"x": 400.0, "y": 200.0})

        # 3. Clean up
        self.client.delete(f"/api/flowchart/{diag_id}", headers=self.student_headers)

    def test_backward_compatible_loading_older_diagram_without_points(self):
        # Directly insert older format diagram without points into DB
        if db is not None:
            legacy_id = f"legacy_diag_{Date_now}" if "Date_now" in dir() else "legacy_diag_99999"
            doc = {
                "diagram_id": legacy_id,
                "title": "Ancient Diagram",
                "owner_email": "student_flow@test.edu",
                "owner_name": "Flowchart Tester",
                "owner_usn": "1MS21CS001",
                "team_name": "Alpha Flow",
                "nodes": [
                    {"id": "n1", "type": "start", "label": "Start", "x": 100, "y": 100},
                    {"id": "n2", "type": "end", "label": "End", "x": 100, "y": 250}
                ],
                "edges": [
                    {"id": "e_old", "source": "n1", "target": "n2", "label": ""}
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 1.0},
                "layout": {"direction": "TB"},
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            db.flowcharts.insert_one(doc)

            get_res = self.client.get(f"/api/flowchart/{legacy_id}", headers=self.student_headers)
            self.assertEqual(get_res.status_code, 200)
            loaded_edge = get_res.get_json()["diagram"]["edges"][0]
            # Must safely load without crashing and have default empty points or None ports
            self.assertIn("points", loaded_edge)
            self.assertEqual(loaded_edge["points"], [])

            db.flowcharts.delete_one({"diagram_id": legacy_id})


if __name__ == "__main__":
    unittest.main()

