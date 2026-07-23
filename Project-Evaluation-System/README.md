# Project Evaluation System - Standalone Prototype

A university-grade **Project Evaluation System** prototype designed for evaluating student project presentations, synopsis, design, report, and attendance. Built matching the official **Shri Madhwa Vadiraja Institute of Technology and Management (SMVITM)** internal assessment evaluation format.

> [!IMPORTANT]
> This module is completely **standalone** and isolated. It operates independently with its own database, server backend, and interactive frontend.

---

## 📁 Folder Structure

```
Project-Evaluation-System/
│
├── backend/
│   ├── server.js          # Express.js REST API server & static file host
│   ├── database.js        # SQLite database connection & schema loader
│   ├── seed.js            # Sample data seeder matching SMVITM Batch 41
│   ├── package.json       # Node.js project configuration & dependencies
│   └── frontend/          # Web frontend application
│       ├── index.html     # Single Page App & University Marksheet UI
│       ├── styles.css     # Design system & printable A4 mark sheet styling
│       └── app.js         # Role switcher, live auto-calculations, validations & API integration
│
├── database/
│   └── schema.sql         # Plain DDL SQL database schema definition
│
├── pdf/                   # Exported PDF marksheet output directory
├── assets/                # Document assets & branding logos
└── README.md              # Documentation & future integration guide
```

---

## 🚀 How to Install & Run

### Prerequisites
- Node.js (v16+ recommended)

### 1. Install Dependencies
Navigate to the `backend` directory and install npm packages:
```bash
cd backend
npm install
```

### 2. Seed Test Database
Initialize and populate the database with SMVITM Batch 41 sample records (Students, Faculty, Coordinator, Project, and Baseline Marks):
```bash
npm run seed
```

### 3. Start Server
Launch the backend server:
```bash
npm start
```
The server will start at **http://localhost:4000**.

### 4. Access Interactive Prototype
Open your browser and navigate to:
```
http://localhost:4000
```

---

## 👥 Roles & Access Controls

| Role | View Marksheet | Enter/Edit Marks | Save Marks | Lock / Unlock | Print & PDF | Security Enforcement |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Faculty** | ✅ | ✅ | ✅ | ❌ | ✅ | Restricted from editing student metadata & locked evaluations. |
| **Student** | ✅ | ❌ | ❌ | ❌ | ✅ | Strictly read-only. API rejects mark updates with HTTP 403. |
| **Coordinator**| ✅ | ✅ | ✅ | ✅ | ✅ | Can edit any evaluation and toggle lock status for sheets. |

---

## 🗄️ Database Schema

### `students`
- `student_id` (PK, TEXT)
- `usn` (TEXT, UNIQUE)
- `name` (TEXT)
- `department` (TEXT)
- `semester` (INTEGER)

### `faculty`
- `faculty_id` (PK, TEXT)
- `name` (TEXT)
- `email` (TEXT, UNIQUE)
- `department` (TEXT)
- `designation` (TEXT)

### `coordinators`
- `coordinator_id` (PK, TEXT)
- `name` (TEXT)
- `email` (TEXT)
- `department` (TEXT)

### `projects`
- `project_id` (PK, TEXT)
- `title` (TEXT)
- `batch_no` (TEXT)
- `academic_year` (TEXT)
- `department` (TEXT)
- `guide_id` (FK -> `faculty.faculty_id`)

### `evaluations`
- `evaluation_id` (INTEGER, PK AUTOINCREMENT)
- `student_id` (FK -> `students.student_id`)
- `project_id` (FK -> `projects.project_id`)
- `faculty_id` (FK -> `faculty.faculty_id`)
- `phase` (TEXT: 'Phase 1', 'Phase 2', 'Report_Attendance')
- `criterion` (TEXT)
- `marks_obtained` (REAL)
- `maximum_marks` (REAL)
- `remarks` (TEXT)
- `status` (TEXT: 'draft', 'submitted', 'locked')
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

### `project_locks`
- `project_id` (FK -> `projects.project_id`, PK)
- `is_locked` (INTEGER: 0 or 1)
- `locked_by` (TEXT)
- `locked_at` (TIMESTAMP)

---

## 🌐 REST API Endpoints

| Method | Endpoint | Description | Security |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/projects` | List all projects with guide & student members | Public |
| `GET` | `/api/evaluations/:projectId` | Fetch complete evaluation matrix for project | Public |
| `POST` | `/api/evaluations` | Upsert evaluation marks | Protected (`X-Role` != Student, Non-locked) |
| `PATCH` | `/api/evaluations/:projectId/lock` | Lock or unlock project evaluation sheet | Protected (`X-Role` == Coordinator) |
| `GET` | `/api/reports` | Get summary assessment report for batch | Protected (`X-Role` != Student) |

---

## 🔄 How to Integrate this Standalone Module into Another Project Later

When you are ready to integrate this prototype into your main project, follow these step-by-step guidelines:

### 1. Database Integration
- Append the DDL table definitions in `database/schema.sql` to your existing project's database migration scripts.
- Replace SQLite references in `backend/database.js` with your main project's database client (e.g. MySQL, PostgreSQL, ORM like Prisma or Sequelize).

### 2. Backend Route Integration
- Copy the API handlers from `backend/server.js` into your main Express/FastAPI application.
- Replace the dummy `X-Role` header check middleware (`checkRole`) with your main application's JWT session authentication middleware (`req.user`).

### 3. Frontend Component Integration
- Embed the `#marksheet-printable` HTML template inside your main project's view/dashboard page.
- Include `styles.css` into your main CSS bundle or scoped component styles.
- Include `app.js` logic or refactor it into React/Vue/Angular state management.
