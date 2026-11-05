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

def create_token(email, role="faculty", name="Faculty User", usn=None):
    payload = {
        "email": email,
        "role": role,
        "name": name,
        "exp": datetime.now(timezone.utc) + timedelta(hours=2)
    }
    if usn:
        payload["usn"] = usn
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

@pytest.fixture(autouse=True)
def clean_data():
    prefix = "TEST_PANEL_FINAL_"
    db.teams.delete_many({"team_name": {"$regex": f"^{prefix}"}})
    db.panel_allocations.delete_many({"team_name": {"$regex": f"^{prefix}"}})
    db.panel_evaluations.delete_many({"team_name": {"$regex": f"^{prefix}"}})
    db.panel_notifications.delete_many({"team_name": {"$regex": f"^{prefix}"}})
    db.evaluations.delete_many({"team_name": {"$regex": f"^{prefix}"}})
    yield
    db.teams.delete_many({"team_name": {"$regex": f"^{prefix}"}})
    db.panel_allocations.delete_many({"team_name": {"$regex": f"^{prefix}"}})
    db.panel_evaluations.delete_many({"team_name": {"$regex": f"^{prefix}"}})
    db.panel_notifications.delete_many({"team_name": {"$regex": f"^{prefix}"}})
    db.evaluations.delete_many({"team_name": {"$regex": f"^{prefix}"}})


def test_01_notification_and_assignment_open_dedicated_panel_evaluation_page(client):
    """Notification and assignments must provide dedicated page link: panel-evaluation.html?alloc_id=<id>."""
    coord_token = create_token("coord_test@example.com", role="coordinator", name="Dr Coordinator")
    team_name = "TEST_PANEL_FINAL_TEAM_1"

    # Setup team
    db.teams.insert_one({
        "team_name": team_name,
        "faculty_email": "guide_p1@example.com",
        "faculty_name": "Dr Guide P1",
        "leader_name": "Student Leader",
        "leader_usn": "1MS21CS001",
        "members": [{"name": "Student Member", "usn": "1MS21CS002"}],
        "project_idea": {"title": "Autonomous Project"}
    })

    # Allocate panel
    alloc_res = client.post(
        "/api/panel/allocate",
        headers={"Authorization": f"Bearer {coord_token}"},
        json={
            "team_name": team_name,
            "semester": 6,
            "phase": "phase_1",
            "guide_email": "guide_p1@example.com",
            "panel_member_emails": [
                "eval1@example.com",
                "eval2@example.com",
                "eval3@example.com"
            ],
            "enable_evaluation": True
        }
    )
    assert alloc_res.status_code in [200, 201]
    alloc_id = alloc_res.get_json()["allocation"]["allocation_id"]

    # Verify notification link points to panel-evaluation.html?alloc_id=...
    notifs = list(db.panel_notifications.find({"team_name": team_name}))
    assert len(notifs) >= 4
    for n in notifs:
        assert "panel-evaluation.html" in n["evaluation_url"]
        assert f"alloc_id={alloc_id}" in n["evaluation_url"]

    # Verify faculty assignment list returns evaluation_url pointing to panel-evaluation.html
    eval1_token = create_token("eval1@example.com", role="faculty", name="Prof Eval 1")
    assign_res = client.get(
        "/api/panel/faculty/assignments",
        headers={"Authorization": f"Bearer {eval1_token}"}
    )
    assert assign_res.status_code == 200
    assignments = assign_res.get_json()
    my_assign = next((a for a in assignments if a["allocation_id"] == alloc_id), None)
    assert my_assign is not None
    assert "panel-evaluation.html" in my_assign["evaluation_url"]
    assert f"alloc_id={alloc_id}" in my_assign["evaluation_url"]


def test_02_single_final_mark_out_of_20_draft_and_submission(client):
    """Faculty can enter, save draft, and submit one final mark out of 20."""
    coord_token = create_token("coord_test@example.com", role="coordinator")
    eval1_token = create_token("eval1@example.com", role="faculty", name="Prof Eval 1")
    team_name = "TEST_PANEL_FINAL_TEAM_2"

    db.teams.insert_one({
        "team_name": team_name,
        "faculty_email": "guide_p2@example.com",
        "faculty_name": "Dr Guide P2",
        "leader_name": "Leader One",
        "leader_usn": "1MS21CS010",
        "members": [{"name": "Member Two", "usn": "1MS21CS011"}],
        "project_idea": {"title": "System Two"}
    })

    alloc_res = client.post(
        "/api/panel/allocate",
        headers={"Authorization": f"Bearer {coord_token}"},
        json={
            "team_name": team_name,
            "semester": 6,
            "phase": "phase_1",
            "guide_email": "guide_p2@example.com",
            "panel_member_emails": ["eval1@example.com", "eval2@example.com", "eval3@example.com"],
            "enable_evaluation": True
        }
    )
    alloc_id = alloc_res.get_json()["allocation"]["allocation_id"]

    # 1. Save draft with final_marks
    draft_res = client.post(
        "/api/panel/evaluation/save",
        headers={"Authorization": f"Bearer {eval1_token}"},
        json={
            "allocation_id": alloc_id,
            "final_marks": {
                "1MS21CS010": 15.5
            }
        }
    )
    assert draft_res.status_code == 200

    # 2. Reject out-of-bounds mark (> 20)
    bad_res = client.post(
        "/api/panel/evaluation/submit",
        headers={"Authorization": f"Bearer {eval1_token}"},
        json={
            "allocation_id": alloc_id,
            "final_marks": {
                "1MS21CS010": 25.0,
                "1MS21CS011": 14.0
            }
        }
    )
    assert bad_res.status_code == 400
    assert "between 0 and 20" in bad_res.get_json()["error"]

    # 3. Reject incomplete submission
    missing_res = client.post(
        "/api/panel/evaluation/submit",
        headers={"Authorization": f"Bearer {eval1_token}"},
        json={
            "allocation_id": alloc_id,
            "final_marks": {
                "1MS21CS010": 16.0
                # 1MS21CS011 is missing!
            }
        }
    )
    assert missing_res.status_code == 400
    assert "Please enter a final mark" in missing_res.get_json()["error"]

    # 4. Successful submission
    submit_res = client.post(
        "/api/panel/evaluation/submit",
        headers={"Authorization": f"Bearer {eval1_token}"},
        json={
            "allocation_id": alloc_id,
            "final_marks": {
                "1MS21CS010": 16.5,
                "1MS21CS011": 17.0
            }
        }
    )
    assert submit_res.status_code == 200
    assert submit_res.get_json()["success"] is True

    # Verify saved document has both final_marks and student_totals
    saved_doc = db.panel_evaluations.find_one({"allocation_id": alloc_id, "faculty_email": "eval1@example.com"})
    assert saved_doc is not None
    assert saved_doc["status"] == "Submitted"
    assert saved_doc["final_marks"]["1MS21CS010"] == 16.5
    assert saved_doc["student_totals"]["1MS21CS010"] == 16.5


def test_03_unauthorized_faculty_cannot_access_or_submit_marks(client):
    """Unauthorized faculty cannot access or submit marks for another team."""
    coord_token = create_token("coord_test@example.com", role="coordinator")
    unauth_token = create_token("unrelated_fac@example.com", role="faculty", name="Prof Unrelated")
    team_name = "TEST_PANEL_FINAL_TEAM_3"

    db.teams.insert_one({
        "team_name": team_name,
        "faculty_email": "guide_p3@example.com",
        "faculty_name": "Dr Guide P3",
        "leader_name": "Leader Three",
        "leader_usn": "1MS21CS020",
        "members": [{"name": "Member Three", "usn": "1MS21CS021"}],
        "project_idea": {"title": "System Three"}
    })

    alloc_res = client.post(
        "/api/panel/allocate",
        headers={"Authorization": f"Bearer {coord_token}"},
        json={
            "team_name": team_name,
            "semester": 6,
            "phase": "phase_1",
            "guide_email": "guide_p3@example.com",
            "panel_member_emails": ["eval1@example.com", "eval2@example.com", "eval3@example.com"],
            "enable_evaluation": True
        }
    )
    alloc_id = alloc_res.get_json()["allocation"]["allocation_id"]

    # 1. Unallocated faculty gets 403 on get_panel_evaluation_sheet
    res_sheet = client.get(
        f"/api/panel/evaluation/{alloc_id}",
        headers={"Authorization": f"Bearer {unauth_token}"}
    )
    assert res_sheet.status_code == 403
    assert "Unauthorized" in res_sheet.get_json()["error"]

    # 2. Unallocated faculty gets 403 on get_team_evaluation
    res_team = client.get(
        f"/api/evaluation/team/{team_name}?semester=6",
        headers={"Authorization": f"Bearer {unauth_token}"}
    )
    assert res_team.status_code == 403
    assert "Forbidden" in res_team.get_json()["error"]


def test_04_average_calculation_four_members_and_three_members(client):
    """
    Final average calculation:
    - 4 panel members submit 12, 14, 15, and 16 -> final average is 14.25 / 20.
    - If only 3 members have submitted 12, 14, and 16, calculate 14.0 / 20. Excludes pending from denominator.
    """
    coord_token = create_token("coord_test@example.com", role="coordinator")
    team_name = "TEST_PANEL_FINAL_TEAM_4"

    db.teams.insert_one({
        "team_name": team_name,
        "faculty_email": "guide_p4@example.com",
        "faculty_name": "Dr Guide P4",
        "leader_name": "Student A",
        "leader_usn": "1MS21CS030",
        "members": [{"name": "Student B", "usn": "1MS21CS031"}],
        "project_idea": {"title": "System Four"}
    })

    # Standard 4-member panel (guide + 3 members)
    alloc_res = client.post(
        "/api/panel/allocate",
        headers={"Authorization": f"Bearer {coord_token}"},
        json={
            "team_name": team_name,
            "semester": 6,
            "phase": "phase_1",
            "guide_email": "guide_p4@example.com",
            "panel_member_emails": ["eval1@example.com", "eval2@example.com", "eval3@example.com"],
            "enable_evaluation": True
        }
    )
    alloc_id = alloc_res.get_json()["allocation"]["allocation_id"]

    guide_token = create_token("guide_p4@example.com", role="faculty", name="Dr Guide")
    m1_token = create_token("eval1@example.com", role="faculty", name="Prof Eval 1")
    m2_token = create_token("eval2@example.com", role="faculty", name="Prof Eval 2")
    m3_token = create_token("eval3@example.com", role="faculty", name="Prof Eval 3")

    # Step A: 3 members submit: Guide=12, Member1=14, Member2=16. (Member 3 has NOT submitted)
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {guide_token}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS030": 12.0, "1MS21CS031": 15.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {m1_token}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS030": 14.0, "1MS21CS031": 15.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {m2_token}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS030": 16.0, "1MS21CS031": 15.0}})

    # Check Guide's view of current average with 3 submissions:
    # 12 + 14 + 16 = 42 -> 42 / 3 = 14.00! (Excludes unsubmitted member 3)
    res_guide = client.get(f"/api/panel/evaluation/{alloc_id}", headers={"Authorization": f"Bearer {guide_token}"})
    assert res_guide.status_code == 200
    guide_data = res_guide.get_json()
    assert guide_data["is_guide"] is True
    assert "panel_summary" in guide_data
    sr = next((s for s in guide_data["panel_summary"]["student_results"] if s["usn"] == "1MS21CS030"), None)
    assert sr is not None
    assert sr["average_mark"] == 14.00
    assert sr["submitted_count"] == 3

    # Step B: Member 3 now submits 15 out of 20
    # 4 members: 12 + 14 + 16 + 15 = 57 -> 57 / 4 = 14.25!
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {m3_token}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS030": 15.0, "1MS21CS031": 15.0}})

    res_guide_4 = client.get(f"/api/panel/evaluation/{alloc_id}", headers={"Authorization": f"Bearer {guide_token}"})
    sr4 = next((s for s in res_guide_4.get_json()["panel_summary"]["student_results"] if s["usn"] == "1MS21CS030"), None)
    assert sr4 is not None
    assert sr4["average_mark"] == 14.25
    assert sr4["submitted_count"] == 4

    # Coordinator finalizes
    fin_res = client.post(
        "/api/panel/evaluation/finalize",
        headers={"Authorization": f"Bearer {coord_token}"},
        json={"allocation_id": alloc_id, "publish": True}
    )
    assert fin_res.status_code == 200
    fin_results = fin_res.get_json()["final_results"]
    assert fin_results["1MS21CS030"]["total_phase_mark"] == 14.25


def test_05_role_specific_visibility_restrictions(client):
    """
    Role-specific visibility restrictions:
    - Coordinator: sees individual final marks and average.
    - Guide: sees panel members' final submitted marks and average, NO criteria breakdown.
    - Student: sees ONLY published average.
    - Other faculty: sees only own evaluation, not others.
    """
    coord_token = create_token("coord_test@example.com", role="coordinator")
    team_name = "TEST_PANEL_FINAL_TEAM_5"

    db.teams.insert_one({
        "team_name": team_name,
        "faculty_email": "guide_p5@example.com",
        "faculty_name": "Dr Guide P5",
        "leader_name": "Student Leader 5",
        "leader_usn": "1MS21CS050",
        "members": [{"name": "Student Member 5", "usn": "1MS21CS051"}],
        "project_idea": {"title": "System Five"}
    })

    alloc_res = client.post(
        "/api/panel/allocate",
        headers={"Authorization": f"Bearer {coord_token}"},
        json={
            "team_name": team_name,
            "semester": 6,
            "phase": "phase_1",
            "guide_email": "guide_p5@example.com",
            "panel_member_emails": ["eval1@example.com", "eval2@example.com", "eval3@example.com"],
            "enable_evaluation": True
        }
    )
    alloc_id = alloc_res.get_json()["allocation"]["allocation_id"]

    guide_token = create_token("guide_p5@example.com", role="faculty", name="Dr Guide")
    m1_token = create_token("eval1@example.com", role="faculty", name="Prof Eval 1")
    m2_token = create_token("eval2@example.com", role="faculty", name="Prof Eval 2")
    m3_token = create_token("eval3@example.com", role="faculty", name="Prof Eval 3")
    student_token = create_token("student_p5@example.com", role="student", name="Student Leader 5", usn="1MS21CS050")

    # Evaluators submit marks
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {guide_token}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS050": 16.0, "1MS21CS051": 15.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {m1_token}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS050": 17.0, "1MS21CS051": 15.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {m2_token}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS050": 18.0, "1MS21CS051": 15.0}})
    client.post("/api/panel/evaluation/submit", headers={"Authorization": f"Bearer {m3_token}"},
                json={"allocation_id": alloc_id, "final_marks": {"1MS21CS050": 17.0, "1MS21CS051": 15.0}})

    # 1. Other faculty (e.g. m1) viewing sheet: receives ONLY my_evaluation, NO panel_summary of other members!
    res_m1 = client.get(f"/api/panel/evaluation/{alloc_id}", headers={"Authorization": f"Bearer {m1_token}"})
    assert res_m1.status_code == 200
    m1_data = res_m1.get_json()
    assert m1_data["is_guide"] is False
    assert "panel_summary" not in m1_data
    assert m1_data["my_evaluation"]["faculty_email"] == "eval1@example.com"

    # 2. Guide viewing sheet: receives panel_summary with each member's final submitted mark out of 20, NO criteria!
    res_guide = client.get(f"/api/panel/evaluation/{alloc_id}", headers={"Authorization": f"Bearer {guide_token}"})
    assert res_guide.status_code == 200
    g_data = res_guide.get_json()
    assert g_data["is_guide"] is True
    assert "panel_summary" in g_data
    sr = g_data["panel_summary"]["student_results"][0]
    for mm in sr["member_marks"]:
        assert "final_mark" in mm
        # NO criteria breakdowns of others
        assert "criteria" not in mm
        assert "marks" not in mm

    # 3. Coordinator views sheet: receives full breakdown and calculated averages
    res_coord = client.get(f"/api/panel/evaluation/{alloc_id}", headers={"Authorization": f"Bearer {coord_token}"})
    assert res_coord.status_code == 200
    c_data = res_coord.get_json()
    assert "student_averages" in c_data
    assert c_data["student_averages"][0]["total_marks"] == 17.0

    # 4. Finalize and publish
    client.post(
        "/api/panel/evaluation/finalize",
        headers={"Authorization": f"Bearer {coord_token}"},
        json={"allocation_id": alloc_id, "publish": True}
    )

    # 5. Student view: student sees ONLY the final published average, NEVER individual faculty marks
    res_stud = client.get("/api/evaluation/student?semester=6", headers={"Authorization": f"Bearer {student_token}"})
    assert res_stud.status_code == 200
    s_data = res_stud.get_json()
    assert "panel_info" not in s_data
    assert "panel_evaluations" not in s_data
    eval_doc = s_data.get("evaluation")
    assert eval_doc is not None
    # Individual faculty names and individual marks are not in the student response
    assert "faculty_email" not in s_data
