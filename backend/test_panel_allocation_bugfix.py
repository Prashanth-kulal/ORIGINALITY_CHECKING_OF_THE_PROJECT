import pytest
import json
import jwt
from app import app, db, normalize_panel_phase_key, normalize_panel_name

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def coordinator_token():
    payload = {
        "email": "coordinator@test.edu",
        "role": "coordinator",
        "name": "Project Coordinator"
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

@pytest.fixture
def faculty_token():
    payload = {
        "email": "prof.alan@test.edu",
        "role": "faculty",
        "name": "Prof. Alan Turing"
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

class TestPanelAllocationBugFix:

    def setup_method(self):
        # Setup clean test state for panel allocations
        db.panel_allocations.delete_many({"team_name": {"$in": ["TEST_TEAM_ALPHA", "TEST_TEAM_BETA"]}})
        db.teams.delete_many({"team_name": {"$in": ["TEST_TEAM_ALPHA", "TEST_TEAM_BETA"]}})
        db.notifications.delete_many({"recipient_email": {"$in": ["prof.alan@test.edu", "prof.ada@test.edu"]}})
        db.panel_notifications.delete_many({"recipient_email": {"$in": ["prof.alan@test.edu", "prof.ada@test.edu"]}})
        
        # Insert test teams in MongoDB
        db.teams.insert_many([
            {
                "team_name": "TEST_TEAM_ALPHA",
                "team_id": "TEAM-ALPHA-101",
                "project_title": "AI Autonomous Navigation",
                "semester": "6th Sem",
                "department": "CSE",
                "faculty_name": "Dr. Grace Hopper",
                "faculty_email": "grace.hopper@test.edu",
                "leader_name": "Alice Smith",
                "leader_usn": "1MS21CS001",
                "leader_email": "alice@test.edu",
                "members": [
                    {"name": "Bob Jones", "usn": "1MS21CS002", "email": "bob@test.edu", "role": "Member"},
                    {"name": "Charlie Brown", "usn": "1MS21CS003", "email": "charlie@test.edu", "role": "Member"}
                ],
                "project_idea": {
                    "title": "AI Autonomous Navigation",
                    "status": "Approved"
                }
            },
            {
                "team_name": "TEST_TEAM_BETA",
                "team_id": "TEAM-BETA-202",
                "project_title": "Quantum Cryptography Suite",
                "semester": "7th Sem",
                "department": "CSE",
                "faculty_name": "Dr. Claude Shannon",
                "faculty_email": "shannon@test.edu",
                "leader_name": "David Miller",
                "leader_usn": "1MS20CS050",
                "leader_email": "david@test.edu",
                "members": [
                    {"name": "Eva Green", "usn": "1MS20CS051", "email": "eva@test.edu", "role": "Member"}
                ],
                "project_idea": {
                    "title": "Quantum Cryptography Suite",
                    "status": "In Progress"
                }
            }
        ])

    def teardown_method(self):
        db.panel_allocations.delete_many({"team_name": {"$in": ["TEST_TEAM_ALPHA", "TEST_TEAM_BETA"]}})
        db.teams.delete_many({"team_name": {"$in": ["TEST_TEAM_ALPHA", "TEST_TEAM_BETA"]}})
        db.notifications.delete_many({"recipient_email": {"$in": ["prof.alan@test.edu", "prof.ada@test.edu"]}})
        db.panel_notifications.delete_many({"recipient_email": {"$in": ["prof.alan@test.edu", "prof.ada@test.edu"]}})

    def test_01_actual_teams_load_from_database_with_full_details(self, client, coordinator_token):
        """1. Actual teams load from the database with team name, ID, title, students, guide, semester, status."""
        res = client.get('/api/panel/eligible_teams?semester=6&phase=Phase%201&panel_id=Panel%201',
                         headers={"Authorization": f"Bearer {coordinator_token}"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["count"] >= 2
        
        teams = data["teams"]
        alpha = next((t for t in teams if t["team_name"] == "TEST_TEAM_ALPHA"), None)
        assert alpha is not None, "TEST_TEAM_ALPHA must be returned from db.teams"
        assert alpha["team_id"] == "TEAM-ALPHA-101"
        assert alpha["project_title"] == "AI Autonomous Navigation"
        assert alpha["guide_name"] == "Dr. Grace Hopper"
        assert alpha["guide_email"] == "grace.hopper@test.edu"
        assert alpha["semester"] == "6th Sem"
        assert alpha["project_status"] == "Approved"
        assert len(alpha["members"]) == 3  # Leader + 2 members
        assert alpha["members"][0]["role"] == "Leader"
        assert alpha["members"][0]["name"] == "Alice Smith"
        assert alpha["members"][0]["usn"] == "1MS21CS001"
        assert "Alice Smith (1MS21CS001)" in alpha["students_display"]
        assert alpha["is_available"] is True
        assert alpha["is_allocated_here"] is False

    def test_02_allocated_team_excluded_only_for_same_semester_and_phase(self, client, coordinator_token):
        """2. Already allocated teams are excluded only for matching semester and phase, remaining available for other phases/semesters."""
        # Allocate TEST_TEAM_ALPHA to Panel 1 for Sem 6 Phase 1
        alloc_payload = {
            "panel_id": "Panel 1",
            "semester": 6,
            "phase": "Phase 1",
            "room_number": "Seminar Hall 1",
            "evaluation_deadline": "2026-11-15T18:00",
            "panel_member_emails": ["prof.alan@test.edu", "prof.ada@test.edu"],
            "team_assignments": [
                {
                    "team_name": "TEST_TEAM_ALPHA",
                    "assigned_faculty_emails": ["prof.alan@test.edu", "prof.ada@test.edu"]
                }
            ]
        }
        res_alloc = client.post('/api/panel/allocate',
                                data=json.dumps(alloc_payload),
                                content_type='application/json',
                                headers={"Authorization": f"Bearer {coordinator_token}"})
        assert res_alloc.status_code in [200, 201]
        
        # When querying for Panel 2, Sem 6, Phase 1: TEST_TEAM_ALPHA must be blocked
        res_p2 = client.get('/api/panel/eligible_teams?semester=6&phase=Phase%201&panel_id=Panel%202',
                            headers={"Authorization": f"Bearer {coordinator_token}"})
        assert res_p2.status_code == 200
        teams_p2 = res_p2.get_json()["teams"]
        alpha_p2 = next((t for t in teams_p2 if t["team_name"] == "TEST_TEAM_ALPHA"), None)
        assert alpha_p2 is not None
        assert alpha_p2["is_available"] is False
        assert alpha_p2["allocated_panel"] == "Panel 1"

        # TEST_TEAM_BETA must remain available for Panel 2, Sem 6, Phase 1
        beta_p2 = next((t for t in teams_p2 if t["team_name"] == "TEST_TEAM_BETA"), None)
        assert beta_p2 is not None
        assert beta_p2["is_available"] is True

        # When querying for Panel 1, Sem 6, Phase 1: TEST_TEAM_ALPHA shows as allocated here
        res_p1 = client.get('/api/panel/eligible_teams?semester=6&phase=Phase%201&panel_id=Panel%201',
                            headers={"Authorization": f"Bearer {coordinator_token}"})
        teams_p1 = res_p1.get_json()["teams"]
        alpha_p1 = next((t for t in teams_p1 if t["team_name"] == "TEST_TEAM_ALPHA"), None)
        assert alpha_p1["is_available"] is True
        assert alpha_p1["is_allocated_here"] is True

        # BUT for Sem 6 Phase 2: TEST_TEAM_ALPHA must be STILL eligible across panels
        res_phase2 = client.get('/api/panel/eligible_teams?semester=6&phase=Phase%202&panel_id=Panel%202',
                                headers={"Authorization": f"Bearer {coordinator_token}"})
        teams_phase2 = res_phase2.get_json()["teams"]
        alpha_phase2 = next((t for t in teams_phase2 if t["team_name"] == "TEST_TEAM_ALPHA"), None)
        assert alpha_phase2["is_available"] is True

        # AND for Sem 7 Phase 4: TEST_TEAM_ALPHA must be STILL eligible
        res_sem7 = client.get('/api/panel/eligible_teams?semester=7&phase=Phase%204&panel_id=Panel%202',
                              headers={"Authorization": f"Bearer {coordinator_token}"})
        teams_sem7 = res_sem7.get_json()["teams"]
        alpha_sem7 = next((t for t in teams_sem7 if t["team_name"] == "TEST_TEAM_ALPHA"), None)
        assert alpha_sem7["is_available"] is True

    def test_03_backend_prevents_duplicate_allocation_to_different_panel(self, client, coordinator_token):
        """3. Backend duplicate allocation prevention blocks assigning already allocated team to a different panel."""
        # First allocation: Panel 1, Sem 6, Phase 1
        payload1 = {
            "panel_id": "Panel 1",
            "semester": 6,
            "phase": "Phase 1",
            "room_number": "Lab 1",
            "evaluation_deadline": "2026-11-20T17:00",
            "panel_member_emails": ["prof.alan@test.edu"],
            "team_assignments": [{"team_name": "TEST_TEAM_ALPHA", "assigned_faculty_emails": ["prof.alan@test.edu"]}]
        }
        res1 = client.post('/api/panel/allocate', data=json.dumps(payload1),
                           content_type='application/json', headers={"Authorization": f"Bearer {coordinator_token}"})
        assert res1.status_code in [200, 201]

        # Attempt to allocate same team to Panel 2 for same semester and phase
        payload2 = {
            "panel_id": "Panel 2",
            "semester": 6,
            "phase": "Phase 1",
            "room_number": "Lab 2",
            "evaluation_deadline": "2026-11-20T17:00",
            "panel_member_emails": ["prof.ada@test.edu"],
            "team_assignments": [{"team_name": "TEST_TEAM_ALPHA", "assigned_faculty_emails": ["prof.ada@test.edu"]}]
        }
        res2 = client.post('/api/panel/allocate', data=json.dumps(payload2),
                           content_type='application/json', headers={"Authorization": f"Bearer {coordinator_token}"})
        assert res2.status_code == 400
        err = res2.get_json()["error"]
        assert "already allocated to Panel 1" in err

    def test_04_coordinator_dashboard_html_structure_and_dynamic_phase_logic(self):
        """4. Verify coordinator frontend HTML contains dynamic phase options and all required element IDs."""
        with open("frontend/project_coordinator-dashboard.html", "r", encoding="utf-8") as f:
            html = f.read()

        # Required form element IDs
        assert 'id="coordinatorPanelSelect"' in html
        assert 'id="coordinatorPanelSemester"' in html
        assert 'id="coordinatorPanelPhase"' in html
        assert 'id="coordinatorEligibleTeamsContainer"' in html
        assert 'id="selectedTeamsDetailsContainer"' in html
        assert 'id="selectedTeamsCountBadge"' in html
        assert 'id="facultyTeamAssignmentTableContainer"' in html
        assert 'id="savePanelAllocBtn"' in html

        # Semester switching functions
        assert 'function onCoordinatorSemChange()' in html
        assert 'function onCoordinatorPhaseChange()' in html
        assert 'function renderSelectedTeamsDetails()' in html
        assert 'function filterCoordinatorEligibleTeams()' in html

        # Semester 6 phase mapping: Phase 1 & Phase 2
        assert 'Phase 1 - Synopsis &amp; Problem Definition' in html
        assert 'Phase 2 - System Design' in html

        # Semester 7 phase mapping: Phase 4 & Phase 5
        assert 'Phase 4 - Implementation &amp; Progress' in html
        assert 'Phase 5 - Final Evaluation &amp; Defense' in html

        # Verify no mixing of 6th and 7th semester phases in onCoordinatorSemChange
        assert 'sem === 6' in html
        assert 'Phase 4' in html and 'Phase 5' in html

    def test_05_faculty_notifications_and_marksheets_identify_correct_phase(self, client, coordinator_token, faculty_token):
        """5. Faculty notifications and evaluation marksheet data identify the correct phase and semester."""
        # Allocate for Sem 7 Phase 4
        payload = {
            "panel_id": "Panel 3",
            "semester": 7,
            "phase": "Phase 4",
            "room_number": "Seminar Hall 3",
            "evaluation_deadline": "2026-11-25T17:00",
            "panel_member_emails": ["prof.alan@test.edu"],
            "team_assignments": [
                {
                    "team_name": "TEST_TEAM_BETA",
                    "assigned_faculty_emails": ["prof.alan@test.edu"]
                }
            ],
            "is_evaluation_enabled": True
        }
        res = client.post('/api/panel/allocate', data=json.dumps(payload),
                          content_type='application/json', headers={"Authorization": f"Bearer {coordinator_token}"})
        assert res.status_code in [200, 201]
        
        # Check notification in db.panel_notifications
        notif = db.panel_notifications.find_one({"recipient_email": "prof.alan@test.edu"})
        assert notif is not None
        assert notif["panel_id"] == "Panel 3"
        assert notif["phase"] == "Phase 4"
        assert notif["semester"] == 7
        assert "Phase 4" in notif["message"]
        assert "Panel 3" in notif["message"]
        assert "panel-evaluation.html?alloc_id=" in notif["evaluation_url"]

        # Also verify faculty can fetch it via /api/panel/notifications
        res_notif = client.get('/api/panel/notifications', headers={"Authorization": f"Bearer {faculty_token}"})
        assert res_notif.status_code == 200
        notifs_list = res_notif.get_json()["notifications"]
        assert any(n.get("phase") == "Phase 4" and n.get("panel_id") == "Panel 3" for n in notifs_list)

        # Verify faculty marksheet evaluation data endpoint
        alloc_doc = db.panel_allocations.find_one({"team_name": "TEST_TEAM_BETA", "phase": "Phase 4"})
        assert alloc_doc is not None
        alloc_id = alloc_doc["allocation_id"]

        res_eval = client.get(f'/api/panel/evaluation/{alloc_id}',
                              headers={"Authorization": f"Bearer {faculty_token}"})
        assert res_eval.status_code == 200
        data = res_eval.get_json()
        alloc = data["allocation"]
        assert alloc["phase"] == "Phase 4"
        assert alloc["semester"] == 7
        assert alloc["panel_id"] == "Panel 3"
        assert alloc["team_name"] == "TEST_TEAM_BETA"
        assert alloc["max_marks"] in [20, 30]
        assert len(data["students"]) == 2
        assert data["students"][0]["usn"] == "1MS20CS050"
