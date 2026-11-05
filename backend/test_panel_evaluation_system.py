import os
import json
import pytest
import jwt
from datetime import datetime, timezone, timedelta
from backend.app import app, db

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture(autouse=True)
def clean_test_data():
    # Cleanup test collections before and after test
    db.panel_allocations.delete_many({"team_name": {"$regex": "^TEST_"}})
    db.panel_evaluations.delete_many({"team_name": {"$regex": "^TEST_"}})
    db.panel_notifications.delete_many({"team_name": {"$regex": "^TEST_"}})
    db.panel_audit_logs.delete_many({"team_name": {"$regex": "^TEST_"}})
    db.evaluations.delete_many({"team_name": {"$regex": "^TEST_"}})
    db.teams.delete_many({"team_name": {"$regex": "^TEST_"}})
    db.users.delete_many({"email": {"$regex": "^test_.*@example.com$"}})
    yield
    db.panel_allocations.delete_many({"team_name": {"$regex": "^TEST_"}})
    db.panel_evaluations.delete_many({"team_name": {"$regex": "^TEST_"}})
    db.panel_notifications.delete_many({"team_name": {"$regex": "^TEST_"}})
    db.panel_audit_logs.delete_many({"team_name": {"$regex": "^TEST_"}})
    db.evaluations.delete_many({"team_name": {"$regex": "^TEST_"}})
    db.teams.delete_many({"team_name": {"$regex": "^TEST_"}})
    db.users.delete_many({"email": {"$regex": "^test_.*@example.com$"}})

def create_token(email, role="faculty", name="Test Faculty", usn=None):
    payload = {
        "email": email,
        "role": role,
        "name": name,
        "exp": datetime.now(timezone.utc) + timedelta(hours=2)
    }
    if usn:
        payload["usn"] = usn
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

def test_panel_allocation_and_notifications(client):
    coord_token = create_token("test_coord@example.com", role="coordinator", name="Dr. Coordinator")
    
    # Setup team
    db.teams.insert_one({
        "team_name": "TEST_TEAM_A",
        "faculty_email": "test_guide@example.com",
        "faculty_name": "Dr. Guide",
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS001",
        "members": [{"name": "Bob Member", "usn": "1MS21CS002"}],
        "project_idea": {"title": "AI Project System"}
    })

    future_deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    presentation_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

    # 1. Allocate 4-member panel
    payload = {
        "team_name": "TEST_TEAM_A",
        "semester": 6,
        "phase": "Phase 1",
        "guide_email": "test_guide@example.com",
        "member_1_email": "test_mem1@example.com",
        "member_1_name": "Prof. One",
        "member_2_email": "test_mem2@example.com",
        "member_2_name": "Prof. Two",
        "member_3_email": "test_mem3@example.com",
        "member_3_name": "Prof. Three",
        "deadline": future_deadline,
        "presentation_datetime": presentation_time
    }

    res = client.post("/api/panel/allocate", json=payload, headers={"Authorization": f"Bearer {coord_token}"})
    assert res.status_code == 201
    alloc_data = res.get_json()
    assert "allocation_id" in alloc_data
    alloc_id = alloc_data["allocation_id"]

    # Verify notifications created for all 4 members
    notifs = list(db.panel_notifications.find({"allocation_id": alloc_id}))
    assert len(notifs) == 4
    emails = {n["recipient_email"] for n in notifs}
    assert "test_guide@example.com" in emails
    assert "test_mem1@example.com" in emails
    assert "test_mem2@example.com" in emails
    assert "test_mem3@example.com" in emails

    # 2. Duplicate faculty member allocation prevention
    dup_payload = dict(payload)
    dup_payload["member_2_email"] = "test_mem1@example.com"
    dup_res = client.post("/api/panel/allocate", json=dup_payload, headers={"Authorization": f"Bearer {coord_token}"})
    assert dup_res.status_code == 400
    assert "duplicate" in dup_res.get_json()["error"].lower()

    # 3. Faculty assignments API
    mem1_token = create_token("test_mem1@example.com", role="faculty", name="Prof. One")
    assign_res = client.get("/api/panel/faculty/assignments", headers={"Authorization": f"Bearer {mem1_token}"})
    assert assign_res.status_code == 200
    assignments = assign_res.get_json()
    assert len(assignments) == 1
    assert assignments[0]["team_name"] == "TEST_TEAM_A"
    assert assignments[0]["phase"] == "Phase 1"
    assert assignments[0]["role_in_panel"] in ["member_1", "Panel Member"]

    # 4. Faculty notifications API
    notif_res = client.get("/api/panel/notifications", headers={"Authorization": f"Bearer {mem1_token}"})
    assert notif_res.status_code == 200
    notif_json = notif_res.get_json()
    assert notif_json["unread_count"] == 1
    notif_id = notif_json["notifications"][0]["notification_id"]

    # Mark as read
    read_res = client.post("/api/panel/notifications/read", json={"notification_id": notif_id}, headers={"Authorization": f"Bearer {mem1_token}"})
    assert read_res.status_code == 200
    notif_res2 = client.get("/api/panel/notifications", headers={"Authorization": f"Bearer {mem1_token}"})
    assert notif_res2.get_json()["unread_count"] == 0

def test_draft_saving_and_editable_resubmission(client):
    coord_token = create_token("test_coord@example.com", role="coordinator")
    guide_token = create_token("test_guide@example.com", role="faculty", name="Dr. Guide")
    mem1_token = create_token("test_mem1@example.com", role="faculty", name="Prof. One")
    mem2_token = create_token("test_mem2@example.com", role="faculty", name="Prof. Two")
    mem3_token = create_token("test_mem3@example.com", role="faculty", name="Prof. Three")

    db.teams.insert_one({
        "team_name": "TEST_TEAM_EDIT",
        "faculty_email": "test_guide@example.com",
        "faculty_name": "Dr. Guide",
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS001",
        "members": [{"name": "Bob Member", "usn": "1MS21CS002"}]
    })

    future_deadline = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    alloc_res = client.post("/api/panel/allocate", json={
        "team_name": "TEST_TEAM_EDIT",
        "semester": 6,
        "phase": "Phase 1",
        "guide_email": "test_guide@example.com",
        "member_1_email": "test_mem1@example.com",
        "member_2_email": "test_mem2@example.com",
        "member_3_email": "test_mem3@example.com",
        "deadline": future_deadline
    }, headers={"Authorization": f"Bearer {coord_token}"})
    alloc_id = alloc_res.get_json()["allocation_id"]

    # 1. Member 1 tries to save draft BEFORE coordinator authorizes -> 403 Forbidden
    draft_marks = {
        "1MS21CS001": {
            "Problem Statement & Objectives": 4,
            "Social & Technical Impact": 4.5,
            "Depth of Review": 3.5,
            "Presentation": 4
        },
        "1MS21CS002": {
            "Problem Statement & Objectives": 3.5,
            "Social & Technical Impact": 4,
            "Depth of Review": 4,
            "Presentation": 3.5
        }
    }
    unauth_save = client.post("/api/panel/evaluation/save", json={
        "allocation_id": alloc_id,
        "student_marks": draft_marks
    }, headers={"Authorization": f"Bearer {mem1_token}"})
    assert unauth_save.status_code == 403
    assert "Evaluation is not yet enabled by the coordinator." in unauth_save.get_json()["error"]

    # Sheet endpoint shows is_evaluation_enabled is False before coordinator enables it
    sheet_unauth = client.get(f"/api/panel/evaluation/{alloc_id}", headers={"Authorization": f"Bearer {mem1_token}"})
    assert sheet_unauth.status_code == 200
    assert sheet_unauth.get_json()["is_evaluation_enabled"] is False
    assert sheet_unauth.get_json()["editing_allowed"] is False
    assert "not yet enabled" in sheet_unauth.get_json()["disabled_reason"].lower()

    # Coordinator explicitly authorizes evaluation for the panel
    auth_res = client.post("/api/panel/allocation/toggle_evaluation", json={
        "allocation_id": alloc_id,
        "enable": True
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert auth_res.status_code == 200
    assert auth_res.get_json()["is_evaluation_enabled"] is True

    # Now Member 1 can save draft
    save_res = client.post("/api/panel/evaluation/save", json={
        "allocation_id": alloc_id,
        "student_marks": draft_marks
    }, headers={"Authorization": f"Bearer {mem1_token}"})
    assert save_res.status_code == 200

    # Verify draft saved without locking
    eval_doc = db.panel_evaluations.find_one({"allocation_id": alloc_id, "faculty_email": "test_mem1@example.com"})
    assert eval_doc is not None
    assert eval_doc["status"] == "Draft Saved"
    assert eval_doc["is_submitted"] is False

    # 2. Member 1 submits
    sub_res = client.post("/api/panel/evaluation/submit", json={
        "allocation_id": alloc_id,
        "student_marks": draft_marks
    }, headers={"Authorization": f"Bearer {mem1_token}"})
    assert sub_res.status_code == 200
    eval_doc = db.panel_evaluations.find_one({"allocation_id": alloc_id, "faculty_email": "test_mem1@example.com"})
    assert eval_doc["status"] == "Submitted"
    assert eval_doc["is_submitted"] is True

    # 3. Member 1 edits marks before deadline and resubmits
    corrected_marks = json.loads(json.dumps(draft_marks))
    corrected_marks["1MS21CS001"]["Problem Statement & Objectives"] = 5.0
    resub_res = client.post("/api/panel/evaluation/submit", json={
        "allocation_id": alloc_id,
        "student_marks": corrected_marks
    }, headers={"Authorization": f"Bearer {mem1_token}"})
    assert resub_res.status_code == 200
    eval_doc = db.panel_evaluations.find_one({"allocation_id": alloc_id, "faculty_email": "test_mem1@example.com"})
    assert eval_doc["status"] == "Submitted"
    assert eval_doc["student_marks"]["1MS21CS001"]["Problem Statement & Objectives"] == 5.0
    assert len(eval_doc.get("edit_history", [])) == 1

def test_deadline_enforcement_and_extension(client):
    coord_token = create_token("test_coord@example.com", role="coordinator")
    guide_token = create_token("test_guide@example.com", role="faculty")
    mem1_token = create_token("test_mem1@example.com", role="faculty")

    db.teams.insert_one({
        "team_name": "TEST_TEAM_DDL",
        "faculty_email": "test_guide@example.com",
        "faculty_name": "Dr. Guide",
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS001",
        "members": []
    })

    past_deadline = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    alloc_res = client.post("/api/panel/allocate", json={
        "team_name": "TEST_TEAM_DDL",
        "semester": 6,
        "phase": "Phase 1",
        "guide_email": "test_guide@example.com",
        "member_1_email": "test_mem1@example.com",
        "member_2_email": "test_mem2@example.com",
        "member_3_email": "test_mem3@example.com",
        "deadline": past_deadline
    }, headers={"Authorization": f"Bearer {coord_token}"})
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Enable evaluation
    client.post("/api/panel/allocation/toggle_evaluation", json={
        "allocation_id": alloc_id,
        "enable": True
    }, headers={"Authorization": f"Bearer {coord_token}"})

    # Try to submit after deadline -> Rejected 403
    marks = {"1MS21CS001": {"Problem Statement & Objectives": 4, "Social & Technical Impact": 4, "Depth of Review": 4, "Presentation": 4}}
    rej_res = client.post("/api/panel/evaluation/submit", json={
        "allocation_id": alloc_id,
        "student_marks": marks
    }, headers={"Authorization": f"Bearer {mem1_token}"})
    assert rej_res.status_code == 403
    assert "deadline" in rej_res.get_json()["error"].lower()

    # Coordinator extends deadline
    new_ddl = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    ext_res = client.post("/api/panel/update_deadline", json={
        "allocation_id": alloc_id,
        "new_deadline": new_ddl,
        "reason": "Extension granted for technical delay"
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert ext_res.status_code == 200

    # Now submission succeeds
    ok_res = client.post("/api/panel/evaluation/submit", json={
        "allocation_id": alloc_id,
        "student_marks": marks
    }, headers={"Authorization": f"Bearer {mem1_token}"})
    assert ok_res.status_code == 200

def test_member_replacement_workflow(client):
    coord_token = create_token("test_coord@example.com", role="coordinator")
    guide_token = create_token("test_guide@example.com", role="faculty")
    old_mem_token = create_token("test_old_mem@example.com", role="faculty")
    new_mem_token = create_token("test_new_mem@example.com", role="faculty", name="Prof. Replacement")

    db.teams.insert_one({
        "team_name": "TEST_TEAM_REP",
        "faculty_email": "test_guide@example.com",
        "faculty_name": "Dr. Guide",
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS001",
        "members": []
    })

    future_deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    alloc_res = client.post("/api/panel/allocate", json={
        "team_name": "TEST_TEAM_REP",
        "semester": 6,
        "phase": "Phase 1",
        "guide_email": "test_guide@example.com",
        "member_1_email": "test_old_mem@example.com",
        "member_2_email": "test_mem2@example.com",
        "member_3_email": "test_mem3@example.com",
        "deadline": future_deadline
    }, headers={"Authorization": f"Bearer {coord_token}"})
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Enable evaluation
    client.post("/api/panel/allocation/toggle_evaluation", json={
        "allocation_id": alloc_id,
        "enable": True
    }, headers={"Authorization": f"Bearer {coord_token}"})

    # Replace old_mem with new_mem
    rep_res = client.post("/api/panel/replace_member", json={
        "allocation_id": alloc_id,
        "old_faculty_email": "test_old_mem@example.com",
        "new_faculty_email": "test_new_mem@example.com",
        "new_faculty_name": "Prof. Replacement",
        "reason": "Faculty member on medical leave"
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert rep_res.status_code == 200

    # Old member attempts to submit -> 403 Forbidden
    marks = {"1MS21CS001": {"Problem Statement & Objectives": 4, "Social & Technical Impact": 4, "Depth of Review": 4, "Presentation": 4}}
    old_sub = client.post("/api/panel/evaluation/submit", json={
        "allocation_id": alloc_id,
        "student_marks": marks
    }, headers={"Authorization": f"Bearer {old_mem_token}"})
    assert old_sub.status_code == 403

    # New member can submit
    new_sub = client.post("/api/panel/evaluation/submit", json={
        "allocation_id": alloc_id,
        "student_marks": marks
    }, headers={"Authorization": f"Bearer {new_mem_token}"})
    assert new_sub.status_code == 200

def test_full_finalization_averaging_and_db_sync(client):
    coord_token = create_token("test_coord@example.com", role="coordinator")
    guide_token = create_token("test_guide@example.com", role="faculty", name="Dr. Guide")
    mem1_token = create_token("test_mem1@example.com", role="faculty", name="Prof. One")
    mem2_token = create_token("test_mem2@example.com", role="faculty", name="Prof. Two")
    mem3_token = create_token("test_mem3@example.com", role="faculty", name="Prof. Three")
    student_token = create_token("student@example.com", role="student", name="Alice Leader", usn="1MS21CS001")

    db.teams.insert_one({
        "team_name": "TEST_TEAM_FINAL",
        "faculty_email": "test_guide@example.com",
        "faculty_name": "Dr. Guide",
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS001",
        "leader_email": "student@example.com",
        "members": [],
        "project_idea": {"title": "Autonomous Project System"}
    })

    future_deadline = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    alloc_res = client.post("/api/panel/allocate", json={
        "team_name": "TEST_TEAM_FINAL",
        "semester": 6,
        "phase": "Phase 1",
        "guide_email": "test_guide@example.com",
        "member_1_email": "test_mem1@example.com",
        "member_2_email": "test_mem2@example.com",
        "member_3_email": "test_mem3@example.com",
        "deadline": future_deadline
    }, headers={"Authorization": f"Bearer {coord_token}"})
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Enable evaluation
    client.post("/api/panel/allocation/toggle_evaluation", json={
        "allocation_id": alloc_id,
        "enable": True
    }, headers={"Authorization": f"Bearer {coord_token}"})

    # Guide marks: 4, 4, 4, 4 = 16/20
    m_guide = {"1MS21CS001": {"Problem Statement & Objectives": 4, "Social & Technical Impact": 4, "Depth of Review": 4, "Presentation": 4}}
    # Mem1 marks: 5, 5, 4, 4 = 18/20
    m_mem1 = {"1MS21CS001": {"Problem Statement & Objectives": 5, "Social & Technical Impact": 5, "Depth of Review": 4, "Presentation": 4}}
    # Mem2 marks: 3, 4, 3, 4 = 14/20
    m_mem2 = {"1MS21CS001": {"Problem Statement & Objectives": 3, "Social & Technical Impact": 4, "Depth of Review": 3, "Presentation": 4}}
    # Mem3 marks: 5, 5, 5, 5 = 20/20
    m_mem3 = {"1MS21CS001": {"Problem Statement & Objectives": 5, "Social & Technical Impact": 5, "Depth of Review": 5, "Presentation": 5}}

    client.post("/api/panel/evaluation/submit", json={"allocation_id": alloc_id, "student_marks": m_guide}, headers={"Authorization": f"Bearer {guide_token}"})
    client.post("/api/panel/evaluation/submit", json={"allocation_id": alloc_id, "student_marks": m_mem1}, headers={"Authorization": f"Bearer {mem1_token}"})
    client.post("/api/panel/evaluation/submit", json={"allocation_id": alloc_id, "student_marks": m_mem2}, headers={"Authorization": f"Bearer {mem2_token}"})

    # Test Role-Based Mark Visibility before Mem3 submits:
    # 1. Guide views team marksheet -> must see submitted totals for mem1 & mem2, but NO criterion marks!
    guide_view = client.get("/api/evaluation/team/TEST_TEAM_FINAL?semester=6", headers={"Authorization": f"Bearer {guide_token}"})
    assert guide_view.status_code == 200
    p1_info = guide_view.get_json()["panel_info"]["phase_1"]
    mem1_eval_guide_sees = next(e for e in p1_info["evaluations"] if e["faculty_email"] == "test_mem1@example.com")
    assert "marks" not in mem1_eval_guide_sees
    assert "student_marks" not in mem1_eval_guide_sees
    assert mem1_eval_guide_sees["student_totals"]["1MS21CS001"] == 18.0

    # 2. Coordinator views team marksheet -> must see FULL criterion marks breakdown for every faculty member!
    coord_view = client.get("/api/evaluation/team/TEST_TEAM_FINAL?semester=6", headers={"Authorization": f"Bearer {coord_token}"})
    assert coord_view.status_code == 200
    p1_info_coord = coord_view.get_json()["panel_info"]["phase_1"]
    mem1_eval_coord_sees = next(e for e in p1_info_coord["evaluations"] if e["faculty_email"] == "test_mem1@example.com")
    assert "student_marks" in mem1_eval_coord_sees or "marks" in mem1_eval_coord_sees

    # Coordinator cannot finalize yet (Mem3 has not submitted)
    fin_incomplete = client.post("/api/panel/evaluation/finalize", json={"allocation_id": alloc_id}, headers={"Authorization": f"Bearer {coord_token}"})
    assert fin_incomplete.status_code == 400
    assert "incomplete" in fin_incomplete.get_json()["error"].lower()

    # Mem3 submits
    client.post("/api/panel/evaluation/submit", json={"allocation_id": alloc_id, "student_marks": m_mem3}, headers={"Authorization": f"Bearer {mem3_token}"})

    # Now finalize succeeds
    fin_ok = client.post("/api/panel/evaluation/finalize", json={"allocation_id": alloc_id}, headers={"Authorization": f"Bearer {coord_token}"})
    assert fin_ok.status_code == 200
    res_data = fin_ok.get_json()["final_results"]["1MS21CS001"]

    # Verify averaging across 4 members:
    # Problem Statement: (4 + 5 + 3 + 5) / 4 = 17 / 4 = 4.25
    # Social Impact: (4 + 5 + 4 + 5) / 4 = 18 / 4 = 4.5
    # Depth Review: (4 + 4 + 3 + 5) / 4 = 16 / 4 = 4.0
    # Presentation: (4 + 4 + 4 + 5) / 4 = 17 / 4 = 4.25
    # Total phase average: 4.25 + 4.5 + 4.0 + 4.25 = 17.0
    crits = res_data["criterion_averages"]
    assert crits["Problem Statement & Objectives"] == 4.25
    assert crits["Social & Technical Impact"] == 4.5
    assert crits["Depth of Review"] == 4.0
    assert crits["Presentation"] == 4.25
    assert res_data["total_phase_mark"] == 17.0

    # Verify db.evaluations was automatically synchronized!
    eval_sync = db.evaluations.find_one({"team_name": "TEST_TEAM_FINAL", "semester": 6})
    assert eval_sync is not None
    p1 = eval_sync["phases"][0]
    assert p1["criteria"][0]["marks"][0]["marks_obtained"] == 4.25

    # Verify student endpoint sees only final averaged marks, NOT individual faculty marks
    stud_res = client.get("/api/evaluation/student?semester=6", headers={"Authorization": f"Bearer {student_token}"})
    assert stud_res.status_code == 200
    stud_json = stud_res.get_json()
    assert "panel_info" not in stud_json
    # Alice's mark in Phase 1 criterion 0 is 4.25
    alice_p1_c0 = stud_json["evaluation"]["phases"][0]["criteria"][0]["marks"][0]
    assert alice_p1_c0["marks_obtained"] == 4.25
    # Ensure no faculty names or individual marks in alice's marks
    assert "faculty_email" not in alice_p1_c0
    assert "individual_marks" not in alice_p1_c0

    # Coordinator can reopen if needed
    reopen_res = client.post("/api/panel/evaluation/reopen", json={"allocation_id": alloc_id, "reason": "Correction requested by panel"}, headers={"Authorization": f"Bearer {coord_token}"})
    assert reopen_res.status_code == 200
    alloc_doc = db.panel_allocations.find_one({"allocation_id": alloc_id})
    assert alloc_doc["status"] == "Reopened"

def test_approved_three_member_panel(client):
    coord_token = create_token("test_coord@example.com", role="coordinator")
    guide_token = create_token("test_guide@example.com", role="faculty")
    mem1_token = create_token("test_mem1@example.com", role="faculty")
    mem2_token = create_token("test_mem2@example.com", role="faculty")

    db.teams.insert_one({
        "team_name": "TEST_TEAM_3MEM",
        "faculty_email": "test_guide@example.com",
        "faculty_name": "Dr. Guide",
        "leader_name": "Alice Leader",
        "leader_usn": "1MS21CS001",
        "members": []
    })

    future_deadline = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    # Allocate with approved_three_member_panel=True (Member 3 is omitted)
    alloc_res = client.post("/api/panel/allocate", json={
        "team_name": "TEST_TEAM_3MEM",
        "semester": 6,
        "phase": "Phase 1",
        "guide_email": "test_guide@example.com",
        "member_1_email": "test_mem1@example.com",
        "member_2_email": "test_mem2@example.com",
        "approved_three_member_panel": True,
        "deadline": future_deadline
    }, headers={"Authorization": f"Bearer {coord_token}"})
    assert alloc_res.status_code == 201
    alloc_id = alloc_res.get_json()["allocation_id"]

    # Enable evaluation
    client.post("/api/panel/allocation/toggle_evaluation", json={
        "allocation_id": alloc_id,
        "enable": True
    }, headers={"Authorization": f"Bearer {coord_token}"})

    # Scores: 16/20, 18/20, 14/20 -> average = (16+18+14)/3 = 48/3 = 16.0
    m_guide = {"1MS21CS001": {"Problem Statement & Objectives": 4, "Social & Technical Impact": 4, "Depth of Review": 4, "Presentation": 4}}
    m_mem1 = {"1MS21CS001": {"Problem Statement & Objectives": 5, "Social & Technical Impact": 5, "Depth of Review": 4, "Presentation": 4}}
    m_mem2 = {"1MS21CS001": {"Problem Statement & Objectives": 3, "Social & Technical Impact": 4, "Depth of Review": 3, "Presentation": 4}}

    client.post("/api/panel/evaluation/submit", json={"allocation_id": alloc_id, "student_marks": m_guide}, headers={"Authorization": f"Bearer {guide_token}"})
    client.post("/api/panel/evaluation/submit", json={"allocation_id": alloc_id, "student_marks": m_mem1}, headers={"Authorization": f"Bearer {mem1_token}"})
    client.post("/api/panel/evaluation/submit", json={"allocation_id": alloc_id, "student_marks": m_mem2}, headers={"Authorization": f"Bearer {mem2_token}"})

    # Finalize with 3 members
    fin_res = client.post("/api/panel/evaluation/finalize", json={"allocation_id": alloc_id}, headers={"Authorization": f"Bearer {coord_token}"})
    assert fin_res.status_code == 200
    res_data = fin_res.get_json()["final_results"]["1MS21CS001"]
    assert res_data["total_phase_mark"] == 16.0
