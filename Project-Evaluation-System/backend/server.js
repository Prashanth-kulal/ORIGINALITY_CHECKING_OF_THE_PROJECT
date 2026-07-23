const express = require('express');
const cors = require('cors');
const path = require('path');
const db = require('./database');

const app = express();
const PORT = process.env.PORT || 4000;

app.use(cors());
app.use(express.json());

// Serve static frontend files
app.use(express.static(path.join(__dirname, '../frontend')));

// Helper middleware for role verification
const checkRole = (req, res, next) => {
    const role = req.headers['x-role'] || req.body.role || 'faculty';
    req.userRole = role.toLowerCase();
    next();
};

// GET /api/projects - Get project list with guide & members info
app.get('/api/projects', (req, res) => {
    const sql = `
        SELECT 
            p.project_id, p.title, p.batch_no, p.academic_year, p.department,
            f.name as guide_name, f.faculty_id as guide_id,
            COALESCE(l.is_locked, 0) as is_locked,
            l.locked_by, l.locked_at
        FROM projects p
        JOIN faculty f ON p.guide_id = f.faculty_id
        LEFT JOIN project_locks l ON p.project_id = l.project_id
    `;

    db.all(sql, [], (err, projects) => {
        if (err) return res.status(500).json({ error: err.message });

        // Fetch students for each project
        const membersSql = `
            SELECT pm.project_id, s.student_id, s.usn, s.name, s.department, s.semester
            FROM project_members pm
            JOIN students s ON pm.student_id = s.student_id
        `;

        db.all(membersSql, [], (err, members) => {
            if (err) return res.status(500).json({ error: err.message });

            const result = projects.map(proj => {
                return {
                    ...proj,
                    members: members.filter(m => m.project_id === proj.project_id)
                };
            });

            res.json(result);
        });
    });
});

// GET /api/faculty - Get list of faculty members & evaluators
app.get('/api/faculty', (req, res) => {
    db.all(`SELECT * FROM faculty`, [], (err, rows) => {
        if (err) return res.status(500).json({ error: err.message });
        res.json(rows);
    });
});

// GET /api/evaluations/:projectId - Get complete evaluation matrix for project
app.get('/api/evaluations/:projectId', (req, res) => {
    const { projectId } = req.params;

    const sql = `
        SELECT 
            e.evaluation_id, e.student_id, e.project_id, e.faculty_id,
            e.phase, e.criterion, e.marks_obtained, e.maximum_marks,
            e.remarks, e.status, e.created_at, e.updated_at,
            s.usn, s.name as student_name,
            f.name as faculty_name
        FROM evaluations e
        JOIN students s ON e.student_id = s.student_id
        JOIN faculty f ON e.faculty_id = f.faculty_id
        WHERE e.project_id = ?
        ORDER BY s.usn, e.phase, e.criterion
    `;

    db.all(sql, [projectId], (err, rows) => {
        if (err) return res.status(500).json({ error: err.message });

        db.get(`SELECT is_locked, locked_by, locked_at FROM project_locks WHERE project_id = ?`, [projectId], (err, lockInfo) => {
            res.json({
                is_locked: lockInfo ? lockInfo.is_locked : 0,
                locked_by: lockInfo ? lockInfo.locked_by : null,
                evaluations: rows
            });
        });
    });
});

// POST /api/evaluations - Save or update marks (Security protected!)
app.post('/api/evaluations', checkRole, (req, res) => {
    const { role } = req;
    const userRole = req.userRole;

    // Security Check 1: Student role CANNOT save or edit marks
    if (userRole === 'student') {
        return res.status(403).json({ 
            error: 'Security Permission Denied: Students are restricted to read-only access and cannot enter or modify marks.' 
        });
    }

    const { project_id, items } = req.body; // items is array of { student_id, faculty_id, phase, criterion, marks_obtained, maximum_marks, remarks }

    if (!project_id || !Array.isArray(items)) {
        return res.status(400).json({ error: 'Invalid payload. Required: project_id and items array.' });
    }

    // Security Check 2: Check lock status
    db.get(`SELECT is_locked FROM project_locks WHERE project_id = ?`, [project_id], (err, lockRow) => {
        if (err) return res.status(500).json({ error: err.message });

        if (lockRow && lockRow.is_locked && userRole !== 'coordinator') {
            return res.status(403).json({ 
                error: 'Evaluation Sheet Locked: A Coordinator has locked this evaluation sheet. Edits are disabled.' 
            });
        }

        // Server-side mark validation ($0 <= mark <= max_marks)
        for (const item of items) {
            const mark = parseFloat(item.marks_obtained);
            const max = parseFloat(item.maximum_marks);

            if (isNaN(mark) || mark < 0) {
                return res.status(400).json({ error: `Validation Error: Mark for ${item.criterion} cannot be negative or invalid.` });
            }
            if (mark > max) {
                return res.status(400).json({ error: `Validation Error: Mark for ${item.criterion} (${mark}) cannot exceed maximum allowed (${max}).` });
            }
        }

        // Upsert into SQLite
        const stmt = db.prepare(`
            INSERT INTO evaluations (student_id, project_id, faculty_id, phase, criterion, marks_obtained, maximum_marks, remarks, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'submitted', CURRENT_TIMESTAMP)
            ON CONFLICT(student_id, project_id, phase, criterion, faculty_id) 
            DO UPDATE SET 
                marks_obtained = excluded.marks_obtained,
                remarks = excluded.remarks,
                updated_at = CURRENT_TIMESTAMP
        `);

        db.serialize(() => {
            db.run('BEGIN TRANSACTION');
            items.forEach(item => {
                stmt.run([
                    item.student_id,
                    project_id,
                    item.faculty_id,
                    item.phase,
                    item.criterion,
                    parseFloat(item.marks_obtained),
                    parseFloat(item.maximum_marks),
                    item.remarks || ''
                ]);
            });
            stmt.finalize();
            db.run('COMMIT', (err) => {
                if (err) return res.status(500).json({ error: err.message });
                res.json({ success: true, message: 'Evaluation marks successfully saved.' });
            });
        });
    });
});

// PATCH /api/evaluations/:projectId/lock - Lock/Unlock evaluation (Coordinator only)
app.patch('/api/evaluations/:projectId/lock', checkRole, (req, res) => {
    if (req.userRole !== 'coordinator') {
        return res.status(403).json({ error: 'Security Permission Denied: Only Coordinators can lock or unlock evaluations.' });
    }

    const { projectId } = req.params;
    const { is_locked, coordinator_name } = req.body;

    const lockVal = is_locked ? 1 : 0;
    const sql = `
        INSERT INTO project_locks (project_id, is_locked, locked_by, locked_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(project_id) DO UPDATE SET
            is_locked = excluded.is_locked,
            locked_by = excluded.locked_by,
            locked_at = CURRENT_TIMESTAMP
    `;

    db.run(sql, [projectId, lockVal, coordinator_name || 'Coordinator'], function(err) {
        if (err) return res.status(500).json({ error: err.message });
        res.json({
            success: true,
            is_locked: lockVal,
            message: lockVal ? 'Project evaluation sheet locked successfully.' : 'Project evaluation sheet unlocked.'
        });
    });
});

// GET /api/reports - Coordinator summary overview
app.get('/api/reports', checkRole, (req, res) => {
    if (req.userRole === 'student') {
        return res.status(403).json({ error: 'Access denied.' });
    }

    const sql = `
        SELECT 
            p.project_id, p.title, p.batch_no,
            s.usn, s.name as student_name,
            e.phase,
            AVG(e.marks_obtained) as avg_mark,
            SUM(e.marks_obtained) as total_mark,
            SUM(e.maximum_marks) as total_max
        FROM projects p
        JOIN project_members pm ON p.project_id = pm.project_id
        JOIN students s ON pm.student_id = s.student_id
        LEFT JOIN evaluations e ON s.student_id = e.student_id AND p.project_id = e.project_id
        GROUP BY p.project_id, s.student_id, e.phase
    `;

    db.all(sql, [], (err, rows) => {
        if (err) return res.status(500).json({ error: err.message });
        res.json(rows);
    });
});

app.listen(PORT, () => {
    console.log(`Standalone Evaluation System Server running at http://localhost:${PORT}`);
});
