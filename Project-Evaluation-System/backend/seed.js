const db = require('./database');

db.serialize(() => {
    console.log('Seeding standalone prototype sample data...');

    // Clear existing tables
    db.run(`DELETE FROM evaluations`);
    db.run(`DELETE FROM project_locks`);
    db.run(`DELETE FROM project_members`);
    db.run(`DELETE FROM projects`);
    db.run(`DELETE FROM students`);
    db.run(`DELETE FROM faculty`);
    db.run(`DELETE FROM coordinators`);

    // Insert Faculty
    const facultyList = [
        ['F001', 'Ms. Tejaswini', 'tejaswini@smvitm.ac.in', 'Computer Science and Engineering', 'Assistant Professor'],
        ['F002', 'Dr. Sachin Bhat', 'sachin.bhat@smvitm.ac.in', 'Computer Science and Engineering', 'Associate Professor'],
        ['F003', 'Dr. Surajit D. B', 'surajit.db@smvitm.ac.in', 'Computer Science and Engineering', 'Professor'],
        ['F004', 'Ms. Sowmya N', 'sowmya.n@smvitm.ac.in', 'Computer Science and Engineering', 'Assistant Professor'],
        ['F005', 'Ms. Reshma', 'reshma@smvitm.ac.in', 'Computer Science and Engineering', 'Assistant Professor']
    ];
    const stmtFaculty = db.prepare(`INSERT INTO faculty (faculty_id, name, email, department, designation) VALUES (?, ?, ?, ?, ?)`);
    facultyList.forEach(f => stmtFaculty.run(f));
    stmtFaculty.finalize();

    // Insert Coordinator
    const stmtCoord = db.prepare(`INSERT INTO coordinators (coordinator_id, name, email, department) VALUES (?, ?, ?, ?)`);
    stmtCoord.run(['C001', 'Dr. Sachin Bhat', 'sachin.coordinator@smvitm.ac.in', 'Computer Science and Engineering']);
    stmtCoord.finalize();

    // Insert Students
    const studentList = [
        ['S001', '4MW23CS092', 'Poorvik Acharya', 'Computer Science and Engineering', 6],
        ['S002', '4MW23CS096', 'Prakhyath Nayak', 'Computer Science and Engineering', 6],
        ['S003', '4MW23CS098', 'Prashanth Kulal', 'Computer Science and Engineering', 6],
        ['S004', '4MW23CS104', 'Prithesh R Shetty', 'Computer Science and Engineering', 6]
    ];
    const stmtStudent = db.prepare(`INSERT INTO students (student_id, usn, name, department, semester) VALUES (?, ?, ?, ?, ?)`);
    studentList.forEach(s => stmtStudent.run(s));
    stmtStudent.finalize();

    // Insert Project
    const projId = 'P041';
    db.run(`INSERT INTO projects (project_id, title, batch_no, academic_year, department, guide_id) VALUES (?, ?, ?, ?, ?, ?)`, [
        projId,
        'Originality Check with Intelligent Student Project Management System',
        'Batch No: 41',
        '2025-26 and 2026-27',
        'Computer Science and Engineering',
        'F001'
    ]);

    // Insert Project Members
    const stmtMembers = db.prepare(`INSERT INTO project_members (project_id, student_id) VALUES (?, ?)`);
    studentList.forEach(s => stmtMembers.run([projId, s[0]]));
    stmtMembers.finalize();

    // Initial Lock Status
    db.run(`INSERT INTO project_locks (project_id, is_locked) VALUES (?, ?)`, [projId, 0]);

    // Seed Evaluations matching sample marksheet values
    // Phase 1 (Synopsis & Problem Definition) - Max 20
    const phase1Criteria = [
        { name: 'Problem Statement & Objectives', max: 5 },
        { name: 'Social & Technical Impact', max: 5 },
        { name: 'Depth of Review', max: 5 },
        { name: 'Presentation', max: 5 }
    ];

    // Phase 2 (System Design - 40% Completion) - Max 40
    const phase2Criteria = [
        { name: 'Technical Clarity', max: 10 },
        { name: 'Novelty', max: 15 },
        { name: 'Relevance to Objectives', max: 10 },
        { name: 'Presentation', max: 5 }
    ];

    // Report & Attendance - Max 40
    const reportCriteria = [
        { name: 'Report', max: 20 },
        { name: 'Attendance', max: 10 },
        { name: 'Synopsis', max: 10 }
    ];

    const stmtEval = db.prepare(`INSERT INTO evaluations (student_id, project_id, faculty_id, phase, criterion, marks_obtained, maximum_marks, remarks, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`);

    const evaluators = ['F001', 'F002', 'F003', 'F004', 'F005']; // Guide + Members 1..4

    studentList.forEach(s => {
        const studentId = s[0];
        // Sample baseline marks (~ 85-90% performance)
        evaluators.forEach(facId => {
            phase1Criteria.forEach(c => {
                const mark = c.max == 5 ? 4.5 : 4.0;
                stmtEval.run([studentId, projId, facId, 'Phase 1', c.name, mark, c.max, 'Good progress', 'submitted']);
            });
            phase2Criteria.forEach(c => {
                const mark = Math.round(c.max * 0.88 * 10) / 10;
                stmtEval.run([studentId, projId, facId, 'Phase 2', c.name, mark, c.max, 'Well designed', 'submitted']);
            });
        });

        // Report & Attendance evaluated by Guide
        reportCriteria.forEach(c => {
            const mark = Math.round(c.max * 0.9 * 10) / 10;
            stmtEval.run([studentId, projId, 'F001', 'Report_Attendance', c.name, mark, c.max, 'Satisfactory', 'submitted']);
        });
    });

    stmtEval.finalize(() => {
        console.log('Sample test data successfully seeded for Batch 41!');
    });
});
