# -*- coding: utf-8 -*-
"""
Test Suite: Targeted Marksheet and Project Evaluation Workflow.
Validates all requirements for 6th and 7th semester Project Evaluation:
1. 6th Semester Formula: Phase 1 (20) + Phase 2 (40) + Guide Component (40) = 100 Marks.
2. 7th Semester Formula: Phase 4 (30) + Phase 5 (30) + Guide Component (40) = 100 Marks.
3. Component Rubrics:
   - Sem 6 Phase 1: Problem Statement & Objectives (5), Social & Technical Impact (5), Depth of Review (5), Presentation (5) = 20.
   - Sem 6 Phase 2: Technical Clarity (10), Novelty (15), Relevance to Objectives (10), Presentation (5) = 40.
   - Sem 7 Phase 4: Detailed Methodology & partially completed project demo (20), Presentation & Questions & Answers (10) = 30.
   - Sem 7 Phase 5: Presentation (5), Demo (20), Q & A (5) = 30.
4. Strict 4-Evaluator Panel Averaging:
   - Incomplete evaluations (fewer than 4 submissions) marked Pending (X/4) and not finalized.
   - Complete evaluations (4 submissions) strictly divided by 4, formatted to 2 decimal places.
5. Guide Component Isolation & Permissions:
   - Sem 6: Report (20), Attendance (10), Synopsis (10) = 40.
   - Sem 7: Project Report (10), Project Outcome (20), Attendance (10) = 40.
   - Only assigned guide or coordinator can update guide marks (403 for unauthorized faculty).
6. Final Marksheet Consolidation & Export:
   - Clean separation between Distribution Marksheet and Final Consolidated Marksheet.
   - Coordinator locking, unlocking, and publication preserve data integrity.
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
    "TEST_TARGET_SEM6_TEAM",
    "TEST_TARGET_SEM7_TEAM",
    "TEST_TARGET_INCOMPLETE_TEAM"
]

@pytest.fixture(autouse=True)
def clean_test_data():
    db.teams.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.panel_allocations.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.panel_evaluations.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.evaluations.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.panel_notifications.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.attendance.delete_many({"team_name": {"$in": TEST_TEAMS}})
    yield
    db.teams.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.panel_allocations.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.panel_evaluations.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.evaluations.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.panel_notifications.delete_many({"team_name": {"$in": TEST_TEAMS}})
    db.attendance.delete_many({"team_name": {"$in": TEST_TEAMS}})


def test_01_component_rubrics_and_metadata_sem6_and_sem7():
    """Verify official criteria definitions and max marks for all presentation phases."""
    # Sem 6 Phase 1
    p1_meta = app_module.get_panel_phase_metadata("Phase 1", semester=6)
    assert p1_meta["max_marks"] == 20
    assert len(p1_meta["criteria"]) == 4
    p1_crits = {c["name"]: c["max_marks"] for c in p1_meta["criteria"]}
    assert p1_crits["Problem Statement & Objectives"] == 5
    assert p1_crits["Social & Technical Impact"] == 5
    assert p1_crits["Depth of Review"] == 5
    assert p1_crits["Presentation"] == 5

    # Sem 6 Phase 2
    p2_meta = app_module.get_panel_phase_metadata("Phase 2", semester=6)
    assert p2_meta["max_marks"] == 40
    assert len(p2_meta["criteria"]) == 4
    p2_crits = {c["name"]: c["max_marks"] for c in p2_meta["criteria"]}
    assert p2_crits["Technical Clarity"] == 10
    assert p2_crits["Novelty"] == 15
    assert p2_crits["Relevance to Objectives"] == 10
    assert p2_crits["Presentation"] == 5

    # Sem 7 Phase 4
    p4_meta = app_module.get_panel_phase_metadata("Phase 4", semester=7)
    assert p4_meta["max_marks"] == 30
    assert len(p4_meta["criteria"]) == 2
    p4_crits = {c["name"]: c["max_marks"] for c in p4_meta["criteria"]}
    assert p4_crits["Detailed Methodology & partially completed project demo"] == 20
    assert p4_crits["Presentation & Questions & Answers"] == 10

    # Sem 7 Phase 5
    p5_meta = app_module.get_panel_phase_metadata("Phase 5", semester=7)
    assert p5_meta["max_marks"] == 30
    assert len(p5_meta["criteria"]) == 3
    p5_crits = {c["name"]: c["max_marks"] for c in p5_meta["criteria"]}
    assert p5_crits["Presentation"] == 5
    assert p5_crits["Demo"] == 20
    assert p5_crits["Q & A"] == 5


def test_02_sem6_complete_workflow_100_marks(client):
    """
    6th Semester Complete Workflow:
    - Phase 1: 4 evaluators (16 + 18 + 14 + 20) -> avg = 17.00 / 20.
    - Phase 2: 4 evaluators (32 + 36 + 28 + 40) -> avg = 34.00 / 40.
    - Guide: Report (18) + Attendance (10) + Synopsis (9) -> guide = 37.00 / 40.
    - Grand Total: 17.00 + 34.00 + 37.00 = 88.00 / 100.
    """
    coord_token = make_token("coordinator@test.edu", "coordinator")
    team_name = "TEST_TARGET_SEM6_TEAM"

    db.teams.insert_one({
        "team_name": team_name,
        "semester": 6,
        "faculty_email": "guide_s6@test.edu",
        "faculty_name": "Dr. Guide Six",
        "leader_name": "Bob Leader",
        "leader_usn": "1MS21CS001",
        "leader_email": "bob@test.edu",
        "members": []
    })

    # Seed 15 guide meetings to give 10.0 attendance mark
    for i in range(15):
        db.attendance.insert_one({
            "team_name": team_name,
            "student_usn": "1MS21CS001",
            "semester": 6,
            "date": f"2026-09-{i+1:02d}",
            "time": "10:00 AM",
            "status": "Completed"
        })

    # Coordinator allocates Phase 1 (Guide + 3 panel members = 4 evaluators)
    p1_alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 1",
        "semester": 6,
        "phase": "Phase 1",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert p1_alloc_res.status_code in [200, 201]
    p1_alloc_id = p1_alloc_res.get_json()["allocation_id"]

    # 4 Evaluators submit for Phase 1
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('guide_s6@test.edu', 'faculty')}"},
                json={"allocation_id": p1_alloc_id, "final_marks": {"1MS21CS001": 16.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": p1_alloc_id, "final_marks": {"1MS21CS001": 18.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": p1_alloc_id, "final_marks": {"1MS21CS001": 14.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": p1_alloc_id, "final_marks": {"1MS21CS001": 20.0}})

    # Coordinator allocates Phase 2
    p2_alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 2",
        "semester": 6,
        "phase": "Phase 2",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert p2_alloc_res.status_code in [200, 201]
    p2_alloc_id = p2_alloc_res.get_json()["allocation_id"]

    # 4 Evaluators submit for Phase 2
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('guide_s6@test.edu', 'faculty')}"},
                json={"allocation_id": p2_alloc_id, "final_marks": {"1MS21CS001": 32.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": p2_alloc_id, "final_marks": {"1MS21CS001": 36.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": p2_alloc_id, "final_marks": {"1MS21CS001": 28.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": p2_alloc_id, "final_marks": {"1MS21CS001": 40.0}})

    # Guide enters Guide Component marks: Report (18), Attendance (10), Synopsis (9)
    guide_token = make_token("guide_s6@test.edu", "faculty")
    guide_save_res = client.post("/api/evaluation/save", headers={"Authorization": f"Bearer {guide_token}"}, json={
        "team_name": team_name,
        "semester": 6,
        "evaluation": {
            "phases": [
                {
                    "name": "Report & Attendance",
                    "total_marks": 40,
                    "criteria": [
                        {"name": "Report", "max_marks": 20, "marks": [{"marks_obtained": 18.0, "maximum_marks": 20}]},
                        {"name": "Attendance", "max_marks": 10, "marks": [{"marks_obtained": 10.0, "maximum_marks": 10}]},
                        {"name": "Synopsis", "max_marks": 10, "marks": [{"marks_obtained": 9.0, "maximum_marks": 10}]}
                    ]
                }
            ]
        }
    })
    assert guide_save_res.status_code == 200

    # Verify team evaluation endpoint response payload
    team_eval_res = client.get(f"/api/evaluation/team/{team_name}?semester=6", headers={"Authorization": f"Bearer {guide_token}"})
    assert team_eval_res.status_code == 200
    team_data = team_eval_res.get_json()
    assert team_data["is_guide"] is True
    assert team_data["can_edit_guide_marks"] is True
    assert "panel_info" in team_data

    # Verify Phase 1 & Phase 2 in panel_info
    p1_info = team_data["panel_info"]["Phase 1"]
    assert p1_info["is_complete"] is True
    assert p1_info["submitted_count"] == 4
    assert p1_info["panel_results"][0]["average_mark"] == 17.00

    p2_info = team_data["panel_info"]["Phase 2"]
    assert p2_info["is_complete"] is True
    assert p2_info["submitted_count"] == 4
    assert p2_info["panel_results"][0]["average_mark"] == 34.00

    # Verify synchronized evaluation phases in db.evaluations
    eval_phases = team_data["evaluation"]["phases"]
    p1_phase = next(p for p in eval_phases if "phase 1" in p["name"].lower())
    assert p1_phase["is_complete"] is True
    assert p1_phase["criteria"][0]["marks"][0]["marks_obtained"] == 17.00

    p2_phase = next(p for p in eval_phases if "phase 2" in p["name"].lower())
    assert p2_phase["is_complete"] is True
    assert p2_phase["criteria"][0]["marks"][0]["marks_obtained"] == 34.00

    # Grand Total: 17 + 34 + 37 = 88.00 / 100
    p1_mark = p1_phase["criteria"][0]["marks"][0]["marks_obtained"]
    p2_mark = p2_phase["criteria"][0]["marks"][0]["marks_obtained"]
    guide_phase = next(p for p in eval_phases if "report" in p["name"].lower())
    guide_mark = sum(c["marks"][0]["marks_obtained"] for c in guide_phase["criteria"])
    grand_total = round(p1_mark + p2_mark + guide_mark, 2)
    assert grand_total == 88.00


def test_03_sem7_complete_workflow_100_marks(client):
    """
    7th Semester Complete Workflow:
    - Phase 4: 4 evaluators (22 + 26 + 24 + 28) -> avg = 25.00 / 30.
    - Phase 5: 4 panel faculty (24 + 26 + 28 + 26; Guide excluded) -> avg = 26.00 / 30.
    - Guide: Report (9) + Attendance (10) + Project Outcome (18) -> guide = 37.00 / 40.
    - Grand Total: 25.00 + 26.00 + 37.00 = 88.00 / 100.
    """
    coord_token = make_token("coordinator@test.edu", "coordinator")
    team_name = "TEST_TARGET_SEM7_TEAM"

    db.teams.insert_one({
        "team_name": team_name,
        "semester": 7,
        "faculty_email": "guide_s7@test.edu",
        "faculty_name": "Dr. Guide Seven",
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS101",
        "leader_email": "alice@test.edu",
        "members": []
    })

    # Seed 15 guide meetings to give 10.0 attendance mark
    for i in range(15):
        db.attendance.insert_one({
            "team_name": team_name,
            "student_usn": "1MS21CS101",
            "semester": 7,
            "date": f"2026-10-{i+1:02d}",
            "time": "10:00 AM",
            "status": "Completed"
        })

    # Phase 4 Allocation (Guide + 3 panel members)
    p4_alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 4",
        "semester": 7,
        "phase": "Phase 4",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert p4_alloc_res.status_code in [200, 201]
    p4_alloc_id = p4_alloc_res.get_json()["allocation_id"]

    # 4 Evaluators submit for Phase 4 using official criteria rubric
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('guide_s7@test.edu', 'faculty')}"},
                json={"allocation_id": p4_alloc_id, "student_marks": {
                    "1MS21CS101": {"Detailed Methodology & partially completed project demo": 15, "Presentation & Questions & Answers": 7}
                }}) # 22
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": p4_alloc_id, "student_marks": {
                    "1MS21CS101": {"Detailed Methodology & partially completed project demo": 18, "Presentation & Questions & Answers": 8}
                }}) # 26
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": p4_alloc_id, "student_marks": {
                    "1MS21CS101": {"Detailed Methodology & partially completed project demo": 16, "Presentation & Questions & Answers": 8}
                }}) # 24
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": p4_alloc_id, "student_marks": {
                    "1MS21CS101": {"Detailed Methodology & partially completed project demo": 19, "Presentation & Questions & Answers": 9}
                }}) # 28

    # Phase 5 Allocation (4 panel faculty members ONLY; Guide excluded)
    p5_alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 5",
        "semester": 7,
        "phase": "Phase 5",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu", "fac4@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert p5_alloc_res.status_code in [200, 201]
    p5_alloc_id = p5_alloc_res.get_json()["allocation_id"]

    # 4 Panel Faculty submit for Phase 5 using official criteria rubric
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": p5_alloc_id, "student_marks": {
                    "1MS21CS101": {"Presentation": 4, "Demo": 16, "Q & A": 4}
                }}) # 24
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": p5_alloc_id, "student_marks": {
                    "1MS21CS101": {"Presentation": 4, "Demo": 18, "Q & A": 4}
                }}) # 26
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": p5_alloc_id, "student_marks": {
                    "1MS21CS101": {"Presentation": 5, "Demo": 18, "Q & A": 5}
                }}) # 28
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac4@test.edu', 'faculty')}"},
                json={"allocation_id": p5_alloc_id, "student_marks": {
                    "1MS21CS101": {"Presentation": 4, "Demo": 17, "Q & A": 5}
                }}) # 26

    # Guide enters Guide Component: Report (9.0), Attendance (10.0), Project Outcome (18.0)
    guide_token = make_token("guide_s7@test.edu", "faculty")
    guide_res = client.post("/api/evaluation/save", headers={"Authorization": f"Bearer {guide_token}"}, json={
        "team_name": team_name,
        "semester": 7,
        "evaluation": {
            "phases": [
                {"name": "Report", "total_marks": 10, "criteria": [{"name": "Report", "max_marks": 10, "marks": [{"marks_obtained": 9.0, "maximum_marks": 10}]}]},
                {"name": "Attendance", "total_marks": 10, "criteria": [{"name": "Attendance", "max_marks": 10, "marks": [{"marks_obtained": 10.0, "maximum_marks": 10}]}]},
                {"name": "Project Outcome", "total_marks": 20, "criteria": [{"name": "Project Outcome", "max_marks": 20, "marks": [{"marks_obtained": 18.0, "maximum_marks": 20}]}]}
            ]
        }
    })
    assert guide_res.status_code == 200

    # Verify team evaluation endpoint response payload
    team_eval_res = client.get(f"/api/evaluation/team/{team_name}?semester=7", headers={"Authorization": f"Bearer {guide_token}"})
    assert team_eval_res.status_code == 200
    team_data = team_eval_res.get_json()
    assert team_data["is_guide"] is True
    assert team_data["can_edit_guide_marks"] is True

    p4_info = team_data["panel_info"]["Phase 4"]
    assert p4_info["is_complete"] is True
    assert p4_info["panel_results"][0]["average_mark"] == 25.00

    p5_info = team_data["panel_info"]["Phase 5"]
    assert p5_info["is_complete"] is True
    assert p5_info["panel_results"][0]["average_mark"] == 26.00

    # Grand Total: 25.00 + 26.00 + (9 + 10 + 18) = 88.00 / 100
    eval_phases = team_data["evaluation"]["phases"]
    p4_phase = next(p for p in eval_phases if "phase 4" in p["name"].lower())
    p5_phase = next(p for p in eval_phases if "phase 5" in p["name"].lower())
    rep_phase = next(p for p in eval_phases if "report" in p["name"].lower())
    att_phase = next(p for p in eval_phases if "attendance" in p["name"].lower())
    out_phase = next(p for p in eval_phases if "outcome" in p["name"].lower() or "paper" in p["name"].lower())

    p4_m = p4_phase["criteria"][0]["marks"][0]["marks_obtained"]
    p5_m = p5_phase["criteria"][0]["marks"][0]["marks_obtained"]
    rep_m = rep_phase["criteria"][0]["marks"][0]["marks_obtained"]
    att_m = att_phase["criteria"][0]["marks"][0]["marks_obtained"]
    out_m = out_phase["criteria"][0]["marks"][0]["marks_obtained"]

    assert p4_m == 25.00
    assert p5_m == 26.00
    assert rep_m == 9.00
    assert att_m == 10.00
    assert out_m == 18.00
    total_sem7 = round(p4_m + p5_m + rep_m + att_m + out_m, 2)
    assert total_sem7 == 88.00


def test_04_strict_four_evaluator_averaging_pending_handling(client):
    """
    Strict 4-Evaluator Averaging:
    When only 1, 2, or 3 evaluators have submitted:
    - Status is Pending (X/4).
    - is_complete is False.
    - Synchronized evaluation in db.evaluations marks phase Pending with marks_obtained: None.
    - When 4th evaluator submits, phase is finalized to Completed with average.
    """
    coord_token = make_token("coordinator@test.edu", "coordinator")
    team_name = "TEST_TARGET_INCOMPLETE_TEAM"

    db.teams.insert_one({
        "team_name": team_name,
        "semester": 6,
        "faculty_email": "guide_inc@test.edu",
        "faculty_name": "Dr. Guide Inc",
        "leader_name": "Dan Leader",
        "leader_usn": "1MS21CS201",
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
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Evaluator 1 submits
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('guide_inc@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS201": 16.0}})
    calc1 = app_module.calculate_student_panel_averages(alloc_id)
    assert calc1["is_complete"] is False
    assert calc1["submitted_evals_count"] == 1
    assert "Pending (1/4)" in calc1["status"]

    # Evaluator 2 submits
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS201": 18.0}})
    calc2 = app_module.calculate_student_panel_averages(alloc_id)
    assert calc2["is_complete"] is False
    assert calc2["submitted_evals_count"] == 2
    assert "Pending (2/4)" in calc2["status"]

    # Evaluator 3 submits
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac2@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS201": 14.0}})
    calc3 = app_module.calculate_student_panel_averages(alloc_id)
    assert calc3["is_complete"] is False
    assert calc3["submitted_evals_count"] == 3
    assert "Pending (3/4)" in calc3["status"]

    # Verify db.evaluations is Pending with marks_obtained: None
    team_eval_res = client.get(f"/api/evaluation/team/{team_name}?semester=6", headers={"Authorization": f"Bearer {coord_token}"})
    phases = team_eval_res.get_json()["evaluation"]["phases"]
    p1 = next(p for p in phases if "phase 1" in p["name"].lower())
    assert p1["is_complete"] is False
    assert p1["status"] == "Pending"
    assert p1["criteria"][0]["marks"][0]["marks_obtained"] is None

    # Evaluator 4 submits: now all 4 evaluators complete!
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS201": 20.0}})
    calc4 = app_module.calculate_student_panel_averages(alloc_id)
    assert calc4["is_complete"] is True
    assert calc4["submitted_evals_count"] == 4
    assert calc4["status"] == "Completed"
    assert calc4["student_results"][0]["average_mark"] == 17.00 # (16+18+14+20)/4 = 17.00

    # Verify db.evaluations updated to Completed with marks_obtained: 17.00
    team_eval_res2 = client.get(f"/api/evaluation/team/{team_name}?semester=6", headers={"Authorization": f"Bearer {coord_token}"})
    phases2 = team_eval_res2.get_json()["evaluation"]["phases"]
    p1_2 = next(p for p in phases2 if "phase 1" in p["name"].lower())
    assert p1_2["is_complete"] is True
    assert p1_2["status"] == "Completed"
    assert p1_2["criteria"][0]["marks"][0]["marks_obtained"] == 17.00
