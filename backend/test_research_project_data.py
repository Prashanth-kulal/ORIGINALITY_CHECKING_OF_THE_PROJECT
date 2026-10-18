import unittest
from unittest.mock import patch

import jwt
from bson import ObjectId

import app as backend_app


class FakeCollection:
    def __init__(self, documents=None, fail=False):
        self.documents = documents or []
        self.fail = fail

    def find(self, query=None, projection=None):
        if self.fail:
            raise RuntimeError("database unavailable")
        query = query or {}
        team_name = query.get("team_name")
        matches = [
            dict(document) for document in self.documents
            if not team_name or document.get("team_name") == team_name
        ]
        if projection and projection.get("_id") == 0:
            for document in matches:
                document.pop("_id", None)
        return matches

    def find_one(self, query, projection=None):
        if "$or" in query:
            for document in self.documents:
                for condition in query["$or"]:
                    if condition.get("leader_email") == document.get("leader_email"):
                        return dict(document)
                    if condition.get("members.email") == document.get("leader_email"):
                        return dict(document)
                    if condition.get("members", {}).get("$in") == document.get("members"):
                        return dict(document)
                    requested_email = condition.get("leader_email")
                    if requested_email and any(
                        isinstance(member, dict) and member.get("email") == requested_email
                        for member in document.get("members", [])
                    ):
                        return dict(document)
            return None

        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return dict(document)
        return None


class FakeDatabase:
    def __init__(self, teams, projects, papers=None):
        self.teams = FakeCollection(teams)
        self.projects = FakeCollection(projects)
        self.research_papers = FakeCollection(papers)


class ResearchProjectDataTests(unittest.TestCase):
    def setUp(self):
        self.original_db = backend_app.db
        backend_app.app.config.update(TESTING=True, SECRET_KEY="research-test-secret")
        self.project_id = ObjectId("65a000000000000000000002")
        self.team = {
            "_id": ObjectId("65a000000000000000000010"),
            "team_name": "Research Team",
            "leader_email": "student@example.test",
            "leader_name": "Student One",
            "leader_usn": "USN001",
            "members": [{"name": "Student Two", "usn": "USN002", "email": "member@example.test"}],
            "faculty_name": "Guide One",
            "faculty_email": "guide@example.test",
            "project_idea": {
                "title": "Current Project",
                "description": "Current project description",
                "abstract": "Current project abstract",
                "technologies": ["Python"],
                "domain": "Data Science",
                "status": "Approved"
            },
            "project_ideas": [
                {
                    "title": "Old Project",
                    "description": "Old project description",
                    "status": "Rejected"
                }
            ]
        }
        self.projects = [
            {
                "_id": ObjectId("65a000000000000000000001"),
                "team_name": "Research Team",
                "title": "Old Project",
                "description": "Old project description",
                "status": "Rejected"
            },
            {
                "_id": self.project_id,
                "team_name": "Research Team",
                "title": "Current Project",
                "description": "Approved project description",
                "abstract": "Current project abstract",
                "technologies": "Python, Flask",
                "status": "Approved"
            }
        ]
        backend_app.db = FakeDatabase([self.team], self.projects)
        self.client = backend_app.app.test_client()

    def tearDown(self):
        backend_app.db = self.original_db

    def token(self, email, role):
        return jwt.encode(
            {"email": email, "role": role},
            backend_app.app.config["SECRET_KEY"],
            algorithm="HS256"
        )

    def get_team_data(self, role="team", email="student@example.test", path="/api/research/team-data"):
        return self.client.get(
            path,
            headers={"Authorization": f"Bearer {self.token(email, role)}"}
        )

    def test_team_data_uses_matching_project_and_stringifies_object_ids(self):
        response = self.get_team_data()

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        project = data["project_info"]
        self.assertEqual(project["project_id"], str(self.project_id))
        self.assertEqual(project["title"], "Current Project")
        self.assertEqual(project["description"], "Current project description")
        self.assertEqual(project["status"], "Approved")
        self.assertEqual(project["technologies"], ["Python"])
        self.assertEqual(data["team_id"], str(self.team["_id"]))
        self.assertEqual(data["students"][1]["display_name"], "Student Two (USN002)")
        self.assertEqual(data["guide"]["name"], "Guide One")

    def test_student_cannot_select_another_team_by_name(self):
        other_team = dict(self.team, team_name="Private Team", leader_email="other@example.test")
        backend_app.db.teams = FakeCollection([self.team, other_team])

        response = self.get_team_data(path="/api/research/team-data/Private%20Team")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["team_name"], "Research Team")

    def test_faculty_must_be_assigned_to_the_selected_team(self):
        response = self.get_team_data(
            role="faculty",
            email="unassigned@example.test",
            path="/api/research/team-data/Research%20Team"
        )

        self.assertEqual(response.status_code, 404)

    def test_missing_optional_project_fields_are_returned_as_empty_values(self):
        self.team["project_idea"] = {"title": "Minimal Project"}
        backend_app.db.projects = FakeCollection([])

        response = self.get_team_data()

        self.assertEqual(response.status_code, 200)
        project = response.get_json()["project_info"]
        self.assertEqual(project["title"], "Minimal Project")
        self.assertEqual(project["description"], "")
        self.assertEqual(project["abstract"], "")
        self.assertEqual(project["technologies"], [])
        self.assertEqual(project["keywords"], [])

    def test_no_project_returns_clear_not_found_response(self):
        self.team["project_idea"] = {}
        self.team["project_ideas"] = []
        backend_app.db.projects = FakeCollection([])

        response = self.get_team_data()

        self.assertEqual(response.status_code, 404)
        self.assertIn("No project details", response.get_json()["error"])

    def test_database_failure_is_reported_as_server_error(self):
        backend_app.db.projects = FakeCollection(fail=True)

        response = self.get_team_data()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"], "Failed to fetch project research data")

    def test_recommendations_use_the_same_current_project_record(self):
        with patch.object(backend_app, "search_openalex_papers_internal", return_value=[]), patch.object(
            backend_app, "extract_project_keywords_direct", return_value=["current project"]
        ) as keyword_extractor:
            response = self.client.get(
                "/api/research/recommendations",
                headers={"Authorization": f"Bearer {self.token('student@example.test', 'team')}"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["project_title"], "Current Project")
        keyword_extractor.assert_called_once()
        self.assertEqual(keyword_extractor.call_args.args[0]["title"], "Current Project")

    def test_team_data_with_student_role(self):
        response = self.get_team_data(role="student", email="student@example.test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["team_name"], "Research Team")


if __name__ == "__main__":
    unittest.main()
