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


if __name__ == "__main__":
    unittest.main()

