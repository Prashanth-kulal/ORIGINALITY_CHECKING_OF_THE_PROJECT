import pytest
import json
import jwt
from datetime import datetime, timezone
from backend.app import app, db

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def test_setup():
    coord_token = jwt.encode(
        {"email": "coord_test@college.edu", "role": "coordinator", "name": "Prof Coordinator"},
        app.config["SECRET_KEY"],
        algorithm="HS256"
    )
    guide_token = jwt.encode(
        {"email": "guide_test@college.edu", "role": "faculty", "name": "Dr Guide"},
        app.config["SECRET_KEY"],
        algorithm="HS256"
    )
    member1_token = jwt.encode(
        {"email": "member1_test@college.edu", "role": "faculty", "name": "Prof Member1"},
        app.config["SECRET_KEY"],
        algorithm="HS256"
    )
    member2_token = jwt.encode(
        {"email": "member2_test@college.edu", "role": "faculty", "name": "Prof Member2"},
        app.config["SECRET_KEY"],
        algorithm="HS256"
    )
    student_token = jwt.encode(
        {"email": "student1_test@college.edu", "role": "student", "name": "Student One", "usn": "1TEST01"},
        app.config["SECRET_KEY"],
        algorithm="HS256"
    )

    team_name = "Team_Privacy_Perm_Test"
    semester = 6

    # Clean up any existing test data
    db.teams.delete_many({"team_name": team_name})
    db.panel_allocations.delete_many({"team_name": team_name})
    db.panel_evaluations.delete_many({"team_name": team_name})
    db.evaluations.delete_many({"team_name": team_name})

    # Create team with schema matching backend app.py
    team_doc = {
        "team_name": team_name,
        "semester": semester,
        "faculty_email": "guide_test@college.edu",
        "faculty_name": "Dr Guide",
        "leader_name": "Student One",
        "leader_usn": "1TEST01",
        "leader_email": "student1_test@college.edu",
        "members": [
            {"name": "Student Two", "usn": "1TEST02", "email": "student2_test@college.edu"}
        ],
        "project_idea": {
            "title": "Automated Privacy and Phase Evaluation Control System",
            "status": "approved"
        }
    }
    db.teams.insert_one(team_doc)

    # Create Panel Allocation with is_evaluation_enabled: False by default
    alloc_id = "alloc_test_privacy_001"
    alloc_doc = {
        "allocation_id": alloc_id,
        "team_name": team_name,
        "semester": semester,
        "phase": "phase_1",
        "presentation_phase": "Phase 1",
        "phase_name": "Phase 1 Presentation",
        "guide": {"email": "guide_test@college.edu", "name": "Dr Guide"},
        "guide_name": "Dr Guide",
        "guide_email": "guide_test@college.edu",
        "panel_members": [
            {"email": "member1_test@college.edu", "name": "Prof Member1", "role": "Panel Member 1"},
            {"email": "member2_test@college.edu", "name": "Prof Member2", "role": "Panel Member 2"}
        ],
        "max_marks": 20,
        "status": "Active",
        "is_evaluation_enabled": False,
        "authorized_evaluator_emails": [],
        "created_at": datetime.now(timezone.utc)
    }
    db.panel_allocations.insert_one(alloc_doc)

    yield {
        "alloc_id": alloc_id,
        "team_name": team_name,
        "semester": semester,
        "coord_token": coord_token,
        "guide_token": guide_token,
        "member1_token": member1_token,
        "member2_token": member2_token,
        "student_token": student_token
    }

    # Teardown
    db.teams.delete_many({"team_name": team_name})
    db.panel_allocations.delete_many({"team_name": team_name})
    db.panel_evaluations.delete_many({"team_name": team_name})
    db.evaluations.delete_many({"team_name": team_name})


def test_01_faculty_cannot_save_or_submit_before_coordinator_authorization(client, test_setup):
    """Faculty mark entry must be rejected with 403 when evaluation is not yet enabled by coordinator."""
    alloc_id = test_setup["alloc_id"]
    member1_token = test_setup["member1_token"]

    draft_payload = {
        "allocation_id": alloc_id,
        "student_marks": {
            "1TEST01": {"Literature Survey": 4.5, "Problem Definition": 4.0}
        }
    }

    # Try saving draft before authorization
    res_draft = client.post(
        "/api/panel/evaluation/save",
        headers={"Authorization": f"Bearer {member1_token}"},
        json=draft_payload
    )
    assert res_draft.status_code == 403
    assert "Evaluation is not yet enabled by the coordinator" in res_draft.get_json()["error"]

    # Try submitting marks before authorization
    res_submit = client.post(
        "/api/panel/evaluation/submit",
        headers={"Authorization": f"Bearer {member1_token}"},
        json=draft_payload
    )
    assert res_submit.status_code == 403
    assert "Evaluation is not yet enabled by the coordinator" in res_submit.get_json()["error"]


def test_02_coordinator_enables_evaluation_permission_and_faculty_submits(client, test_setup):
    """Coordinator authorizes mark entry, allowing authorized faculty to save and submit marks."""
    alloc_id = test_setup["alloc_id"]
    coord_token = test_setup["coord_token"]
    member1_token = test_setup["member1_token"]

    # Coordinator enables evaluation for this allocation
    res_toggle = client.post(
        "/api/panel/allocation/toggle_evaluation",
        headers={"Authorization": f"Bearer {coord_token}"},
        json={"allocation_id": alloc_id, "is_evaluation_enabled": True}
    )
    assert res_toggle.status_code == 200
    assert res_toggle.get_json()["success"] is True

    # Member 1 now successfully saves draft
    draft_payload = {
        "allocation_id": alloc_id,
        "student_marks": {
            "1TEST01": {"Literature Survey": 4.5, "Problem Definition": 4.0},
            "1TEST02": {"Literature Survey": 4.0, "Problem Definition": 3.5}
        }
    }
    res_draft = client.post(
        "/api/panel/evaluation/save",
        headers={"Authorization": f"Bearer {member1_token}"},
        json=draft_payload
    )
    assert res_draft.status_code == 200
    assert res_draft.get_json()["success"] is True

    # Member 1 submits marks
    submit_payload = {
        "allocation_id": alloc_id,
        "student_marks": {
            "1TEST01": {"Literature Survey": 4.5, "Problem Definition": 4.5, "Methodology": 4.0, "Presentation": 4.0},
            "1TEST02": {"Literature Survey": 4.0, "Problem Definition": 4.0, "Methodology": 3.5, "Presentation": 3.5}
        }
    }
    res_submit = client.post(
        "/api/panel/evaluation/submit",
        headers={"Authorization": f"Bearer {member1_token}"},
        json=submit_payload
    )
    assert res_submit.status_code == 200
    assert res_submit.get_json()["success"] is True


def test_03_active_phase_allocations_endpoint_returns_correct_schema_and_progress(client, test_setup):
    """GET /api/panel/allocations returns success: True, allocations array, and real-time evaluator progress."""
    coord_token = test_setup["coord_token"]
    alloc_id = test_setup["alloc_id"]

    res = client.get(
        "/api/panel/allocations",
        headers={"Authorization": f"Bearer {coord_token}"}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("success") is True
    assert isinstance(data.get("allocations"), list)

    target_alloc = next((a for a in data["allocations"] if a["allocation_id"] == alloc_id), None)
    assert target_alloc is not None
    assert target_alloc["team_name"] == test_setup["team_name"]
    assert "Phase 1" in target_alloc["presentation_phase"]
    assert "guide_name" in target_alloc
    assert "guide_status" in target_alloc
    assert "panel_members" in target_alloc
    assert "is_evaluation_enabled" in target_alloc


def test_04_coordinator_sees_full_criterion_breakdown(client, test_setup):
    """Coordinator dashboard receives full criterion-level marks for every faculty member."""
    team_name = test_setup["team_name"]
    alloc_id = test_setup["alloc_id"]
    coord_token = test_setup["coord_token"]
    member1_token = test_setup["member1_token"]

    # Authorize and submit an evaluation so marks exist
    client.post(
        "/api/panel/allocation/toggle_evaluation",
        headers={"Authorization": f"Bearer {coord_token}"},
        json={"allocation_id": alloc_id, "is_evaluation_enabled": True}
    )
    client.post(
        "/api/panel/evaluation/submit",
        headers={"Authorization": f"Bearer {member1_token}"},
        json={
            "allocation_id": alloc_id,
            "student_marks": {
                "1TEST01": {"Problem Statement & Objectives": 4.5, "Social & Technical Impact": 4.5, "Depth of Review": 4.0, "Presentation": 4.0},
                "1TEST02": {"Problem Statement & Objectives": 4.0, "Social & Technical Impact": 4.0, "Depth of Review": 3.5, "Presentation": 3.5}
            }
        }
    )

    res = client.get(
        f"/api/evaluation/team/{team_name}?semester=6",
        headers={"Authorization": f"Bearer {coord_token}"}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["team"]["team_name"] == team_name
    assert len(data["students"]) == 2
    assert "panel_info" in data
    assert "Phase 1" in data["panel_info"]

    p_info = data["panel_info"]["Phase 1"]
    evals = p_info["evaluations"]
    assert len(evals) >= 1
    m1_eval = next((e for e in evals if e.get("faculty_email") == "member1_test@college.edu"), None)
    assert m1_eval is not None
    # Coordinator MUST see criterion-level marks
    assert ("marks" in m1_eval or "student_marks" in m1_eval)


def test_05_guide_privacy_strictly_enforced_no_criterion_breakdown_of_others(client, test_setup):
    """Guide receives only final submitted totals (student_totals) of panel members, with NO criteria marks exposed."""
    team_name = test_setup["team_name"]
    alloc_id = test_setup["alloc_id"]
    coord_token = test_setup["coord_token"]
    guide_token = test_setup["guide_token"]
    member1_token = test_setup["member1_token"]

    # Authorize and submit Member 1 evaluation
    client.post(
        "/api/panel/allocation/toggle_evaluation",
        headers={"Authorization": f"Bearer {coord_token}"},
        json={"allocation_id": alloc_id, "is_evaluation_enabled": True}
    )
    client.post(
        "/api/panel/evaluation/submit",
        headers={"Authorization": f"Bearer {member1_token}"},
        json={
            "allocation_id": alloc_id,
            "student_marks": {
                "1TEST01": {"Problem Statement & Objectives": 4.5, "Social & Technical Impact": 4.5, "Depth of Review": 4.0, "Presentation": 4.0},
                "1TEST02": {"Problem Statement & Objectives": 4.0, "Social & Technical Impact": 4.0, "Depth of Review": 3.5, "Presentation": 3.5}
            }
        }
    )

    res = client.get(
        f"/api/evaluation/team/{team_name}?semester=6",
        headers={"Authorization": f"Bearer {guide_token}"}
    )
    assert res.status_code == 200
    data = res.get_json()
    p_info = data["panel_info"]["Phase 1"]
    evals = p_info["evaluations"]

    m1_eval = next((e for e in evals if e.get("faculty_email") == "member1_test@college.edu"), None)
    assert m1_eval is not None
    # Guide MUST NOT see marks array or student_marks dict of other faculty
    assert "marks" not in m1_eval
    assert "student_marks" not in m1_eval
    # Guide MUST see student_totals (final total per student)
    assert "student_totals" in m1_eval
    assert m1_eval["student_totals"].get("1TEST01") == 17.0
    assert m1_eval["student_totals"].get("1TEST02") == 15.0


def test_06_student_does_not_see_individual_faculty_breakdown(client, test_setup):
    """Student endpoint returns only the unified semester evaluation marksheet, never individual panel breakdown."""
    student_token = test_setup["student_token"]

    res = client.get(
        "/api/evaluation/student?semester=6",
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert "panel_info" not in data
    assert "panel_evaluations" not in data
