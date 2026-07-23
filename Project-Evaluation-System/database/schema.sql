-- Project Evaluation System Standalone Database Schema (SQLite)

CREATE TABLE IF NOT EXISTS faculty (
    faculty_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    department TEXT NOT NULL,
    designation TEXT
);

CREATE TABLE IF NOT EXISTS coordinators (
    coordinator_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    department TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY,
    usn TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    department TEXT NOT NULL,
    semester INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    batch_no TEXT NOT NULL,
    academic_year TEXT NOT NULL,
    department TEXT NOT NULL,
    guide_id TEXT NOT NULL,
    FOREIGN KEY (guide_id) REFERENCES faculty(faculty_id)
);

CREATE TABLE IF NOT EXISTS project_members (
    project_id TEXT NOT NULL,
    student_id TEXT NOT NULL,
    PRIMARY KEY (project_id, student_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (student_id) REFERENCES students(student_id)
);

CREATE TABLE IF NOT EXISTS evaluations (
    evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    faculty_id TEXT NOT NULL,
    phase TEXT NOT NULL,          -- 'Phase 1', 'Phase 2', 'Report_Attendance'
    criterion TEXT NOT NULL,      -- e.g. 'Problem statement & Objectives', 'Technical Clarity', etc.
    marks_obtained REAL NOT NULL,
    maximum_marks REAL NOT NULL,
    remarks TEXT,
    status TEXT DEFAULT 'submitted', -- 'draft', 'submitted', 'locked'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(student_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (faculty_id) REFERENCES faculty(faculty_id),
    UNIQUE(student_id, project_id, phase, criterion, faculty_id)
);

CREATE TABLE IF NOT EXISTS project_locks (
    project_id TEXT PRIMARY KEY,
    is_locked INTEGER DEFAULT 0,  -- 0 = unlocked, 1 = locked by coordinator
    locked_by TEXT,
    locked_at TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(project_id)
);
