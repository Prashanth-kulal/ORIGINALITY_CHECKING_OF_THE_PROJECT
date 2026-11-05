# -*- coding: utf-8 -*-
"""
Pytest configuration and test database isolation safeguards.
Guarantees tests only run against 'student_project_test_db' and never touch production data.
"""
import os
import sys

# Ensure root and backend directories are in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.abspath(os.path.dirname(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Pre-set environment variables before any application imports occur
os.environ["TESTING"] = "true"
os.environ["MONGO_URI"] = os.getenv("TEST_MONGO_URI", "mongodb://localhost:27017/student_project_test_db")

import pytest

@pytest.fixture(scope="session", autouse=True)
def verify_test_database_isolation():
    """
    Session-level safeguard fixture:
    Guarantees that test suites NEVER connect to or modify the live production database.
    """
    try:
        import backend.app as app_module
    except ImportError:
        import app as app_module

    db_name = app_module.db.name
    print(f"\n[TEST DATABASE ISOLATION ACTIVE] Connected to: {db_name}")
    if "test" not in db_name.lower():
        raise RuntimeError(
            f"CRITICAL SAFETY VIOLATION: Pytest is connected to non-test database '{db_name}'. "
            f"All test executions against live databases are blocked to prevent data loss."
        )
    yield
