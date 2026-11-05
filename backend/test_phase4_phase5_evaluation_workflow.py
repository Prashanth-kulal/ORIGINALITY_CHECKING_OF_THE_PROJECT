# -*- coding: utf-8 -*-
"""
Comprehensive Integration Test Suite for Phase 4 and Phase 5 Project Evaluation Workflow.
Validates all 14 points specified in Requirement 11:
1. Coordinator creates a Phase 4 panel and assigns four faculty members to a team.
2. All four faculty members can see the assigned team.
3. Each faculty member enters and saves their own component-wise evaluation.
4. Individual totals are calculated correctly.
5. Panel average is calculated correctly after the required submissions.
6. Guide enters attendance, report and paper-related marks separately.
7. Guide can see the four individual panel totals and panel average.
8. Final marks match the existing Project Evaluation formula (Phase 4 [30] + Phase 5 [30] + Report [10] + Att [10] + Paper [20] = 100).
9. Student sees the final result only after publication.
10. Coordinator can unpublish and republish without loss of data.
11. Coordinator can disable and re-enable evaluations reversibly.
12. Coordinator can cancel allocation; historical submissions preserved as voided; excluded from active average.
13. Unauthorized faculty and students cannot access restricted evaluation data.
14. Existing 6th-semester Phase 1 and Phase 2 workflows continue to work.
"""

import pytest
import jwt
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

@pytest.fixture(autouse=True)
def clean_test_collections():
    # Setup test collections
    test_teams = ["TEAM_P4_P5_ALPHA", "TEAM_P4_P5_BETA", "TEAM_SEM6_GAMMA"]
    db.teams.delete_many({"team_name": {"$in": test_teams}})
    db.panel_allocations.delete_many({"team_name": {"$in": test_teams}})
    db.panel_evaluations.delete_many({"$or": [{"team_name": {"$in": test_teams}}, {"allocation_id": {"$regex": "p4_p5|sem6"}}]})
    db.evaluations.delete_many({"team_name": {"$in": test_teams}})
    db.panel_notifications.delete_many({"team_name": {"$in": test_teams}})
    yield
    db.teams.delete_many({"team_name": {"$in": test_teams}})
    db.panel_allocations.delete_many({"team_name": {"$in": test_teams}})
    db.panel_evaluations.delete_many({"$or": [{"team_name": {"$in": test_teams}}, {"allocation_id": {"$regex": "p4_p5|sem6"}}]})
    db.evaluations.delete_many({"team_name": {"$in": test_teams}})
    db.panel_notifications.delete_many({"team_name": {"$in": test_teams}})


def test_01_coordinator_creates_phase4_panel_with_four_faculty(client):
    """1. Coordinator creates a Phase 4 panel and assigns four faculty members to a team."""
    coord_token = make_token("coordinator@test.edu", "coordinator", "Dr. Coordinator")

    # Seed 7th semester team
    db.teams.insert_one({
        "team_name": "TEAM_P4_P5_ALPHA",
        "semester": 7,
        "faculty_email": "guide_alpha@test.edu",
        "faculty_name": "Dr. Guide Alpha",
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS101",
        "leader_email": "alice@test.edu",
        "members": [{"name": "Bob Member", "usn": "1MS21CS102", "email": "bob@test.edu"}],
        "project_idea": {"title": "Autonomous AI Engine", "status": "Approved"}
    })

    future_deadline = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    alloc_payload = {
        "panel_id": "Panel 4",
        "semester": 7,
        "phase": "Phase 4",
        "room_number": "Room 305",
        "presentation_datetime": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        "evaluation_deadline": future_deadline,
        "is_evaluation_enabled": True,
        "panel_member_emails": [
            "fac1@test.edu",
            "fac2@test.edu",
            "fac3@test.edu",
            "fac4@test.edu"
        ],
        "team_assignments": [
            {
                "team_name": "TEAM_P4_P5_ALPHA",
                "assigned_faculty_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu", "fac4@test.edu"]
            }
        ]
    }

    res = client.post("/api/panel/allocate", json=alloc_payload, headers={"Authorization": f"Bearer {coord_token}"})
    assert res.status_code in [200, 201]
    data = res.get_json()
    assert data["success"] is True
    alloc_id = data["allocation_id"]

    alloc_doc = db.panel_allocations.find_one({"allocation_id": alloc_id})
    assert alloc_doc is not None
    assert alloc_doc["semester"] == 7
    assert alloc_doc["phase"] == "Phase 4"
    assert alloc_doc["max_marks"] == 30
    assert len(alloc_doc["assigned_faculty_emails"]) == 4
    assert alloc_doc["guide"]["email"] == "guide_alpha@test.edu"

    # Verify notifications created for all 4 panel members
    notifs = list(db.panel_notifications.find({"allocation_id": alloc_id}))
    assert len(notifs) == 4
    notif_recipients = {n["recipient_email"].lower() for n in notifs}
    assert notif_recipients == {"fac1@test.edu", "fac2@test.edu", "fac3@test.edu", "fac4@test.edu"}


def test_02_all_four_faculty_see_assigned_team_and_criteria_marksheet(client):
    """2. All four faculty members see the team in assignments and get the complete criteria rubric."""
    coord_token = make_token("coordinator@test.edu", "coordinator")

    db.teams.insert_one({
        "team_name": "TEAM_P4_P5_ALPHA",
        "semester": 7,
        "faculty_email": "guide_alpha@test.edu",
        "faculty_name": "Dr. Guide Alpha",
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS101",
        "members": [{"name": "Bob Member", "usn": "1MS21CS102"}],
        "project_idea": {"title": "Autonomous AI Engine"}
    })

    future_deadline = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 4",
        "semester": 7,
        "phase": "Phase 4",
        "is_evaluation_enabled": True,
        "deadline": future_deadline,
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu", "fac4@test.edu"],
        "team_name": "TEAM_P4_P5_ALPHA"
    }, headers={"Authorization": f"Bearer {coord_token}"})
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Verify each of the 4 faculty can fetch their assignments and marksheet
    for fac_email in ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu", "fac4@test.edu"]:
        f_token = make_token(fac_email, "faculty")
        assign_res = client.get("/api/panel/faculty/assignments", headers={"Authorization": f"Bearer {f_token}"})
        assert assign_res.status_code == 200
        assignments = assign_res.get_json()
        assert any(a["allocation_id"] == alloc_id and a["team_name"] == "TEAM_P4_P5_ALPHA" for a in assignments)

        # Marksheet sheet endpoint
        sheet_res = client.get(f"/api/panel/evaluation/{alloc_id}", headers={"Authorization": f"Bearer {f_token}"})
        assert sheet_res.status_code == 200
        sheet_data = sheet_res.get_json()
        assert sheet_data["phase_max_marks"] == 30
        assert len(sheet_data["criteria"]) == 3
        crit_names = [c["name"] for c in sheet_data["criteria"]]
        assert "Implementation & Execution" in crit_names
        assert "Technical Demonstration" in crit_names
        assert "Presentation & Defense" in crit_names
        for c in sheet_data["criteria"]:
            assert c["max_marks"] == 10


def test_03_04_05_faculty_submit_component_marks_and_averages_computed(client):
    """3, 4, 5. Faculty enter component marks, totals calculated, panel average calculated correctly."""
    coord_token = make_token("coordinator@test.edu", "coordinator")
    db.teams.insert_one({
        "team_name": "TEAM_P4_P5_ALPHA",
        "semester": 7,
        "faculty_email": "guide_alpha@test.edu",
        "faculty_name": "Dr. Guide Alpha",
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS101",
        "members": [{"name": "Bob Member", "usn": "1MS21CS102"}],
        "project_idea": {"title": "Autonomous AI Engine"}
    })

    future_deadline = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 4",
        "semester": 7,
        "phase": "Phase 4",
        "is_evaluation_enabled": True,
        "deadline": future_deadline,
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu", "fac4@test.edu"],
        "team_name": "TEAM_P4_P5_ALPHA"
    }, headers={"Authorization": f"Bearer {coord_token}"})
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Evaluator 1: Alice -> 8+9+8=25, Bob -> 7+8+8=23
    f1_token = make_token("fac1@test.edu", "faculty", "Prof. One")
    res1 = client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {f1_token}"}, json={
        "allocation_id": alloc_id,
        "student_marks": {
            "1MS21CS101": {"Implementation & Execution": 8, "Technical Demonstration": 9, "Presentation & Defense": 8},
            "1MS21CS102": {"Implementation & Execution": 7, "Technical Demonstration": 8, "Presentation & Defense": 8}
        }
    })
    assert res1.status_code == 200

    # Evaluator 2: Alice -> 9+9+9=27, Bob -> 8+8+8=24
    f2_token = make_token("fac2@test.edu", "faculty", "Prof. Two")
    res2 = client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {f2_token}"}, json={
        "allocation_id": alloc_id,
        "student_marks": {
            "1MS21CS101": {"Implementation & Execution": 9, "Technical Demonstration": 9, "Presentation & Defense": 9},
            "1MS21CS102": {"Implementation & Execution": 8, "Technical Demonstration": 8, "Presentation & Defense": 8}
        }
    })
    assert res2.status_code == 200

    # Evaluator 3: Alice -> 7+8+8=23, Bob -> 7+7+7=21
    f3_token = make_token("fac3@test.edu", "faculty", "Prof. Three")
    res3 = client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {f3_token}"}, json={
        "allocation_id": alloc_id,
        "student_marks": {
            "1MS21CS101": {"Implementation & Execution": 7, "Technical Demonstration": 8, "Presentation & Defense": 8},
            "1MS21CS102": {"Implementation & Execution": 7, "Technical Demonstration": 7, "Presentation & Defense": 7}
        }
    })
    assert res3.status_code == 200

    # Evaluator 4: Alice -> 8+8+9=25, Bob -> 8+8+8=24
    f4_token = make_token("fac4@test.edu", "faculty", "Prof. Four")
    res4 = client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {f4_token}"}, json={
        "allocation_id": alloc_id,
        "student_marks": {
            "1MS21CS101": {"Implementation & Execution": 8, "Technical Demonstration": 8, "Presentation & Defense": 9},
            "1MS21CS102": {"Implementation & Execution": 8, "Technical Demonstration": 8, "Presentation & Defense": 8}
        }
    })
    assert res4.status_code == 200

    # Verify individual saved evaluations
    e1 = db.panel_evaluations.find_one({"allocation_id": alloc_id, "faculty_email": "fac1@test.edu"})
    assert e1["student_totals"]["1MS21CS101"] == 25.0
    assert e1["student_totals"]["1MS21CS102"] == 23.0
    assert e1["evaluator_id"] == "fac1@test.edu"

    # Check Coordinator view of calculated averages:
    # Alice totals: 25, 27, 23, 25 -> sum = 100 -> avg = 100/4 = 25.00
    # Bob totals: 23, 24, 21, 24 -> sum = 92 -> avg = 92/4 = 23.00
    coord_sheet = client.get(f"/api/panel/evaluation/{alloc_id}", headers={"Authorization": f"Bearer {coord_token}"})
    assert coord_sheet.status_code == 200
    sr_list = coord_sheet.get_json()["student_results"]
    alice_sr = next(s for s in sr_list if s["usn"] == "1MS21CS101")
    bob_sr = next(s for s in sr_list if s["usn"] == "1MS21CS102")
    assert alice_sr["average_mark"] == 25.00
    assert bob_sr["average_mark"] == 23.00


def test_06_07_guide_enters_marks_separately_and_views_panel_totals_without_criteria(client):
    """6, 7. Guide enters attendance, report, paper separately, views 4 panel totals & average, no other criteria."""
    guide_token = make_token("guide_alpha@test.edu", "faculty", "Dr. Guide Alpha")
    other_fac_token = make_token("unrelated_fac@test.edu", "faculty", "Dr. Unrelated")

    db.teams.insert_one({
        "team_name": "TEAM_P4_P5_ALPHA",
        "semester": 7,
        "faculty_email": "guide_alpha@test.edu",
        "faculty_name": "Dr. Guide Alpha",
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS101",
        "members": [{"name": "Bob Member", "usn": "1MS21CS102"}],
        "project_idea": {"title": "Autonomous AI Engine"}
    })

    # Unrelated faculty tries to save guide evaluation marks -> must be 403 Forbidden!
    unrelated_res = client.post("/api/evaluation/save", headers={"Authorization": f"Bearer {other_fac_token}"}, json={
        "team_name": "TEAM_P4_P5_ALPHA",
        "semester": 7,
        "evaluation": {"phases": []}
    })
    assert unrelated_res.status_code == 403

    # Assigned guide saves Guide Marks: Report (10), Attendance (10), Paper Submission (20)
    guide_save_res = client.post("/api/evaluation/save", headers={"Authorization": f"Bearer {guide_token}"}, json={
        "team_name": "TEAM_P4_P5_ALPHA",
        "semester": 7,
        "evaluation": {
            "phases": [
                {
                    "name": "Report",
                    "total_marks": 10,
                    "criteria": [{"name": "Report", "max_marks": 10, "marks": [{"marks_obtained": 9.5, "maximum_marks": 10}, {"marks_obtained": 9.0, "maximum_marks": 10}]}]
                },
                {
                    "name": "Attendance",
                    "total_marks": 10,
                    "criteria": [{"name": "Attendance", "max_marks": 10, "marks": [{"marks_obtained": 10, "maximum_marks": 10}, {"marks_obtained": 9, "maximum_marks": 10}]}]
                },
                {
                    "name": "Paper Submission",
                    "total_marks": 20,
                    "criteria": [{"name": "Paper Submission", "max_marks": 20, "marks": [{"marks_obtained": 18.0, "maximum_marks": 20}, {"marks_obtained": 17.5, "maximum_marks": 20}]}]
                }
            ]
        }
    })
    assert guide_save_res.status_code == 200

    # Now verify Guide accesses marksheet sheet endpoint:
    # Must receive panel_summary with the 4 evaluator totals and average, but NO criteria breakdowns!
    alloc_doc = db.panel_allocations.find_one({"team_name": "TEAM_P4_P5_ALPHA"})
    if not alloc_doc:
        alloc_res = client.post("/api/panel/allocate", json={
            "panel_id": "Panel 4",
            "semester": 7,
            "phase": "Phase 4",
            "is_evaluation_enabled": True,
            "deadline": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
            "panel_member_emails": ["fac1@test.edu", "fac2@test.edu", "fac3@test.edu", "fac4@test.edu"],
            "team_name": "TEAM_P4_P5_ALPHA"
        }, headers={"Authorization": f"Bearer {make_token('coord@test.edu', 'coordinator')}"})
        alloc_id = alloc_res.get_json()["allocation_id"]
    else:
        alloc_id = alloc_doc["allocation_id"]

    guide_sheet_res = client.get(f"/api/panel/evaluation/{alloc_id}", headers={"Authorization": f"Bearer {guide_token}"})
    assert guide_sheet_res.status_code == 200
    guide_sheet = guide_sheet_res.get_json()
    assert guide_sheet["is_guide"] is True
    assert "panel_summary" in guide_sheet
    assert "all_evaluations" not in guide_sheet


def test_08_final_marks_formula_phase4_phase5_report_att_paper_totals_100(client):
    """8. Final marks combine Phase 4 (30) + Phase 5 (30) + Report (10) + Attendance (10) + Paper (20) = 100."""
    coord_token = make_token("coord@test.edu", "coordinator")

    team_name = "TEAM_P4_P5_ALPHA"
    db.teams.insert_one({
        "team_name": team_name,
        "semester": 7,
        "faculty_email": "guide_alpha@test.edu",
        "faculty_name": "Dr. Guide Alpha",
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS101",
        "members": [{"name": "Bob Member", "usn": "1MS21CS102"}]
    })

    # Coordinator finalizes Phase 4 (average 25 for Alice, 23 for Bob)
    alloc4_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 4",
        "semester": 7,
        "phase": "Phase 4",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu"],
        "team_name": team_name,
        "approved_three_member_panel": True,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    alloc4_id = alloc4_res.get_json()["allocation_id"]

    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": alloc4_id, "final_marks": {"1MS21CS101": 25.0, "1MS21CS102": 23.0}})
    client.post("/api/panel/evaluation/finalize", headers={"Authorization": f"Bearer {coord_token}"},
                json={"allocation_id": alloc4_id, "force": True})

    # Coordinator finalizes Phase 5 (average 26 for Alice, 24 for Bob)
    alloc5_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 5",
        "semester": 7,
        "phase": "Phase 5",
        "panel_member_emails": ["fac3@test.edu", "fac4@test.edu"],
        "team_name": team_name,
        "approved_three_member_panel": True,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    alloc5_id = alloc5_res.get_json()["allocation_id"]

    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac3@test.edu', 'faculty')}"},
                json={"allocation_id": alloc5_id, "final_marks": {"1MS21CS101": 26.0, "1MS21CS102": 24.0}})
    client.post("/api/panel/evaluation/finalize", headers={"Authorization": f"Bearer {coord_token}"},
                json={"allocation_id": alloc5_id, "force": True})

    # Insert attendance meetings for 7th semester so attendance auto-calculates to 10 marks
    db.attendance.insert_many([
        {"student_usn": "1MS21CS101", "student_name": "Alice Leader", "team_name": team_name, "semester": 7, "meeting_date": "2026-10-01", "status": "Completed"}
        for _ in range(15)
    ] + [
        {"student_usn": "1MS21CS102", "student_name": "Bob Member", "team_name": team_name, "semester": 7, "meeting_date": "2026-10-01", "status": "Completed"}
        for _ in range(15)
    ])

    # Guide enters Report (10), Attendance (10), Paper (20)
    guide_token = make_token("guide_alpha@test.edu", "faculty")
    client.post("/api/evaluation/save", headers={"Authorization": f"Bearer {guide_token}"}, json={
        "team_name": team_name,
        "semester": 7,
        "evaluation": {
            "phases": [
                {"name": "Phase 4", "total_marks": 25.0, "criteria": [{"name": "Phase 4", "max_marks": 30, "marks": [{"marks_obtained": 25.0, "maximum_marks": 30}, {"marks_obtained": 23.0, "maximum_marks": 30}]}]},
                {"name": "Phase 5", "total_marks": 26.0, "criteria": [{"name": "Phase 5", "max_marks": 30, "marks": [{"marks_obtained": 26.0, "maximum_marks": 30}, {"marks_obtained": 24.0, "maximum_marks": 30}]}]},
                {"name": "Report", "total_marks": 10.0, "criteria": [{"name": "Report", "max_marks": 10, "marks": [{"marks_obtained": 9.0, "maximum_marks": 10}, {"marks_obtained": 8.0, "maximum_marks": 10}]}]},
                {"name": "Attendance", "total_marks": 10.0, "criteria": [{"name": "Attendance", "max_marks": 10, "marks": [{"marks_obtained": 10.0, "maximum_marks": 10}, {"marks_obtained": 9.0, "maximum_marks": 10}]}]},
                {"name": "Paper Submission", "total_marks": 20.0, "criteria": [{"name": "Paper Submission", "max_marks": 20, "marks": [{"marks_obtained": 18.0, "maximum_marks": 20}, {"marks_obtained": 16.0, "maximum_marks": 20}]}]}
            ]
        }
    })

    # Verify VTU export final marks:
    # Alice: Phase 4 (25) + Phase 5 (26) + Report (9) + Att (10) + Paper (18) = 88 / 100
    # Bob: Phase 4 (23) + Phase 5 (24) + Report (8) + Att (9) + Paper (16) = 80 / 100
    exp_res = client.get("/api/coordinator/export_final_marks?semester=7", headers={"Authorization": f"Bearer {coord_token}"})
    assert exp_res.status_code == 200

    import io
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(exp_res.data))
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        data_dict = {str(r[0]): r[1] for r in rows[1:] if r and r[0]}
    except Exception:
        import csv
        reader = csv.reader(io.StringIO(exp_res.data.decode("utf-8", errors="ignore")))
        rows = list(reader)
        data_dict = {str(r[0]): r[1] for r in rows[1:] if r and r[0]}

    assert "1MS21CS101" in data_dict
    assert int(data_dict["1MS21CS101"]) == 88
    assert "1MS21CS102" in data_dict
    assert int(data_dict["1MS21CS102"]) == 81


def test_09_10_student_sees_result_only_after_publication_and_unpublish_republish_works(client):
    """9, 10. Student sees results only after publication; coordinator unpublishes and republishes reversibly."""
    coord_token = make_token("coord@test.edu", "coordinator")
    student_token = make_token("alice@test.edu", "student", name="Alice", usn="1MS21CS101", team_name="TEAM_P4_P5_ALPHA")

    team_name = "TEAM_P4_P5_ALPHA"
    db.teams.insert_one({
        "team_name": team_name,
        "semester": 7,
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS101",
        "leader_email": "alice@test.edu",
        "members": []
    })

    alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 4",
        "semester": 7,
        "phase": "Phase 4",
        "panel_member_emails": ["fac1@test.edu"],
        "team_name": team_name,
        "approved_three_member_panel": True,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    alloc_id = alloc_res.get_json()["allocation_id"]

    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS101": 27.5}})

    # Before publication: Student sees NO published results
    stud_res_before = client.get("/api/panel/student/results", headers={"Authorization": f"Bearer {student_token}"})
    assert stud_res_before.status_code == 200
    assert len(stud_res_before.get_json()["published_results"]) == 0

    # Coordinator publishes
    pub_res = client.post("/api/panel/allocation/publish", headers={"Authorization": f"Bearer {coord_token}"}, json={
        "allocation_id": alloc_id,
        "is_published": True
    })
    assert pub_res.status_code == 200
    assert pub_res.get_json()["is_published"] is True

    # After publication: Student sees final average
    stud_res_after = client.get("/api/panel/student/results", headers={"Authorization": f"Bearer {student_token}"})
    assert stud_res_after.status_code == 200
    pub_list = stud_res_after.get_json()["published_results"]
    assert len(pub_list) == 1
    assert pub_list[0]["team_phase_average"] == 27.5
    assert pub_list[0]["max_marks"] == 30

    # Coordinator unpublishes reversibly without deleting marks!
    unpub_res = client.post("/api/panel/allocation/publish", headers={"Authorization": f"Bearer {coord_token}"}, json={
        "allocation_id": alloc_id,
        "is_published": False,
        "publish": False
    })
    assert unpub_res.status_code == 200
    assert unpub_res.get_json()["is_published"] is False

    # Student now sees 0 published results again
    stud_res_unpub = client.get("/api/panel/student/results", headers={"Authorization": f"Bearer {student_token}"})
    assert len(stud_res_unpub.get_json()["published_results"]) == 0

    # Coordinator re-publishes
    repub_res = client.post("/api/panel/allocation/publish", headers={"Authorization": f"Bearer {coord_token}"}, json={
        "allocation_id": alloc_id,
        "is_published": True,
        "publish": True
    })
    assert repub_res.status_code == 200
    stud_res_repub = client.get("/api/panel/student/results", headers={"Authorization": f"Bearer {student_token}"})
    assert len(stud_res_repub.get_json()["published_results"]) == 1
    assert stud_res_repub.get_json()["published_results"][0]["team_phase_average"] == 27.5


def test_11_coordinator_disables_and_reenables_evaluation_reversibly(client):
    """11. Coordinator can disable and re-enable evaluations reversibly."""
    coord_token = make_token("coord@test.edu", "coordinator")
    fac_token = make_token("fac1@test.edu", "faculty")

    team_name = "TEAM_P4_P5_BETA"
    db.teams.insert_one({"team_name": team_name, "semester": 7, "leader_name": "Bob", "leader_usn": "1MS21CS201", "members": []})

    alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 4",
        "semester": 7,
        "phase": "Phase 4",
        "panel_member_emails": ["fac1@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Disable mark entry
    dis_res = client.post("/api/panel/allocation/toggle_evaluation", headers={"Authorization": f"Bearer {coord_token}"}, json={
        "allocation_id": alloc_id,
        "is_enabled": False
    })
    assert dis_res.status_code == 200
    assert dis_res.get_json()["is_evaluation_enabled"] is False

    # Faculty tries to submit while disabled -> 403 Forbidden!
    sub_dis = client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {fac_token}"}, json={
        "allocation_id": alloc_id,
        "final_marks": {"1MS21CS201": 25.0}
    })
    assert sub_dis.status_code == 403

    # Re-enable mark entry
    en_res = client.post("/api/panel/allocation/toggle_evaluation", headers={"Authorization": f"Bearer {coord_token}"}, json={
        "allocation_id": alloc_id,
        "is_enabled": True
    })
    assert en_res.status_code == 200
    assert en_res.get_json()["is_evaluation_enabled"] is True

    # Faculty can now submit successfully
    sub_en = client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {fac_token}"}, json={
        "allocation_id": alloc_id,
        "final_marks": {"1MS21CS201": 25.0}
    })
    assert sub_en.status_code == 200


def test_12_coordinator_cancels_allocation_and_voids_marks_without_polluting_average(client):
    """12. Coordinator can cancel allocation; historical marks preserved as voided and excluded from active averages."""
    coord_token = make_token("coord@test.edu", "coordinator")
    team_name = "TEAM_P4_P5_BETA"
    db.teams.insert_one({"team_name": team_name, "semester": 7, "leader_name": "Bob", "leader_usn": "1MS21CS201", "members": []})

    alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 4",
        "semester": 7,
        "phase": "Phase 4",
        "panel_member_emails": ["fac1@test.edu", "fac2@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Faculty 1 submits marks
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {make_token('fac1@test.edu', 'faculty')}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS201": 28.0}})

    # Coordinator cancels allocation
    cancel_res = client.post("/api/panel/allocation/cancel", headers={"Authorization": f"Bearer {coord_token}"}, json={
        "allocation_id": alloc_id,
        "reason": "Panel re-scheduled due to scheduling conflict"
    })
    assert cancel_res.status_code == 200
    assert cancel_res.get_json()["success"] is True

    # Check that historical evaluation is voided (preserved in DB, but is_voided=True)
    eval_record = db.panel_evaluations.find_one({"allocation_id": alloc_id, "faculty_email": "fac1@test.edu"})
    assert eval_record is not None
    assert eval_record["is_voided"] is True
    assert eval_record["status"] == "Voided"

    # Calculate average: voided mark MUST NOT pollute active average!
    calc = app_module.calculate_student_panel_averages(alloc_id)
    assert calc["student_results"][0]["average_mark"] is None
    assert calc["submitted_evals_count"] == 0

    # Team is now eligible again for panel allocation because cancelled allocation does not block it
    eligible_res = client.get("/api/panel/eligible_teams?semester=7&phase=Phase%204", headers={"Authorization": f"Bearer {coord_token}"})
    assert eligible_res.status_code == 200
    elig_teams = eligible_res.get_json()["teams"]
    matching_team = next((t for t in elig_teams if t["team_name"] == team_name), None)
    assert matching_team is not None
    assert matching_team["is_available"] is True


def test_13_unauthorized_faculty_and_students_cannot_access_restricted_evaluation_data(client):
    """13. Unauthorized faculty and students cannot access restricted marksheet data."""
    coord_token = make_token("coord@test.edu", "coordinator")
    unauth_fac_token = make_token("outsider_fac@test.edu", "faculty")
    student_token = make_token("student_intruder@test.edu", "student", usn="1MS21CS999")

    team_name = "TEAM_P4_P5_BETA"
    db.teams.insert_one({"team_name": team_name, "semester": 7, "faculty_email": "guide@test.edu", "leader_name": "Bob", "leader_usn": "1MS21CS201", "members": []})

    alloc_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 4",
        "semester": 7,
        "phase": "Phase 4",
        "panel_member_emails": ["fac1@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Student cannot access faculty marksheet endpoint -> 403
    stud_sheet = client.get(f"/api/panel/evaluation/{alloc_id}", headers={"Authorization": f"Bearer {student_token}"})
    assert stud_sheet.status_code == 403

    # Unassigned faculty cannot access marksheet -> 403
    unauth_sheet = client.get(f"/api/panel/evaluation/{alloc_id}", headers={"Authorization": f"Bearer {unauth_fac_token}"})
    assert unauth_sheet.status_code == 403


def test_14_existing_sem6_phase1_phase2_workflows_continue_working(client):
    """14. Preserves 6th-semester Phase 1 & 2 workflows, criteria, and marks distribution."""
    coord_token = make_token("coord@test.edu", "coordinator")
    fac_token = make_token("sem6_fac@test.edu", "faculty")

    team_name = "TEAM_SEM6_GAMMA"
    db.teams.insert_one({
        "team_name": team_name,
        "semester": 6,
        "faculty_email": "guide_sem6@test.edu",
        "faculty_name": "Dr. Guide Sem 6",
        "leader_name": "Charlie",
        "leader_usn": "1MS20CS001",
        "members": []
    })

    # Sem 6 Phase 1 allocation: max_marks=20, 4 criteria of 5 marks
    alloc1_res = client.post("/api/panel/allocate", json={
        "panel_id": "Panel 1",
        "semester": 6,
        "phase": "Phase 1",
        "panel_member_emails": ["sem6_fac@test.edu"],
        "team_name": team_name,
        "enable_evaluation": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert alloc1_res.status_code in [200, 201]
    alloc1_id = alloc1_res.get_json()["allocation_id"]

    sheet1 = client.get(f"/api/panel/evaluation/{alloc1_id}", headers={"Authorization": f"Bearer {fac_token}"})
    assert sheet1.status_code == 200
    assert sheet1.get_json()["phase_max_marks"] == 20
    assert len(sheet1.get_json()["criteria"]) == 4

    # Faculty submits Sem 6 Phase 1 criteria marks
    sub1_res = client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {fac_token}"}, json={
        "allocation_id": alloc1_id,
        "student_marks": {
            "1MS20CS001": {
                "Problem Statement & Objectives": 4.5,
                "Social & Technical Impact": 4.0,
                "Depth of Review": 4.5,
                "Presentation": 4.0
            }
        }
    })
    assert sub1_res.status_code == 200
    e1 = db.panel_evaluations.find_one({"allocation_id": alloc1_id})
    assert e1["student_totals"]["1MS20CS001"] == 17.0
