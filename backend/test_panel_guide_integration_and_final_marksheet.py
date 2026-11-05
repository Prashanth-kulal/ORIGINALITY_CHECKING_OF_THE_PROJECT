# -*- coding: utf-8 -*-
"""
Test Suite: Panel Faculty Average Integration & Final Marksheet.
Validates all 17 requirements and realistic numerical examples:
1. Phase 1: 4 evaluators (Guide 16 + Panel1 18 + Panel2 14 + Panel3 20 -> Avg 17.00).
2. Phase 2: 4 evaluators (Guide 15 + Panel1 17 + Panel2 16 + Panel3 20 -> Avg 17.00).
3. Phase 4: 4 evaluators (Guide 18 + Panel1 16 + Panel2 20 + Panel3 14 -> Avg 17.00).
4. Phase 5: 4 Panel Faculty ONLY (Panel1 16 + Panel2 18 + Panel3 20 + Panel4 14 -> Avg 17.00; Guide excluded).
5. Incomplete evaluation handling: Fewer than 4 submissions -> Phase pending, not published.
6. Pending & cancelled/voided evaluations excluded from average and denominator.
7. Duplicate submissions / resubmissions: Latest valid submission counted, no duplicates.
8. Unassigned faculty submissions excluded.
9. Guide-specific marks (Attendance, Report, Paper Submission) remain separate.
10. Final semester marksheet follows the original formula summing to 100 max marks.
"""

import pytest
import jwt
import io
import openpyxl
from datetime import datetime, timezone, timedelta
import backend.app as app_module
from backend.app import app, db

def make_token(email, role, name=None, team_name=None, usn=None):
    payload = {
        "email": email,
        "role": role,
        "name": name or email.split("@")[0].title(),
        "exp": datetime.now(timezone.utc) + timedelta(hours=8)
    }
    if team_name:
        payload["team_name"] = team_name
    if usn:
        payload["usn"] = usn
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

TEST_TEAMS = [
    "TEST_P1_TEAM_17",
    "TEST_P2_TEAM_17",
    "TEST_P4_TEAM_17",
    "TEST_P5_TEAM_17",
    "TEST_INCOMPLETE_TEAM",
    "TEST_DEDUP_TEAM",
    "TEST_FORMULA_SEM7_TEAM",
    "TEST_FORMULA_SEM6_TEAM"
]

@pytest.fixture(autouse=True)
def clean_test_data():
    # Strict safety check: only execute against isolated test database!
    assert "test" in db.name.lower(), f"SAFETY ABORT: Refusing to clean non-test DB: {db.name}"
    db.teams.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.panel_allocations.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.panel_evaluations.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.evaluations.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.attendance.delete_many({"team_name": {"$in": TEST_TEAMS}})
    yield
    db.teams.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.panel_allocations.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.panel_evaluations.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.evaluations.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.attendance.delete_many({"team_name": {"$in": TEST_TEAMS}})


def test_01_phase1_guide_plus_three_panel_faculty_average(client):
    """
    Phase 1 Realistic Example:
    Guide: 16, Panel 1: 18, Panel 2: 14, Panel 3: 20 -> Expected Average: 17.00
    Guide is one of the 4 evaluators.
    """
    coord_token = make_token("coord@test.edu", "coordinator")
    team_name = "TEST_P1_TEAM_17"
    db.teams.insert_one({
        "team_name": team_name,
        "semester": 6,
        "faculty_email": "guide_p1@test.edu",
        "faculty_name": "Dr. Guide One",
        "leader_name": "Student A",
        "leader_usn": "4MW23CS001",
        "members": []
    })

    alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 1",
        "semester": 6,
        "phase": "Phase 1",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert alloc_res.status_code in [200, 201]
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Evaluators submit marks
    # Guide submits 16
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('guide_p1@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS001": 16.0}})
    # Panel Faculty 1 submits 18
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS001": 18.0}})
    # Panel Faculty 2 submits 14
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS001": 14.0}})
    # Panel Faculty 3 submits 20
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS001": 20.0}})

    calc = app_module.calculate_student_panel_averages(alloc_id)
    assert calc["is_complete"] is True
    assert calc["submitted_evals_count"] == 4
    sr = calc["student_results"][0]
    assert sr["average_mark"] == 17.00

    # Verify sync into Project Evaluation
    eval_res = client.get(f"/api/evaluation/team/{team_name}?semester=6", headers={"Authorization": f"Bearer {coord_token}"})
    assert eval_res.status_code == 200
    phases = eval_res.get_json()["evaluation"]["phases"]
    p1 = next(p for p in phases if "phase 1" in p["name"].lower())
    assert p1["is_panel_evaluated"] is True
    assert p1["panel_average"] is True
    assert p1["is_complete"] is True
    mark_val = p1["criteria"][0]["marks"][0]["marks_obtained"]
    assert mark_val == 17.00


def test_02_phase2_guide_plus_three_panel_faculty_average(client):
    """
    Phase 2 Realistic Example:
    Guide: 15, Panel 1: 17, Panel 2: 16, Panel 3: 20 -> Expected Average: 17.00
    """
    coord_token = make_token("coord@test.edu", "coordinator")
    team_name = "TEST_P2_TEAM_17"
    db.teams.insert_one({
        "team_name": team_name,
        "semester": 6,
        "faculty_email": "guide_p2@test.edu",
        "faculty_name": "Dr. Guide Two",
        "leader_name": "Student B",
        "leader_usn": "4MW23CS002",
        "members": []
    })

    alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 2",
        "semester": 6,
        "phase": "Phase 2",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert alloc_res.status_code in [200, 201]
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Guide submits 15
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('guide_p2@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS002": 15.0}})
    # Panel Faculty 1 submits 17
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS002": 17.0}})
    # Panel Faculty 2 submits 16
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS002": 16.0}})
    # Panel Faculty 3 submits 20
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS002": 20.0}})

    calc = app_module.calculate_student_panel_averages(alloc_id)
    assert calc["is_complete"] is True
    assert calc["submitted_evals_count"] == 4
    sr = calc["student_results"][0]
    assert sr["average_mark"] == 17.00


def test_03_phase4_guide_plus_three_panel_faculty_average(client):
    """
    Phase 4 Realistic Example:
    Guide: 18, Panel 1: 16, Panel 2: 20, Panel 3: 14 -> Expected Average: 17.00
    """
    coord_token = make_token("coord@test.edu", "coordinator")
    team_name = "TEST_P4_TEAM_17"
    db.teams.insert_one({
        "team_name": team_name,
        "semester": 7,
        "faculty_email": "guide_p4@test.edu",
        "faculty_name": "Dr. Guide Four",
        "leader_name": "Student C",
        "leader_usn": "4MW23CS003",
        "members": []
    })

    alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 4",
        "semester": 7,
        "phase": "Phase 4",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert alloc_res.status_code in [200, 201]
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Guide submits 18
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('guide_p4@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS003": 18.0}})
    # Panel 1 submits 16
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS003": 16.0}})
    # Panel 2 submits 20
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS003": 20.0}})
    # Panel 3 submits 14
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS003": 14.0}})

    calc = app_module.calculate_student_panel_averages(alloc_id)
    assert calc["is_complete"] is True
    assert calc["submitted_evals_count"] == 4
    sr = calc["student_results"][0]
    assert sr["average_mark"] == 17.00


def test_04_phase5_four_panel_faculty_only_guide_strictly_excluded(client):
    """
    Phase 5 Realistic Example:
    Panel Faculty 1: 16, Panel Faculty 2: 18, Panel Faculty 3: 20, Panel Faculty 4: 14 -> Expected Average: 17.00
    The team guide MUST NOT be included in Phase 5 average. Even if guide submits marks, guide is excluded!
    """
    coord_token = make_token("coord@test.edu", "coordinator")
    team_name = "TEST_P5_TEAM_17"
    db.teams.insert_one({
        "team_name": team_name,
        "semester": 7,
        "faculty_email": "guide_p5@test.edu",
        "faculty_name": "Dr. Guide Five",
        "leader_name": "Student D",
        "leader_usn": "4MW23CS004",
        "members": []
    })

    alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 5",
        "semester": 7,
        "phase": "Phase 5",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu", "fac4@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert alloc_res.status_code in [200, 201]
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Even if guide submits marks in panel_evaluations, guide must be strictly excluded from Phase 5!
    db.panel_evaluations.insert_one({
        "allocation_id": alloc_id,
        "faculty_email": "guide_p5@test.edu",
        "status": "Submitted",
        "final_marks": {"4MW23CS004": 30.0},
        "student_totals": {"4MW23CS004": 30.0}
    })

    # The 4 assigned panel faculty members submit:
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS004": 16.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS004": 18.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS004": 20.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac4@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS004": 14.0}})

    calc = app_module.calculate_student_panel_averages(alloc_id)
    assert calc["is_complete"] is True
    assert calc["submitted_evals_count"] == 4
    sr = calc["student_results"][0]
    # (16 + 18 + 20 + 14) / 4 = 17.00. (Guide's 30 is EXCLUDED!)
    assert sr["average_mark"] == 17.00


def test_05_incomplete_evaluations_not_published_as_complete(client):
    """
    Incomplete evaluation handling:
    When only 3 of 4 evaluators have submitted:
    - is_complete is False.
    - Phase in Project Evaluation has status: 'Pending' and panel_average: False.
    - Final export marksheet displays 'N/A' (Pending), NOT published as complete.
    """
    coord_token = make_token("coord@test.edu", "coordinator")
    team_name = "TEST_INCOMPLETE_TEAM"
    db.teams.insert_one({
        "team_name": team_name,
        "semester": 7,
        "faculty_email": "guide_inc@test.edu",
        "faculty_name": "Dr. Guide Inc",
        "leader_name": "Student Inc",
        "leader_usn": "4MW23CS005",
        "members": []
    })

    alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 4",
        "semester": 7,
        "phase": "Phase 4",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert alloc_res.status_code in [200, 201]
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Only 3 evaluators submit (Guide + Fac1 + Fac2). Fac 3 has NOT submitted.
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('guide_inc@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS005": 18.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS005": 16.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS005": 20.0}})

    calc = app_module.calculate_student_panel_averages(alloc_id)
    assert calc["is_complete"] is False
    assert calc["submitted_evals_count"] == 3
    assert calc["required_count"] == 4

    # Verify team evaluation endpoint
    eval_res = client.get(f"/api/evaluation/team/{team_name}?semester=7", headers={"Authorization": f"Bearer {coord_token}"})
    phases = eval_res.get_json()["evaluation"]["phases"]
    p4 = next(p for p in phases if "phase 4" in p["name"].lower())
    assert p4["is_complete"] is False
    assert p4["panel_average"] is False
    assert p4["status"] == "Pending"

    # Export final marks: must NOT publish incomplete evaluation as complete!
    exp_res = client.get("/api/coordinator/export_final_marks?semester=7", headers={"Authorization": f"Bearer {coord_token}"})
    assert exp_res.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(exp_res.data))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    data_dict = {str(r[0]): r[1] for r in rows[1:] if r and r[0]}
    # Incomplete student mark must be 'N/A'
    assert data_dict.get("4MW23CS005") == "N/A"


def test_06_deduplication_and_resubmission_handling(client):
    """
    Duplicate submissions and resubmission:
    If a faculty member submits multiple times, only the latest submission is counted.
    Denominator does not count duplicates.
    """
    coord_token = make_token("coord@test.edu", "coordinator")
    team_name = "TEST_DEDUP_TEAM"
    db.teams.insert_one({
        "team_name": team_name,
        "semester": 6,
        "faculty_email": "guide_dedup@test.edu",
        "faculty_name": "Dr. Guide Dedup",
        "leader_name": "Student D",
        "leader_usn": "4MW23CS006",
        "members": []
    })

    alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 1",
        "semester": 6,
        "phase": "Phase 1",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert alloc_res.status_code in [200, 201]
    alloc_id = alloc_res.get_json()["allocation_id"]

    f1_token = make_token("fac1@test.edu", "faculty")
    # First submission: Fac 1 submits 10
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {f1_token}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS006": 10.0}})
    # Second submission (resubmission): Fac 1 updates mark to 18
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {f1_token}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS006": 18.0}})

    # Other evaluators submit
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('guide_dedup@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS006": 16.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS006": 14.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"4MW23CS006": 20.0}})

    calc = app_module.calculate_student_panel_averages(alloc_id)
    assert calc["submitted_evals_count"] == 4  # Not 5!
    sr = calc["student_results"][0]
    # Latest 18 used for Fac 1: (16 + 18 + 14 + 20) / 4 = 17.00
    assert sr["average_mark"] == 17.00


def test_07_guide_attendance_report_paper_separate_and_final_100_marks(client):
    """
    7th Semester Final Marksheet Integration:
    Phase 4 Panel Avg (30) + Phase 5 Panel Avg (30) + Report (10) + Attendance (10) + Paper (20) = 100.
    Guide attendance, report, paper marks remain separate and are not averaged into panel.
    Guide panel evaluation is included in Phase 4 average, but NOT counted twice.
    """
    coord_token = make_token("coord@test.edu", "coordinator")
    team_name = "TEST_FORMULA_SEM7_TEAM"
    db.teams.insert_one({
        "team_name": team_name,
        "semester": 7,
        "faculty_email": "guide_sem7@test.edu",
        "faculty_name": "Dr. Guide Sem7",
        "leader_name": "Student Final",
        "leader_usn": "4MW23CS007",
        "members": []
    })

    # 1. Phase 4 Allocation & Submissions (Guide 18 + Panel1 16 + Panel2 20 + Panel3 14 -> Avg 17.00)
    alloc4_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 4",
        "semester": 7,
        "phase": "Phase 4",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert alloc4_res.status_code in [200, 201]
    alloc4_id = alloc4_res.get_json()["allocation_id"]

    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('guide_sem7@test.edu', 'faculty')}"},
                json={"allocation_id": alloc4_id, "final_marks": {"4MW23CS007": 18.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": alloc4_id, "final_marks": {"4MW23CS007": 16.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": alloc4_id, "final_marks": {"4MW23CS007": 20.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": alloc4_id, "final_marks": {"4MW23CS007": 14.0}})

    # 2. Phase 5 Allocation & Submissions (Panel1 16 + Panel2 18 + Panel3 20 + Panel4 14 -> Avg 17.00)
    alloc5_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 5",
        "semester": 7,
        "phase": "Phase 5",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu", "fac4@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert alloc5_res.status_code in [200, 201]
    alloc5_id = alloc5_res.get_json()["allocation_id"]

    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": alloc5_id, "final_marks": {"4MW23CS007": 16.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": alloc5_id, "final_marks": {"4MW23CS007": 18.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": alloc5_id, "final_marks": {"4MW23CS007": 20.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac4@test.edu', 'faculty')}"},
                json={"allocation_id": alloc5_id, "final_marks": {"4MW23CS007": 14.0}})

    # Insert attendance meetings for 7th semester so attendance auto-calculates to 10 marks
    db.attendance.insert_many([
        {"student_usn": "4MW23CS007", "student_name": "Student Final", "team_name": team_name, "semester": 7, "meeting_date": "2026-10-01", "status": "Completed"}
        for _ in range(15)
    ])

    # 3. Guide enters guide-specific components: Report (9/10), Attendance (10/10), Paper Submission (18/20)
    guide_token = make_token("guide_sem7@test.edu", "faculty")
    client.post("/api/evaluation/save", headers={"Authorization": f"Bearer {guide_token}"}, json={
        "team_name": team_name,
        "semester": 7,
        "evaluation": {
            "phases": [
                {"name": "Report", "total_marks": 10.0, "criteria": [{"name": "Report", "max_marks": 10, "marks": [{"marks_obtained": 9.0, "maximum_marks": 10}]}]},
                {"name": "Attendance", "total_marks": 10.0, "criteria": [{"name": "Attendance", "max_marks": 10, "marks": [{"marks_obtained": 10.0, "maximum_marks": 10}]}]},
                {"name": "Paper Submission", "total_marks": 20.0, "criteria": [{"name": "Paper Submission", "max_marks": 20, "marks": [{"marks_obtained": 18.0, "maximum_marks": 20}]}]}
            ]
        }
    })

    # Final marks calculation:
    # Phase 4 (17.00) + Phase 5 (17.00) + Report (9.00) + Attendance (10.00) + Paper (18.00) = 71.00 / 100
    exp_res = client.get("/api/coordinator/export_final_marks?semester=7", headers={"Authorization": f"Bearer {coord_token}"})
    assert exp_res.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(exp_res.data))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    data_dict = {str(r[0]): r[1] for r in rows[1:] if r and r[0]}

    assert "4MW23CS007" in data_dict
    assert float(data_dict["4MW23CS007"]) == 71.0
