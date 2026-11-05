import unittest
import json
import jwt
import re
from datetime import datetime, timezone
from app import app, db

class TestStudentPanelPrivacy(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = app.test_client()
        self.secret = app.config['SECRET_KEY']

        # Setup test data
        self.team_name = "Team Student Privacy Test"
        self.student_email = "student_priv@test.edu"
        self.student_usn = "1RV21CS999"
        self.student_name = "Alice Student"

        # Create or update team
        db.teams.update_one(
            {"team_name": self.team_name},
            {"$set": {
                "team_name": self.team_name,
                "leader_email": self.student_email,
                "leader_name": self.student_name,
                "leader_usn": self.student_usn,
                "members": [],
                "faculty_email": "guide_priv@test.edu",
                "faculty_name": "Prof Guide Priv",
                "project_idea": {"title": "Privacy Preserving Project"}
            }},
            upsert=True
        )

        self.student_token = jwt.encode(
            {"email": self.student_email, "role": "student", "usn": self.student_usn, "team_name": self.team_name},
            self.secret,
            algorithm="HS256"
        )
        self.coord_token = jwt.encode(
            {"email": "coord_priv@test.edu", "role": "coordinator"},
            self.secret,
            algorithm="HS256"
        )
        self.fac1_token = jwt.encode(
            {"email": "fac1_priv@test.edu", "role": "faculty", "name": "Faculty 1 Priv"},
            self.secret,
            algorithm="HS256"
        )
        self.fac2_token = jwt.encode(
            {"email": "fac2_priv@test.edu", "role": "faculty", "name": "Faculty 2 Priv"},
            self.secret,
            algorithm="HS256"
        )

    def tearDown(self):
        db.teams.delete_many({"team_name": self.team_name})
        db.panel_allocations.delete_many({"team_name": self.team_name})
        db.panel_evaluations.delete_many({"team_name": self.team_name})

    def test_student_sees_only_published_final_average(self):
        # 1. Coordinator allocates panel
        alloc_res = self.client.post(
            '/api/panel/allocate',
            headers={'Authorization': f'Bearer {self.coord_token}'},
            json={
                "panel_id": "Panel 3",
                "semester": 6,
                "phase": "Phase 1",
                "presentation_phase": "Phase 1",
                "room_number": "Room 303",
                "evaluation_deadline": "2026-12-31T23:59",
                "is_evaluation_enabled": True,
                "panel_member_emails": ["fac1_priv@test.edu", "fac2_priv@test.edu"],
                "team_assignments": [{
                    "team_name": self.team_name,
                    "assigned_faculty_emails": ["fac1_priv@test.edu", "fac2_priv@test.edu"]
                }]
            }
        )
        self.assertIn(alloc_res.status_code, [200, 201])
        alloc_data = alloc_res.get_json()
        alloc_id = alloc_data["allocations"][0]["allocation_id"]

        # Before submission/publication, student results should be empty
        res_before = self.client.get(
            '/api/panel/student/results',
            headers={'Authorization': f'Bearer {self.student_token}'}
        )
        self.assertEqual(res_before.status_code, 200)
        self.assertEqual(len(res_before.get_json().get("published_results", [])), 0)

        # 2. Faculty 1 submits 16/20
        sub1 = self.client.post(
            '/api/panel/evaluation/submit',
            headers={'Authorization': f'Bearer {self.fac1_token}'},
            json={
                "allocation_id": alloc_id,
                "final_marks": {self.student_usn: 16}
            }
        )
        self.assertEqual(sub1.status_code, 200)

        # 3. Faculty 2 submits 18/20
        sub2 = self.client.post(
            '/api/panel/evaluation/submit',
            headers={'Authorization': f'Bearer {self.fac2_token}'},
            json={
                "allocation_id": alloc_id,
                "final_marks": {self.student_usn: 18}
            }
        )
        self.assertEqual(sub2.status_code, 200)

        # Still unpublished -> student must not see it
        res_unpub = self.client.get(
            '/api/panel/student/results',
            headers={'Authorization': f'Bearer {self.student_token}'}
        )
        self.assertEqual(len(res_unpub.get_json().get("published_results", [])), 0)

        # 4. Coordinator finalizes and publishes
        fin = self.client.post(
            '/api/panel/evaluation/finalize',
            headers={'Authorization': f'Bearer {self.coord_token}'},
            json={"allocation_id": alloc_id, "publish": True}
        )
        self.assertEqual(fin.status_code, 200)

        # 5. Student now sees published average: (16 + 18) / 2 = 17.0
        res_pub = self.client.get(
            '/api/panel/student/results',
            headers={'Authorization': f'Bearer {self.student_token}'}
        )
        self.assertEqual(res_pub.status_code, 200)
        data = res_pub.get_json()
        self.assertTrue(data.get("success"))
        results = data.get("published_results")
        self.assertEqual(len(results), 1)

        result_item = results[0]
        self.assertEqual(result_item["phase"], "Phase 1")
        self.assertEqual(result_item["semester"], 6)
        self.assertEqual(result_item["team_phase_average"], 17.0)

        # STRICT PRIVACY CHECKS:
        # No evaluator names
        raw_text = json.dumps(result_item)
        self.assertNotIn("fac1_priv", raw_text)
        self.assertNotIn("fac2_priv", raw_text)
        self.assertNotIn("Faculty 1 Priv", raw_text)
        self.assertNotIn("Faculty 2 Priv", raw_text)
        # No criteria breakdown
        self.assertNotIn("rubric", raw_text.lower())
        self.assertNotIn("criteria", raw_text.lower())
        # No individual faculty marks 16 or 18 as individual components
        student_avgs = result_item["student_averages"]
        self.assertEqual(len(student_avgs), 1)
        self.assertEqual(student_avgs[0]["usn"], self.student_usn)
        self.assertEqual(student_avgs[0]["final_average"], 17.0)
        self.assertNotIn("individual_marks", student_avgs[0])

    def test_student_cannot_access_panel_evaluation_api_directly(self):
        # Create a real allocation
        alloc_res = self.client.post(
            '/api/panel/allocate',
            headers={'Authorization': f'Bearer {self.coord_token}'},
            json={
                "panel_id": "Panel 3",
                "semester": 6,
                "phase": "Phase 1",
                "room_number": "Room 303",
                "evaluation_deadline": "2026-12-31T23:59",
                "is_evaluation_enabled": True,
                "panel_member_emails": ["fac1_priv@test.edu"],
                "team_assignments": [{
                    "team_name": self.team_name,
                    "assigned_faculty_emails": ["fac1_priv@test.edu"]
                }]
            }
        )
        alloc_id = alloc_res.get_json()["allocation_id"]

        # Direct call by student to evaluator endpoint must return 403 Forbidden
        res = self.client.get(
            f'/api/panel/evaluation/{alloc_id}',
            headers={'Authorization': f'Bearer {self.student_token}'}
        )
        self.assertEqual(res.status_code, 403)

if __name__ == '__main__':
    unittest.main()
