# -*- coding: utf-8 -*-
"""
Automated Integration and Security Test Suite for Secure Forgot Password & Reset Password.
Ensures full coverage of all 17 security and functionality requirements in an isolated test database.
"""
import unittest
import os
import sys
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
import jwt

sys.path.insert(0, os.path.dirname(__file__))

import app
from app import app as flask_app, db, TEST_PASSWORD_RESET_OUTBOX, limiter


class TestSecurePasswordResetSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config["TESTING"] = True
        # Safety assertion: verify connected to test database only
        assert "test" in db.name.lower(), f"CRITICAL: Non-test DB detected: {db.name}"

    def setUp(self):
        self.client = flask_app.test_client()
        limiter.reset()
        TEST_PASSWORD_RESET_OUTBOX.clear()
        
        # Test identifiers to prevent collisions
        self.tag = secrets.token_hex(4)
        self.student_email = f"student_{self.tag}@college.edu"
        self.faculty_email = f"faculty_{self.tag}@college.edu"
        self.coord_email = f"coord_{self.tag}@college.edu"
        self.unaffected_email = f"unaffected_{self.tag}@college.edu"
        
        self.initial_password = "InitialPassword123"
        self.new_password = "UpdatedPassword456"
        
        # Seed test student team
        self.team_id = db.teams.insert_one({
            "team_name": f"Team-{self.tag}",
            "leader_name": "Test Leader",
            "leader_usn": f"4MW{self.tag.upper()}001",
            "leader_email": self.student_email,
            "password": generate_password_hash(self.initial_password),
            "members": [
                {"name": "Member One", "email": f"m1_{self.tag}@college.edu", "usn": f"4MW{self.tag.upper()}002"}
            ],
            "role": "team",
            "created_at": datetime.now(timezone.utc)
        }).inserted_id

        # Seed test faculty
        self.faculty_id = db.faculty.insert_one({
            "name": f"Dr. Faculty {self.tag}",
            "email": self.faculty_email,
            "password": generate_password_hash(self.initial_password),
            "role": "faculty",
            "expertise": ["AI", "Web"],
            "created_at": datetime.now(timezone.utc)
        }).inserted_id

        # Seed unaffected faculty (to test requirement 16)
        self.unaffected_id = db.faculty.insert_one({
            "name": f"Dr. Unaffected {self.tag}",
            "email": self.unaffected_email,
            "password": generate_password_hash(self.initial_password),
            "role": "faculty",
            "expertise": ["Security"],
            "created_at": datetime.now(timezone.utc)
        }).inserted_id

        # Seed test coordinator
        self.coord_id = db.coordinator.insert_one({
            "name": f"Coordinator {self.tag}",
            "email": self.coord_email,
            "password": generate_password_hash(self.initial_password),
            "role": "coordinator",
            "created_at": datetime.now(timezone.utc)
        }).inserted_id

    def tearDown(self):
        # Clean up only seeded test records
        db.teams.delete_many({"_id": self.team_id})
        db.faculty.delete_many({"_id": {"$in": [self.faculty_id, self.unaffected_id]}})
        db.coordinator.delete_many({"_id": self.coord_id})
        db.password_resets.delete_many({
            "email": {
                "$in": [
                    self.student_email,
                    self.faculty_email,
                    self.coord_email,
                    self.unaffected_email,
                    f"m1_{self.tag}@college.edu"
                ]
            }
        })
        TEST_PASSWORD_RESET_OUTBOX.clear()
        limiter.reset()

    # -------------------------------------------------------------------------
    # Requirement 1: Valid registered email request
    # -------------------------------------------------------------------------
    def test_01_valid_registered_email_request(self):
        resp = self.client.post("/api/auth/forgot-password", json={"email": self.faculty_email})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("message", data)
        self.assertIn("reset link has been sent", data["message"].lower())

        # Check MongoDB record
        record = db.password_resets.find_one({"email": self.faculty_email, "used": False})
        self.assertIsNotNone(record)
        self.assertTrue(record.get("token_hash"))
        self.assertFalse(record.get("used"))
        exp = record.get("expires_at")
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        self.assertGreater(exp, datetime.now(timezone.utc))

        # Check outbox email
        self.assertEqual(len(TEST_PASSWORD_RESET_OUTBOX), 1)
        dispatched = TEST_PASSWORD_RESET_OUTBOX[0]
        self.assertEqual(dispatched["to"], self.faculty_email)
        self.assertIn("reset-password.html?token=", dispatched["reset_url"])

    # -------------------------------------------------------------------------
    # Requirement 2: Unregistered email request (Anti-enumeration)
    # -------------------------------------------------------------------------
    def test_02_unregistered_email_request(self):
        unregistered = f"ghost_{secrets.token_hex(4)}@nowhere.edu"
        resp = self.client.post("/api/auth/forgot-password", json={"email": unregistered})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        # Must return the exact same generic message
        self.assertIn("If an account with that email exists", data["message"])

        # Must NOT create reset record
        record = db.password_resets.find_one({"email": unregistered})
        self.assertIsNone(record)
        # Must NOT send email
        self.assertEqual(len(TEST_PASSWORD_RESET_OUTBOX), 0)

    # -------------------------------------------------------------------------
    # Requirement 3: Invalid email format
    # -------------------------------------------------------------------------
    def test_03_invalid_email_format(self):
        # Missing @
        r1 = self.client.post("/api/auth/forgot-password", json={"email": "notanemail"})
        self.assertEqual(r1.status_code, 400)
        self.assertIn("error", r1.get_json())

        # Empty email
        r2 = self.client.post("/api/auth/forgot-password", json={"email": ""})
        self.assertEqual(r2.status_code, 400)

        # Missing payload
        r3 = self.client.post("/api/auth/forgot-password", json={})
        self.assertEqual(r3.status_code, 400)

    # -------------------------------------------------------------------------
    # Requirement 4: Successful reset using a valid token
    # -------------------------------------------------------------------------
    def test_04_successful_reset_using_valid_token(self):
        # 1. Request reset
        resp = self.client.post("/api/auth/forgot-password", json={"email": self.faculty_email})
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(TEST_PASSWORD_RESET_OUTBOX), 0)
        raw_token = TEST_PASSWORD_RESET_OUTBOX[0]["reset_url"].split("token=")[-1]

        # 2. Validate token
        val_resp = self.client.get(f"/api/auth/validate-reset-token?token={raw_token}")
        self.assertEqual(val_resp.status_code, 200)
        val_data = val_resp.get_json()
        self.assertTrue(val_data.get("valid"))

        # 3. Reset password
        reset_resp = self.client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": self.new_password,
            "confirm_password": self.new_password
        })
        self.assertEqual(reset_resp.status_code, 200)
        self.assertIn("successfully reset", reset_resp.get_json().get("message", ""))

        # Token must now be marked used
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        rec = db.password_resets.find_one({"token_hash": token_hash})
        self.assertTrue(rec.get("used"))

    # -------------------------------------------------------------------------
    # Requirement 5: Expired token rejection
    # -------------------------------------------------------------------------
    def test_05_expired_token(self):
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        # Seed expired record (expired 10 minutes ago)
        db.password_resets.insert_one({
            "token_hash": token_hash,
            "email": self.faculty_email,
            "accounts": [{"account_id": self.faculty_id, "collection": "faculty", "role": "faculty"}],
            "created_at": datetime.now(timezone.utc) - timedelta(minutes=25),
            "expires_at": datetime.now(timezone.utc) - timedelta(minutes=10),
            "used": False
        })

        # Validate should fail
        v_resp = self.client.get(f"/api/auth/validate-reset-token?token={raw_token}")
        self.assertEqual(v_resp.status_code, 400)
        self.assertIn("expired", v_resp.get_json().get("error", "").lower())

        # Reset should fail
        r_resp = self.client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": self.new_password,
            "confirm_password": self.new_password
        })
        self.assertEqual(r_resp.status_code, 400)
        self.assertIn("expired", r_resp.get_json().get("error", "").lower())

    # -------------------------------------------------------------------------
    # Requirement 6: Invalid / non-existent token rejection
    # -------------------------------------------------------------------------
    def test_06_invalid_token(self):
        bogus_token = "totally-fake-token-never-issued-12345"

        v_resp = self.client.get(f"/api/auth/validate-reset-token?token={bogus_token}")
        self.assertEqual(v_resp.status_code, 400)
        self.assertFalse(v_resp.get_json().get("valid", True))

        r_resp = self.client.post("/api/auth/reset-password", json={
            "token": bogus_token,
            "new_password": self.new_password,
            "confirm_password": self.new_password
        })
        self.assertEqual(r_resp.status_code, 400)
        self.assertIn("invalid", r_resp.get_json().get("error", "").lower())

    # -------------------------------------------------------------------------
    # Requirement 7: Reusing an already-used token
    # -------------------------------------------------------------------------
    def test_07_reusing_already_used_token(self):
        self.client.post("/api/auth/forgot-password", json={"email": self.faculty_email})
        self.assertGreater(len(TEST_PASSWORD_RESET_OUTBOX), 0)
        raw_token = TEST_PASSWORD_RESET_OUTBOX[0]["reset_url"].split("token=")[-1]

        # Use it first time
        r1 = self.client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": self.new_password,
            "confirm_password": self.new_password
        })
        self.assertEqual(r1.status_code, 200)

        # Attempt to use it a second time
        r2 = self.client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": "AnotherNewPassword789",
            "confirm_password": "AnotherNewPassword789"
        })
        self.assertEqual(r2.status_code, 400)
        self.assertIn("already been used", r2.get_json().get("error", "").lower())

    # -------------------------------------------------------------------------
    # Requirement 8: Resetting with mismatched passwords
    # -------------------------------------------------------------------------
    def test_08_mismatched_passwords(self):
        self.client.post("/api/auth/forgot-password", json={"email": self.faculty_email})
        self.assertGreater(len(TEST_PASSWORD_RESET_OUTBOX), 0)
        raw_token = TEST_PASSWORD_RESET_OUTBOX[0]["reset_url"].split("token=")[-1]

        resp = self.client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": "PasswordOne123",
            "confirm_password": "PasswordTwo456"
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("do not match", resp.get_json().get("error", "").lower())

        # Token must remain valid and unconsumed
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        rec = db.password_resets.find_one({"token_hash": token_hash})
        self.assertFalse(rec.get("used"))

    # -------------------------------------------------------------------------
    # Requirement 9: Weak password rejection
    # -------------------------------------------------------------------------
    def test_09_weak_password_rejection(self):
        self.client.post("/api/auth/forgot-password", json={"email": self.faculty_email})
        self.assertGreater(len(TEST_PASSWORD_RESET_OUTBOX), 0)
        raw_token = TEST_PASSWORD_RESET_OUTBOX[0]["reset_url"].split("token=")[-1]

        # Password with length < 6
        resp = self.client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": "123",
            "confirm_password": "123"
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("at least 6 characters", resp.get_json().get("error", "").lower())

    # -------------------------------------------------------------------------
    # Requirement 10: Rate-limit enforcement
    # -------------------------------------------------------------------------
    def test_10_rate_limit_enforcement(self):
        target_email = f"ratelimit_{secrets.token_hex(4)}@college.edu"
        db.faculty.insert_one({
            "name": "Rate Limit Target",
            "email": target_email,
            "password": generate_password_hash("SomePassword123"),
            "role": "faculty"
        })

        # Send 3 requests (max per email in 15 mins)
        for _ in range(3):
            r = self.client.post("/api/auth/forgot-password", json={"email": target_email})
            self.assertEqual(r.status_code, 200)

        # 4th request must be rate-limited by per-email limiter (HTTP 429)
        r4 = self.client.post("/api/auth/forgot-password", json={"email": target_email})
        self.assertEqual(r4.status_code, 429)
        self.assertIn("Too many password reset requests", r4.get_json().get("error", ""))

        db.faculty.delete_many({"email": target_email})
        db.password_resets.delete_many({"email": target_email})

    # -------------------------------------------------------------------------
    # Requirement 11 & 12: Existing login with new password & old password rejection
    # -------------------------------------------------------------------------
    def test_11_and_12_login_with_new_password_and_old_rejected(self):
        # Verify initial login works with old password
        old_login = self.client.post("/api/login", json={
            "email": self.faculty_email,
            "password": self.initial_password,
            "role": "faculty"
        })
        self.assertEqual(old_login.status_code, 200)

        # Reset password
        self.client.post("/api/auth/forgot-password", json={"email": self.faculty_email})
        self.assertGreater(len(TEST_PASSWORD_RESET_OUTBOX), 0)
        raw_token = TEST_PASSWORD_RESET_OUTBOX[0]["reset_url"].split("token=")[-1]
        self.client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": self.new_password,
            "confirm_password": self.new_password
        })

        # 12. Old password rejection
        rejected_login = self.client.post("/api/login", json={
            "email": self.faculty_email,
            "password": self.initial_password,
            "role": "faculty"
        })
        self.assertEqual(rejected_login.status_code, 401)

        # 11. Existing login with new password
        successful_login = self.client.post("/api/login", json={
            "email": self.faculty_email,
            "password": self.new_password,
            "role": "faculty"
        })
        self.assertEqual(successful_login.status_code, 200)
        self.assertTrue(successful_login.get_json().get("token"))

    # -------------------------------------------------------------------------
    # Requirement 13: Student account reset
    # -------------------------------------------------------------------------
    def test_13_student_account_reset(self):
        # 1. Forgot password for student leader email
        resp = self.client.post("/api/auth/forgot-password", json={"email": self.student_email})
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(TEST_PASSWORD_RESET_OUTBOX), 0)
        raw_token = TEST_PASSWORD_RESET_OUTBOX[0]["reset_url"].split("token=")[-1]

        # 2. Reset password
        r = self.client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": self.new_password,
            "confirm_password": self.new_password
        })
        self.assertEqual(r.status_code, 200)

        # 3. Student login using team role
        login_resp = self.client.post("/api/login", json={
            "email": self.student_email,
            "password": self.new_password,
            "role": "team"
        })
        self.assertEqual(login_resp.status_code, 200)
        self.assertIn("token", login_resp.get_json())

    # -------------------------------------------------------------------------
    # Requirement 14: Faculty account reset
    # -------------------------------------------------------------------------
    def test_14_faculty_account_reset(self):
        resp = self.client.post("/api/auth/forgot-password", json={"email": self.faculty_email})
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(TEST_PASSWORD_RESET_OUTBOX), 0)
        raw_token = TEST_PASSWORD_RESET_OUTBOX[0]["reset_url"].split("token=")[-1]

        r = self.client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": self.new_password,
            "confirm_password": self.new_password
        })
        self.assertEqual(r.status_code, 200)

        login_resp = self.client.post("/api/login", json={
            "email": self.faculty_email,
            "password": self.new_password,
            "role": "faculty"
        })
        self.assertEqual(login_resp.status_code, 200)

    # -------------------------------------------------------------------------
    # Requirement 15: Coordinator account reset
    # -------------------------------------------------------------------------
    def test_15_coordinator_account_reset(self):
        resp = self.client.post("/api/auth/forgot-password", json={"email": self.coord_email})
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(TEST_PASSWORD_RESET_OUTBOX), 0)
        raw_token = TEST_PASSWORD_RESET_OUTBOX[0]["reset_url"].split("token=")[-1]

        r = self.client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": self.new_password,
            "confirm_password": self.new_password
        })
        self.assertEqual(r.status_code, 200)

        login_resp = self.client.post("/api/login", json={
            "email": self.coord_email,
            "password": self.new_password,
            "role": "coordinator"
        })
        self.assertEqual(login_resp.status_code, 200)

    # -------------------------------------------------------------------------
    # Requirement 16: Existing accounts and password hashes remain intact
    # -------------------------------------------------------------------------
    def test_16_unaffected_accounts_remain_intact(self):
        unaffected_before = db.faculty.find_one({"_id": self.unaffected_id})
        original_hash = unaffected_before["password"]

        # Reset faculty_email
        self.client.post("/api/auth/forgot-password", json={"email": self.faculty_email})
        self.assertGreater(len(TEST_PASSWORD_RESET_OUTBOX), 0)
        raw_token = TEST_PASSWORD_RESET_OUTBOX[0]["reset_url"].split("token=")[-1]
        self.client.post("/api/auth/reset-password", json={
            "token": raw_token,
            "new_password": self.new_password,
            "confirm_password": self.new_password
        })

        # Verify unaffected faculty password has NOT changed
        unaffected_after = db.faculty.find_one({"_id": self.unaffected_id})
        self.assertEqual(unaffected_after["password"], original_hash)

        # Verify unaffected account can still log in with original password
        login_resp = self.client.post("/api/login", json={
            "email": self.unaffected_email,
            "password": self.initial_password,
            "role": "faculty"
        })
        self.assertEqual(login_resp.status_code, 200)

    # -------------------------------------------------------------------------
    # Requirement 17: Existing workflows continue working seamlessly
    # -------------------------------------------------------------------------
    def test_17_existing_workflows_continue_working(self):
        # 1. Faculty Registration workflow
        new_fac_email = f"newfac_{secrets.token_hex(4)}@college.edu"
        reg_resp = self.client.post("/api/register/faculty", json={
            "name": "New Registered Faculty",
            "email": new_fac_email,
            "password": "RegisterPass123",
            "expertise": ["Data Science"]
        })
        self.assertEqual(reg_resp.status_code, 201)

        # 2. Login with newly registered faculty
        login_resp = self.client.post("/api/login", json={
            "email": new_fac_email,
            "password": "RegisterPass123",
            "role": "faculty"
        })
        self.assertEqual(login_resp.status_code, 200)
        token = login_resp.get_json()["token"]

        # 3. Authenticated dashboard request using JWT
        dash_resp = self.client.get("/api/dashboard/faculty", headers={
            "Authorization": f"Bearer {token}"
        })
        # Verifies JWT validation and dashboard workflow continue functioning
        self.assertIn(dash_resp.status_code, [200, 404])

        db.faculty.delete_many({"email": new_fac_email})


if __name__ == "__main__":
    unittest.main()
