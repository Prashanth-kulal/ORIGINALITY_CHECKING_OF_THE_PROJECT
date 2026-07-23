// Project Evaluation System - Client Application Logic

const API_BASE = '/api';

// Global State
const state = {
    activeRole: 'faculty', // 'faculty', 'student', 'coordinator'
    currentProjectId: 'P041',
    projects: [],
    evaluations: [],
    isLocked: false,
    facultyList: []
};

// DOM Elements
const elRoleFacultyBtn = document.getElementById('btn-role-faculty');
const elRoleStudentBtn = document.getElementById('btn-role-student');
const elRoleCoordBtn = document.getElementById('btn-role-coordinator');

const elRoleBadge = document.getElementById('role-badge');
const elLockStatusBadge = document.getElementById('lock-status-badge');
const elProjectSelect = document.getElementById('project-select');

const elBtnSave = document.getElementById('btn-save');
const elBtnLock = document.getElementById('btn-lock');
const elBtnPdf = document.getElementById('btn-pdf');
const elBtnReport = document.getElementById('btn-report');

const elBanner = document.getElementById('notification-banner');
const elRemarks = document.getElementById('input-remarks');

const elReportModal = document.getElementById('report-modal');
const elModalClose = document.getElementById('modal-close');
const elReportContent = document.getElementById('report-content');

// Initial Load
document.addEventListener('DOMContentLoaded', () => {
    initRoleSwitcher();
    initActionButtons();
    loadProjects();
});

// Role Switcher Setup
function initRoleSwitcher() {
    const roleBtns = [elRoleFacultyBtn, elRoleStudentBtn, elRoleCoordBtn];
    roleBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            roleBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.activeRole = btn.dataset.role;
            updateRoleUI();
        });
    });
}

function updateRoleUI() {
    // Update Badge
    elRoleBadge.className = 'badge ' + state.activeRole + '-badge';
    elRoleBadge.textContent = 'Role: ' + state.activeRole.toUpperCase();

    // Lock button visibility
    if (state.activeRole === 'coordinator') {
        elBtnLock.style.display = 'inline-flex';
    } else {
        elBtnLock.style.display = 'none';
    }

    // Save button state
    if (state.activeRole === 'student' || (state.isLocked && state.activeRole !== 'coordinator')) {
        elBtnSave.disabled = true;
        elBtnSave.title = state.activeRole === 'student' ? 'Students cannot save marks' : 'Sheet is locked by Coordinator';
    } else {
        elBtnSave.disabled = false;
        elBtnSave.title = 'Save entered marks';
    }

    // Toggle Read-Only on All Mark Inputs
    const allMarkInputs = document.querySelectorAll('.mark-input');
    const isReadOnly = (state.activeRole === 'student') || (state.isLocked && state.activeRole !== 'coordinator');

    allMarkInputs.forEach(input => {
        input.disabled = isReadOnly;
        input.readOnly = isReadOnly;
    });

    if (elRemarks) {
        elRemarks.readOnly = isReadOnly;
    }

    showBanner(`Switched active view role to: <strong>${state.activeRole.toUpperCase()}</strong>`, 'info');
}

// Action Buttons
function initActionButtons() {
    elBtnSave.addEventListener('click', saveEvaluationMarks);
    elBtnLock.addEventListener('click', toggleLockStatus);
    elBtnPdf.addEventListener('click', exportPDF);
    elBtnReport.addEventListener('click', showReportModal);
    
    if (elModalClose) {
        elModalClose.addEventListener('click', () => elReportModal.style.display = 'none');
    }
    
    elProjectSelect.addEventListener('change', (e) => {
        state.currentProjectId = e.target.value;
        loadProjectEvaluation(state.currentProjectId);
    });
}

// Fetch Projects List
async function loadProjects() {
    try {
        const res = await fetch(`${API_BASE}/projects`);
        const projects = await res.json();
        state.projects = projects;

        elProjectSelect.innerHTML = '';
        projects.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.project_id;
            opt.textContent = `${p.batch_no} - ${p.title}`;
            elProjectSelect.appendChild(opt);
        });

        if (projects.length > 0) {
            state.currentProjectId = projects[0].project_id;
            loadProjectEvaluation(state.currentProjectId);
        }
    } catch (err) {
        showBanner('Error loading projects: ' + err.message, 'error');
    }
}

// Fetch Project Evaluations
async function loadProjectEvaluation(projectId) {
    try {
        const res = await fetch(`${API_BASE}/evaluations/${projectId}`);
        const data = await res.json();

        state.isLocked = !!data.is_locked;
        state.evaluations = data.evaluations || [];

        // Update Lock Status Badge
        if (state.isLocked) {
            elLockStatusBadge.className = 'badge locked-badge';
            elLockStatusBadge.textContent = '🔒 Locked';
            elBtnLock.textContent = '🔓 Unlock Evaluation';
        } else {
            elLockStatusBadge.className = 'badge unlocked-badge';
            elLockStatusBadge.textContent = '🔓 Editable';
            elBtnLock.textContent = '🔒 Lock Evaluation';
        }

        // Update Metadata
        const proj = state.projects.find(p => p.project_id === projectId);
        if (proj) {
            document.getElementById('meta-academic-year').textContent = proj.academic_year;
            document.getElementById('meta-batch').textContent = proj.batch_no;
            document.getElementById('meta-project-title').textContent = proj.title;
        }

        // Render Tables
        renderPhase1Table(proj);
        renderPhase2Table(proj);
        renderReportTable(proj);
        recalculateAllTotals();
        updateRoleUI();

    } catch (err) {
        showBanner('Error loading evaluations: ' + err.message, 'error');
    }
}

// Render Phase 1 Matrix Table
function renderPhase1Table(proj) {
    const tbody = document.getElementById('tbody-phase1');
    tbody.innerHTML = '';

    if (!proj || !proj.members) return;

    proj.members.forEach((m, idx) => {
        const tr = document.createElement('tr');

        // Evaluator marks mapping: Guide (F001), Member 1 (F002), Member 2 (F003), Member 3 (F004), Member 4 (F005)
        const evaluators = ['F001', 'F002', 'F003', 'F004', 'F005'];
        
        let inputsHtml = '';
        evaluators.forEach(facId => {
            const ev = state.evaluations.find(e => e.student_id === m.student_id && e.phase === 'Phase 1' && e.faculty_id === facId);
            const val = ev ? ev.marks_obtained : 18;
            inputsHtml += `
                <td>
                    <input type="number" step="0.5" min="0" max="20" 
                           class="mark-input phase1-input" 
                           data-student="${m.student_id}" 
                           data-faculty="${facId}" 
                           data-phase="Phase 1" 
                           data-max="20"
                           value="${val}">
                </td>
            `;
        });

        tr.innerHTML = `
            <td>${idx + 1}</td>
            <td><strong>${m.usn}</strong></td>
            <td style="text-align: left;">${m.name}</td>
            ${inputsHtml}
            <td class="col-highlight"><strong id="p1-avg-${m.student_id}">0.0</strong></td>
        `;
        tbody.appendChild(tr);
    });

    attachInputListeners();
}

// Render Phase 2 Matrix Table
function renderPhase2Table(proj) {
    const tbody = document.getElementById('tbody-phase2');
    tbody.innerHTML = '';

    if (!proj || !proj.members) return;

    proj.members.forEach((m, idx) => {
        const tr = document.createElement('tr');
        const evaluators = ['F001', 'F002', 'F003', 'F004', 'F005'];
        
        let inputsHtml = '';
        evaluators.forEach(facId => {
            const ev = state.evaluations.find(e => e.student_id === m.student_id && e.phase === 'Phase 2' && e.faculty_id === facId);
            const val = ev ? ev.marks_obtained : 35;
            inputsHtml += `
                <td>
                    <input type="number" step="0.5" min="0" max="40" 
                           class="mark-input phase2-input" 
                           data-student="${m.student_id}" 
                           data-faculty="${facId}" 
                           data-phase="Phase 2" 
                           data-max="40"
                           value="${val}">
                </td>
            `;
        });

        tr.innerHTML = `
            <td>${idx + 1}</td>
            <td><strong>${m.usn}</strong></td>
            <td style="text-align: left;">${m.name}</td>
            ${inputsHtml}
            <td class="col-highlight"><strong id="p2-avg-${m.student_id}">0.0</strong></td>
        `;
        tbody.appendChild(tr);
    });

    attachInputListeners();
}

// Render Report & Attendance Table
function renderReportTable(proj) {
    const tbody = document.getElementById('tbody-report');
    tbody.innerHTML = '';

    if (!proj || !proj.members) return;

    proj.members.forEach((m, idx) => {
        const tr = document.createElement('tr');

        const evReport = state.evaluations.find(e => e.student_id === m.student_id && e.phase === 'Report_Attendance' && e.criterion === 'Report');
        const evAttd = state.evaluations.find(e => e.student_id === m.student_id && e.phase === 'Report_Attendance' && e.criterion === 'Attendance');
        const evSyn = state.evaluations.find(e => e.student_id === m.student_id && e.phase === 'Report_Attendance' && e.criterion === 'Synopsis');

        const valReport = evReport ? evReport.marks_obtained : 18;
        const valAttd = evAttd ? evAttd.marks_obtained : 9;
        const valSyn = evSyn ? evSyn.marks_obtained : 9;

        tr.innerHTML = `
            <td>${idx + 1}</td>
            <td><strong>${m.usn}</strong></td>
            <td style="text-align: left;">${m.name}</td>
            <td>
                <input type="number" step="0.5" min="0" max="20" class="mark-input report-input" data-student="${m.student_id}" data-criterion="Report" data-max="20" value="${valReport}">
            </td>
            <td>
                <input type="number" step="0.5" min="0" max="10" class="mark-input report-input" data-student="${m.student_id}" data-criterion="Attendance" data-max="10" value="${valAttd}">
            </td>
            <td>
                <input type="number" step="0.5" min="0" max="10" class="mark-input report-input" data-student="${m.student_id}" data-criterion="Synopsis" data-max="10" value="${valSyn}">
            </td>
            <td class="col-highlight"><strong id="report-total-${m.student_id}">0.0</strong></td>
        `;
        tbody.appendChild(tr);
    });

    attachInputListeners();
}

// Live Calculation Engine
function attachInputListeners() {
    const inputs = document.querySelectorAll('.mark-input');
    inputs.forEach(input => {
        input.removeEventListener('input', onMarkInputChange);
        input.addEventListener('input', onMarkInputChange);
    });
}

function onMarkInputChange(e) {
    const input = e.target;
    const val = parseFloat(input.value);
    const max = parseFloat(input.dataset.max);

    // Validate bounds
    if (isNaN(val) || val < 0 || val > max) {
        input.classList.add('invalid-mark');
        showBanner(`Validation Error: Mark must be between 0 and ${max}`, 'error');
    } else {
        input.classList.remove('invalid-mark');
        hideBanner();
    }

    recalculateAllTotals();
}

function recalculateAllTotals() {
    const proj = state.projects.find(p => p.project_id === state.currentProjectId);
    if (!proj || !proj.members) return;

    const summaryTbody = document.getElementById('tbody-summary');
    summaryTbody.innerHTML = '';

    proj.members.forEach((m, idx) => {
        // Calculate Phase 1 Avg
        const p1Inputs = document.querySelectorAll(`.phase1-input[data-student="${m.student_id}"]`);
        let p1Sum = 0, p1Count = 0;
        p1Inputs.forEach(inp => {
            const v = parseFloat(inp.value) || 0;
            p1Sum += v;
            p1Count++;
        });
        const p1Avg = p1Count > 0 ? (p1Sum / p1Count).toFixed(1) : '0.0';
        const p1El = document.getElementById(`p1-avg-${m.student_id}`);
        if (p1El) p1El.textContent = p1Avg;

        // Calculate Phase 2 Avg
        const p2Inputs = document.querySelectorAll(`.phase2-input[data-student="${m.student_id}"]`);
        let p2Sum = 0, p2Count = 0;
        p2Inputs.forEach(inp => {
            const v = parseFloat(inp.value) || 0;
            p2Sum += v;
            p2Count++;
        });
        const p2Avg = p2Count > 0 ? (p2Sum / p2Count).toFixed(1) : '0.0';
        const p2El = document.getElementById(`p2-avg-${m.student_id}`);
        if (p2El) p2El.textContent = p2Avg;

        // Calculate Report & Attendance Total
        const reportInputs = document.querySelectorAll(`.report-input[data-student="${m.student_id}"]`);
        let reportTotal = 0;
        reportInputs.forEach(inp => {
            reportTotal += parseFloat(inp.value) || 0;
        });
        const reportEl = document.getElementById(`report-total-${m.student_id}`);
        if (reportEl) reportEl.textContent = reportTotal.toFixed(1);

        // Overall Grand Total & Percentage
        const grandTotal = (parseFloat(p1Avg) + parseFloat(p2Avg) + reportTotal).toFixed(1);
        const percentage = (grandTotal / 100 * 100).toFixed(1) + '%';

        // Update Summary Row
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${idx + 1}</td>
            <td><strong>${m.usn}</strong></td>
            <td style="text-align: left;">${m.name}</td>
            <td>${p1Avg}</td>
            <td>${p2Avg}</td>
            <td>${reportTotal.toFixed(1)}</td>
            <td class="col-total">${grandTotal}</td>
            <td class="col-total">${percentage}</td>
        `;
        summaryTbody.appendChild(tr);
    });
}

// Save Evaluation Marks API Call
async function saveEvaluationMarks() {
    if (state.activeRole === 'student') {
        showBanner('Security Restriction: Student role cannot save or edit marks!', 'error');
        return;
    }

    const proj = state.projects.find(p => p.project_id === state.currentProjectId);
    if (!proj) return;

    const items = [];
    let hasValidationError = false;

    // Collect Phase 1 & 2 marks
    ['phase1', 'phase2'].forEach(phaseKey => {
        const phaseName = phaseKey === 'phase1' ? 'Phase 1' : 'Phase 2';
        const inputs = document.querySelectorAll(`.${phaseKey}-input`);
        inputs.forEach(inp => {
            const val = parseFloat(inp.value);
            const max = parseFloat(inp.dataset.max);
            if (isNaN(val) || val < 0 || val > max) {
                hasValidationError = true;
            }
            items.push({
                student_id: inp.dataset.student,
                faculty_id: inp.dataset.faculty,
                phase: phaseName,
                criterion: 'Combined Evaluation Criteria',
                marks_obtained: val,
                maximum_marks: max,
                remarks: elRemarks ? elRemarks.value : ''
            });
        });
    });

    // Collect Report & Attendance marks
    const reportInputs = document.querySelectorAll('.report-input');
    reportInputs.forEach(inp => {
        const val = parseFloat(inp.value);
        const max = parseFloat(inp.dataset.max);
        if (isNaN(val) || val < 0 || val > max) {
            hasValidationError = true;
        }
        items.push({
            student_id: inp.dataset.student,
            faculty_id: 'F001', // Guide
            phase: 'Report_Attendance',
            criterion: inp.dataset.criterion,
            marks_obtained: val,
            maximum_marks: max,
            remarks: elRemarks ? elRemarks.value : ''
        });
    });

    if (hasValidationError) {
        showBanner('Cannot save: Invalid marks detected! Correct errors highlighted in red.', 'error');
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/evaluations`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Role': state.activeRole
            },
            body: JSON.stringify({
                project_id: state.currentProjectId,
                role: state.activeRole,
                items: items
            })
        });

        const data = await res.json();
        if (!res.ok) {
            showBanner(`Security / Validation Error: ${data.error}`, 'error');
        } else {
            showBanner(`Success: ${data.message}`, 'success');
        }
    } catch (err) {
        showBanner('Network Error saving marks: ' + err.message, 'error');
    }
}

// Lock / Unlock Evaluation Sheet API Call (Coordinator Only)
async function toggleLockStatus() {
    if (state.activeRole !== 'coordinator') {
        showBanner('Security Restriction: Only Coordinators can lock/unlock evaluations.', 'error');
        return;
    }

    const newLockState = !state.isLocked;

    try {
        const res = await fetch(`${API_BASE}/evaluations/${state.currentProjectId}/lock`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-Role': state.activeRole
            },
            body: JSON.stringify({
                is_locked: newLockState,
                coordinator_name: 'Dr. Sachin Bhat'
            })
        });

        const data = await res.json();
        if (!res.ok) {
            showBanner(data.error, 'error');
        } else {
            state.isLocked = newLockState;
            showBanner(data.message, 'success');
            loadProjectEvaluation(state.currentProjectId);
        }
    } catch (err) {
        showBanner('Error toggling lock status: ' + err.message, 'error');
    }
}

// PDF Export Feature
function exportPDF() {
    const element = document.getElementById('marksheet-printable');
    const opt = {
        margin: [10, 10, 10, 10],
        filename: `Marksheet_Batch41_${state.currentProjectId}.pdf`,
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'landscape' }
    };

    showBanner('Generating A4 PDF Marksheet...', 'info');

    html2pdf().set(opt).from(element).save().then(() => {
        showBanner('PDF Marksheet downloaded successfully!', 'success');
    }).catch(err => {
        showBanner('Error exporting PDF: ' + err.message, 'error');
    });
}

// Summary Report Modal
async function showReportModal() {
    elReportModal.style.display = 'flex';
    elReportContent.innerHTML = '<p>Loading coordinator evaluation summary...</p>';

    try {
        const res = await fetch(`${API_BASE}/reports`, {
            headers: { 'X-Role': state.activeRole }
        });
        const rows = await res.json();

        if (!res.ok) {
            elReportContent.innerHTML = `<p class="text-danger">${rows.error}</p>`;
            return;
        }

        let html = `
            <table class="marks-table" style="width:100%; margin-top:10px;">
                <thead>
                    <tr>
                        <th>USN</th>
                        <th>Student Name</th>
                        <th>Phase</th>
                        <th>Total Marks</th>
                        <th>Max Marks</th>
                    </tr>
                </thead>
                <tbody>
        `;
        rows.forEach(r => {
            html += `
                <tr>
                    <td>${r.usn}</td>
                    <td>${r.student_name}</td>
                    <td>${r.phase || 'N/A'}</td>
                    <td>${r.total_mark ? r.total_mark.toFixed(1) : '0'}</td>
                    <td>${r.total_max || 0}</td>
                </tr>
            `;
        });
        html += '</tbody></table>';
        elReportContent.innerHTML = html;
    } catch (err) {
        elReportContent.innerHTML = `<p>Error loading report: ${err.message}</p>`;
    }
}

// Helper Banner Notifications
function showBanner(msg, type = 'info') {
    elBanner.style.display = 'block';
    elBanner.className = `banner banner-${type} no-print`;
    elBanner.innerHTML = msg;
}

function hideBanner() {
    elBanner.style.display = 'none';
}
