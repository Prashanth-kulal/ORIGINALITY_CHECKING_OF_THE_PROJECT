from flask_dance.contrib.google import make_google_blueprint, google
from flask import redirect, url_for, request
import os, jwt
import os # <--- FIXED IMPORT ORDER
from flask import Flask, request, jsonify, send_from_directory
from flask_pymongo import PyMongo
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename # CRITICAL for file upload security
import jwt
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from flask_socketio import SocketIO, emit, join_room
import random

import smtplib
from email.mime.text import MIMEText
# -------------------- Load Environment Variables -------------------- #
load_dotenv()


# --- Define the frontend folder path relative to the app.py file --- #
frontend_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))

# Configure Flask
app = Flask(__name__, static_folder=frontend_folder, static_url_path='/')
CORS(app)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# -------------------- Configuration -------------------- #
app.config["MONGO_URI"] = os.getenv("MONGO_URI")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

mongo = PyMongo(app)
db = mongo.db

# Ensure index on attendance collection (team_name + date unique constraint)
try:
    db.attendance.create_index([("team_name", 1), ("date", 1)], unique=True)
    db.teams.create_index("team_code", unique=True, sparse=True)
except Exception as idx_err:
    print("Notice setting up attendance/team indexes:", idx_err)

def generate_unique_team_code():
    """Generates a predictable, collision-free unique team code e.g. SMV261042."""
    year_prefix = datetime.now().strftime("%y")
    prefix = f"SMV{year_prefix}"
    for _ in range(100):
        rand_digits = str(random.randint(1000, 9999))
        code = f"{prefix}{rand_digits}"
        if not db.teams.find_one({"team_code": code}):
            return code
    return f"{prefix}{int(datetime.now().timestamp()) % 10000:04d}"

def migrate_legacy_teams():
    try:
        teams_without_code = list(db.teams.find({"team_code": {"$exists": False}}))
        for team in teams_without_code:
            code = generate_unique_team_code()
            db.teams.update_one({"_id": team["_id"]}, {"$set": {"team_code": code}})
            print(f"Migrated legacy team '{team.get('team_name')}' -> Team Code: {code}")
    except Exception as e:
        print(f"Notice during team code migration: {e}")

migrate_legacy_teams()



# --- Configuration for File Uploads ---
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')

# CRITICAL: Create the folder if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER



def send_email_notification(to_email, subject, message):
    try:
        sender_email = os.getenv("EMAIL_USER")
        sender_password = os.getenv("EMAIL_PASS")

        msg = MIMEText(message)
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = to_email

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)

        server.sendmail(sender_email, to_email, msg.as_string())
        server.quit()

        print("✅ Email sent to:", to_email)

    except Exception as e:
        print("❌ Email error:", e)

# ==================================================================== #
#                       FRONTEND ROUTES                                #
# ==================================================================== #

@app.route('/')
def serve_login():
    """Redirect root URL to login page"""
    return send_from_directory(frontend_folder, 'login.html')

@app.route('/<path:filename>')
def serve_static_files(filename):
    """Serve frontend files"""
    return send_from_directory(frontend_folder, filename)

# ==================================================================== #
#                       REGISTRATION ROUTES                            #
# ==================================================================== #
from flask_dance.contrib.google import google
from flask import redirect, request

@app.route("/login/success")
def google_login_success():
    if not google.authorized:
        return redirect("/login")

    resp = google.get("/oauth2/v2/userinfo")
    user_info = resp.json()

    email = user_info.get("email")
    name = user_info.get("name")

    # Check TEAM
    user = mongo.db.teams.find_one({"leader_email": email})
    if user:
        role = "team"
        token = jwt.encode({"email": email, "role": role}, app.config["SECRET_KEY"], algorithm="HS256")
        return redirect(f"/team-dasboard.html?token={token}")

    # Check FACULTY
    user = mongo.db.faculty.find_one({"email": email})
    if user:
        role = "faculty"
        token = jwt.encode({"email": email, "role": role}, app.config["SECRET_KEY"], algorithm="HS256")
        return redirect(f"/faculty-dashboard.html?token={token}")

    # ❌ New user → go to registration
    return redirect(f"/index.html?email={email}&name={name}")
    

google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    scope=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile"
    ],
    redirect_url="/login/success"
)


app.register_blueprint(google_bp, url_prefix="/login")

@app.route("/api/login/team", methods=["POST"])
def team_login():
    # Redirect to main login endpoint with team role
    data = request.json
    data["role"] = "team"
    
    # Call the main login logic
    email = data.get("email")
    password = data.get("password")
    role = "team"

    if not email or not password:
        return jsonify({"error": "All fields are required"}), 400

    user = db.teams.find_one({"leader_email": email})

    if not user:
        return jsonify({"error": "User not found"}), 404

    # ✅ FIX: Handle both 'leader_password' and 'password'
    stored_password = user.get("password") or user.get("leader_password", "")

    # ✅ FIX: Handle both hashed + plain
    valid_password = False
    try:
        if any(stored_password.startswith(p) for p in ["pbkdf2:", "scrypt:", "$2b$", "$2a$", "bcrypt:"]):
            valid_password = check_password_hash(stored_password, password)
        else:
            valid_password = (stored_password == password)
    except Exception as e:
        print(f"Password check error: {e}")
        valid_password = False

    if not valid_password:
        return jsonify({"error": "Invalid password"}), 401

    # Create JWT token
    token = jwt.encode({
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=2)
    }, app.config["SECRET_KEY"], algorithm="HS256")

    return jsonify({
        "message": "Login successful",
        "token": token,
        "redirect": "team-dasboard.html",
        "leader_name": user.get("leader_name")
    }), 200




@app.route('/api/register/team', methods=['POST'])
def register_team():
    data = request.json or {}
    team_name = data.get("team_name", "").strip()
    leader_name = data.get("leader_name", "").strip()
    leader_email = data.get("leader_email", "").strip().lower()
    leader_password = data.get("leader_password", "")
    members = data.get("members", [])
    interests = data.get("interests", [])

    if not team_name or not leader_email or not leader_password:
        return jsonify({"error": "Missing required fields (Team Name, Leader Email, Password)"}), 400

    if db.teams.find_one({"leader_email": leader_email}):
        return jsonify({"error": "Leader email is already registered"}), 400

    if db.teams.find_one({"team_name": team_name}):
        return jsonify({"error": "Team name is already registered"}), 400

    # Normalize member emails
    clean_members = [m.strip().lower() for m in members if isinstance(m, str) and m.strip()]

    team_code = generate_unique_team_code()
    hashed_password = generate_password_hash(leader_password)

    db.teams.insert_one({
        "team_code": team_code,
        "team_name": team_name,
        "leader_name": leader_name,
        "leader_email": leader_email,
        "password": hashed_password,
        "members": clean_members,
        "interests": interests,
        "role": "team",
        "created_at": datetime.now(timezone.utc)
    })

    return jsonify({
        "message": "Team registered successfully!",
        "team_code": team_code,
        "team_name": team_name
    }), 201


@app.route('/api/register/faculty', methods=['POST'])
def register_faculty():
    data = request.json
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")
    expertise = data.get("expertise", [])

    if not name or not email or not password:
        return jsonify({"error": "Missing required fields"}), 400

    if db.faculty.find_one({"email": email}):
        return jsonify({"error": "Faculty already registered"}), 400

    db.faculty.insert_one({
        "name": name,
        "email": email,
        "password": generate_password_hash(password),
        "expertise": expertise,
        "role": "faculty",
        "created_at": datetime.now(timezone.utc)
    })

    return jsonify({"message": "Faculty registered successfully!"}), 201

# ==================================================================== #
#                       LOGIN ROUTE                                    #
# ==================================================================== #

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password")
    role = data.get("role")
    team_code = data.get("team_code", "").strip().upper()

    if not email or not password or not role:
        return jsonify({"error": "All fields are required"}), 400

    user = None

    # Identify correct collection & role
    if role in ["student", "team"]:
        if team_code:
            user = db.teams.find_one({"team_code": team_code})
            if not user:
                return jsonify({"error": "Invalid Team Code. Please check and try again."}), 404

            # Verify student email belongs to this team (leader or member)
            team_leader = user.get("leader_email", "").strip().lower()
            team_members = [m.strip().lower() for m in user.get("members", []) if isinstance(m, str)]

            if email != team_leader and email not in team_members:
                return jsonify({"error": "Student email is not registered under this Team Code."}), 403
        else:
            # Fallback for legacy login without Team Code
            user = db.teams.find_one({
                "$or": [
                    {"leader_email": email},
                    {"members": {"$in": [email]}}
                ]
            })
            if not user:
                return jsonify({"error": "Team Code is required for student login."}), 400

        role = "team"
    elif role == "faculty":
        user = db.faculty.find_one({"email": email})
        if not user:
            user = db.faculty.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
    elif role == "coordinator":
        user = db.coordinator.find_one({"email": email})
        if not user:
            user = db.faculty.find_one({"email": email, "role": "coordinator"})

    if not user:
        return jsonify({"error": "User not found"}), 404

    # Password check
    stored_password = user.get("password") or user.get("leader_password", "")
    valid_password = False
    try:
        if any(stored_password.startswith(p) for p in ["pbkdf2:", "scrypt:", "$2b$", "$2a$", "bcrypt:"]):
            valid_password = check_password_hash(stored_password, password)
        else:
            valid_password = (stored_password == password)
    except Exception as e:
        print(f"Password check error: {e}")
        valid_password = False

    if not valid_password:
        return jsonify({"error": "Incorrect Team Password" if role == "team" else "Invalid password"}), 401

    # Auto-normalize DB for old teams
    if "leader_password" in user and "password" not in user:
        db.teams.update_one(
            {"_id": user["_id"]},
            {"$set": {"password": stored_password}, "$unset": {"leader_password": ""}}
        )

    # Create JWT token
    token = jwt.encode({
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=2)
    }, app.config["SECRET_KEY"], algorithm="HS256")

    # Redirect based on role
    redirect_url = ""
    if role in ["student", "team"]:
        redirect_url = "team-dasboard.html"
    elif role == "faculty":
        redirect_url = "faculty-dashboard.html"
    elif role == "coordinator":
        redirect_url = "project_coordinator-dashboard.html"

    return jsonify({"token": token, "redirect": redirect_url}), 200

# ==================================================================== #
#                       TEAM DASHBOARD ROUTE (FINAL)                   #
# ==================================================================== #

@app.route('/api/dashboard/team', methods=['GET'])
def team_dashboard():
    
    token_full = request.headers.get("Authorization")
    if not token_full:
        return jsonify({"error": "Missing token"}), 401

    token = token_full.split()[-1]

    try:
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded["email"]

        # ✅ Find team by leader or member email
        team = db.teams.find_one({
            "$or": [
                {"leader_email": email},
                {"members": {"$in": [email]}}
            ]
        })

        if not team:
            return jsonify({"error": "Team not found"}), 404

        data = {
            "team_name": team.get("team_name"),
            "leader_name": team.get("leader_name"),
            "members": team.get("members", []),
            "interests": team.get("interests", []),
            "tasks": team.get("tasks", []),
            "approvals": team.get("approvals", []),
            "feedbacks": team.get("feedbacks", []),
            "marks": team.get("marks", []),
            "progress": team.get("progress", []),

            # ✅ ✅ ✅ ADD THIS LINE
            "project_idea": team.get("project_idea")
        }

        return jsonify(data), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except Exception as e:
        print(f"Token processing error in team dashboard: {e}")
        return jsonify({"error": "Authentication failed"}), 401


# ==================================================================== #
#                       FACULTY DASHBOARD ROUTE (UPDATED)              #
# ==================================================================== #

@app.route('/api/dashboard/faculty', methods=['GET'])
def faculty_dashboard():
    token_full = request.headers.get("Authorization")
    if not token_full:
        return jsonify({"error": "Missing token"}), 401

    token = token_full.split()[-1]

    try:
        decoded = jwt.decode(
            token,
            app.config["SECRET_KEY"],
            algorithms=["HS256"]
        )
        email = decoded["email"]

        if decoded.get("role") not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized role"}), 403

        faculty = db.faculty.find_one({"email": email})
        if not faculty:
            return jsonify({"error": "Faculty not found"}), 404

        # ✅ Fetch all teams assigned to this faculty, INCLUDING tasks, feedbacks, and marks
        teams = list(
    db.teams.find(
        {"faculty_email": email},
        {
            "_id": 0,
            "team_name": 1,
            "leader_name": 1,
            "members": 1,
            "interests": 1,
            "progress": 1,
            "tasks": 1,
            "feedbacks": 1,
            "marks": 1,
            "project_idea": 1   # ✅ REQUIRED
        }
    )
)

        # If no teams assigned, fetch all teams (fallback for testing)
        if not teams:
            print(f"No teams assigned to faculty {email}, fetching all teams as fallback")
            teams = list(
                db.teams.find(
                    {},
                    {
                        "_id": 0,
                        "team_name": 1,
                        "leader_name": 1,
                        "members": 1,
                        "interests": 1,
                        "progress": 1,
                        "tasks": 1,
                        "feedbacks": 1,
                        "marks": 1,
                        "project_idea": 1,
                        "faculty_email": 1,
                        "faculty_name": 1
                    }
                )
            )


        data = {
            "faculty_name": faculty.get("name"),
            "expertise": faculty.get("expertise", []),
            "allocated_teams": teams
        }

        return jsonify(data), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401

    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

    except Exception as e:
        print(f"Token processing error in faculty dashboard: {e}")
        return jsonify({"error": "Authentication failed"}), 401



# ==================================================================== #
#                     FACULTY → UPDATE FEEDBACK/TASKS/APPROVALS        #
# ==================================================================== #

@app.route('/api/faculty/update_feedback', methods=['POST'])
def update_feedback():
    data = request.json
    team_name = data.get("team_name")
    feedback_text = data.get("feedback")

    if not team_name or not feedback_text:
        return jsonify({"error": "Team name and feedback are required"}), 400

    # ✅ Create feedback entry with timestamp
    new_feedback = {
        "feedback": feedback_text,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    # ✅ Push into array (DO NOT REPLACE)
    db.teams.update_one(
        {"team_name": team_name},
        {"$push": {"feedbacks": new_feedback}}
    )

    # 🔥 ADD EMAIL HERE
    team = db.teams.find_one({"team_name": team_name})
    if team and team.get("leader_email"):
        send_email_notification(
            team["leader_email"],
            "💬 New Feedback Received",
            f"Hello {team_name},\n\nFeedback:\n{feedback_text}\n\nCheck your dashboard."
        )

    return jsonify({"message": "Feedback added successfully!"}), 200


@app.route("/api/faculty/delete_feedback", methods=["POST"])
def delete_feedback():
    data = request.json
    team_name = data.get("team_name")
    feedback_index = data.get("feedback_index")

    db.teams.update_one(
        {"team_name": team_name},
        {"$unset": {f"feedbacks.{feedback_index}": 1}}
    )
    db.teams.update_one(
        {"team_name": team_name},
        {"$pull": {"feedbacks": None}}
    )

    return jsonify({"message": "Feedback deleted"}), 200


@app.route('/api/faculty/update_tasks', methods=['POST'])
def update_tasks():
    data = request.json
    team_name = data.get("team_name")
    new_task = data.get("new_task") # FIX: Expecting single new_task object

    if not team_name or not new_task:
        return jsonify({"error": "Team name and new task required"}), 400

    # FIX: Use $push to append the new task to the array
    db.teams.update_one({"team_name": team_name}, {"$push": {"tasks": new_task}})
    # 🔥 ADD EMAIL HERE
    team = db.teams.find_one({"team_name": team_name})
    if team and team.get("leader_email"):
        send_email_notification(
            team["leader_email"],
            "📌 New Task Assigned",
            f"Hello {team_name},\n\nNew Task: {new_task.get('name')}\nDeadline: {new_task.get('deadline')}\n\nCheck your dashboard."
        )
    return jsonify({"message": "Task assigned successfully!"}), 200



@app.route("/api/faculty/delete_task", methods=["POST"])
def delete_task():
    data = request.json
    team_name = data.get("team_name")
    task_index = data.get("task_index")

    db.teams.update_one(
        {"team_name": team_name},
        {"$unset": {f"tasks.{task_index}": 1}}
    )
    db.teams.update_one(
        {"team_name": team_name},
        {"$pull": {"tasks": None}}
    )

    return jsonify({"message": "Task deleted successfully"}), 200


@app.route('/api/faculty/update_approvals', methods=['POST'])
def update_approvals():
    data = request.json
    team_name = data.get("team_name")
    new_approval = data.get("new_approval") # FIX: Expecting single new_approval object

    if not team_name or not new_approval:
        return jsonify({"error": "Team name and approval status required"}), 400

    # 1. Try to update an existing stage's status
    result = db.teams.update_one(
        {"team_name": team_name, "approvals.stage": new_approval["stage"]},
        {"$set": {"approvals.$.status": new_approval["status"]}}
    )

    # 2. If no existing stage was modified (matched_count == 0), push the new one
    if result.matched_count == 0:
        db.teams.update_one(
            {"team_name": team_name},
            {"$push": {"approvals": new_approval}}
        )

    return jsonify({"message": "Approval status updated successfully!"}), 200


@app.route("/api/faculty/update_project_status", methods=["POST"])
def update_project_status():
    data = request.json
    team_name = data.get("team_name")
    status = data.get("status")

    db.teams.update_one(
        {"team_name": team_name},
        {"$set": {"project_idea.status": status}}
    )

    return jsonify({"message": f"Project idea {status}"}), 200

@app.route("/api/team/save_project_idea", methods=["POST"])
def save_project_idea():
    token_full = request.headers.get("Authorization")
    if not token_full:
        return jsonify({"error": "Missing token"}), 401

    token = token_full.split()[-1]

    try:
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded["email"]

        team = db.teams.find_one({
            "$or": [
                {"leader_email": email},
                {"members": {"$in": [email]}}
            ]
        })

        if not team:
            return jsonify({"error": "Team not found"}), 404

        data = request.json

        project_data = {
            "title": data.get("title"),
            "abstract": data.get("abstract"),
            "originality_score": data.get("originality_score"),
            "similarity_percent": data.get("similarity_percent"),
            "most_similar_project": data.get("most_similar_project"),
            "status": "Pending Faculty Approval",
            "submitted_at": datetime.now().isoformat()
        }

        db.teams.update_one(
            {"team_name": team["team_name"]},
            {"$set": {"project_idea": project_data}}
        )

        return jsonify({"message": "Project idea submitted to faculty"}), 200

    except Exception as e:
        print("Error saving project idea:", e)
        return jsonify({"error": "Internal server error"}), 500

# ==================================================================== #
#                     FACULTY → ADD ASSESSMENT MARKS                    #
# ==================================================================== #

from datetime import datetime, timezone # Ensure these imports are at the top

@app.route('/api/faculty/add_assessment_marks', methods=['POST'])
def add_assessment_marks():
    # --- Authentication/Authorization check would ideally go here ---
    
    data = request.json
    team_name = data.get("team_name")
    new_assessment = data.get("new_assessment") # Expected: {"assessment": str, "members": [{"member": str, "marks": int}, ...]}

    if not team_name or not new_assessment or not new_assessment.get("assessment") or not new_assessment.get("members"):
        return jsonify({"error": "Team name, assessment name, and member marks list are all required"}), 400

    # Structure to be pushed to the 'marks' array in the team document
    marks_entry = {
        "assessment": new_assessment.get("assessment"),
        "date": datetime.now(timezone.utc).isoformat(),
        "members_marks": new_assessment.get("members")
    }

    # Use $push to append the new assessment entry to the 'marks' array
    # This assumes the 'marks' field in the MongoDB 'teams' collection is an array.
    db.teams.update_one(
        {"team_name": team_name}, 
        {"$push": {"marks": marks_entry}}
    )

    # 🔥 ADD EMAIL HERE
    team = db.teams.find_one({"team_name": team_name})
    if team and team.get("leader_email"):
        send_email_notification(
            team["leader_email"],
            "🏆 Marks Updated",
            f"Hello {team_name},\n\nMarks added for: {marks_entry.get('assessment')}\n\nCheck dashboard."
        )
    
    return jsonify({"message": f"Assessment marks recorded successfully for {team_name} ({marks_entry['assessment']})!"}), 200


@app.route("/api/faculty/delete_marks", methods=["POST"])
def delete_marks():
    data = request.json
    team_name = data.get("team_name")
    marks_index = data.get("marks_index")

    db.teams.update_one(
        {"team_name": team_name},
        {"$unset": {f"marks.{marks_index}": 1}}
    )
    db.teams.update_one(
        {"team_name": team_name},
        {"$pull": {"marks": None}}
    )

    return jsonify({"message": "Marks entry deleted"}), 200


# ==================================================================== #
#                       TEAM → UPLOAD PROGRESS FILE (CORRECTED)                 #
# ==================================================================== #

@app.route('/api/team/upload_progress', methods=['POST'])
def upload_progress():
    token_full = request.headers.get("Authorization")
    if not token_full:
        return jsonify({"error": "Missing token"}), 401

    token = token_full.split()[-1]
    file_path = None

    try:
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded["email"]

        team = db.teams.find_one({
            "$or": [
                {"leader_email": email},
                {"members": {"$in": [email]}}
            ]
        })

        if not team:
            return jsonify({"error": "Team not found"}), 404

        # FIX: Retrieve form data (using request.form and request.files for FormData)
        file = request.files.get('progress_file')
        file_name_from_form = request.form.get("file_name")
        notes = request.form.get("notes")

        if not file_name_from_form and not notes:
            return jsonify({"error": "File name or notes required"}), 400

        # ---- Correct File Save Logic ----
        unique_filename = None

        if file and file.filename != '':
            filename_secured = secure_filename(file.filename)
            unique_filename = f"{team['team_name']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename_secured}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(save_path)


        # Prepare database entry
        new_entry = {
        "file_name": unique_filename,     # Always store REAL filename
        "notes": notes or "",
        "file_path": unique_filename,     # Store only filename
        "submitted_at": datetime.now().isoformat()
    }


        # Append new progress entry to team document
        db.teams.update_one(
            {"team_name": team["team_name"]},
            {"$push": {"progress": new_entry}}
        )

        return jsonify({
            "message": "Progress uploaded successfully!",
            "file_uploaded": bool(file_path),
            "file_name": file_name_from_form
        }), 200

    except Exception as e:
        print("Error in upload_progress:", e)
        return jsonify({"error": "Internal server error"}), 500


# ==================================================================== #
#                       FILE DOWNLOAD ROUTE                            #
# ==================================================================== #

@app.route('/api/download_file/<filename>', methods=['GET'])
def download_file(filename):
    try:
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            filename,
            as_attachment=True
        )
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404



# ==================================================================== #
#                        COORDINATOR DASHBOARD ROUTE (FIXED)           #
# ==================================================================== #

@app.route('/api/dashboard/coordinator', methods=['GET'])
def coordinator_dashboard():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401

    try:
        token = token.split(" ")[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded["email"]

        coordinator = db.coordinator.find_one({"email": email})
        if not coordinator:
            coordinator = db.faculty.find_one({"email": email, "role": "coordinator"})
        if not coordinator:
            return jsonify({"error": "Coordinator not found"}), 404

        # 1. Fetch ALL Teams with required progress/approval data
        teams = list(db.teams.find({}, {
            "_id": 0, 
            "team_name": 1, 
            "leader_name": 1, 
            "progress": 1, 
            "approvals": 1,
            "marks": 1,
            "project_idea": 1   # ADD THIS

        }))
        
        # 2. Fetch ALL CURRENT Allocations from the live collection
        allocations = list(db.allocations.find({}, {
            "_id": 0,
            "team_name": 1,
            "faculty_name": 1,
            "faculty_email": 1
        }))

        data = {
            "coordinator_name": coordinator.get("name"),
            "teams": teams, # Contains full team data
            "allocations": allocations, # Contains the live team-faculty mapping
        }
        return jsonify(data), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except Exception as e:
        return jsonify({"error": "Authentication failed"}), 401
        

@app.route('/api/marks/<team_name>', methods=['GET'])
def get_team_marks(team_name):
    team = db.teams.find_one({"team_name": team_name}, {"_id": 0, "marks": 1})
    
    if not team:
        return jsonify({"error": "Team not found"}), 404

    marks = team.get("marks", [])
    if not marks:
        return jsonify({"message": "No marks available for this team."}), 200

    return jsonify({"marks": marks}), 200



# Get all ideas from all teams (handles single project_idea or multiple project_ideas)
@app.route('/api/ideas/all', methods=['GET'])
def get_all_ideas():
    try:
        ideas_out = []
        teams = list(db.teams.find({}, {"_id": 0, "team_name": 1, "faculty_email": 1, "faculty_name": 1, "project_idea": 1, "project_ideas": 1}))
        for t in teams:
            team_name = t.get("team_name", "Unknown Team")
            faculty_name = t.get("faculty_name") or t.get("faculty_email") or "Not Assigned"

            # Case 1: single idea object
            if isinstance(t.get("project_idea"), dict):
                pi = t["project_idea"]
                ideas_out.append({
                    "team_name": team_name,
                    "faculty_name": faculty_name,
                    "title": pi.get("title"),
                    "abstract": pi.get("abstract"),
                    "originality_score": pi.get("originality_score"),
                    "similarity_percent": pi.get("similarity_percent"),
                    "status": pi.get("status", "Pending Faculty Approval"),
                    "submitted_at": pi.get("submitted_at")
                })

            # Case 2: multiple ideas in array
            if isinstance(t.get("project_ideas"), list):
                for pi in t["project_ideas"]:
                    ideas_out.append({
                        "team_name": team_name,
                        "faculty_name": faculty_name,
                        "title": pi.get("title"),
                        "abstract": pi.get("abstract"),
                        "originality_score": pi.get("originality_score"),
                        "similarity_percent": pi.get("similarity_percent"),
                        "status": pi.get("status", "Pending Faculty Approval"),
                        "submitted_at": pi.get("submitted_at")
                    })

        return jsonify({"ideas": ideas_out}), 200

    except Exception as e:
        print("Error in get_all_ideas:", e)
        return jsonify({"error": "Internal server error"}), 500


# Update idea status (Approve / Reject) for a team idea
@app.route('/api/ideas/update_status', methods=['POST'])
def update_idea_status():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") not in ["coordinator", "faculty"]:
            return jsonify({"error": "Unauthorized"}), 403

        data = request.json
        team_name = data.get("team_name")
        title = data.get("title")
        new_status = data.get("status")

        if not team_name or not title or not new_status:
            return jsonify({"error": "team_name, title and status are required"}), 400

        # Try to update single project_idea
        team = db.teams.find_one({"team_name": team_name})
        if not team:
            return jsonify({"error": "Team not found"}), 404

        updated = False
        # single idea
        if isinstance(team.get("project_idea"), dict) and team["project_idea"].get("title") == title:
            db.teams.update_one({"team_name": team_name}, {"$set": {"project_idea.status": new_status}})
            updated = True

        # multiple ideas
        if not updated and isinstance(team.get("project_ideas"), list):
            # update the matching array element
            result = db.teams.update_one(
                {"team_name": team_name, "project_ideas.title": title},
                {"$set": {"project_ideas.$.status": new_status}}
            )
            if result.modified_count > 0:
                updated = True

        if not updated:
            return jsonify({"error": "Idea not found for given team and title"}), 404

        return jsonify({"message": f"Idea status updated to {new_status}"}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except Exception as e:
        print("Error in update_idea_status:", e)
        return jsonify({"error": "Internal server error"}), 500



# ==================================================================== #
#                   MANAGE USERS ROUTES (NEW)                          #
# ==================================================================== #

@app.route('/api/admin/faculty', methods=['GET'])
def get_all_faculty_details():
    """Returns all faculty details for management (excluding password hash)."""
    try:
        # Exclude password hash and _id
        faculties = list(db.faculty.find({}, {"_id": 0, "password": 0})) 
        return jsonify({"faculty": faculties}), 200
    except Exception as e:
        print(f"Error fetching faculty list: {e}")
        return jsonify({"error": "Server error fetching faculty list"}), 500

@app.route('/api/admin/teams', methods=['GET'])
def get_all_team_details():
    """Returns all team details for management (excluding leader password)."""
    try:
        # Exclude password hash and _id
        teams = list(db.teams.find({}, {"_id": 0, "leader_password": 0}))
        return jsonify({"teams": teams}), 200
    except Exception as e:
        print(f"Error fetching team list: {e}")
        return jsonify({"error": "Server error fetching team list"}), 500

@app.route('/api/admin/faculty/delete', methods=['POST'])
def delete_faculty():
    """Deletes a faculty member and removes their assignments."""
    try:
        data = request.json
        email = data.get('email')
        if not email:
            return jsonify({"error": "Faculty email required"}), 400

        # 1. Delete the faculty member
        db.faculty.delete_one({"email": email})
        
        # 2. Unassign teams from this faculty
        db.teams.update_many(
            {"faculty_email": email},
            {"$set": {"faculty_email": None, "faculty_name": None, "manual_allocation": False}}
        )
        # 3. Remove from current allocation snapshot
        db.allocations.delete_many({"faculty_email": email})

        return jsonify({"message": f"Faculty {email} and associated teams unassigned."}), 200
    except Exception as e:
        print(f"Error deleting faculty: {e}")
        return jsonify({"error": "Server error deleting faculty"}), 500


@app.route('/api/admin/teams/delete', methods=['POST'])
def delete_team():
    """Deletes a team and all related documents (ideas, allocations)."""
    try:
        data = request.json
        team_name = data.get('team_name')
        if not team_name:
            return jsonify({"error": "Team name required"}), 400

        # 1. Delete the team
        db.teams.delete_one({"team_name": team_name})
        
        # 2. Delete related documents
        db.ideas.delete_many({"team_name": team_name})
        db.allocations.delete_many({"team_name": team_name})

        return jsonify({"message": f"Team {team_name} and all related data deleted."}), 200
    except Exception as e:
        print(f"Error deleting team: {e}")
        return jsonify({"error": "Server error deleting team"}), 500

# ==================================================================== #
#                   SMART AUTO ALLOCATION (UPDATED)                    #
# ==================================================================== #
@app.route('/api/allocate', methods=['POST'])
def smart_auto_allocate():
    """
    Smart allocation of teams to faculty:
    - Prioritizes matching by shared interests/expertise.
    - Limits each faculty to 3 teams max.
    - Fills unallocated teams with available faculty.
    - PRESERVES teams where manual_allocation=True.
    """
    try:
        # Fetch all teams, including new fields for manual allocation status
        teams = list(db.teams.find({}, {"_id": 0, "team_name": 1, "leader_name": 1, "interests": 1, "manual_allocation": 1, "faculty_email": 1, "faculty_name": 1}))
        faculties = list(db.faculty.find({}, {"_id": 0, "name": 1, "email": 1, "expertise": 1}))

        if not teams or not faculties:
            return jsonify({"error": "No teams or faculty found"}), 400

        max_teams_per_faculty = 3
        allocations = []
        
        # Initialize Load with 0
        faculty_load = {f["email"]: 0 for f in faculties}

        # --- STEP A: Handle Manually Allocated Teams (LOCKED) ---
        # Separate teams into "Locked" (Manual) and "Free" (Auto)
        locked_teams = [t for t in teams if t.get("manual_allocation") is True]
        free_teams = [t for t in teams if t.get("manual_allocation") is not True]

        # Process Locked Teams: Count them towards the load and add to allocations
        for team in locked_teams:
            f_email = team.get("faculty_email")
            # We must count them towards capacity, even if the faculty email is null or non-existent
            if f_email and f_email in faculty_load:
                faculty_load[f_email] += 1
                allocations.append({
                    "team_name": team["team_name"],
                    "faculty_name": team.get("faculty_name", "Unknown"),
                    "faculty_email": f_email,
                    "match_score": 0,
                    "match_percentage": "Manual" # Flag for UI
                })
        
        # --- STEP B: Auto Allocate the Free Teams ---
        
        # Compute similarity scores for all pairs (using only free_teams)
        matches = []
        for team in free_teams:
            for faculty in faculties:
                team_interests = [i.lower() for i in team.get("interests", [])]
                faculty_expertise = [e.lower() for e in faculty.get("expertise", [])]

                overlap = len(set(team_interests) & set(faculty_expertise))
                max_keywords = max(len(team_interests), len(faculty_expertise)) or 1
                similarity_percentage = round((overlap / max_keywords) * 100, 2)

                matches.append({
                    "team": team["team_name"],
                    "faculty": faculty["name"],
                    "faculty_email": faculty["email"],
                    "score": overlap,
                    "match_percentage": similarity_percentage
                })

        # Sort all matches by score descending
        matches.sort(key=lambda x: x["score"], reverse=True)

        allocated_free_teams = set()

        # Assign best matches first
        for match in matches:
            team_name = match["team"]
            faculty_email = match["faculty_email"]

            # Check if team is already handled OR faculty is full (faculty_load includes manual teams)
            if team_name not in allocated_free_teams and faculty_load[faculty_email] < max_teams_per_faculty:
                allocations.append({
                    "team_name": team_name,
                    "faculty_name": match["faculty"],
                    "faculty_email": faculty_email,
                    "match_score": match["score"],
                    "match_percentage": match["match_percentage"]
                })
                allocated_free_teams.add(team_name)
                faculty_load[faculty_email] += 1

                # Update team document: set faculty_name and manual_allocation=False
                db.teams.update_one(
                    {"team_name": team_name},
                    {"$set": {"faculty_email": faculty_email, "faculty_name": match["faculty"], "manual_allocation": False}}
                )

        # --- STEP C: Handle Leftovers (Unmatched Free Teams) ---
        unallocated_free = [t for t in free_teams if t["team_name"] not in allocated_free_teams]

        for team in unallocated_free:
            # Find least busy available faculty
            available_faculty = [f for f in faculties if faculty_load[f["email"]] < max_teams_per_faculty]
            
            if available_faculty:
                # Pick the one with lowest load
                available_faculty.sort(key=lambda f: faculty_load[f["email"]])
                fac = available_faculty[0]
                
                allocations.append({
                    "team_name": team["team_name"],
                    "faculty_name": fac["name"],
                    "faculty_email": fac["email"],
                    "match_score": 0,
                    "match_percentage": 0 
                })
                faculty_load[fac["email"]] += 1

                # Update team document: set faculty_name and manual_allocation=False
                db.teams.update_one(
                    {"team_name": team["team_name"]},
                    {"$set": {"faculty_email": fac["email"], "faculty_name": fac["name"], "manual_allocation": False}}
                )
            # else: Team remains unassigned if all faculty are full.

        # Step 5: Save Allocation Snapshot
        db.allocations.delete_many({})
        if allocations:
            db.allocations.insert_many(allocations)

        return jsonify({
            "message": "✅ Allocation completed (Manual assignments preserved)!",
            "allocations": allocations
        }), 200

    except Exception as e:
        print("⚠️ Smart Allocation Error:", e)
        return jsonify({"error": str(e)}), 500


# ==================================================================== #
#                   GET ALL FACULTY ROUTE (NEW)                        #
# ==================================================================== #
@app.route('/api/faculty/all', methods=['GET'])
def get_all_faculty():
    """Returns a list of all faculty members."""
    try:
        # Fetch name and email for all faculty from the database
        faculties = list(db.faculty.find({}, {"_id": 0, "name": 1, "email": 1}))
        return jsonify({"faculties": faculties}), 200
    except Exception as e:
        print("Error fetching all faculty:", e)
        return jsonify({"error": "Internal server error fetching faculty list"}), 500
    


# ==================================================================== #
#        PROJECT ORIGINALITY CHECK MODULE (STANDALONE LOGIC)           #
# ==================================================================== #
# NOTE: This section relies on 'flask', 'request', and 'jsonify' being
# imported in the main app file.

import json
import requests
import time
import re
from difflib import SequenceMatcher
from sentence_transformers import SentenceTransformer, util
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# --- GEMINI API CONFIGURATION & SETUP ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
MAX_RETRIES = 5

# Load the Sentence Transformer model once
try:
    similarity_model = SentenceTransformer('all-MiniLM-L6-v2')
except Exception as _e:
    print(f"Notice loading SentenceTransformer: {_e}")
    similarity_model = None

STOP_WORDS = {
    'the', 'is', 'are', 'was', 'were', 'this', 'that', 'these', 'those', 'for', 'with',
    'and', 'or', 'of', 'to', 'in', 'on', 'at', 'by', 'from', 'a', 'an', 'as', 'it', 'its',
    'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'but', 'if', 'then',
    'else', 'when', 'where', 'which', 'who', 'whom', 'what', 'how', 'why', 'all', 'any',
    'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
    'only', 'own', 'same', 'so', 'than', 'too', 'very', 'can', 'will', 'just', 'should', 'now'
}

TECH_KEYWORDS = {
    'react', 'node', 'express', 'mongodb', 'machine learning', 'cnn', 'rnn', 'lstm',
    'resnet', 'transformer', 'bert', 'gpt', 'firebase', 'python', 'java', 'javascript',
    'typescript', 'c++', 'docker', 'kubernetes', 'aws', 'azure', 'gcp', 'opencv',
    'tensorflow', 'pytorch', 'scikit-learn', 'pandas', 'numpy', 'blockchain',
    'smart contract', 'ethereum', 'iot', 'arduino', 'raspberry pi', 'flutter',
    'react native', 'android', 'ios', 'sql', 'postgresql', 'mysql', 'redis',
    'graphql', 'rest api', 'microservices', 'nlp', 'computer vision', 'deep learning',
    'neural network', 'sentiment analysis', 'recommendation system', 'pathfinding',
    'a* algorithm', 'image classification', 'web application', 'mobile app',
    'e-commerce', 'chatbot', 'cyber security', 'encryption', 'steganography'
}

class IntelligentOriginalityEngine:
    def __init__(self):
        self.model = similarity_model
        self.embedding_cache = {}

    def normalize_text(self, text):
        if not text:
            return ""
        text = str(text).lower()
        text = re.sub(r'[^a-z0-9\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def split_sentences(self, text):
        if not text:
            return []
        raw_sentences = re.split(r'[.!?\n]+', str(text))
        return [s.strip() for s in raw_sentences if len(s.strip()) > 3]

    def extract_keywords(self, text):
        if not text:
            return set()
        text_lower = str(text).lower()
        found = set()
        for tech in TECH_KEYWORDS:
            if tech in text_lower:
                found.add(tech)
        
        words = re.findall(r'\b[a-z]{3,}\b', text_lower)
        for w in words:
            if w not in STOP_WORDS and len(w) > 3:
                found.add(w)
        return found

    def extract_ngrams(self, text, n):
        words = [w for w in re.findall(r'\b[a-z0-9]+\b', str(text).lower()) if w not in STOP_WORDS]
        if len(words) < n:
            return []
        return [" ".join(words[i:i+n]) for i in range(len(words)-n+1)]

    def compute_exact_phrase_matching(self, sub_sentences, db_sentences):
        if not sub_sentences or not db_sentences:
            return 0.0, []
        
        norm_db_sentences = [self.normalize_text(s) for s in db_sentences]
        matching_sentences = []
        match_count = 0.0

        for sub_s in sub_sentences:
            norm_sub_s = self.normalize_text(sub_s)
            if not norm_sub_s:
                continue
            if norm_sub_s in norm_db_sentences:
                match_count += 1.0
                matching_sentences.append(sub_s)
            else:
                for db_s in norm_db_sentences:
                    if len(norm_sub_s) > 15 and (norm_sub_s in db_s or db_s in norm_sub_s):
                        match_count += 0.8
                        matching_sentences.append(sub_s)
                        break

        score = min(1.0, match_count / max(1, len(sub_sentences)))
        return score, list(set(matching_sentences))

    def compute_ngram_similarity(self, sub_text, db_text):
        scores = []
        for n, weight in [(1, 0.20), (2, 0.35), (3, 0.45)]:
            sub_ngrams = set(self.extract_ngrams(sub_text, n))
            db_ngrams = set(self.extract_ngrams(db_text, n))
            if not sub_ngrams or not db_ngrams:
                scores.append(0.0)
                continue
            overlap = len(sub_ngrams.intersection(db_ngrams))
            denom = min(len(sub_ngrams), len(db_ngrams))
            scores.append(weight * (overlap / denom if denom > 0 else 0.0))
        return sum(scores)

    def compute_fuzzy_similarity(self, sub_text, db_text):
        norm_sub = self.normalize_text(sub_text)
        norm_db = self.normalize_text(db_text)
        if not norm_sub or not norm_db:
            return 0.0
        return SequenceMatcher(None, norm_sub, norm_db).ratio()

    def compute_keyword_similarity(self, sub_keywords, db_keywords):
        if not sub_keywords or not db_keywords:
            return 0.0, []
        common = list(sub_keywords.intersection(db_keywords))
        denom = min(len(sub_keywords), len(db_keywords))
        score = len(common) / denom if denom > 0 else 0.0
        return score, common

    def compute_section_tfidf_similarity(self, sub_dict, db_dict):
        section_weights = {
            "title": 0.10,
            "abstract": 0.35,
            "objectives": 0.15,
            "methodology": 0.20,
            "description": 0.20
        }
        section_scores = {}
        weighted_score = 0.0

        for sec, weight in section_weights.items():
            t1 = sub_dict.get(sec, "")
            t2 = db_dict.get(sec, "")
            if not t1 and sec in ["abstract", "description", "methodology"]:
                t1 = sub_dict.get("abstract", "")
            if not t2 and sec in ["abstract", "description", "methodology"]:
                t2 = db_dict.get("abstract", "")

            if not t1 or not t2:
                section_scores[sec] = 0.0
                continue

            try:
                vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words='english')
                tfidf = vectorizer.fit_transform([t1, t2])
                sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
                section_scores[sec] = float(sim)
            except Exception:
                section_scores[sec] = 0.0

            weighted_score += weight * section_scores[sec]

        return weighted_score, section_scores

    def compute_semantic_similarity(self, sub_full_text, db_full_text):
        if not self.model or not sub_full_text or not db_full_text:
            return 0.0
        try:
            embeddings = self.model.encode([sub_full_text, db_full_text], convert_to_tensor=True)
            sim = util.cos_sim(embeddings[0], embeddings[1])[0][0].item()
            return max(0.0, float(sim))
        except Exception as e:
            print("Semantic sim notice:", e)
            return 0.0

    def highlight_sentences(self, sub_sentences, db_all_text):
        highlighted = []
        for s in sub_sentences:
            norm_s = self.normalize_text(s)
            if not norm_s:
                continue
            
            sim_score = 0.0
            db_s_list = self.split_sentences(db_all_text)
            for db_s in db_s_list:
                norm_db_s = self.normalize_text(db_s)
                if not norm_db_s:
                    continue
                if norm_s == norm_db_s:
                    sim_score = 1.0
                    break
                ratio = SequenceMatcher(None, norm_s, norm_db_s).ratio()
                if ratio > sim_score:
                    sim_score = ratio

            if sim_score > 0.70:
                highlighted.append(f'<span style="color:#dc3545; font-weight:bold;" class="similarity-high" data-sim="{round(sim_score*100)}%">{s}</span>')
            elif sim_score >= 0.30:
                highlighted.append(f'<span style="color:#d97706; font-weight:bold;" class="similarity-moderate" data-sim="{round(sim_score*100)}%">{s}</span>')
            else:
                highlighted.append(f'<span style="color:#28a745;" class="similarity-unique">{s}</span>')

        return " ".join(highlighted)

    def generate_section_analysis(self, submission, top_match, max_sim, section_scores, common_kws):
        is_matched = (max_sim > 25.0) and (top_match is not None)
        
        sections = []
        overall_suggestions = []
        
        sub_title = submission.get("title", "")
        sub_abstract = submission.get("abstract", "")
        sub_objectives = submission.get("objectives", "")
        sub_methodology = submission.get("methodology", "")
        sub_description = submission.get("description", "")
        
        combined_sub = f"{sub_title} {sub_abstract} {sub_objectives} {sub_methodology} {sub_description}".lower()
        
        # 1. ABSTRACT SECTION
        abs_sim = round(section_scores.get("abstract", 0.0) * 100, 1)
        if abs_sim > 70:
            abs_status = "Highly Similar"
        elif abs_sim >= 30:
            abs_status = "Moderately Similar"
        else:
            abs_status = "Unique"
            
        abs_strengths = []
        abs_weaknesses = []
        abs_sug = []
        
        if len(sub_abstract.split()) > 30:
            abs_strengths.append("Comprehensive introductory framing and problem context.")
        else:
            abs_weaknesses.append("Abstract is brief; lacks detailed problem context and target metrics.")
            
        if is_matched and abs_sim >= 25.0:
            match_title = top_match.get("title", "existing database project")
            abs_reason = f"Structural and semantic correlation detected with project '{match_title}'."
            abs_weaknesses.append(f"Phrasing and conceptual overlap with '{match_title}'.")
            abs_sug.append(f"Reframe problem formulation to emphasize your unique target domain rather than matching '{match_title}'.")
            abs_sug.append("Introduce specific quantitative targets (e.g., target accuracy, latency, or throughput metrics).")
            abs_sug.append("Explicitly state your team's custom implementation novelty.")
        else:
            abs_reason = "Evaluated independently against domain benchmarks (No DB match > 25%)."
            abs_strengths.append("High semantic distinction from all registered projects in the database.")
            abs_sug.append("Elaborate on real-world practical use cases and deployment scenarios.")
            abs_sug.append("Specify key evaluation datasets, baseline benchmarks, and target performance metrics.")
            abs_sug.append("Detail operational constraints, target users, and environment specifications.")

        sections.append({
            "section": "Abstract",
            "similarity": abs_sim,
            "status": abs_status,
            "strengths": abs_strengths,
            "weaknesses": abs_weaknesses,
            "reason": abs_reason,
            "suggestions": abs_sug
        })

        # 2. OBJECTIVES SECTION
        obj_sim = round(section_scores.get("objectives", 0.0) * 100, 1)
        if obj_sim > 70:
            obj_status = "Highly Similar"
        elif obj_sim >= 30:
            obj_status = "Moderately Similar"
        else:
            obj_status = "Unique"

        obj_strengths = []
        obj_weaknesses = []
        obj_sug = []

        if sub_objectives and len(sub_objectives.split()) > 15:
            obj_strengths.append("Includes clear bullet points defining scope.")
        else:
            obj_weaknesses.append("Objectives use generic template phrasing or lack measurable verification metrics.")

        if is_matched and obj_sim >= 25.0:
            match_title = top_match.get("title", "existing database project")
            obj_reason = f"Objective goals mirror project milestones of '{match_title}'."
            obj_weaknesses.append("Primary goal statements overlap with standard project implementations.")
            obj_sug.append("Formulate SMART objectives (Specific, Measurable, Achievable, Relevant, Time-bound).")
            obj_sug.append("Add unique sub-objectives detailing specialized edge-cases or novel feature additions.")
            obj_sug.append("Specify verification mechanisms for each listed objective.")
        else:
            obj_reason = "Independent objective analysis (No DB match > 25%)."
            obj_strengths.append("Objectives demonstrate clear project direction and original goals.")
            obj_sug.append("Differentiate primary core goals from secondary phase deliverables.")
            obj_sug.append("Include measurable target metrics for validation (e.g., benchmark accuracy >92%, response time <200ms).")
            obj_sug.append("Highlight security, compliance, or scalability objectives.")

        sections.append({
            "section": "Objectives",
            "similarity": obj_sim,
            "status": obj_status,
            "strengths": obj_strengths,
            "weaknesses": obj_weaknesses,
            "reason": obj_reason,
            "suggestions": obj_sug
        })

        # 3. METHODOLOGY & ARCHITECTURE
        meth_sim = round(section_scores.get("methodology", 0.0) * 100, 1)
        if meth_sim > 70:
            meth_status = "Highly Similar"
        elif meth_sim >= 30:
            meth_status = "Moderately Similar"
        else:
            meth_status = "Unique"

        meth_strengths = []
        meth_weaknesses = []
        meth_sug = []

        if sub_methodology and len(sub_methodology.split()) > 20:
            meth_strengths.append("Technical pipeline and methodology steps described.")
        else:
            meth_weaknesses.append("Methodology lacks architectural diagrams, data flow specifications, or algorithm choices.")

        if is_matched and meth_sim >= 25.0:
            match_title = top_match.get("title", "existing database project")
            meth_reason = f"Architectural workflow matches data pipeline of '{match_title}'."
            meth_weaknesses.append("Model architecture or system pipeline shares identical sequence of operations.")
            meth_sug.append("Detail custom algorithmic modifications or hybrid pipeline variations.")
            meth_sug.append("Document custom data preprocessing, data augmentation, or state management strategies.")
            meth_sug.append("Provide a clear system architecture block diagram explaining module interactions.")
        else:
            meth_reason = "Novel methodology framework (No DB match > 25%)."
            meth_strengths.append("High technical novelty in algorithmic approach and module layout.")
            meth_sug.append("Elaborate on data preprocessing, feature engineering, and validation split strategy.")
            meth_sug.append("Include failover mechanisms, edge-case handling, and exception recovery in the pipeline.")
            meth_sug.append("Compare alternative algorithms considered and justify your selected architecture.")

        sections.append({
            "section": "Methodology & Architecture",
            "similarity": meth_sim,
            "status": meth_status,
            "strengths": meth_strengths,
            "weaknesses": meth_weaknesses,
            "reason": meth_reason,
            "suggestions": meth_sug
        })

        # 4. TECHNOLOGY STACK & INNOVATION
        tech_sim = round(section_scores.get("description", 0.0) * 100, 1)
        if tech_sim > 70:
            tech_status = "Highly Similar"
        elif tech_sim >= 30:
            tech_status = "Moderately Similar"
        else:
            tech_status = "Unique"

        tech_strengths = []
        tech_weaknesses = []
        tech_sug = []

        if any(tech in combined_sub for tech in ["react", "python", "tensorflow", "node", "express", "mongodb", "pytorch"]):
            tech_strengths.append("Modern technology choices and standard industry stack identified.")
        else:
            tech_weaknesses.append("Technology stack details are brief or implicit.")

        if is_matched and tech_sim >= 25.0:
            tech_reason = "Technology choices mirror existing database project baseline."
            tech_sug.append("Specify exact library versions, custom hyperparameter choices, and hardware deployment constraints.")
            tech_sug.append("Incorporate advanced auxiliary tools (e.g., Redis caching, Docker containerization, WebSockets).")
        else:
            tech_reason = "Independent technology stack analysis."
            tech_strengths.append("Clean technology alignment for project requirements.")
            tech_sug.append("Detail database indexing, query optimization, and scalability considerations.")
            tech_sug.append("Explain security implementations (JWT/OAuth2, HTTPS, data encryption at rest).")

        sections.append({
            "section": "Technology Stack & Innovation",
            "similarity": tech_sim,
            "status": tech_status,
            "strengths": tech_strengths,
            "weaknesses": tech_weaknesses,
            "reason": tech_reason,
            "suggestions": tech_sug
        })

        return sections

    def generate_ai_mentor_suggestions(self, submission):
        title = submission.get("title", "").strip()
        abstract = submission.get("abstract", "").strip()
        objectives = submission.get("objectives", "").strip()
        methodology = submission.get("methodology", "").strip()
        description = submission.get("description", "").strip()

        full_text = f"{title}. {abstract} {objectives} {methodology} {description}".strip()
        text_lower = full_text.lower()

        # Extract specific subject words from title and abstract
        title_words = [w for w in re.findall(r'\b[a-zA-Z]{4,}\b', title) if w.lower() not in STOP_WORDS]
        topic_name = title if title else "Submitted Project Idea"

        # Multi-Domain identification logic with specific domain boundary definitions
        is_ecommerce = any(k in text_lower for k in ["shopping", "cart", "store", "product", "recommendation", "price", "retail", "eco-friendly", "green", "carbon", "buyer", "seller", "customer", "ecommerce", "e-commerce", "groceries"])
        is_agriculture = any(k in text_lower for k in ["crop", "soil", "farm", "yield", "agriculture", "plant", "harvest", "pest", "irrigation", "fertilizer", "agritech", "field photo", "leaf photo"])
        is_healthcare = any(k in text_lower for k in ["patient", "medical", "doctor", "hospital", "clinical", "pharmacy", "ecg", "ehr", "nurse", "biomedical", "vitals", "icu", "health log"])
        is_security = any(k in text_lower for k in ["security", "cipher", "threat", "vulnerability", "attack", "encryption", "malware", "cyber", "firewall", "steganography", "auth", "intrusion"])
        is_education = any(k in text_lower for k in ["student", "teacher", "school", "learning", "course", "grade", "quiz", "attendance", "campus", "exam", "education", "classroom", "tutor"])
        is_drone_logistics = any(k in text_lower for k in ["drone", "uav", "robot", "delivery", "pathfinding", "navigation", "parcel", "vehicle", "autonomous", "flight", "logistics"])
        is_finance = any(k in text_lower for k in ["bank", "loan", "fraud", "transaction", "payment", "credit", "stock", "finance", "crypto", "trading", "investment", "fintech"])

        if is_ecommerce or "green" in text_lower or "cart" in text_lower or "eco" in text_lower:
            suggestions = [
                "1. Add barcode scanning so users can instantly check whether a product is eco-friendly during physical or online shopping.",
                "2. Integrate carbon footprint estimation for every purchase transaction to calculate net environmental impact.",
                "3. Recommend nearby physical or local stores selling verified sustainable and organic alternatives.",
                "4. Reward users with redeemable Green Points for choosing environmentally friendly products.",
                "5. Include AI-based personalized sustainability tips tailored to past shopping habits and user preference profiles.",
                "6. Provide side-by-side product comparisons evaluating recyclability, packaging impact, and carbon score.",
                "7. Integrate government-certified eco-label verification to filter out greenwashing claims.",
                "8. Display net CO2 savings achieved over time through an interactive personal environmental impact dashboard.",
                "9. Predict long-term environmental degradation and resource impact using predictive machine learning models.",
                "10. Enable a community review portal dedicated specifically to verifying product sustainability and ethical sourcing rather than price alone."
            ]
        elif is_healthcare:
            suggestions = [
                "1. Integrate real-time alert dispatch to emergency contacts and nearby medical facilities when patient vital signs cross critical thresholds.",
                "2. Incorporate automated prescription management and medication adherence tracking for chronic care patients.",
                "3. Enable HIPAA-compliant tele-consultation video modules allowing remote physicians to review patient diagnostic logs.",
                "4. Implement AI-driven symptom triaging to assist medical staff in prioritizing urgent patient care cases.",
                "5. Add wearable sensor telemetry integration to continuously monitor heart rate, blood oxygen, and body temperature.",
                "6. Provide personalized health risk scoring and preventive lifestyle recommendations based on historical clinical data.",
                "7. Integrate automated lab result analysis that highlights out-of-range biomarkers for attending physicians.",
                "8. Build a caregiver management portal enabling family members to monitor daily health updates and medication schedules.",
                "9. Predict potential disease progression risks using machine learning models trained on anonymized health records.",
                "10. Enable offline diagnostic data synchronization so field healthcare workers can log patient data without continuous internet connection."
            ]
        elif is_agriculture:
            suggestions = [
                "1. Integrate real-time soil moisture, pH, and NPK nutrient sensor telemetry for targeted precision irrigation.",
                "2. Incorporate AI-based crop disease and pest identification from smartphone field leaf photos.",
                "3. Provide hyper-local microclimate weather forecasts alerting farmers to impending frost, heavy rainfall, or drought.",
                "4. Recommend optimal crop harvest and planting windows based on regional market price trends and crop maturity metrics.",
                "5. Connect farmers directly with nearby agricultural equipment rental hubs and grain cold storage facilities.",
                "6. Analyze drone or satellite multispectral imagery to detect early crop stress and nutrient deficiencies across fields.",
                "7. Integrate automated fertilizer dosage recommendations based on specific soil test reports and target yields.",
                "8. Build a direct-to-consumer marketplace allowing farmers to list produce directly to wholesale buyers without intermediaries.",
                "9. Predict seasonal crop yield and market revenue outcomes using machine learning models combining historical weather and soil data.",
                "10. Include voice-guided agricultural advisory support in local regional languages for accessibility in rural farming communities."
            ]
        elif is_drone_logistics:
            suggestions = [
                "1. Integrate real-time weather telemetry (wind speed, precipitation, visibility) to dynamically adjust flight corridors.",
                "2. Add automated emergency drop-zone selection and parachute deployment for sudden hardware or battery failures.",
                "3. Implement multi-drone swarm coordination for multi-package delivery routing across high-density airspace.",
                "4. Incorporate real-time package temperature and shock telemetry monitoring for sensitive medical or food payloads.",
                "5. Add automated obstacle avoidance for low-altitude urban hazards such as power lines, trees, and buildings.",
                "6. Build a recipient tracking portal showing real-time flight altitude, live map location, and precise arrival ETA.",
                "7. Integrate automated battery swap station dispatch to minimize ground turnaround time between delivery runs.",
                "8. Implement dynamic geofencing to automatically avoid restricted airspace around airports, schools, and government sites.",
                "9. Predict rotor wear and battery degradation over cumulative flight hours using predictive maintenance machine learning.",
                "10. Allow secure payload release using dynamic OTP or QR code verification upon reaching the destination drop zone."
            ]
        elif is_security:
            suggestions = [
                "1. Integrate real-time threat intelligence feeds to automatically cross-reference incoming traffic against active zero-day attack lists.",
                "2. Incorporate user behavior analytics (UBA) to flag anomalous privilege escalation and out-of-hours data exfiltration attempts.",
                "3. Add automated incident response playbooks that automatically quarantine compromised network endpoints upon breach detection.",
                "4. Implement zero-trust microsegmentation rules to restrict lateral movement across internal network resources.",
                "5. Provide dynamic risk scoring for connected endpoints based on OS patch levels, firewall status, and running processes.",
                "6. Build a SIEM security dashboard visualizing real-time attack vectors, geographical threat origins, and alert severity levels.",
                "7. Add automated vulnerability scanning for web API endpoints to detect SQL injection and cross-site scripting risks.",
                "8. Implement automated honeypot traps to deceive malicious actors and analyze adversary tactics inside the network.",
                "9. Predict upcoming cyber threat campaigns by analyzing historical breach patterns and dark web indicator trends.",
                "10. Enable automated compliance auditing against ISO 27001 and NIST cybersecurity standards."
            ]
        elif is_education:
            suggestions = [
                "1. Incorporate adaptive learning path recommendations that dynamically adjust quiz difficulty based on student comprehension levels.",
                "2. Add automated essay evaluation and grammar feedback tailored to specific assignment rubrics and grade levels.",
                "3. Integrate peer-to-peer study group matchmaking based on complementary learning gaps and course schedules.",
                "4. Implement interactive flashcard generation automatically extracted from uploaded lecture notes or textbook chapters.",
                "5. Build a teacher analytics dashboard identifying struggling students who require early academic intervention.",
                "6. Include gamified learning badges and streak tracking to increase student engagement and course completion rates.",
                "7. Add automated attendance and participation tracking using classroom video or interaction logs.",
                "8. Provide personalized revision schedules leading up to exams based on historical topic error rates.",
                "9. Predict student course drop-out risk using machine learning models analyzing login frequency and assignment submission times.",
                "10. Enable multi-language translation for course materials to support non-native speaking students."
            ]
        elif is_finance:
            suggestions = [
                "1. Integrate real-time transaction monitoring that flags suspicious credit card charges based on geolocation anomalies.",
                "2. Incorporate automated credit risk assessment combining non-traditional utility bill payment history with traditional credit scores.",
                "3. Provide personalized budgeting advice and recurring subscription tracking to help users optimize monthly savings.",
                "4. Add AI-driven portfolio rebalancing recommendations based on user risk tolerance and market volatility.",
                "5. Implement automated invoice reconciliation and receipt scanning using optical character recognition (OCR).",
                "6. Build a financial health dashboard displaying net worth trajectories, debt payoff timelines, and emergency fund goals.",
                "7. Integrate automated tax deduction identification to highlight eligible business expenses throughout the year.",
                "8. Add fraud prevention step-up authentication when transfer amounts exceed user historical thresholds.",
                "9. Predict stock or commodity price trends using sentiment analysis on financial news headlines and quarterly earnings reports.",
                "10. Enable multi-currency wallet management with real-time foreign exchange rate conversion alerts."
            ]
        else:
            kw1 = title_words[0] if len(title_words) > 0 else "core"
            kw2 = title_words[1] if len(title_words) > 1 else "feature"
            
            suggestions = [
                f"1. Expand the core workflow of '{topic_name}' by adding automated real-time alert triggers for critical events.",
                f"2. Integrate interactive visual reporting dashboards so users can analyze key performance metrics and filter historical records.",
                f"3. Incorporate AI-driven predictive insights to forecast future user demand and operational requirements.",
                f"4. Add granular role-based access permissions allowing administrators and end-users customized workspace views.",
                f"5. Implement automated anomaly detection to flag suspicious user inputs or data entries before processing.",
                f"6. Provide automated export utilities (PDF/Excel) enabling users to generate official summary reports in one click.",
                f"7. Enable mobile-responsive offline data synchronization so users can continue capturing data without active connectivity.",
                f"8. Integrate third-party API webhook support enabling '{topic_name}' to seamlessly sync data with external enterprise tools.",
                f"9. Build an automated activity audit trail log recording all user modifications and system updates for accountability.",
                f"10. Create an interactive onboarding walkthrough guiding new users step-by-step through the primary capabilities of {kw1} and {kw2}."
            ]

        return suggestions

    def generate_plain_text_suggestions(self, ai_mentor_suggestions):
        return "\n\n".join(ai_mentor_suggestions)

    def evaluate(self, submission, db_projects):
        sub_title = submission.get("title", "")
        sub_abstract = submission.get("abstract", "")
        sub_objectives = submission.get("objectives", "")
        sub_methodology = submission.get("methodology", "")
        sub_description = submission.get("description", "")

        sub_full_text = f"{sub_title}. {sub_abstract} {sub_objectives} {sub_methodology} {sub_description}".strip()
        sub_sentences = self.split_sentences(sub_full_text)
        sub_keywords = self.extract_keywords(sub_full_text)

        sub_dict = {
            "title": sub_title,
            "abstract": sub_abstract,
            "objectives": sub_objectives,
            "methodology": sub_methodology,
            "description": sub_description
        }

        project_results = []

        for proj in db_projects:
            db_title = proj.get("title") or proj.get("project_title") or "Untitled Project"
            db_abstract = proj.get("abstract", "")
            db_objectives = proj.get("objectives", "")
            db_methodology = proj.get("methodology", "")
            db_description = proj.get("description", "")

            db_full_text = f"{db_title}. {db_abstract} {db_objectives} {db_methodology} {db_description}".strip()
            db_sentences = self.split_sentences(db_full_text)
            db_keywords = self.extract_keywords(db_full_text)

            db_dict = {
                "title": db_title,
                "abstract": db_abstract,
                "objectives": db_objectives,
                "methodology": db_methodology,
                "description": db_description
            }

            # 1. Exact phrase matching
            exact_score, matching_sents = self.compute_exact_phrase_matching(sub_sentences, db_sentences)

            # 2. Semantic similarity
            semantic_score = self.compute_semantic_similarity(sub_full_text, db_full_text)

            # 3. Section TF-IDF Cosine similarity
            tfidf_score, section_scores = self.compute_section_tfidf_similarity(sub_dict, db_dict)

            # 4. Keyword similarity
            kw_score, common_kws = self.compute_keyword_similarity(sub_keywords, db_keywords)

            # 5. N-gram similarity
            ngram_score = self.compute_ngram_similarity(sub_full_text, db_full_text)

            # 6. Fuzzy string matching
            fuzzy_score = self.compute_fuzzy_similarity(sub_title + " " + sub_abstract, db_title + " " + db_abstract)

            # Weighted combination
            composite_score = (
                0.30 * semantic_score +
                0.25 * tfidf_score +
                0.15 * exact_score +
                0.15 * ngram_score +
                0.10 * kw_score +
                0.05 * fuzzy_score
            )

            sim_percent = min(100.0, max(0.0, composite_score * 100.0))

            project_results.append({
                "title": db_title,
                "similarity_percent": round(sim_percent, 2),
                "matched_sections": {sec: round(val * 100, 1) for sec, val in section_scores.items()},
                "matching_sentences": matching_sents,
                "common_keywords": common_kws,
                "overall_similarity_score": round(sim_percent, 2),
                "db_full_text": db_full_text,
                "raw_section_scores": section_scores
            })

        # Sort projects by similarity descending
        project_results.sort(key=lambda x: x["similarity_percent"], reverse=True)

        top_5 = project_results[:5]
        top_1 = top_5[0] if top_5 else None

        # Check threshold (25%)
        SIMILARITY_THRESHOLD = 25.0
        
        if top_1 and top_1["similarity_percent"] > SIMILARITY_THRESHOLD and len(db_projects) > 0:
            is_genuine_match = True
            max_sim = top_1["similarity_percent"]
            most_similar_title = top_1["title"]
            all_db_text = top_1["db_full_text"]
            top_sec_scores = top_1["raw_section_scores"]
            top_matching_sents = top_1["matching_sentences"]
            top_common_kws = top_1["common_keywords"]
            status_msg = f"Similarities detected with existing database project '{most_similar_title}'."
        else:
            is_genuine_match = False
            max_sim = top_1["similarity_percent"] if top_1 else 0.0
            most_similar_title = "None"
            all_db_text = ""
            top_sec_scores = top_1["raw_section_scores"] if top_1 else {}
            top_matching_sents = []
            top_common_kws = []
            status_msg = "No significantly similar project found in the existing database."

        originality_score = round(max(0.0, 100.0 - max_sim), 2)

        # Highlight text
        highlighted_text = self.highlight_sentences(sub_sentences, all_db_text)

        # Generate section analysis and pure mentor-level AI suggestions
        section_analysis = self.generate_section_analysis(
            submission, top_1 if is_genuine_match else None, max_sim, top_sec_scores, top_common_kws
        )

        overall_suggestions = self.generate_ai_mentor_suggestions(submission)

        plain_text_suggestions = self.generate_plain_text_suggestions(overall_suggestions)

        # Confidence level calculation
        if len(db_projects) == 0:
            confidence = "High (100%) - Baseline project"
        elif max_sim > 75 or max_sim <= 25:
            confidence = f"High ({min(99, max(85, round(85 + (abs(max_sim - 50) / 50) * 14)))}%)"
        else:
            confidence = f"Medium ({round(70 + (abs(max_sim - 50) / 50) * 14)}%)"

        formatted_top_5 = []
        for p in top_5:
            formatted_top_5.append({
                "project_title": p["title"],
                "similarity_percent": p["similarity_percent"],
                "matched_sections": p["matched_sections"],
                "matching_sentences": p["matching_sentences"],
                "common_keywords": p["common_keywords"],
                "overall_similarity_score": p["overall_similarity_score"]
            })

        return {
            "message": "✅ Originality check completed successfully",
            "status": status_msg,
            "overall_originality": originality_score,
            "overall_similarity": max_sim,
            "originality_score": originality_score,
            "similarity_percent": max_sim,
            "most_similar_project": most_similar_title,
            "confidence": confidence,
            "confidence_level": confidence,
            "top_matching_projects": formatted_top_5,
            "section_analysis": section_analysis,
            "overall_suggestions": overall_suggestions,
            "matched_sections": top_1["matched_sections"] if top_1 else {},
            "matching_sentences": top_matching_sents,
            "common_keywords": top_common_kws,
            "highlighted_similar_text": highlighted_text,
            "detailed_improvement_suggestions": plain_text_suggestions,
            "suggestion": plain_text_suggestions
        }

# Global Engine Instance
originality_engine = IntelligentOriginalityEngine()

def call_gemini_api_with_retry(payload, originality_score, most_similar_title):
    headers = {'Content-Type': 'application/json'}
    full_api_url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(full_api_url, headers=headers, data=json.dumps(payload))
            if response.status_code == 403:
                print("⚠️ 403 Forbidden detected. Returning simulated AI suggestion.")
                mock_suggestion = (
                    f"Based on the {originality_score}% originality score and similarity to '{most_similar_title}', "
                    "here are key improvement recommendations:\n"
                    "* Integrate real-time weather data to dynamically adjust drone paths.\n"
                    "* Add a public-facing monitoring dashboard for package tracking transparency.\n"
                    "* Use reinforcement learning instead of traditional pathfinding for better adaptability.\n"
                    "* Implement secure drone hand-off protocols for multi-stage delivery.\n"
                    "* Develop a dynamic geofencing system based on current urban events."
                )
                return {
                    "candidates": [{
                        "content": {"parts": [{"text": mock_suggestion}]}
                    }]
                }

            if response.status_code >= 500 or response.status_code == 429:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
            
            response.raise_for_status() 
            return response.json()

        except requests.exceptions.RequestException as e:
            if hasattr(e.response, 'status_code') and e.response.status_code < 500 and e.response.status_code != 429:
                raise e
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                raise e

    raise Exception("API call failed after all retries.")


@app.route('/api/check_originality', methods=['POST'])
def check_originality():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "JSON payload required"}), 400

        title = data.get("title", "")
        abstract = data.get("abstract", "")
        objectives = data.get("objectives", "")
        methodology = data.get("methodology", "")
        description = data.get("description", "")

        if not abstract or not title:
            return jsonify({"error": "Both title and abstract are required"}), 400

        submission_data = {
            "title": title,
            "abstract": abstract,
            "objectives": objectives,
            "methodology": methodology,
            "description": description
        }

        # Collect existing projects from DB (projects collection and teams collection)
        db_projects = []
        try:
            for proj in db.projects.find({}, {"_id": 0}):
                if isinstance(proj, dict) and (proj.get("title") or proj.get("abstract")):
                    db_projects.append(proj)
        except Exception as e:
            print("Notice fetching db.projects:", e)

        try:
            for team in db.teams.find({}, {"_id": 0, "project_idea": 1, "project_ideas": 1}):
                pi = team.get("project_idea")
                if isinstance(pi, dict) and pi.get("title"):
                    db_projects.append(pi)
                pis = team.get("project_ideas")
                if isinstance(pis, list):
                    for item in pis:
                        if isinstance(item, dict) and item.get("title"):
                            db_projects.append(item)
        except Exception as e:
            print("Notice fetching db.teams:", e)

        # Run multi-technique originality engine evaluation
        result = originality_engine.evaluate(submission_data, db_projects)

        return jsonify(result), 200

    except Exception as e:
        print(f"🔥 Error in originality check: {e}")
        return jsonify({"error": "Internal server error"}), 500




# ==================================================================== #
#                 MANUAL REALLOCATION ROUTE (NEW)                      #
# ==================================================================== #

@app.route('/api/allocate/manual', methods=['POST'])
def manual_reallocate():
    try:
        data = request.json
        team_name = data.get("team_name")
        faculty_email = data.get("faculty_email")
        
        if not team_name or not faculty_email:
            return jsonify({"error": "Team and Faculty selection required"}), 400

        # 1. Verify Faculty Exists
        faculty = db.faculty.find_one({"email": faculty_email})
        if not faculty:
            return jsonify({"error": "Selected faculty not found"}), 404

        # 2. Check Faculty Capacity (Max 3)
        current_count = db.teams.count_documents({"faculty_email": faculty_email})
        if current_count >= 3:
             return jsonify({"error": f"Faculty {faculty['name']} is already at max capacity (3 teams)."}), 400

        # 3. Update the Team (Set manual_allocation = True)
        db.teams.update_one(
            {"team_name": team_name},
            {
                "$set": {
                    "faculty_email": faculty_email,
                    "faculty_name": faculty["name"], # Store name for easier frontend display
                    "manual_allocation": True 
                }
            }
        )

        # 4. Update the Allocations Collection (for the dashboard view)
        # We update the existing allocation or insert if missing
        db.allocations.update_one(
            {"team_name": team_name},
            {
                "$set": {
                    "faculty_name": faculty["name"],
                    "faculty_email": faculty_email,
                    "team_name": team_name,
                    # We set match_score to "Manual" so it's clear in UI
                    "match_percentage": "Manual"
                }
            },
            upsert=True
        )

        return jsonify({"message": f"Successfully reallocated {team_name} to {faculty['name']}"}), 200

    except Exception as e:
        print("Error in manual reallocation:", e)
        return jsonify({"error": "Internal server error"}), 500


# ==================================================================== #
# ANALYTICS DASHBOARD ROUTE
# ==================================================================== #

@app.route('/api/analytics/dashboard', methods=['GET'])
def analytics_dashboard():
    try:
        total_teams = db.teams.count_documents({})
        total_faculty = db.faculty.count_documents({})

        allocated_teams = db.teams.count_documents({
            "faculty_email": {"$ne": None}
        })

        pending_allocation = total_teams - allocated_teams

        submitted_ideas = db.teams.count_documents({
            "project_idea": {"$exists": True}
        })

        approved_ideas = db.teams.count_documents({
            "project_idea.status": "Approved"
        })

        rejected_ideas = db.teams.count_documents({
            "project_idea.status": "Rejected"
        })

        progress_uploaded = db.teams.count_documents({
            "progress.0": {"$exists": True}
        })

        no_progress = total_teams - progress_uploaded

        # Faculty workload
        faculty_load = list(db.teams.aggregate([
            {
                "$group": {
                    "_id": "$faculty_name",
                    "teams": {"$sum": 1}
                }
            }
        ]))

        # Average marks
        all_teams = list(db.teams.find({}, {"team_name":1, "marks":1}))

        marks_data = []

        for team in all_teams:
            total = 0
            count = 0

            for exam in team.get("marks", []):
                for m in exam.get("members_marks", []):
                    total += int(m.get("marks", 0))
                    count += 1

            avg = round(total / count, 2) if count > 0 else 0

            marks_data.append({
                "team_name": team["team_name"],
                "average": avg
            })

        top_team = max(marks_data, key=lambda x: x["average"], default={})
        low_team = min(marks_data, key=lambda x: x["average"], default={})

        return jsonify({
            "total_teams": total_teams,
            "total_faculty": total_faculty,
            "allocated_teams": allocated_teams,
            "pending_allocation": pending_allocation,
            "submitted_ideas": submitted_ideas,
            "approved_ideas": approved_ideas,
            "rejected_ideas": rejected_ideas,
            "progress_uploaded": progress_uploaded,
            "no_progress": no_progress,
            "faculty_load": faculty_load,
            "top_team": top_team,
            "low_team": low_team
        }), 200

    except Exception as e:
        print(e)
        return jsonify({"error":"Analytics failed"}),500
    
# ===================== CHAT SYSTEM ===================== #

@socketio.on('join')
def handle_join(data):
    room = data['team_name']
    join_room(room)

@socketio.on('send_message')
def handle_message(data):
    team_name = data['team_name']
    message = data['message']
    sender = data['sender']

    msg_data = {
        "team_name": team_name,
        "sender": sender,
        "message": message,
        "timestamp": datetime.now().isoformat()
    }

    # Save to DB
    result = db.chats.insert_one(msg_data)

    # ❗ REMOVE ObjectId BEFORE SENDING
    msg_data["_id"] = str(result.inserted_id)

    # Send message
    emit('receive_message', msg_data, room=team_name)


# OPTIONAL: Load old messages
@app.route('/api/chat/<team_name>', methods=['GET'])
def get_chat(team_name):
    chats = list(db.chats.find({"team_name": team_name}, {"_id": 0}))
    return jsonify(chats)


# ==================================================================== #
#              PROJECT EVALUATION SYSTEM INTEGRATION                   #
# ==================================================================== #

# Helper function to get student's team and project
def get_student_project_info(email):
    """Auto-detect student's team and project from email"""
    team = db.teams.find_one({
        "$or": [
            {"leader_email": email},
            {"members": {"$in": [email]}}
        ]
    })
    
    if not team:
        return None, None
    
    # Get project from team's project_idea
    project_idea = team.get("project_idea", {})
    if not project_idea or not project_idea.get("title"):
        return team, None
    
    return team, project_idea

# GET /api/evaluation/student - Get student's evaluation (auto-detected)
@app.route('/api/evaluation/student', methods=['GET'])
def get_student_evaluation():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded["email"]
        
        # Auto-detect team and project
        team, project_idea = get_student_project_info(email)
        
        if not team:
            return jsonify({"error": "Student not found in any team"}), 404
        
        if not project_idea:
            return jsonify({"error": "No project submitted yet"}), 404
        
        # Get evaluation for this team
        team_name = team.get("team_name")
        evaluation = db.evaluations.find_one({"team_name": team_name}, {"_id": 0})
        
        if not evaluation:
            # Return empty evaluation structure
            return jsonify({
                "team_name": team_name,
                "project_title": project_idea.get("title"),
                "faculty_name": team.get("faculty_name", "Not Assigned"),
                "members": team.get("members", []),
                "leader_name": team.get("leader_name"),
                "evaluation": None,
                "is_locked": False
            })
        
        return jsonify({
            "team_name": team_name,
            "project_title": project_idea.get("title"),
            "faculty_name": team.get("faculty_name", "Not Assigned"),
            "members": team.get("members", []),
            "leader_name": team.get("leader_name"),
            "evaluation": evaluation,
            "is_locked": evaluation.get("is_locked", False)
        })
        
    except Exception as e:
        print(f"Error getting student evaluation: {e}")
        return jsonify({"error": "Internal server error"}), 500

# GET /api/evaluation/faculty/teams - Get teams assigned to faculty
@app.route('/api/evaluation/faculty/teams', methods=['GET'])
def get_faculty_evaluation_teams():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded["email"]
        
        if decoded.get("role") not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized"}), 403
        
        # Get teams assigned to this faculty
        teams = list(db.teams.find(
            {"faculty_email": email},
            {"_id": 0, "team_name": 1, "leader_name": 1, "members": 1, "project_idea": 1, "faculty_name": 1}
        ))
        
        # If no teams assigned, fetch all teams (fallback for testing)
        if not teams:
            print(f"No teams assigned to faculty {email} for evaluation, fetching all teams as fallback")
            teams = list(db.teams.find(
                {},
                {"_id": 0, "team_name": 1, "leader_name": 1, "members": 1, "project_idea": 1, "faculty_name": 1, "faculty_email": 1}
            ))
        
        return jsonify(teams)
        
    except Exception as e:
        print(f"Error getting faculty teams: {e}")
        return jsonify({"error": "Internal server error"}), 500

# GET /api/evaluation/team/<team_name> - Get evaluation for specific team
@app.route('/api/evaluation/team/<team_name>', methods=['GET'])
def get_team_evaluation(team_name):
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        
        if decoded.get("role") not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized"}), 403
        
        team = db.teams.find_one({"team_name": team_name}, {"_id": 0})
        if not team:
            return jsonify({"error": "Team not found"}), 404
        
        evaluation = db.evaluations.find_one({"team_name": team_name}, {"_id": 0})
        
        return jsonify({
            "team": team,
            "evaluation": evaluation,
            "is_locked": evaluation.get("is_locked", False) if evaluation else False
        })
        
    except Exception as e:
        print(f"Error getting team evaluation: {e}")
        return jsonify({"error": "Internal server error"}), 500

# POST /api/evaluation/save - Save or update evaluation marks
@app.route('/api/evaluation/save', methods=['POST'])
def save_evaluation():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        
        if decoded.get("role") not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized - Students cannot save marks"}), 403
        
        data = request.json
        team_name = data.get("team_name")
        evaluation_data = data.get("evaluation")
        
        if not team_name or not evaluation_data:
            return jsonify({"error": "Missing required fields"}), 400
        
        # Check if evaluation is locked
        existing = db.evaluations.find_one({"team_name": team_name})
        if existing and existing.get("is_locked", False) and decoded.get("role") != "coordinator":
            return jsonify({"error": "Evaluation is locked by coordinator"}), 403
        
        # Validate marks
        for phase in evaluation_data.get("phases", []):
            for criterion in phase.get("criteria", []):
                for mark_entry in criterion.get("marks", []):
                    marks_obtained = mark_entry.get("marks_obtained", 0)
                    maximum_marks = mark_entry.get("maximum_marks", 0)
                    if marks_obtained < 0 or marks_obtained > maximum_marks:
                        return jsonify({"error": f"Invalid marks: {marks_obtained} exceeds maximum {maximum_marks}"}), 400
        
        # Save or update evaluation
        evaluation_data["team_name"] = team_name
        evaluation_data["updated_at"] = datetime.now(timezone.utc)
        evaluation_data["updated_by"] = decoded.get("email")
        
        if existing:
            db.evaluations.update_one(
                {"team_name": team_name},
                {"$set": evaluation_data}
            )
        else:
            evaluation_data["created_at"] = datetime.now(timezone.utc)
            evaluation_data["is_locked"] = False
            db.evaluations.insert_one(evaluation_data)
        
        return jsonify({"success": True, "message": "Evaluation saved successfully"})
        
    except Exception as e:
        print(f"Error saving evaluation: {e}")
        return jsonify({"error": "Internal server error"}), 500

# PATCH /api/evaluation/lock/<team_name> - Lock/unlock evaluation (coordinator only)
@app.route('/api/evaluation/lock/<team_name>', methods=['PATCH'])
def lock_evaluation(team_name):
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized - Only coordinators can lock evaluations"}), 403
        
        data = request.json
        is_locked = data.get("is_locked", False)
        
        db.evaluations.update_one(
            {"team_name": team_name},
            {"$set": {
                "is_locked": is_locked,
                "locked_by": decoded.get("email"),
                "locked_at": datetime.now(timezone.utc) if is_locked else None
            }}
        )
        
        return jsonify({
            "success": True,
            "message": f"Evaluation {'locked' if is_locked else 'unlocked'} successfully"
        })
        
    except Exception as e:
        print(f"Error locking evaluation: {e}")
        return jsonify({"error": "Internal server error"}), 500

# GET /api/evaluation/coordinator/all - Get all evaluations for coordinator
@app.route('/api/evaluation/coordinator/all', methods=['GET'])
def get_all_evaluations():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized"}), 403
        
        # Get all teams with their evaluations
        teams = list(db.teams.find({}, {"_id": 0}))
        evaluations = list(db.evaluations.find({}, {"_id": 0}))
        
        # Combine data
        result = []
        for team in teams:
            team_name = team.get("team_name")
            eval_data = next((e for e in evaluations if e.get("team_name") == team_name), None)
            
            result.append({
                "team": team,
                "evaluation": eval_data,
                "has_evaluation": eval_data is not None,
                "is_locked": eval_data.get("is_locked", False) if eval_data else False
            })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Error getting all evaluations: {e}")
        return jsonify({"error": "Internal server error"}), 500




# ==================================================================== #
#                  STUDENT ATTENDANCE MANAGEMENT MODULE                #
# ==================================================================== #

# GET /api/faculty/attendance/teams - Get faculty assigned teams with member roster
@app.route('/api/faculty/attendance/teams', methods=['GET'])
def get_faculty_attendance_teams():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401

        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded.get("email")
        role = decoded.get("role")

        if role not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized"}), 403

        # Fetch faculty details to get faculty_name
        faculty = db.faculty.find_one({
            "$or": [
                {"email": email},
                {"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}
            ]
        })
        faculty_name = faculty.get("name") if faculty else None

        query_conditions = [
            {"faculty_email": email},
            {"faculty_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}
        ]
        if faculty_name:
            query_conditions.append({"faculty_name": faculty_name})

        # Fetch teams assigned to faculty
        teams = list(db.teams.find(
            {"$or": query_conditions},
            {"_id": 0, "team_name": 1, "leader_name": 1, "leader_email": 1, "members": 1, "faculty_name": 1, "faculty_email": 1}
        ))

        # Fallback for testing/coordinators if no direct teams assigned
        if not teams and role in ["faculty", "coordinator"]:
            teams = list(db.teams.find(
                {},
                {"_id": 0, "team_name": 1, "leader_name": 1, "leader_email": 1, "members": 1, "faculty_name": 1, "faculty_email": 1}
            ))


        formatted_teams = []
        for team in teams:
            leader_email = team.get("leader_email")
            leader_name = team.get("leader_name", "Leader")
            members = team.get("members", [])

            roster = []
            if leader_email:
                roster.append({"email": leader_email, "name": f"{leader_name} (Leader)"})

            for m in members:
                if isinstance(m, str) and m != leader_email:
                    name_part = m.split("@")[0].replace(".", " ").title()
                    roster.append({"email": m, "name": name_part})
                elif isinstance(m, dict):
                    m_email = m.get("email")
                    if m_email and m_email != leader_email:
                        roster.append({"email": m_email, "name": m.get("name", m_email)})

            formatted_teams.append({
                "team_name": team.get("team_name"),
                "faculty_name": team.get("faculty_name", "Assigned Faculty"),
                "roster": roster
            })

        return jsonify({"teams": formatted_teams}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except Exception as e:
        print(f"Error fetching faculty attendance teams: {e}")
        return jsonify({"error": "Internal server error"}), 500


# POST /api/faculty/attendance/mark - Save or edit attendance record for a team & date
@app.route('/api/faculty/attendance/mark', methods=['POST'])
def mark_faculty_attendance():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401

        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded.get("email")
        role = decoded.get("role")

        if role not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized role"}), 403

        data = request.json or {}
        team_name = data.get("team_name")
        date_str = data.get("date")
        records = data.get("records", [])

        if not team_name or not date_str or not records:
            return jsonify({"error": "team_name, date, and student records are required"}), 400

        # Verify faculty assignment
        team = db.teams.find_one({"team_name": team_name})
        if not team:
            return jsonify({"error": "Team not found"}), 404

        if role == "faculty" and team.get("faculty_email") and team.get("faculty_email") != email:
            return jsonify({"error": "Unauthorized to mark attendance for team assigned to another faculty"}), 403

        attendance_doc = {
            "team_name": team_name,
            "faculty_email": email,
            "faculty_name": team.get("faculty_name", "Faculty"),
            "date": date_str,
            "records": records,
            "marked_by": email,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        # Upsert attendance by team_name and date
        existing = db.attendance.find_one({"team_name": team_name, "date": date_str})
        if existing:
            db.attendance.update_one(
                {"_id": existing["_id"]},
                {"$set": attendance_doc}
            )
            msg = f"Attendance updated for {team_name} on {date_str}."
        else:
            attendance_doc["created_at"] = datetime.now(timezone.utc).isoformat()
            db.attendance.insert_one(attendance_doc)
            msg = f"Attendance marked for {team_name} on {date_str}."

        return jsonify({"message": msg, "success": True}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except Exception as e:
        print(f"Error marking attendance: {e}")
        return jsonify({"error": "Internal server error"}), 500


# GET /api/faculty/attendance/history - View previously marked attendance logs
@app.route('/api/faculty/attendance/history', methods=['GET'])
def get_faculty_attendance_history():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401

        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded.get("email")
        role = decoded.get("role")

        if role not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized"}), 403

        team_name = request.args.get("team_name")
        date_str = request.args.get("date")

        query = {}
        if role == "faculty":
            query["faculty_email"] = email
        if team_name:
            query["team_name"] = team_name
        if date_str:
            query["date"] = date_str

        logs = list(db.attendance.find(query, {"_id": 0}).sort("date", -1))
        return jsonify({"history": logs}), 200

    except Exception as e:
        print(f"Error fetching attendance history: {e}")
        return jsonify({"error": "Internal server error"}), 500


# GET /api/student/attendance - Student attendance statistics & logs
@app.route('/api/student/attendance', methods=['GET'])
def get_student_attendance():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401

        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded.get("email")

        # Find team for student
        team = db.teams.find_one({
            "$or": [
                {"leader_email": email},
                {"members": {"$in": [email]}}
            ]
        })

        if not team:
            return jsonify({"error": "Student team not found"}), 404

        team_name = team.get("team_name")
        logs = list(db.attendance.find({"team_name": team_name}, {"_id": 0}).sort("date", -1))

        total_classes = len(logs)
        present_count = 0
        absent_count = 0
        late_count = 0
        on_duty_count = 0

        recent_logs = []
        monthly_map = {}

        for log in logs:
            log_date = log.get("date", "")
            month_key = log_date[:7] if len(log_date) >= 7 else "Overall"

            if month_key not in monthly_map:
                monthly_map[month_key] = {"present": 0, "total": 0}

            monthly_map[month_key]["total"] += 1

            status = "Absent"
            for rec in log.get("records", []):
                if rec.get("student_email") == email:
                    status = rec.get("status", "Absent")
                    break

            if status == "Present":
                present_count += 1
                monthly_map[month_key]["present"] += 1
            elif status == "Late":
                late_count += 1
                present_count += 1
                monthly_map[month_key]["present"] += 1
            elif status == "On Duty":
                on_duty_count += 1
                present_count += 1
                monthly_map[month_key]["present"] += 1
            else:
                absent_count += 1

            recent_logs.append({
                "date": log_date,
                "status": status,
                "marked_by": log.get("faculty_name", "Faculty")
            })

        percentage = round((present_count / total_classes * 100), 1) if total_classes > 0 else 100.0

        monthly_breakdown = []
        for m_key, val in sorted(monthly_map.items(), reverse=True):
            m_pct = round((val["present"] / val["total"] * 100), 1) if val["total"] > 0 else 0.0
            monthly_breakdown.append({
                "month": m_key,
                "present": val["present"],
                "total": val["total"],
                "percentage": m_pct
            })

        return jsonify({
            "team_name": team_name,
            "total_classes": total_classes,
            "present_count": present_count,
            "absent_count": absent_count,
            "late_count": late_count,
            "on_duty_count": on_duty_count,
            "attendance_percentage": percentage,
            "monthly_breakdown": monthly_breakdown,
            "recent_logs": recent_logs
        }), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except Exception as e:
        print(f"Error fetching student attendance: {e}")
        return jsonify({"error": "Internal server error"}), 500


# GET /api/coordinator/attendance/all - System-wide attendance oversight for Coordinator
@app.route('/api/coordinator/attendance/all', methods=['GET'])
def get_coordinator_attendance_all():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401

        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized"}), 403

        teams = list(db.teams.find({}, {"_id": 0, "team_name": 1, "leader_name": 1, "leader_email": 1, "members": 1, "faculty_name": 1, "faculty_email": 1}))
        all_logs = list(db.attendance.find({}, {"_id": 0}))

        team_stats = []
        for t in teams:
            t_name = t.get("team_name")
            t_logs = [l for l in all_logs if l.get("team_name") == t_name]
            t_classes = len(t_logs)

            t_present = 0
            t_total_slots = 0

            for l in t_logs:
                for rec in l.get("records", []):
                    t_total_slots += 1
                    if rec.get("status") in ["Present", "Late", "On Duty"]:
                        t_present += 1

            t_pct = round((t_present / t_total_slots * 100), 1) if t_total_slots > 0 else 0.0

            team_stats.append({
                "team_name": t_name,
                "faculty_name": t.get("faculty_name", "Not Assigned"),
                "faculty_email": t.get("faculty_email"),
                "total_sessions": t_classes,
                "attendance_percentage": t_pct,
                "is_low_attendance": (t_pct < 75.0 and t_classes > 0)
            })

        low_attendance_teams = [ts for ts in team_stats if ts["is_low_attendance"]]
        top_attendance_teams = sorted(team_stats, key=lambda x: x["attendance_percentage"], reverse=True)

        return jsonify({
            "total_teams": len(teams),
            "total_logs": len(all_logs),
            "team_stats": team_stats,
            "low_attendance_teams": low_attendance_teams,
            "top_attendance_teams": top_attendance_teams[:5]
        }), 200

    except Exception as e:
        print(f"Error in coordinator attendance all: {e}")
        return jsonify({"error": "Internal server error"}), 500


# ==================================================================== #
#                       RUN SERVER                                     #
# ==================================================================== #


if __name__ == "__main__":
    socketio.run(app, debug=True, use_reloader=False)
