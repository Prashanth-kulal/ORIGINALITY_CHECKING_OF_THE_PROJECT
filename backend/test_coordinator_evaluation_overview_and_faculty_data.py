import pytest
import json
import jwt
from app import app, db

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def coordinator_token():
    payload = {
        "email": "coordinator@admin.com",
        "role": "coordinator",
        "name": "Admin Coordinator"
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

@pytest.fixture
def faculty_evaluator1_token():
    payload = {
        "email": "evaluator1@test.edu",
        "role": "faculty",
        "name": "Prof. Evaluator One"
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

@pytest.fixture
def faculty_evaluator2_token():
    payload = {
        "email": "evaluator2@test.edu",
        "role": "faculty",
        "name": "Prof. Evaluator Two"
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

@pytest.fixture
def faculty_guide_token():
    payload = {
        "email": "guidedprof@test.edu",
        "role": "faculty",
        "name": "Dr. Guided Prof"
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

class TestCoordinatorOverviewAndFacultyData:

    def setup_method(self):
        # Cleanup
        db.panel_allocations.delete_many({"team_name": {"$in": ["OVERVIEW_TEAM_1", "OVERVIEW_TEAM_2"]}})
        db.teams.delete_many({"team_name": {"$in": ["OVERVIEW_TEAM_1", "OVERVIEW_TEAM_2"]}})
        db.panel_evaluations.delete_many({"team_name": {"$in": ["OVERVIEW_TEAM_1", "OVERVIEW_TEAM_2"]}})
        db.faculty.delete_many({"email": {"$in": ["evaluator1@test.edu", "evaluator2@test.edu", "guidedprof@test.edu"]}})

        # Setup faculty
        db.faculty.insert_many([
            {"email": "evaluator1@test.edu", "name": "Prof. Evaluator One", "role": "faculty"},
            {"email": "evaluator2@test.edu", "name": "Prof. Evaluator Two", "role": "faculty"},
            {"email": "guidedprof@test.edu", "name": "Dr. Guided Prof", "role": "faculty"}
        ])

        # Setup teams
        db.teams.insert_many([
            {
                "team_name": "OVERVIEW_TEAM_1",
                "team_id": "OV-TEAM-01",
                "project_title": "Smart Grid Energy Optimizer",
                "semester": "6th Sem",
                "department": "CSE",
                "faculty_email": "guidedprof@test.edu",
                "faculty_name": "Dr. Guided Prof",
                "leader_name": "Student A",
                "leader_usn": "1MS21CS101",
                "members": [
                    {"name": "Student B", "usn": "1MS21CS102", "role": "Member"}
                ],
                "project_idea": {
                    "title": "Smart Grid Energy Optimizer",
                    "status": "Approved"
                }
            },
            {
                "team_name": "OVERVIEW_TEAM_2",
                "team_id": "OV-TEAM-02",
                "project_title": "Blockchain Identity Vault",
                "semester": "6th Sem",
                "department": "CSE",
                "faculty_email": "evaluator2@test.edu",
                "faculty_name": "Prof. Evaluator Two",
                "leader_name": "Student C",
                "leader_usn": "1MS21CS201",
                "members": [
                    {"name": "Student D", "usn": "1MS21CS202", "role": "Member"}
                ],
                "project_idea": {
                    "title": "Blockchain Identity Vault",
                    "status": "Approved"
                }
            }
        ])

        # Setup panel allocations:
        # OVERVIEW_TEAM_1 is assigned ONLY to evaluator1@test.edu in Panel 1
        db.panel_allocations.insert_one({
            "allocation_id": "alloc_ov_team_1_p1_sem6_phase1",
            "panel_id": "Panel 1",
            "panel_name": "Panel 1",
            "team_name": "OVERVIEW_TEAM_1",
            "project_title": "Smart Grid Energy Optimizer",
            "semester": 6,
            "phase": "Phase 1",
            "phase_name": "Phase 1 - Synopsis & Problem Definition",
            "max_marks": 20,
            "room_number": "Seminar Hall A",
            "evaluation_deadline": "2026-11-30T18:00",
            "guide": {
                "email": "guidedprof@test.edu",
                "name": "Dr. Guided Prof",
                "role": "guide"
            },
            "panel_members": [
                {"email": "evaluator1@test.edu", "name": "Prof. Evaluator One", "role": "member_1"},
                {"email": "evaluator2@test.edu", "name": "Prof. Evaluator Two", "role": "member_2"}
            ],
            "assigned_faculty_emails": ["evaluator1@test.edu"], # EXPLICITLY assigned ONLY to evaluator1
            "is_evaluation_enabled": True,
            "status": "Active",
            "is_finalized": False,
            "is_published": False
        })

        # Add submitted evaluation for OVERVIEW_TEAM_1 by evaluator1
        db.panel_evaluations.insert_one({
            "allocation_id": "alloc_ov_team_1_p1_sem6_phase1",
            "team_name": "OVERVIEW_TEAM_1",
            "faculty_email": "evaluator1@test.edu",
            "faculty_name": "Prof. Evaluator One",
            "final_marks": {
                "1MS21CS101": 18.5,
                "1MS21CS102": 19.0
            },
            "submitted_total": 18.75,
            "status": "Submitted"
        })

    def teardown_method(self):
        db.panel_allocations.delete_many({"team_name": {"$in": ["OVERVIEW_TEAM_1", "OVERVIEW_TEAM_2"]}})
        db.teams.delete_many({"team_name": {"$in": ["OVERVIEW_TEAM_1", "OVERVIEW_TEAM_2"]}})
        db.panel_evaluations.delete_many({"team_name": {"$in": ["OVERVIEW_TEAM_1", "OVERVIEW_TEAM_2"]}})
        db.faculty.delete_many({"email": {"$in": ["evaluator1@test.edu", "evaluator2@test.edu", "guidedprof@test.edu"]}})

    def test_01_coordinator_allocations_endpoint_returns_consistent_evaluator_fields_and_averages(self, client, coordinator_token):
        """Issue 1 Test: /api/panel/allocations returns evaluators_progress with faculty_name and student_averages mapping."""
        res = client.get('/api/panel/allocations', headers={"Authorization": f"Bearer {coordinator_token}"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        allocs = data["allocations"]
        
        target = next((a for a in allocs if a.get("team_name") == "OVERVIEW_TEAM_1"), None)
        assert target is not None

        # Evaluator progress must have faculty_name, faculty_email, submitted_total, and status
        evaluators = target.get("evaluators_progress", [])
        assert len(evaluators) == 1
        ev = evaluators[0]
        assert ev["faculty_email"] == "evaluator1@test.edu"
        assert ev["faculty_name"] == "Prof. Evaluator One"
        assert ev["is_submitted"] is True
        assert ev["status"] == "Submitted"
        assert ev["submitted_total"] is not None

        # Student averages must be directly mapped by USN without treating missing marks as zero
        st_avgs = target.get("student_averages", {})
        assert isinstance(st_avgs, dict)
        assert st_avgs.get("1MS21CS101") == 18.5
        assert st_avgs.get("1MS21CS102") == 19.0

        # Filtering by panel, semester, and phase works
        res_filtered = client.get('/api/panel/allocations?panel_id=Panel%201&semester=6&phase=Phase%201',
                                  headers={"Authorization": f"Bearer {coordinator_token}"})
        assert res_filtered.status_code == 200
        filtered_allocs = res_filtered.get_json()["allocations"]
        assert any(a.get("team_name") == "OVERVIEW_TEAM_1" for a in filtered_allocs)

    def test_02_faculty_sees_only_explicitly_assigned_teams_in_panel_evaluations(self, client, faculty_evaluator1_token, faculty_evaluator2_token):
        """Issue 2 Test: Evaluator 1 sees OVERVIEW_TEAM_1, but Evaluator 2 is NOT assigned and does not see it."""
        # Evaluator 1 is explicitly assigned to OVERVIEW_TEAM_1
        res1 = client.get('/api/panel/faculty/assignments', headers={"Authorization": f"Bearer {faculty_evaluator1_token}"})
        assert res1.status_code == 200
        assigns1 = res1.get_json()
        assert any(a.get("team_name") == "OVERVIEW_TEAM_1" for a in assigns1)

        # Evaluator 2 is a panel member on Panel 1, but NOT in assigned_faculty_emails for OVERVIEW_TEAM_1
        res2 = client.get('/api/panel/faculty/assignments', headers={"Authorization": f"Bearer {faculty_evaluator2_token}"})
        assert res2.status_code == 200
        assigns2 = res2.get_json()
        assert not any(a.get("team_name") == "OVERVIEW_TEAM_1" for a in assigns2)

    def test_03_guide_panel_teams_endpoint_returns_guided_teams_with_evaluator_totals_and_no_criteria(self, client, faculty_guide_token):
        """Issue 2 Test: /api/panel/guide/teams returns teams list with evaluator final marks without criterion breakdown."""
        res = client.get('/api/panel/guide/teams', headers={"Authorization": f"Bearer {faculty_guide_token}"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        
        # Must return teams key matching frontend expectations
        teams = data.get("teams", [])
        assert len(teams) >= 1
        g_team = next((t for t in teams if t.get("team_name") == "OVERVIEW_TEAM_1"), None)
        assert g_team is not None
        assert g_team["project_title"] == "Smart Grid Energy Optimizer"
        assert g_team["semester"] == 6
        assert g_team["phase"] == "Phase 1"

        # Evaluators list contains final mark per student
        evals = g_team.get("evaluators", [])
        assert len(evals) >= 1
        ev1 = next((e for e in evals if e.get("email") == "evaluator1@test.edu"), None)
        assert ev1 is not None
        assert ev1["is_submitted"] is True
        assert ev1["student_totals"]["1MS21CS101"] == 18.5
        assert ev1["student_totals"]["1MS21CS102"] == 19.0
        # Absolutely NO criteria breakdown returned
        assert "criteria" not in ev1
        assert "rubric" not in ev1

        # Student averages out of 20
        assert g_team["student_averages"]["1MS21CS101"] == 18.5
        assert g_team["student_averages"]["1MS21CS102"] == 19.0

    def test_04_faculty_evaluation_marksheet_shows_only_student_marks_out_of_20_and_no_other_evaluators(self, client, faculty_evaluator1_token):
        """Issue 2 Test: Evaluator opening marksheet sees simple student name, USN, and one mark /20."""
        alloc_id = "alloc_ov_team_1_p1_sem6_phase1"
        res = client.get(f'/api/panel/evaluation/{alloc_id}', headers={"Authorization": f"Bearer {faculty_evaluator1_token}"})
        assert res.status_code == 200
        sheet = res.get_json()
        
        # Max marks is 20
        assert sheet["allocation"]["max_marks"] == 20
        assert len(sheet["students"]) == 2
        
        # Regular panel member does NOT receive other members' marks or evaluations
        assert sheet["is_guide"] is False
        assert "all_evaluations" not in sheet
        assert "panel_summary" not in sheet

    def test_05_faculty_evaluation_teams_dropdown_populates_guided_teams(self, client, faculty_guide_token):
        """Issue 2 Test: /api/evaluation/faculty/teams populates guided teams for Project Evaluation."""
        res = client.get('/api/evaluation/faculty/teams', headers={"Authorization": f"Bearer {faculty_guide_token}"})
        assert res.status_code == 200
        teams = res.get_json()
        assert any(t.get("team_name") == "OVERVIEW_TEAM_1" for t in teams)
