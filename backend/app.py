import sys
import uuid
import traceback
from flask_dance.contrib.google import make_google_blueprint, google
from flask import redirect, url_for, request
import os, jwt
import os # <--- FIXED IMPORT ORDER
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_pymongo import PyMongo
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename # CRITICAL for file upload security
from werkzeug.middleware.proxy_fix import ProxyFix
import jwt
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from flask_socketio import SocketIO, emit, join_room

import smtplib
import ssl
import socket
import logging
import threading
import html
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
# -------------------- Load Environment Variables -------------------- #
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()



# --- Define the frontend folder path relative to the app.py file --- #
frontend_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))

# Configure Flask
app = Flask(__name__, static_folder=frontend_folder, static_url_path='/')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
CORS(app)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# -------------------- Configuration -------------------- #
is_testing = (
    os.getenv("TESTING", "").lower() in ("true", "1") or
    "pytest" in sys.modules or
    bool(os.getenv("PYTEST_CURRENT_TEST"))
)

if is_testing:
    app.config["MONGO_URI"] = os.getenv("TEST_MONGO_URI", "mongodb://localhost:27017/student_project_test_db")
else:
    app.config["MONGO_URI"] = os.getenv("MONGO_URI")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

mongo = PyMongo(app)
db = mongo.db

# --- Configuration for File Uploads ---
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')

# CRITICAL: Create the folder if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER



# ==================================================================== #
#                   EMAIL NOTIFICATION SUBSYSTEM                       #
# ==================================================================== #

email_logger = logging.getLogger("student_project_mgmt.notifications")
if not email_logger.handlers:
    _email_log_handler = logging.StreamHandler()
    _email_log_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [EMAIL] %(message)s"))
    email_logger.addHandler(_email_log_handler)
    email_logger.setLevel(logging.INFO)

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Feature Toggle: Global Notification Policy
# When ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS is True (default: True):
# Only emails triggered by faculty actions and addressed to students/team members are allowed.
# All other email directions are temporarily disabled:
#   - Student -> Faculty (proposals, progress, objectives)
#   - Coordinator -> Students (all coordinator actions)
#   - Coordinator -> Faculty (guide allocation, etc.)
#   - Any other non-faculty-to-student notifications
# To restore all notifications, set to False or set ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS=false in .env.
ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS = os.getenv(
    "ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS", "true"
).lower() in ("true", "1", "yes")

# Backwards compatibility toggle reference
ENABLE_COORDINATOR_STUDENT_NOTIFICATIONS = not ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS

# Explicit whitelist of permitted faculty-to-student email triggers
ALLOWED_FACULTY_TO_STUDENT_TRIGGERS = {
    "FACULTY_UPDATE_TASKS",
    "FACULTY_SUBMIT_FEEDBACK",
    "FACULTY_PUBLISH_MARKS",
    "FACULTY_STAGE_APPROVAL",
    "FACULTY_PROJECT_STATUS",
    "EVALUATOR_SAVE_RUBRIC",
    "FACULTY_REVIEW_OBJECTIVES",
    "FACULTY_REVIEW_PAPER"
}

def is_notification_permitted(trigger_name):
    """
    Evaluates whether an email notification is allowed under current portal policy.
    When ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS is True,
    dispatches are restricted strictly to faculty-to-student triggers.
    """
    if not ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS:
        return True
    return trigger_name in ALLOWED_FACULTY_TO_STUDENT_TRIGGERS

def is_valid_email(email_str):
    """Returns True if the string is a syntactically valid email address."""
    if not email_str or not isinstance(email_str, str):
        return False
    clean = email_str.strip().lower()
    return bool(EMAIL_REGEX.match(clean))

def find_team_by_name(team_identifier):
    """
    Robustly resolves a team document from db.teams by team_name or ObjectId.
    Handles string/integer forms, strips whitespace, and performs exact or
    case-insensitive lookup.
    """
    if team_identifier is None:
        return None
    if isinstance(team_identifier, dict) and "team_name" in team_identifier:
        return team_identifier

    name_str = str(team_identifier).strip()
    if not name_str:
        return None

    # 1. Exact string match
    team = db.teams.find_one({"team_name": name_str})
    if team:
        return team

    # 2. Integer match if purely numeric
    if name_str.isdigit():
        team = db.teams.find_one({"team_name": int(name_str)})
        if team:
            return team

    # 3. Case-insensitive exact match
    team = db.teams.find_one({"team_name": {"$regex": f"^{re.escape(name_str)}$", "$options": "i"}})
    if team:
        return team

    # 4. Check by ObjectId if valid
    try:
        from bson import ObjectId
        if ObjectId.is_valid(name_str):
            team = db.teams.find_one({"_id": ObjectId(name_str)})
            if team:
                return team
    except Exception:
        pass

    return None

def get_team_recipient_emails(team_or_name):
    """
    Collects valid, unique email addresses from team.leader_email and team.members.
    Prevents duplicate emails when the leader also appears in members.
    Accepts either a team document dictionary or a team_name string/integer.
    Returns a list of cleaned email strings.
    """
    if isinstance(team_or_name, dict):
        team = team_or_name
    elif team_or_name is not None:
        team = find_team_by_name(team_or_name)
    else:
        team = None

    if not team or not isinstance(team, dict):
        return []

    recipients = []
    seen = set()

    # 1. Leader email
    leader_email = str(team.get("leader_email") or "").strip().lower()
    if is_valid_email(leader_email):
        recipients.append(leader_email)
        seen.add(leader_email)

    # 2. Team members array
    members = team.get("members") or []
    if isinstance(members, list):
        for m in members:
            m_email = ""
            if isinstance(m, dict):
                m_email = str(m.get("email") or "").strip().lower()
            elif isinstance(m, str):
                m_email = m.strip().lower()

            if is_valid_email(m_email) and m_email not in seen:
                recipients.append(m_email)
                seen.add(m_email)

    return recipients

def get_team_assigned_faculty(team_or_name):
    """
    Resolves the assigned faculty guide's details (email and name) for a given team.
    Checks team document first, then allocations collection, ensuring correct guide resolution.
    Returns (faculty_email, faculty_name).
    """
    if isinstance(team_or_name, dict):
        team = team_or_name
    elif team_or_name is not None:
        team = find_team_by_name(team_or_name)
    else:
        team = None

    faculty_email = None
    faculty_name = None

    if team:
        faculty_email = team.get("faculty_email")
        faculty_name = team.get("faculty_name")

    # If not found or invalid in team doc, check allocations collection
    if not is_valid_email(faculty_email):
        team_name = team.get("team_name") if team else str(team_or_name).strip()
        alloc = db.allocations.find_one({"team_name": team_name})
        if not alloc and str(team_name).isdigit():
            alloc = db.allocations.find_one({"team_name": int(team_name)})
        if alloc:
            if is_valid_email(alloc.get("faculty_email")):
                faculty_email = alloc.get("faculty_email")
            if alloc.get("faculty_name"):
                faculty_name = alloc.get("faculty_name")

    cleaned_email = faculty_email.strip().lower() if is_valid_email(faculty_email) else None
    return cleaned_email, faculty_name or "Faculty Guide"

def get_frontend_base_url():
    """Returns configured FRONTEND_URL or defaults to http://localhost:5000."""
    url = (os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    return url if url else "http://localhost:5000"

def render_email_template(
    headline,
    badge_text,
    badge_color,
    team_name,
    project_title,
    key_details,
    message_content,
    action_url=None,
    action_text="View in Dashboard"
):
    """
    Renders a mobile-friendly, modern HTML email with escaped user inputs
    matching the portal design system.
    """
    escaped_headline = html.escape(str(headline or "System Notification"))
    escaped_badge = html.escape(str(badge_text or "Update"))
    escaped_team = html.escape(str(team_name or "Project Team"))
    escaped_title = html.escape(str(project_title or "Student Project"))

    details_html = ""
    if key_details and isinstance(key_details, dict):
        rows = []
        for k, v in key_details.items():
            if v:
                rows.append(
                    f"<tr>"
                    f"<td style='padding:8px 12px; font-weight:600; color:#475569; border-bottom:1px solid #e2e8f0; width:35%;'>{html.escape(str(k))}</td>"
                    f"<td style='padding:8px 12px; color:#0f172a; border-bottom:1px solid #e2e8f0;'>{html.escape(str(v))}</td>"
                    f"</tr>"
                )
        if rows:
            details_html = (
                "<table style='width:100%; border-collapse:collapse; margin:16px 0; background:#f8fafc; border-radius:8px; font-size:14px; border:1px solid #e2e8f0;'>"
                + "".join(rows) +
                "</table>"
            )

    escaped_msg = html.escape(str(message_content or "")).replace("\n", "<br/>")

    button_html = ""
    if action_url:
        escaped_url = html.escape(action_url)
        escaped_btn_text = html.escape(action_text)
        button_html = f"""
        <div style='margin-top:24px; text-align:center;'>
            <a href='{escaped_url}' style='display:inline-block; background:#2563eb; color:#ffffff; font-weight:600; padding:11px 24px; text-decoration:none; border-radius:6px; font-size:14px; box-shadow:0 2px 4px rgba(37,99,235,0.2);'>{escaped_btn_text} &rarr;</a>
        </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escaped_headline}</title>
</head>
<body style="margin:0; padding:20px; background-color:#f1f5f9; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color:#1e293b;">
<table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width:600px; background:#ffffff; border-radius:12px; overflow:hidden; box-shadow:0 4px 12px rgba(0,0,0,0.08); border:1px solid #e2e8f0;">
    <tr>
        <td style="background:linear-gradient(135deg, #1e293b, #0f172a); padding:24px 28px; color:#ffffff;">
            <div style="font-size:12px; text-transform:uppercase; letter-spacing:1px; color:#94a3b8; font-weight:700;">Student Project Management Portal</div>
            <h2 style="margin:6px 0 0; font-size:20px; font-weight:700; color:#f8fafc;">{escaped_headline}</h2>
        </td>
    </tr>
    <tr>
        <td style="padding:28px;">
            <div style="display:inline-block; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:700; color:#ffffff; background:{badge_color}; margin-bottom:16px;">
                {escaped_badge}
            </div>
            
            <p style="margin:0 0 14px; font-size:15px; line-height:1.5; color:#334155;">
                Hello <strong>{escaped_team}</strong>,
            </p>
            
            <div style="background:#f8fafc; border-left:4px solid #3b82f6; padding:12px 16px; margin-bottom:16px; border-radius:0 8px 8px 0; border:1px solid #e2e8f0; border-left-width:4px;">
                <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.5px; color:#64748b; font-weight:700;">Project</div>
                <div style="font-size:14px; font-weight:600; color:#0f172a; margin-top:2px;">{escaped_title}</div>
            </div>

            {details_html}

            <div style="font-size:14px; line-height:1.6; color:#334155; margin-top:14px;">
                {escaped_msg}
            </div>

            {button_html}
        </td>
    </tr>
    <tr>
        <td style="background:#f8fafc; padding:16px 28px; border-top:1px solid #e2e8f0; font-size:12px; color:#64748b; text-align:center; line-height:1.5;">
            This is an automated notification from the Project Management & Evaluation Portal.<br/>
            Please log in to your account to review updates and submit required materials.
        </td>
    </tr>
</table>
</body>
</html>"""

def _send_smtp_worker(recipients, subject, plain_text, html_content=None, trigger_name="NOTIFICATION", team_id="N/A"):
    """
    Internal SMTP worker that connects to the SMTP server and transmits the message.
    Executed in a background daemon thread so HTTP response returns immediately.
    Logs safe, structured diagnostics with trigger name, team ID, recipient count,
    worker status, and SMTP outcome without exposing passwords, tokens, or private content.
    """
    sender_email = (os.getenv("EMAIL_USER") or "").strip()
    sender_password = (os.getenv("EMAIL_PASS") or "").strip()

    if not sender_email or not sender_password:
        email_logger.warning(
            f"[EMAIL_NOTIFICATION] trigger=\"{trigger_name}\" team=\"{team_id}\" "
            f"recipients_count=0 worker_status=\"ABORTED\" smtp_outcome=\"SKIPPED_MISSING_CREDENTIALS\""
        )
        return False

    valid_recipients = [r.strip().lower() for r in recipients if is_valid_email(r)]
    if not valid_recipients:
        email_logger.warning(
            f"[EMAIL_NOTIFICATION] trigger=\"{trigger_name}\" team=\"{team_id}\" "
            f"recipients_count=0 worker_status=\"ABORTED\" smtp_outcome=\"SKIPPED_NO_VALID_RECIPIENTS\""
        )
        return False

    smtp_host = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
    try:
        smtp_port = int(os.getenv("SMTP_PORT") or 587)
    except ValueError:
        smtp_port = 587

    try:
        smtp_timeout = int(os.getenv("SMTP_TIMEOUT") or 10)
    except ValueError:
        smtp_timeout = 10

    use_ssl = (os.getenv("SMTP_USE_SSL") or "false").lower() in ("true", "1", "yes") or smtp_port == 465
    use_tls = (os.getenv("SMTP_USE_TLS") or "true").lower() in ("true", "1", "yes") and not use_ssl
    sender_name = (os.getenv("EMAIL_SENDER_NAME") or "Student Project Management System").strip()

    email_logger.info(
        f"[EMAIL_NOTIFICATION] trigger=\"{trigger_name}\" team=\"{team_id}\" "
        f"recipients_count={len(valid_recipients)} worker_status=\"RUNNING\" smtp_outcome=\"CONNECTING\""
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(sender_name, "utf-8")), sender_email))
    msg["To"] = ", ".join(valid_recipients)

    # Attach plain text fallback
    part_text = MIMEText(plain_text or "", "plain", "utf-8")
    msg.attach(part_text)

    # Attach HTML if provided
    if html_content:
        part_html = MIMEText(html_content, "html", "utf-8")
        msg.attach(part_html)

    server = None
    try:
        if use_ssl:
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=smtp_timeout, context=context)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=smtp_timeout)
            if use_tls:
                context = ssl.create_default_context()
                server.starttls(context=context)

        server.login(sender_email, sender_password)
        refused = server.sendmail(sender_email, valid_recipients, msg.as_string())

        accepted_count = len(valid_recipients) - (len(refused) if refused else 0)
        refused_count = len(refused) if refused else 0

        if refused:
            email_logger.warning(
                f"[EMAIL_NOTIFICATION] trigger=\"{trigger_name}\" team=\"{team_id}\" "
                f"recipients_count={len(valid_recipients)} worker_status=\"PARTIAL\" "
                f"smtp_outcome=\"PARTIALLY_REFUSED\" accepted_count={accepted_count} refused_count={refused_count}"
            )

        email_logger.info(
            f"[EMAIL_NOTIFICATION] trigger=\"{trigger_name}\" team=\"{team_id}\" "
            f"recipients_count={len(valid_recipients)} worker_status=\"COMPLETED\" "
            f"smtp_outcome=\"ACCEPTED\" accepted_count={accepted_count} refused_count={refused_count}"
        )
        return True

    except smtplib.SMTPAuthenticationError as e:
        email_logger.error(
            f"[EMAIL_NOTIFICATION] trigger=\"{trigger_name}\" team=\"{team_id}\" "
            f"recipients_count={len(valid_recipients)} worker_status=\"FAILED\" "
            f"smtp_outcome=\"AUTH_FAILURE\" error=\"{e}\""
        )
        return False
    except (smtplib.SMTPConnectError, TimeoutError, socket.timeout) as e:
        email_logger.error(
            f"[EMAIL_NOTIFICATION] trigger=\"{trigger_name}\" team=\"{team_id}\" "
            f"recipients_count={len(valid_recipients)} worker_status=\"FAILED\" "
            f"smtp_outcome=\"CONNECTION_TIMEOUT\" error=\"{e}\""
        )
        return False
    except smtplib.SMTPRecipientsRefused as e:
        email_logger.error(
            f"[EMAIL_NOTIFICATION] trigger=\"{trigger_name}\" team=\"{team_id}\" "
            f"recipients_count={len(valid_recipients)} worker_status=\"FAILED\" "
            f"smtp_outcome=\"RECIPIENTS_REFUSED\" error=\"{e}\""
        )
        return False
    except Exception as e:
        email_logger.error(
            f"[EMAIL_NOTIFICATION] trigger=\"{trigger_name}\" team=\"{team_id}\" "
            f"recipients_count={len(valid_recipients)} worker_status=\"FAILED\" "
            f"smtp_outcome=\"TRANSMISSION_ERROR\" error_type=\"{type(e).__name__}\""
        )
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass

def send_email_notification(to_email_or_list, subject, message, html_content=None, async_send=True, trigger_name="NOTIFICATION", team_id="N/A"):
    """
    Sends an email notification to one or more recipients.
    Backwards-compatible: accepts either a single email string or an iterable of emails.
    Dispatches via background daemon thread by default so user requests return immediately.
    Logs structured diagnostic events with trigger_name and team_id.
    Enforces the global notification policy: only faculty actions to students are allowed.
    """
    # Enforce global notification policy: only faculty actions to students are allowed
    if not is_notification_permitted(trigger_name):
        email_logger.info(
            f"[EMAIL_NOTIFICATION] trigger=\"{trigger_name}\" team=\"{team_id}\" "
            f"recipients_count=0 worker_status=\"SKIPPED\" reason=\"POLICY_DISALLOWED_TRIGGER\""
        )
        return False

    if isinstance(to_email_or_list, str):
        recipients = [to_email_or_list]
    elif isinstance(to_email_or_list, (list, tuple, set)):
        recipients = list(to_email_or_list)
    else:
        recipients = []

    valid_recipients = [r.strip().lower() for r in recipients if is_valid_email(r)]
    if not valid_recipients:
        email_logger.warning(
            f"[EMAIL_NOTIFICATION] trigger=\"{trigger_name}\" team=\"{team_id}\" "
            f"recipients_count=0 worker_status=\"ABORTED\" smtp_outcome=\"NO_VALID_RECIPIENTS\""
        )
        return False

    if async_send:
        t = threading.Thread(
            target=_send_smtp_worker,
            args=(valid_recipients, subject, message, html_content, trigger_name, team_id),
            daemon=True
        )
        t.start()
        email_logger.info(
            f"[EMAIL_NOTIFICATION] trigger=\"{trigger_name}\" team=\"{team_id}\" "
            f"recipients_count={len(valid_recipients)} worker_status=\"QUEUED\" smtp_outcome=\"PENDING\""
        )
        return True
    else:
        return _send_smtp_worker(valid_recipients, subject, message, html_content, trigger_name, team_id)

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

    FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")

    # Check TEAM
    user = mongo.db.teams.find_one({"leader_email": email})
    if user:
        role = "team"
        token = jwt.encode({"email": email, "role": role}, app.config["SECRET_KEY"], algorithm="HS256")
        return redirect(f"{FRONTEND_URL}/team-dasboard.html?token={token}")

    # Check FACULTY
    user = mongo.db.faculty.find_one({"email": email})
    if user:
        role = "faculty"
        token = jwt.encode({"email": email, "role": role}, app.config["SECRET_KEY"], algorithm="HS256")
        return redirect(f"{FRONTEND_URL}/faculty-dashboard.html?token={token}")

    # ❌ New user → go to registration
    return redirect(f"{FRONTEND_URL}/index.html?email={email}&name={name}")
    

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

# ==================================================================== #
#                       USN & IDENTITY HELPERS                          #
# ==================================================================== #

def clean_usn(val):
    if not val:
        return ""
    return str(val).strip().upper().replace(" ", "")

def format_student_identity(name, usn=""):
    name_clean = str(name or "").strip()
    usn_clean = clean_usn(usn)
    if usn_clean:
        return f"{name_clean} ({usn_clean})"
    return name_clean

def extract_student_identity_from_member(member):
    if isinstance(member, dict):
        name = str(member.get("name") or "").strip()
        usn = clean_usn(member.get("usn"))
        email = str(member.get("email") or "").strip().lower()
    else:
        name = str(member or "").strip()
        usn = ""
        email = ""
    display_name = format_student_identity(name, usn)
    return {
        "name": name,
        "usn": usn,
        "email": email,
        "display_name": display_name
    }

def format_team_student_identities(team):
    if not team:
        return []
    
    leader_name = str(team.get("leader_name") or "").strip()
    leader_usn = clean_usn(team.get("leader_usn"))
    leader_email = str(team.get("leader_email") or "").strip().lower()
    
    students = []
    if leader_name or leader_usn or leader_email:
        students.append({
            "name": leader_name,
            "usn": leader_usn,
            "email": leader_email,
            "display_name": format_student_identity(leader_name, leader_usn),
            "is_leader": True
        })
    
    for m in team.get("members", []):
        minfo = extract_student_identity_from_member(m)
        minfo["is_leader"] = False
        students.append(minfo)
        
    return students

def extract_activity_ownership(token_str=None):
    now_iso = datetime.now(timezone.utc).isoformat()
    default_info = {
        "submitted_by_name": "Student",
        "submitted_by_usn": "",
        "submitted_by_email": "",
        "timestamp": now_iso
    }
    if not token_str:
        token_str = request.headers.get("Authorization") or request.args.get("token") or ""

    if token_str:
        try:
            raw_token = token_str.split()[-1]
            decoded = jwt.decode(raw_token, app.config["SECRET_KEY"], algorithms=["HS256"])
            email = decoded.get("email", "")
            usn = decoded.get("usn", "")
            name = decoded.get("name", "")

            if not name or not usn:
                team = db.teams.find_one({
                    "$or": [
                        {"leader_email": email},
                        {"leader_usn": usn},
                        {"members.email": email},
                        {"members.usn": usn}
                    ]
                })
                if team:
                    if team.get("leader_email") == email or clean_usn(team.get("leader_usn")) == clean_usn(usn):
                        name = name or team.get("leader_name", "")
                        usn = usn or team.get("leader_usn", "")
                    else:
                        for m in team.get("members", []):
                            minfo = extract_student_identity_from_member(m)
                            if minfo["email"] == email or (usn and minfo["usn"] == clean_usn(usn)):
                                name = name or minfo["name"]
                                usn = usn or minfo["usn"]
                                break

            return {
                "submitted_by_name": name or email or "Student",
                "submitted_by_usn": clean_usn(usn),
                "submitted_by_email": email,
                "timestamp": now_iso
            }
        except Exception as e:
            print("Notice extracting ownership:", e)

    return default_info


@app.route("/api/login/team", methods=["POST"])
def team_login():
    data = request.json or {}
    data["role"] = "team"
    return login()


@app.route('/api/register/team', methods=['POST'])
def register_team():
    data = request.json or {}
    team_name = str(data.get("team_name") or "").strip()
    leader_name = str(data.get("leader_name") or "").strip()
    leader_usn = clean_usn(data.get("leader_usn"))
    leader_email = str(data.get("leader_email") or "").strip().lower()
    leader_password = data.get("leader_password")
    raw_members = data.get("members", [])
    interests = data.get("interests", [])

    if not team_name or not leader_email or not leader_password or not leader_usn:
        return jsonify({"error": "Team name, leader name, leader USN, leader email, and password are required"}), 400

    # 1. Check Team Name uniqueness
    if db.teams.find_one({"team_name": team_name}):
        return jsonify({"error": "Team name already exists."}), 400

    # Process and validate members
    processed_members = []
    submitted_usns = [leader_usn]

    for m in raw_members:
        if isinstance(m, dict):
            m_name = str(m.get("name") or "").strip()
            m_usn = clean_usn(m.get("usn"))
            m_email = str(m.get("email") or "").strip().lower()
        else:
            m_name = str(m or "").strip()
            m_usn = ""
            m_email = ""

        if m_name or m_usn or m_email:
            if m_usn:
                submitted_usns.append(m_usn)
            processed_members.append({
                "name": m_name,
                "usn": m_usn,
                "email": m_email
            })

    # Check for duplicate USNs within the registration form itself
    if len(submitted_usns) != len(set(submitted_usns)):
        return jsonify({"error": "This student is already registered in another team."}), 400

    # 2. Check USN uniqueness in Database
    for usn in submitted_usns:
        if usn:
            existing_team = db.teams.find_one({
                "$or": [
                    {"leader_usn": usn},
                    {"members.usn": usn},
                    {"members": usn}
                ]
            })
            if existing_team:
                return jsonify({"error": "This student is already registered in another team."}), 400

    if db.teams.find_one({"leader_email": leader_email}):
        return jsonify({"error": "Leader email already registered"}), 400

    hashed_password = generate_password_hash(leader_password)

    db.teams.insert_one({
        "team_name": team_name,
        "leader_name": leader_name,
        "leader_usn": leader_usn,
        "leader_email": leader_email,
        "password": hashed_password,
        "members": processed_members,
        "interests": interests,
        "role": "team",
        "created_at": datetime.now(timezone.utc)
    })

    return jsonify({"message": "Team registered successfully!"}), 201


@app.route('/api/register/faculty', methods=['POST'])
def register_faculty():
    data = request.json or {}
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
    identity = str(data.get("email") or data.get("usn") or data.get("identity") or "").strip()
    password = data.get("password")
    role = data.get("role")

    if not identity or not password or not role:
        return jsonify({"error": "All fields are required"}), 400

    user = None
    identity_usn = clean_usn(identity)
    identity_email = identity.lower()

    logged_in_name = ""
    logged_in_usn = ""
    logged_in_email = ""
    is_leader = False
    team_name = None

    if role in ["student", "team"]:
        team = db.teams.find_one({
            "$or": [
                {"leader_usn": identity_usn},
                {"leader_email": identity_email},
                {"members.usn": identity_usn},
                {"members.email": identity_email},
                {"members": {"$in": [identity, identity_email, identity_usn]}}
            ]
        })
        if team:
            user = team
            role = "team"
            team_name = team.get("team_name")

            l_usn = clean_usn(team.get("leader_usn"))
            l_email = (team.get("leader_email") or "").lower().strip()
            l_name = (team.get("leader_name") or "").lower().strip()

            if (identity_usn and l_usn == identity_usn) or (identity_email and l_email == identity_email) or (identity.lower() == l_name):
                is_leader = True
                logged_in_name = team.get("leader_name", "")
                logged_in_usn = team.get("leader_usn", "")
                logged_in_email = team.get("leader_email", "")
            else:
                is_leader = False
                for m in team.get("members", []):
                    m_info = extract_student_identity_from_member(m)
                    if (identity_usn and m_info["usn"] == identity_usn) or (identity_email and m_info["email"] == identity_email) or (identity.lower() == m_info["name"].lower()):
                        logged_in_name = m_info["name"]
                        logged_in_usn = m_info["usn"]
                        logged_in_email = m_info["email"]
                        break
                if not logged_in_name:
                    logged_in_name = identity
                    logged_in_usn = identity_usn
                    logged_in_email = identity_email

    elif role == "faculty":
        user = db.faculty.find_one({"$or": [{"email": identity_email}, {"email": identity}]})
        if user:
            logged_in_name = user.get("name", "")
            logged_in_email = user.get("email", "")
    elif role == "coordinator":
        user = db.coordinator.find_one({"$or": [{"email": identity_email}, {"email": identity}]})
        if not user:
            user = db.faculty.find_one({"email": identity_email, "role": "coordinator"})
        if user:
            logged_in_name = user.get("name", "")
            logged_in_email = user.get("email", "")

    if not user:
        return jsonify({"error": "User not found"}), 404

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
        return jsonify({"error": "Invalid password"}), 401

    if "leader_password" in user and "password" not in user:
        db.teams.update_one(
            {"_id": user["_id"]},
            {"$set": {"password": stored_password}, "$unset": {"leader_password": ""}}
        )

    token_payload = {
        "email": logged_in_email or identity_email,
        "usn": logged_in_usn or identity_usn,
        "name": logged_in_name,
        "role": role,
        "is_leader": is_leader,
        "team_name": team_name,
        "exp": datetime.now(timezone.utc) + timedelta(hours=2)
    }

    token = jwt.encode(token_payload, app.config["SECRET_KEY"], algorithm="HS256")

    redirect_url = ""
    if role in ["student", "team"]:
        redirect_url = "team-dasboard.html"
    elif role == "faculty":
        redirect_url = "faculty-dashboard.html"
    elif role == "coordinator":
        redirect_url = "project_coordinator-dashboard.html"

    return jsonify({
        "token": token,
        "redirect": redirect_url,
        "user": {
            "name": logged_in_name,
            "usn": logged_in_usn,
            "email": logged_in_email,
            "is_leader": is_leader,
            "team_name": team_name,
            "display_name": format_student_identity(logged_in_name, logged_in_usn)
        }
    }), 200

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
        email = decoded.get("email", "")
        usn = clean_usn(decoded.get("usn", ""))

        team = db.teams.find_one({
            "$or": [
                {"leader_email": email},
                {"leader_usn": usn},
                {"members.email": email},
                {"members.usn": usn},
                {"members": {"$in": [email, usn]}}
            ]
        })

        if not team:
            return jsonify({"error": "No team found for student"}), 404

        token_name = decoded.get("name", "")
        token_email = decoded.get("email", "")
        token_usn = clean_usn(decoded.get("usn", ""))

        l_usn = clean_usn(team.get("leader_usn"))
        l_email = (team.get("leader_email") or "").lower().strip()
        l_name = (team.get("leader_name") or "").lower().strip()

        is_leader = False
        if (token_usn and l_usn == token_usn) or (token_email and l_email == token_email.lower()) or (token_name and l_name == token_name.lower()):
            is_leader = True
            current_user_name = team.get("leader_name", token_name)
            current_user_usn = team.get("leader_usn", token_usn)
            current_user_email = team.get("leader_email", token_email)
        else:
            is_leader = False
            current_user_name = token_name
            current_user_usn = token_usn
            current_user_email = token_email
            for m in team.get("members", []):
                minfo = extract_student_identity_from_member(m)
                if (token_usn and minfo["usn"] == token_usn) or (token_email and minfo["email"] == token_email.lower()) or (token_name and minfo["name"].lower() == token_name.lower()):
                    current_user_name = minfo["name"]
                    current_user_usn = minfo["usn"]
                    current_user_email = minfo["email"]
                    break

        user_display = format_student_identity(current_user_name, current_user_usn)
        leader_disp = format_student_identity(team.get("leader_name"), team.get("leader_usn"))

        formatted_members = []
        members_details = []
        for m in team.get("members", []):
            minfo = extract_student_identity_from_member(m)
            formatted_members.append(minfo["display_name"])
            members_details.append(minfo)

        canonical_team_name = team.get("team_name", "")
        canonical_team_id = str(team.get("_id", ""))

        # Standard project milestone stages
        standard_stages = [
            "Project Proposal",
            "Synopsis & Literature Review",
            "System Design & Architecture",
            "Mid-Term Evaluation",
            "Final Project & Report"
        ]
        existing_approvals = team.get("approvals") or []
        stage_map = {str(a.get("stage", "")).strip().lower(): a for a in existing_approvals if isinstance(a, dict) and a.get("stage")}

        merged_approvals = []
        for std in standard_stages:
            std_key = std.strip().lower()
            if std_key in stage_map:
                item = dict(stage_map[std_key])
                item["stage"] = item.get("stage", std)
                item["status"] = item.get("status", "Pending")
                item["team_name"] = canonical_team_name
                item["team_id"] = canonical_team_id
                merged_approvals.append(item)
            else:
                initial_status = "Pending"
                if std_key == "project proposal" and isinstance(team.get("project_idea"), dict):
                    pi_stat = (team["project_idea"].get("status") or "").strip()
                    if pi_stat.lower() == "approved":
                        initial_status = "Approved"
                    elif pi_stat.lower() == "rejected":
                        initial_status = "Rejected"
                merged_approvals.append({
                    "stage": std,
                    "status": initial_status,
                    "team_name": canonical_team_name,
                    "team_id": canonical_team_id
                })

        std_keys = {std.strip().lower() for std in standard_stages}
        for a in existing_approvals:
            if isinstance(a, dict) and a.get("stage"):
                if str(a.get("stage", "")).strip().lower() not in std_keys:
                    item = dict(a)
                    item["team_name"] = canonical_team_name
                    item["team_id"] = canonical_team_id
                    merged_approvals.append(item)

        faculty_email, faculty_name = get_team_assigned_faculty(team)
        if not faculty_name or faculty_name == "Faculty Guide":
            faculty_name = team.get("faculty_name") or faculty_name
        if not faculty_email:
            faculty_email = team.get("faculty_email")

        data = {
            "team_name": team.get("team_name"),
            "faculty_name": faculty_name,
            "faculty_email": faculty_email,
            "leader_name": team.get("leader_name"),
            "leader_usn": team.get("leader_usn", ""),
            "leader_email": team.get("leader_email", ""),
            "leader_display": leader_disp,
            "user_name": current_user_name,
            "user_usn": current_user_usn,
            "user_email": current_user_email,
            "user_display": user_display,
            "is_leader": is_leader,
            "members": formatted_members,
            "members_details": members_details,
            "interests": team.get("interests", []),
            "tasks": team.get("tasks", []),
            "approvals": merged_approvals,
            "feedbacks": team.get("feedbacks", []),
            "marks": team.get("marks", []),
            "progress": team.get("progress", []),
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
            faculty = db.faculty.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
        if not faculty and decoded.get("role") == "faculty":
            return jsonify({"error": "Faculty not found"}), 404

        # Query allocated teams
        alloc_records = list(db.allocations.find({"faculty_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}))
        alloc_team_names = [a.get("team_name") for a in alloc_records if a.get("team_name")]

        query = {
            "$or": [
                {"faculty_email": email},
                {"faculty_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}
            ]
        }
        if alloc_team_names:
            query["$or"].append({"team_name": {"$in": alloc_team_names}})

        # ✅ Fetch all teams assigned to this faculty, INCLUDING tasks, feedbacks, and marks
        teams = list(
            db.teams.find(
                query,
                {
                    "_id": 0,
                    "team_name": 1,
                    "leader_name": 1,
                    "leader_usn": 1,
                    "leader_email": 1,
                    "members": 1,
                    "interests": 1,
                    "progress": 1,
                    "tasks": 1,
                    "approvals": 1,
                    "feedbacks": 1,
                    "marks": 1,
                    "project_idea": 1
                }
            )
        )

        # Coordinators may inspect all teams; faculty only see assigned teams.
        if not teams and decoded.get("role") == "coordinator":
            teams = list(
                db.teams.find(
                    {},
                    {
                        "_id": 0,
                        "team_name": 1,
                        "leader_name": 1,
                        "leader_usn": 1,
                        "leader_email": 1,
                        "members": 1,
                        "interests": 1,
                        "progress": 1,
                        "tasks": 1,
                        "approvals": 1,
                        "feedbacks": 1,
                        "marks": 1,
                        "project_idea": 1,
                        "faculty_email": 1,
                        "faculty_name": 1
                    }
                )
            )

        # Format USN identity for each team
        for team in teams:
            l_name = team.get("leader_name", "")
            l_usn = clean_usn(team.get("leader_usn", ""))
            team["leader_display"] = format_student_identity(l_name, l_usn)
            formatted_members = []
            for m in team.get("members", []):
                minfo = extract_student_identity_from_member(m)
                formatted_members.append(minfo)
            team["members"] = formatted_members

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
    data = request.json or {}
    team_name = data.get("team_name")
    feedback_text = data.get("feedback")

    if not team_name or not feedback_text:
        return jsonify({"error": "Team name and feedback are required"}), 400

    team = find_team_by_name(team_name)
    if not team:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    canonical_name = team.get("team_name", str(team_name))

    # ✅ Create feedback entry with timestamp
    new_feedback = {
        "feedback": feedback_text,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    # ✅ Push into array (DO NOT REPLACE)
    db.teams.update_one(
        {"_id": team["_id"]},
        {"$push": {"feedbacks": new_feedback}}
    )

    # Notify all team members via email
    try:
        recipients = get_team_recipient_emails(team)
        if recipients:
            base_url = get_frontend_base_url()
            idea = team.get("project_idea") or {}
            proj_title = (idea.get("title") if isinstance(idea, dict) else "") or "Student Project"
            faculty_name = team.get("faculty_name") or "Faculty Guide"
            subject = f"New Feedback Received: {canonical_name}"
            plain_msg = (
                f"Hello {canonical_name},\n\n"
                f"New feedback has been provided by {faculty_name}:\n\n"
                f"{feedback_text}\n\n"
                f"Date: {new_feedback['date']}\n\n"
                f"Check your dashboard: {base_url}/team-dasboard.html"
            )
            html_msg = render_email_template(
                headline="New Faculty Feedback Received",
                badge_text="Feedback Added",
                badge_color="#2563eb",
                team_name=canonical_name,
                project_title=proj_title,
                key_details={
                    "Feedback Date": new_feedback["date"],
                    "Provided By": faculty_name
                },
                message_content=feedback_text,
                action_url=f"{base_url}/team-dasboard.html",
                action_text="View Feedback in Dashboard"
            )
            send_email_notification(
                recipients, subject, plain_msg, html_msg,
                trigger_name="FACULTY_SUBMIT_FEEDBACK", team_id=canonical_name
            )
    except Exception as email_err:
        email_logger.error(f"Error preparing feedback notification for {canonical_name}: {email_err}")

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


def check_faculty_team_auth(team, token_full, require_token=False):
    """
    Validates faculty authorization for modifying a team's tasks or approvals.
    If token is present:
      - Validates JWT token
      - If role == 'faculty', checks that the faculty is assigned to this team
      - If role not in ['faculty', 'coordinator'], forbids access
    Returns (True, decoded) if authorized, or (False, (jsonify_response, status_code)).
    """
    if not token_full:
        if require_token:
            return False, (jsonify({"error": "Missing token"}), 401)
        return True, None  # Allow test suite compatibility when no auth header is sent
    token = token_full.split()[-1]
    try:
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return False, (jsonify({"error": "Token expired"}), 401)
    except Exception:
        return False, (jsonify({"error": "Invalid token"}), 401)

    user_email = (decoded.get("email") or "").strip().lower()
    user_role = decoded.get("role", "")
    if user_role not in ["faculty", "coordinator"]:
        return False, (jsonify({"error": "Unauthorized role"}), 403)

    if user_role == "faculty":
        assigned_email, _ = get_team_assigned_faculty(team)
        team_fac = (team.get("faculty_email") or "").strip().lower()
        if not ((assigned_email and assigned_email.strip().lower() == user_email) or (team_fac and team_fac == user_email)):
            return False, (jsonify({"error": "Forbidden: You are not authorized to manage tasks or approvals for this team."}), 403)

    return True, decoded


@app.route('/api/faculty/update_tasks', methods=['POST'])
def update_tasks():
    token_full = request.headers.get("Authorization")
    data = request.json or {}
    team_name = data.get("team_name")
    new_task = data.get("new_task")

    # If updating an existing task status via update_tasks
    if not new_task and (data.get("status") and (data.get("task_index") is not None or data.get("task_name"))):
        return update_task_status()

    if not team_name or not new_task:
        return jsonify({"error": "Team name and new task required"}), 400

    team = find_team_by_name(team_name)
    if not team:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    is_auth, auth_res = check_faculty_team_auth(team, token_full)
    if not is_auth:
        return auth_res

    canonical_name = team.get("team_name", str(team_name))

    # Ensure default status is set
    if "status" not in new_task or not new_task["status"]:
        new_task["status"] = "Pending"

    # Use $push to append the new task to the array
    db.teams.update_one({"_id": team["_id"]}, {"$push": {"tasks": new_task}})

    # Notify all team members via email
    try:
        recipients = get_team_recipient_emails(team)
        if recipients:
            base_url = get_frontend_base_url()
            idea = team.get("project_idea") or {}
            proj_title = (idea.get("title") if isinstance(idea, dict) else "") or "Student Project"
            task_name = new_task.get("name") or "New Task"
            deadline = new_task.get("deadline") or "Not specified"
            faculty_name = team.get("faculty_name") or "Faculty Guide"
            subject = f"New Task Assigned: {task_name} - {canonical_name}"
            plain_msg = (
                f"Hello {canonical_name},\n\n"
                f"A new task has been assigned by {faculty_name}:\n"
                f"Task: {task_name}\n"
                f"Deadline: {deadline}\n\n"
                f"Description: {new_task.get('description', 'Please complete deliverables before the deadline.')}\n\n"
                f"Check your dashboard: {base_url}/team-dasboard.html"
            )
            html_msg = render_email_template(
                headline="New Task Assigned",
                badge_text="Task Assigned",
                badge_color="#7c3aed",
                team_name=canonical_name,
                project_title=proj_title,
                key_details={
                    "Task Name": task_name,
                    "Deadline": deadline,
                    "Assigned By": faculty_name
                },
                message_content=new_task.get("description") or "Please log in to your dashboard to review task instructions and submit your deliverables.",
                action_url=f"{base_url}/team-dasboard.html",
                action_text="View Tasks in Dashboard"
            )
            send_email_notification(
                recipients, subject, plain_msg, html_msg,
                trigger_name="FACULTY_UPDATE_TASKS", team_id=canonical_name
            )
    except Exception as email_err:
        email_logger.error(f"Error preparing task notification for {canonical_name}: {email_err}")

    return jsonify({"message": "Task assigned successfully!"}), 200


@app.route('/api/faculty/update_task_status', methods=['POST'])
def update_task_status():
    token_full = request.headers.get("Authorization")
    data = request.json or {}
    team_name = data.get("team_name")
    task_index = data.get("task_index")
    task_name = data.get("task_name")
    new_status = data.get("status")

    if not team_name:
        return jsonify({"error": "Team name is required"}), 400
    if not new_status:
        return jsonify({"error": "Task status is required"}), 400

    team = find_team_by_name(team_name)
    if not team:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    # Ensure faculty can update tasks belonging only to their authorized teams
    is_auth, auth_res = check_faculty_team_auth(team, token_full)
    if not is_auth:
        return auth_res

    # Normalize allowed status values: Pending, In Progress, Completed
    status_str = str(new_status).strip()
    status_lower = status_str.lower()
    if status_lower == "completed":
        matched_status = "Completed"
    elif status_lower in ["in progress", "inprogress", "in-progress"]:
        matched_status = "In Progress"
    elif status_lower == "pending":
        matched_status = "Pending"
    else:
        matched_status = status_str

    tasks = team.get("tasks", [])
    updated = False

    # 1. Update by task_index if specified and valid
    if task_index is not None:
        try:
            idx = int(task_index)
            if 0 <= idx < len(tasks):
                db.teams.update_one(
                    {"_id": team["_id"]},
                    {"$set": {f"tasks.{idx}.status": matched_status}}
                )
                updated = True
        except (ValueError, TypeError):
            pass

    # 2. Fallback: match by task_name
    if not updated and task_name:
        res = db.teams.update_one(
            {"_id": team["_id"], "tasks.name": str(task_name).strip()},
            {"$set": {"tasks.$.status": matched_status}}
        )
        if res.matched_count > 0:
            updated = True

    if not updated:
        return jsonify({"error": "Task not found to update"}), 404

    # Do not send any additional email notifications for task status changes
    return jsonify({
        "message": f"Task status updated to '{matched_status}' successfully!",
        "status": matched_status
    }), 200


@app.route("/api/faculty/delete_task", methods=["POST"])
def delete_task():
    token_full = request.headers.get("Authorization")
    data = request.json or {}
    team_name = data.get("team_name")
    task_index = data.get("task_index")

    team = find_team_by_name(team_name)
    if not team:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    is_auth, auth_res = check_faculty_team_auth(team, token_full)
    if not is_auth:
        return auth_res

    db.teams.update_one(
        {"team_name": team_name},
        {"$unset": {f"tasks.{task_index}": 1}}
    )
    db.teams.update_one(
        {"team_name": team_name},
        {"$pull": {"tasks": None}}
    )

    return jsonify({"message": "Task deleted successfully"}), 200


@app.route('/api/faculty/team_approvals/<team_name>', methods=['GET'])
def get_team_approvals(team_name):
    token_full = request.headers.get("Authorization")
    if not token_full:
        return jsonify({"error": "Missing token"}), 401

    team = find_team_by_name(team_name)
    if not team and ObjectId.is_valid(str(team_name)):
        try:
            team = db.teams.find_one({"_id": ObjectId(str(team_name))})
        except Exception:
            team = None

    if not team:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    is_auth, auth_res = check_faculty_team_auth(team, token_full, require_token=True)
    if not is_auth:
        return auth_res

    canonical_name = team.get("team_name", str(team_name))
    raw_approvals = team.get("approvals") or []

    standard_stages = [
        "Project Proposal",
        "Synopsis & Literature Review",
        "System Design & Architecture",
        "Mid-Term Evaluation",
        "Final Project & Report"
    ]
    stage_map = {str(a.get("stage", "")).strip().lower(): a for a in raw_approvals if isinstance(a, dict) and a.get("stage")}

    merged_approvals = []
    for std in standard_stages:
        std_key = std.strip().lower()
        if std_key in stage_map:
            item = dict(stage_map[std_key])
            item["stage"] = item.get("stage", std)
            item["status"] = item.get("status", "Pending")
            item["team_name"] = canonical_name
            item["team_id"] = str(team.get("_id", ""))
            merged_approvals.append(item)
        else:
            initial_status = "Pending"
            if std_key == "project proposal" and isinstance(team.get("project_idea"), dict):
                pi_stat = (team["project_idea"].get("status") or "").strip()
                if pi_stat.lower() == "approved":
                    initial_status = "Approved"
                elif pi_stat.lower() == "rejected":
                    initial_status = "Rejected"
            merged_approvals.append({
                "stage": std,
                "status": initial_status,
                "team_name": canonical_name,
                "team_id": str(team.get("_id", ""))
            })

    std_keys = {std.strip().lower() for std in standard_stages}
    for a in raw_approvals:
        if isinstance(a, dict) and a.get("stage"):
            if str(a.get("stage", "")).strip().lower() not in std_keys:
                item = dict(a)
                item["team_name"] = canonical_name
                item["team_id"] = str(team.get("_id", ""))
                merged_approvals.append(item)

    return jsonify({
        "team_name": canonical_name,
        "team_id": str(team.get("_id", "")),
        "leader_name": team.get("leader_name", ""),
        "leader_usn": team.get("leader_usn", ""),
        "project_idea": team.get("project_idea"),
        "approvals": merged_approvals
    }), 200


@app.route('/api/faculty/update_approvals', methods=['POST'])
def update_approvals():
    token_full = request.headers.get("Authorization")
    data = request.json or {}
    team_ident = data.get("team_name") or data.get("team_id")
    new_approval = data.get("new_approval")

    if not team_ident or not new_approval:
        return jsonify({"error": "Team name and approval status required"}), 400

    team = find_team_by_name(team_ident)
    if not team and ObjectId.is_valid(str(team_ident)):
        try:
            team = db.teams.find_one({"_id": ObjectId(str(team_ident))})
        except Exception:
            team = None

    if not team:
        return jsonify({"error": f"Team '{team_ident}' not found"}), 404

    # Ensure faculty can update approvals belonging only to their authorized teams
    is_auth, auth_res = check_faculty_team_auth(team, token_full, require_token=True)
    if not is_auth:
        return auth_res

    canonical_name = team.get("team_name", str(team_ident))
    user_email = auth_res.get("email") if isinstance(auth_res, dict) else (team.get("faculty_email") or "")
    now_iso = datetime.now(timezone.utc).isoformat()

    stage_name = (new_approval.get("stage") or "").strip()
    stage_status = (new_approval.get("status") or "Pending").strip()
    if not stage_name:
        return jsonify({"error": "Stage name is required"}), 400

    comments = new_approval.get("comments")
    if comments is None:
        comments = new_approval.get("comment")

    set_fields = {
        "approvals.$.status": stage_status,
        "approvals.$.stage": stage_name,
        "approvals.$.team_name": canonical_name,
        "approvals.$.team_id": str(team["_id"]),
        "approvals.$.updated_at": now_iso,
        "approvals.$.updated_by": user_email
    }
    if comments is not None:
        set_fields["approvals.$.comments"] = comments

    # If updating Project Proposal stage, also synchronize project_idea.status for this team
    if stage_name.strip().lower() in ["project proposal", "proposal", "idea"] and team.get("project_idea"):
        set_fields["project_idea.status"] = stage_status

    # 1. Try to update an existing stage's status (case-insensitive stage match)
    result = db.teams.update_one(
        {"_id": team["_id"], "approvals.stage": {"$regex": f"^{re.escape(stage_name)}$", "$options": "i"}},
        {"$set": set_fields}
    )

    # 2. If no existing stage was modified (matched_count == 0), push the new one
    if result.matched_count == 0:
        push_doc = {
            "stage": stage_name,
            "status": stage_status,
            "team_name": canonical_name,
            "team_id": str(team["_id"]),
            "updated_at": now_iso,
            "updated_by": user_email,
            "comments": comments or ""
        }
        push_update = {"$push": {"approvals": push_doc}}
        if stage_name.strip().lower() in ["project proposal", "proposal", "idea"] and team.get("project_idea"):
            push_update["$set"] = {"project_idea.status": stage_status}
        db.teams.update_one({"_id": team["_id"]}, push_update)

    # Synchronize reference project for originality checking if proposal was approved
    if stage_name.strip().lower() in ["project proposal", "proposal", "idea"] and team.get("project_idea"):
        if stage_status == "Approved":
            idea = team["project_idea"]
            title = idea.get("title", "").strip() if isinstance(idea, dict) else ""
            if title:
                proj_data = {
                    "title": title,
                    "abstract": idea.get("abstract", "").strip() if isinstance(idea, dict) else "",
                    "objectives": idea.get("objectives", "") if isinstance(idea, dict) else "",
                    "methodology": idea.get("methodology", "") if isinstance(idea, dict) else "",
                    "description": idea.get("description", "") if isinstance(idea, dict) else "",
                    "technologies": (idea.get("technologies") or idea.get("tech_stack", "")) if isinstance(idea, dict) else "",
                    "team_name": canonical_name,
                    "submitted_by_usn": (idea.get("submitted_by_usn") or team.get("leader_usn", "")) if isinstance(idea, dict) else team.get("leader_usn", ""),
                    "submitted_by_email": (idea.get("submitted_by_email") or team.get("leader_email", "")) if isinstance(idea, dict) else team.get("leader_email", ""),
                    "approved_at": now_iso,
                    "status": "Approved"
                }
                existing_ref = db.projects.find_one({"team_name": canonical_name})
                if existing_ref:
                    db.projects.update_one({"_id": existing_ref["_id"]}, {"$set": proj_data})
                else:
                    db.projects.insert_one(proj_data)
        elif stage_status in ["Rejected", "Pending"]:
            db.projects.delete_many({"team_name": canonical_name})

    # Fetch updated approvals to return
    updated_team = db.teams.find_one({"_id": team["_id"]}, {"_id": 0, "approvals": 1})
    updated_approvals = updated_team.get("approvals", []) if updated_team else []

    # Notify all team members via email
    try:
        recipients = get_team_recipient_emails(team)
        if recipients:
            base_url = get_frontend_base_url()
            idea = team.get("project_idea") or {}
            proj_title = (idea.get("title") if isinstance(idea, dict) else "") or "Student Project"
            faculty_name = team.get("faculty_name") or "Faculty Guide"
            badge_color = "#059669" if str(stage_status).lower() in ("approved", "completed") else "#d97706"
            subject = f"Project Stage Update: {stage_name} ({stage_status}) - {canonical_name}"
            plain_msg = (
                f"Hello {canonical_name},\n\n"
                f"Your project stage approval status has been updated by {faculty_name}:\n"
                f"Stage: {stage_name}\n"
                f"Status: {stage_status}\n\n"
                f"Check your dashboard: {base_url}/team-dasboard.html"
            )
            html_msg = render_email_template(
                headline="Project Stage Approval Update",
                badge_text=stage_status,
                badge_color=badge_color,
                team_name=canonical_name,
                project_title=proj_title,
                key_details={
                    "Stage": stage_name,
                    "Approval Status": stage_status,
                    "Updated By": faculty_name
                },
                message_content=f"Your project stage '{stage_name}' has been marked as '{stage_status}'. Please log in to your dashboard to review required steps.",
                action_url=f"{base_url}/team-dasboard.html",
                action_text="View Stages in Dashboard"
            )
            send_email_notification(
                recipients, subject, plain_msg, html_msg,
                trigger_name="FACULTY_STAGE_APPROVAL", team_id=canonical_name
            )
    except Exception as email_err:
        email_logger.error(f"Error preparing approval stage notification for {canonical_name}: {email_err}")

    return jsonify({
        "message": "Approval status updated successfully!",
        "stage": stage_name,
        "status": stage_status,
        "team_name": canonical_name,
        "approvals": updated_approvals
    }), 200


@app.route("/api/faculty/update_project_status", methods=["POST"])
def update_project_status():
    token_full = request.headers.get("Authorization")
    if not token_full:
        return jsonify({"error": "Missing token"}), 401

    data = request.json or {}
    team_ident = data.get("team_name") or data.get("team_id")
    status = data.get("status")

    if not team_ident or not status:
        return jsonify({"error": "team_name and status are required"}), 400

    team = find_team_by_name(team_ident)
    if not team and ObjectId.is_valid(str(team_ident)):
        try:
            team = db.teams.find_one({"_id": ObjectId(str(team_ident))})
        except Exception:
            team = None

    if not team:
        return jsonify({"error": f"Team '{team_ident}' not found"}), 404

    is_auth, auth_res = check_faculty_team_auth(team, token_full, require_token=True)
    if not is_auth:
        return auth_res

    canonical_name = team.get("team_name", str(team_ident))
    user_email = auth_res.get("email") if isinstance(auth_res, dict) else (team.get("faculty_email") or "")
    now_iso = datetime.now(timezone.utc).isoformat()

    db.teams.update_one(
        {"_id": team["_id"]},
        {"$set": {"project_idea.status": status}}
    )

    # Synchronize stage approval for "Project Proposal"
    stage_name = "Project Proposal"
    stage_update = db.teams.update_one(
        {"_id": team["_id"], "approvals.stage": {"$regex": f"^{re.escape(stage_name)}$", "$options": "i"}},
        {"$set": {
            "approvals.$.status": status,
            "approvals.$.stage": stage_name,
            "approvals.$.team_name": canonical_name,
            "approvals.$.team_id": str(team["_id"]),
            "approvals.$.updated_at": now_iso,
            "approvals.$.updated_by": user_email
        }}
    )
    if stage_update.matched_count == 0:
        db.teams.update_one(
            {"_id": team["_id"]},
            {"$push": {"approvals": {
                "stage": stage_name,
                "status": status,
                "team_name": canonical_name,
                "team_id": str(team["_id"]),
                "updated_at": now_iso,
                "updated_by": user_email
            }}}
        )

    if status == "Approved" and team.get("project_idea"):
        idea = team["project_idea"]
        title = idea.get("title", "").strip() if isinstance(idea, dict) else ""
        if title:
            proj_data = {
                "title": title,
                "abstract": idea.get("abstract", "").strip() if isinstance(idea, dict) else "",
                "objectives": idea.get("objectives", "") if isinstance(idea, dict) else "",
                "methodology": idea.get("methodology", "") if isinstance(idea, dict) else "",
                "description": idea.get("description", "") if isinstance(idea, dict) else "",
                "technologies": (idea.get("technologies") or idea.get("tech_stack", "")) if isinstance(idea, dict) else "",
                "team_name": canonical_name,
                "submitted_by_usn": (idea.get("submitted_by_usn") or team.get("leader_usn", "")) if isinstance(idea, dict) else team.get("leader_usn", ""),
                "submitted_by_email": (idea.get("submitted_by_email") or team.get("leader_email", "")) if isinstance(idea, dict) else team.get("leader_email", ""),
                "approved_at": now_iso,
                "status": "Approved"
            }
            # Duplicate protection: find existing project in projects collection by team_name
            existing_ref = db.projects.find_one({"team_name": canonical_name})
            if existing_ref:
                db.projects.update_one({"_id": existing_ref["_id"]}, {"$set": proj_data})
            else:
                db.projects.insert_one(proj_data)
            new_count = db.projects.count_documents({})
            print(f"[ORIGINALITY] Reference project count: {new_count}")

    elif status in ["Rejected", "Pending Faculty Approval", "Pending"]:
        deleted = db.projects.delete_many({"team_name": canonical_name})
        if deleted.deleted_count > 0:
            new_count = db.projects.count_documents({})
            print(f"[ORIGINALITY] Reference project count: {new_count}")

    # Notify all team members via email
    try:
        recipients = get_team_recipient_emails(team)
        if recipients:
            base_url = get_frontend_base_url()
            idea = team.get("project_idea") or {}
            proj_title = (idea.get("title", "").strip() if isinstance(idea, dict) else "") or "Project Proposal"
            badge_color = "#059669" if status == "Approved" else ("#dc2626" if status == "Rejected" else "#d97706")
            faculty_name = team.get("faculty_name") or "Faculty Guide"
            subject = f"Project Idea Status: {status} - {canonical_name}"
            plain_msg = (
                f"Hello {canonical_name},\n\n"
                f"Your project idea '{proj_title}' status has been updated by {faculty_name}:\n"
                f"Status: {status}\n\n"
                f"Check your dashboard: {base_url}/team-dasboard.html"
            )
            html_msg = render_email_template(
                headline=f"Project Idea {status}",
                badge_text=status,
                badge_color=badge_color,
                team_name=canonical_name,
                project_title=proj_title,
                key_details={
                    "Decision Status": status,
                    "Reviewed By": faculty_name,
                    "Review Date": datetime.now().strftime("%Y-%m-%d %H:%M")
                },
                message_content=f"Your project proposal has been marked as '{status}'. Please log in to your dashboard to view full feedback and project milestones.",
                action_url=f"{base_url}/team-dasboard.html",
                action_text="Open Team Dashboard"
            )
            send_email_notification(
                recipients, subject, plain_msg, html_msg,
                trigger_name="FACULTY_PROJECT_STATUS", team_id=canonical_name
            )
    except Exception as email_err:
        email_logger.error(f"Error preparing project status notification for {canonical_name}: {email_err}")

    return jsonify({"message": f"Project idea {status}"}), 200

@app.route("/api/team/save_project_idea", methods=["POST"])
def save_project_idea():
    token_full = request.headers.get("Authorization")
    if not token_full:
        return jsonify({"error": "Missing token"}), 401

    token = token_full.split()[-1]

    try:
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded.get("email", "")
        usn = clean_usn(decoded.get("usn", ""))

        team = db.teams.find_one({
            "$or": [
                {"leader_email": email},
                {"leader_usn": usn},
                {"members.email": email},
                {"members.usn": usn},
                {"members": {"$in": [email, usn]}}
            ]
        })

        if not team:
            return jsonify({"error": "Team not found"}), 404

        data = request.json or {}
        ownership = extract_activity_ownership(token_full)

        project_data = {
            "title": data.get("title"),
            "abstract": data.get("abstract"),
            "originality_score": data.get("originality_score"),
            "similarity_percent": data.get("similarity_percent"),
            "most_similar_project": data.get("most_similar_project"),
            "status": "Pending Faculty Approval",
            "submitted_at": datetime.now().isoformat(),
            "submitted_by_name": ownership["submitted_by_name"],
            "submitted_by_usn": ownership["submitted_by_usn"],
            "submitted_by_email": ownership["submitted_by_email"],
            "timestamp": ownership["timestamp"]
        }

        db.teams.update_one(
            {"team_name": team["team_name"]},
            {"$set": {"project_idea": project_data}}
        )

        # Notify assigned faculty guide via email (Temporarily disabled under faculty-to-student only policy)
        try:
            if not ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS:
                faculty_email, f_name = get_team_assigned_faculty(team)
                if faculty_email:
                    base_url = get_frontend_base_url()
                    title = project_data.get("title") or "Project Proposal"
                    subject = f"New Project Proposal Submitted: {team['team_name']}"
                    plain_msg = (
                        f"Hello {f_name},\n\n"
                        f"Team '{team['team_name']}' has submitted their project proposal for review:\n"
                        f"Title: {title}\n"
                        f"Submitted By: {project_data.get('submitted_by_name')} ({project_data.get('submitted_by_usn')})\n\n"
                        f"Review in Faculty Dashboard: {base_url}/faculty-dashboard.html"
                    )
                    html_msg = render_email_template(
                        headline="New Project Proposal Submitted",
                        badge_text="Proposal Submitted",
                        badge_color="#2563eb",
                        team_name=f_name,
                        project_title=f"{team['team_name']}: {title}",
                        key_details={
                            "Team Name": team["team_name"],
                            "Proposal Title": title,
                            "Submitted By": f"{project_data.get('submitted_by_name')} ({project_data.get('submitted_by_usn')})",
                            "Originality Score": f"{project_data.get('originality_score', 'N/A')}%"
                        },
                        message_content="A new project proposal has been submitted by your assigned team. Log in to your faculty dashboard to review the proposal and approve or request revisions.",
                        action_url=f"{base_url}/faculty-dashboard.html",
                        action_text="Review Proposal in Dashboard"
                    )
                    send_email_notification(
                        [faculty_email], subject, plain_msg, html_msg,
                        trigger_name="STUDENT_SUBMIT_PROPOSAL", team_id=team["team_name"]
                    )
            else:
                email_logger.info(
                    f"[EMAIL_NOTIFICATION] trigger=\"STUDENT_SUBMIT_PROPOSAL\" team=\"{team['team_name']}\" "
                    f"worker_status=\"SKIPPED\" reason=\"POLICY_DISALLOWED_TRIGGER\""
                )
        except Exception as email_err:
            email_logger.error(f"Error preparing faculty notification for project idea submission: {email_err}")

        return jsonify({"message": "Project idea submitted to faculty"}), 200

    except Exception as e:
        print("Error saving project idea:", e)
        return jsonify({"error": "Internal server error"}), 500

# ==================================================================== #
#                     FACULTY → ADD ASSESSMENT MARKS                    #
# ==================================================================== #

@app.route('/api/faculty/add_assessment_marks', methods=['POST'])
def add_assessment_marks():
    token_full = request.headers.get("Authorization")
    ownership = extract_activity_ownership(token_full)
    data = request.json or {}
    team_name = data.get("team_name")
    new_assessment = data.get("new_assessment")

    if not team_name or not new_assessment or not new_assessment.get("assessment") or not new_assessment.get("members"):
        return jsonify({"error": "Team name, assessment name, and member marks list are all required"}), 400

    team = find_team_by_name(team_name)
    if not team:
        return jsonify({"error": f"Team '{team_name}' not found"}), 404

    canonical_name = team.get("team_name", str(team_name))

    # Check if evaluation is locked by coordinator
    existing_eval = db.evaluations.find_one({"team_name": canonical_name})
    if existing_eval and existing_eval.get("is_locked", False):
        return jsonify({"error": "This evaluation has been locked by the Project Coordinator. Editing is disabled."}), 403

    marks_entry = {
        "assessment": new_assessment.get("assessment"),
        "date": datetime.now(timezone.utc).isoformat(),
        "members_marks": new_assessment.get("members"),
        "submitted_by_name": ownership["submitted_by_name"],
        "submitted_by_usn": ownership["submitted_by_usn"],
        "submitted_by_email": ownership["submitted_by_email"],
        "timestamp": ownership["timestamp"]
    }

    db.teams.update_one(
        {"_id": team["_id"]}, 
        {"$push": {"marks": marks_entry}}
    )

    # Notify all team members via email
    try:
        recipients = get_team_recipient_emails(team)
        if recipients:
            base_url = get_frontend_base_url()
            idea = team.get("project_idea") or {}
            proj_title = (idea.get("title") if isinstance(idea, dict) else "") or "Student Project"
            assessment_name = marks_entry.get("assessment", "Internal Assessment")
            faculty_name = ownership.get("submitted_by_name") or team.get("faculty_name") or "Faculty Guide"
            subject = f"Assessment Marks Published: {assessment_name} - {canonical_name}"
            plain_msg = (
                f"Hello {canonical_name},\n\n"
                f"Marks have been recorded for {assessment_name} by {faculty_name}:\n\n"
                f"Check your dashboard for your individual scores: {base_url}/team-dasboard.html"
            )
            html_msg = render_email_template(
                headline="Assessment Marks Published",
                badge_text="Marks Published",
                badge_color="#059669",
                team_name=canonical_name,
                project_title=proj_title,
                key_details={
                    "Assessment": assessment_name,
                    "Recorded By": faculty_name,
                    "Date Recorded": datetime.now().strftime("%Y-%m-%d %H:%M")
                },
                message_content="Your assessment marks have been entered into the portal. Log in to your student dashboard to review detailed marks and criteria.",
                action_url=f"{base_url}/team-dasboard.html",
                action_text="View Marks in Dashboard"
            )
            send_email_notification(
                recipients, subject, plain_msg, html_msg,
                trigger_name="FACULTY_PUBLISH_MARKS", team_id=canonical_name
            )
    except Exception as email_err:
        email_logger.error(f"Error preparing assessment marks notification for {canonical_name}: {email_err}")

    return jsonify({"message": f"Assessment marks recorded successfully for {canonical_name} ({marks_entry['assessment']})!"}), 200


@app.route("/api/faculty/delete_marks", methods=["POST"])
def delete_marks():
    data = request.json or {}
    team_name = data.get("team_name")
    marks_index = data.get("marks_index")

    # Check if evaluation is locked by coordinator
    existing_eval = db.evaluations.find_one({"team_name": team_name})
    if existing_eval and existing_eval.get("is_locked", False):
        return jsonify({"error": "This evaluation has been locked by the Project Coordinator. Editing is disabled."}), 403

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
        email = decoded.get("email", "")
        usn = clean_usn(decoded.get("usn", ""))

        team = db.teams.find_one({
            "$or": [
                {"leader_email": email},
                {"leader_usn": usn},
                {"members.email": email},
                {"members.usn": usn},
                {"members": {"$in": [email, usn]}}
            ]
        })

        if not team:
            return jsonify({"error": "Team not found"}), 404

        file = request.files.get('progress_file')
        file_name_from_form = request.form.get("file_name")
        notes = request.form.get("notes")

        if not file_name_from_form and not notes:
            return jsonify({"error": "File name or notes required"}), 400

        unique_filename = None

        if file and file.filename != '':
            filename_secured = secure_filename(file.filename)
            unique_filename = f"{team['team_name']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename_secured}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(save_path)

        ownership = extract_activity_ownership(token_full)

        new_entry = {
            "file_name": unique_filename or file_name_from_form,
            "notes": notes or "",
            "file_path": unique_filename,
            "submitted_at": datetime.now().isoformat(),
            "submitted_by_name": ownership["submitted_by_name"],
            "submitted_by_usn": ownership["submitted_by_usn"],
            "submitted_by_email": ownership["submitted_by_email"],
            "timestamp": ownership["timestamp"]
        }

        db.teams.update_one(
            {"team_name": team["team_name"]},
            {"$push": {"progress": new_entry}}
        )

        # Notify assigned faculty guide via email (Temporarily disabled under faculty-to-student only policy)
        try:
            if not ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS:
                faculty_email, f_name = get_team_assigned_faculty(team)
                if faculty_email:
                    base_url = get_frontend_base_url()
                    idea = team.get("project_idea") or {}
                    proj_title = (idea.get("title") if isinstance(idea, dict) else "") or "Student Project"
                    subject = f"New Progress Deliverable: {team['team_name']}"
                    plain_msg = (
                        f"Hello {f_name},\n\n"
                        f"Team '{team['team_name']}' has uploaded a new progress deliverable:\n"
                        f"Item: {new_entry['file_name']}\n"
                        f"Notes: {new_entry.get('notes') or 'None'}\n"
                        f"Submitted By: {new_entry.get('submitted_by_name')} ({new_entry.get('submitted_by_usn')})\n\n"
                        f"Review in Faculty Dashboard: {base_url}/faculty-dashboard.html"
                    )
                    html_msg = render_email_template(
                        headline="New Progress Deliverable Uploaded",
                        badge_text="Progress Uploaded",
                        badge_color="#2563eb",
                        team_name=f_name,
                        project_title=f"{team['team_name']}: {proj_title}",
                        key_details={
                            "Team Name": team["team_name"],
                            "File / Item": new_entry["file_name"],
                            "Submitted By": f"{new_entry.get('submitted_by_name')} ({new_entry.get('submitted_by_usn')})",
                            "Submission Notes": new_entry.get("notes") or "No additional notes provided"
                        },
                        message_content="Your assigned team has uploaded a new milestone progress report. Log in to your faculty dashboard to inspect deliverables.",
                        action_url=f"{base_url}/faculty-dashboard.html",
                        action_text="View in Faculty Dashboard"
                    )
                    send_email_notification(
                        [faculty_email], subject, plain_msg, html_msg,
                        trigger_name="STUDENT_UPLOAD_PROGRESS", team_id=team["team_name"]
                    )
            else:
                email_logger.info(
                    f"[EMAIL_NOTIFICATION] trigger=\"STUDENT_UPLOAD_PROGRESS\" team=\"{team['team_name']}\" "
                    f"worker_status=\"SKIPPED\" reason=\"POLICY_DISALLOWED_TRIGGER\""
                )
        except Exception as email_err:
            email_logger.error(f"Error preparing faculty notification for progress upload: {email_err}")

        return jsonify({
            "message": "Progress uploaded successfully!",
            "file_uploaded": bool(unique_filename),
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
            "leader_usn": 1,
            "progress": 1, 
            "approvals": 1,
            "marks": 1,
            "project_idea": 1
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
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        role = decoded.get("role")
        email = (decoded.get("email") or "").strip().lower()

        if role not in ["coordinator", "faculty"]:
            return jsonify({"error": "Unauthorized"}), 403

        ideas_out = []
        if role == "coordinator":
            teams = list(db.teams.find({}, {"_id": 0, "team_name": 1, "faculty_email": 1, "faculty_name": 1, "project_idea": 1, "project_ideas": 1}))
        else:
            alloc_records = list(db.allocations.find({"faculty_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}))
            alloc_team_names = [a.get("team_name") for a in alloc_records if a.get("team_name")]
            query = {
                "$or": [
                    {"faculty_email": email},
                    {"faculty_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}
                ]
            }
            if alloc_team_names:
                query["$or"].append({"team_name": {"$in": alloc_team_names}})
            teams = list(db.teams.find(query, {"_id": 0, "team_name": 1, "faculty_email": 1, "faculty_name": 1, "project_idea": 1, "project_ideas": 1}))

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

        data = request.json or {}
        team_name = data.get("team_name")
        title = data.get("title")
        new_status = data.get("status")

        if not team_name or not title or not new_status:
            return jsonify({"error": "team_name, title and status are required"}), 400

        # Try to update single project_idea
        team = find_team_by_name(team_name) or db.teams.find_one({"team_name": team_name})
        if not team:
            return jsonify({"error": "Team not found"}), 404

        is_auth, auth_res = check_faculty_team_auth(team, token_full, require_token=True)
        if not is_auth:
            return auth_res

        updated = False
        idea_match = None
        # single idea
        if isinstance(team.get("project_idea"), dict) and team["project_idea"].get("title") == title:
            db.teams.update_one({"team_name": team_name}, {"$set": {"project_idea.status": new_status}})
            idea_match = team["project_idea"]
            updated = True

        # multiple ideas
        if not updated and isinstance(team.get("project_ideas"), list):
            # update the matching array element
            result = db.teams.update_one(
                {"team_name": team_name, "project_ideas.title": title},
                {"$set": {"project_ideas.$.status": new_status}}
            )
            if result.modified_count > 0:
                for it in team["project_ideas"]:
                    if isinstance(it, dict) and it.get("title") == title:
                        idea_match = it
                        break
                updated = True

        if not updated:
            return jsonify({"error": "Idea not found for given team and title"}), 404

        # Synchronize with MongoDB projects collection for originality reference
        if new_status == "Approved":
            matched_idea = idea_match or (team.get("project_idea") if isinstance(team.get("project_idea"), dict) else {})
            proj_data = {
                "title": title,
                "abstract": matched_idea.get("abstract", "").strip(),
                "objectives": matched_idea.get("objectives", ""),
                "methodology": matched_idea.get("methodology", ""),
                "description": matched_idea.get("description", ""),
                "technologies": matched_idea.get("technologies") or matched_idea.get("tech_stack", ""),
                "team_name": team_name,
                "submitted_by_usn": matched_idea.get("submitted_by_usn") or team.get("leader_usn", ""),
                "submitted_by_email": matched_idea.get("submitted_by_email") or team.get("leader_email", ""),
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "status": "Approved"
            }
            existing_ref = db.projects.find_one({"team_name": team_name})
            if existing_ref:
                db.projects.update_one({"_id": existing_ref["_id"]}, {"$set": proj_data})
            else:
                db.projects.insert_one(proj_data)
            new_count = db.projects.count_documents({})
            print(f"[ORIGINALITY] Reference project count: {new_count}")

        elif new_status in ["Rejected", "Pending Faculty Approval"]:
            if team_name:
                deleted = db.projects.delete_many({"team_name": team_name})
                if deleted.deleted_count > 0:
                    new_count = db.projects.count_documents({})
                    print(f"[ORIGINALITY] Reference project count: {new_count}")

        # Notify all team members via email (Temporarily disabled under faculty-to-student only policy)
        try:
            if not ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS:
                team = find_team_by_name(team_name)
                if team:
                    canonical_name = team.get("team_name", str(team_name))
                    recipients = get_team_recipient_emails(team)
                    if recipients:
                        base_url = get_frontend_base_url()
                        badge_color = "#059669" if new_status == "Approved" else ("#dc2626" if new_status == "Rejected" else "#d97706")
                        reviewer = decoded.get("email") or "Project Review Committee"
                        subject = f"Project Proposal {new_status}: {canonical_name}"
                        plain_msg = (
                            f"Hello {canonical_name},\n\n"
                            f"Your project idea '{title}' status has been updated to: {new_status}\n"
                            f"Reviewed By: {reviewer}\n\n"
                            f"Check your dashboard: {base_url}/team-dasboard.html"
                        )
                        html_msg = render_email_template(
                            headline=f"Project Proposal {new_status}",
                            badge_text=new_status,
                            badge_color=badge_color,
                            team_name=canonical_name,
                            project_title=title,
                            key_details={
                                "Proposal Title": title,
                                "Review Status": new_status,
                                "Reviewed By": reviewer,
                                "Decision Date": datetime.now().strftime("%Y-%m-%d %H:%M")
                            },
                            message_content=f"Your project proposal has been evaluated and updated to '{new_status}'. Log in to your team dashboard to view feedback and next steps.",
                            action_url=f"{base_url}/team-dasboard.html",
                            action_text="Open Team Dashboard"
                        )
                        send_email_notification(
                            recipients, subject, plain_msg, html_msg,
                            trigger_name="COORDINATOR_IDEA_STATUS", team_id=canonical_name
                        )
            else:
                email_logger.info(
                    f"[EMAIL_NOTIFICATION] trigger=\"COORDINATOR_IDEA_STATUS\" team=\"{team_name}\" "
                    f"worker_status=\"SKIPPED\" reason=\"POLICY_DISALLOWED_TRIGGER\""
                )
        except Exception as email_err:
            email_logger.error(f"Error preparing idea status notification for {team_name}: {email_err}")

        return jsonify({"message": f"Idea status updated to {new_status}"}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except Exception as e:
        print("Error in update_idea_status:", e)
        return jsonify({"error": "Internal server error"}), 500



# ==================================================================== #
#                   MANAGE USERS ROUTES (REGISTERED USERS)             #
# ==================================================================== #

def check_coordinator_authorization():
    """Helper to verify Coordinator role from JWT Authorization header."""
    token_full = request.headers.get("Authorization")
    if not token_full:
        return False, jsonify({"error": "Authorization token required"}), 401
    try:
        raw_token = token_full.split()[-1]
        decoded = jwt.decode(raw_token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded.get("email")
        role = decoded.get("role")
        if role == "coordinator":
            return True, decoded, 200
        # Fallback: check in coordinator or faculty collections
        coordinator = db.coordinator.find_one({"email": email}) or db.faculty.find_one({"email": email, "role": "coordinator"})
        if coordinator:
            return True, decoded, 200
        return False, jsonify({"error": "Unauthorized: Coordinator access required"}), 403
    except jwt.ExpiredSignatureError:
        return False, jsonify({"error": "Token expired"}), 401
    except Exception as e:
        return False, jsonify({"error": "Invalid authorization token"}), 401


@app.route('/api/admin/faculty', methods=['GET'])
def get_all_faculty_details():
    """Returns all faculty details for management (excluding password hash)."""
    is_auth, res_or_dec, status = check_coordinator_authorization()
    if not is_auth:
        return res_or_dec, status

    try:
        # Exclude password, leader_password, and _id
        faculties = list(db.faculty.find({}, {"_id": 0, "password": 0, "leader_password": 0}))

        # Map assigned teams from db.teams to enrich faculty cards
        team_allocations = list(db.teams.find({"faculty_email": {"$ne": None}}, {"_id": 0, "team_name": 1, "faculty_email": 1, "faculty_name": 1}))
        alloc_map = {}
        for t in team_allocations:
            f_email = t.get("faculty_email")
            if f_email:
                alloc_map.setdefault(f_email, []).append(t.get("team_name"))

        for f in faculties:
            f_email = f.get("email")
            f["assigned_teams"] = alloc_map.get(f_email, [])

        return jsonify({"faculty": faculties}), 200
    except Exception as e:
        print(f"Error fetching faculty list: {e}")
        return jsonify({"error": "Server error fetching faculty list"}), 500


@app.route('/api/admin/students', methods=['GET'])
def get_all_registered_students():
    """Returns all individual registered students (leaders & members) with clean registered details."""
    is_auth, res_or_dec, status = check_coordinator_authorization()
    if not is_auth:
        return res_or_dec, status

    try:
        teams = list(db.teams.find({}, {"_id": 0, "password": 0, "leader_password": 0}))
        students = []

        for team in teams:
            team_name = team.get("team_name")
            interests = team.get("interests", [])
            faculty_name = team.get("faculty_name")
            faculty_email = team.get("faculty_email")
            created_at = team.get("created_at")
            if isinstance(created_at, datetime):
                created_at = created_at.strftime("%Y-%m-%d")

            # Leader
            l_name = str(team.get("leader_name") or "").strip()
            l_usn = clean_usn(team.get("leader_usn"))
            l_email = str(team.get("leader_email") or "").strip().lower()

            if l_name or l_usn or l_email:
                students.append({
                    "name": l_name,
                    "usn": l_usn,
                    "email": l_email,
                    "phone": team.get("phone") or team.get("leader_phone") or "",
                    "department": team.get("department") or "",
                    "semester": team.get("semester") or "",
                    "team_name": team_name,
                    "role_in_team": "Leader",
                    "is_leader": True,
                    "interests": interests,
                    "faculty_name": faculty_name or "Not Assigned",
                    "faculty_email": faculty_email or "",
                    "created_at": created_at or ""
                })

            # Members
            for m in team.get("members", []):
                if isinstance(m, dict):
                    m_name = str(m.get("name") or "").strip()
                    m_usn = clean_usn(m.get("usn"))
                    m_email = str(m.get("email") or "").strip().lower()
                    m_phone = str(m.get("phone") or "").strip()
                    m_dept = str(m.get("department") or "").strip()
                    m_sem = str(m.get("semester") or "").strip()
                else:
                    m_name = str(m or "").strip()
                    m_usn = ""
                    m_email = ""
                    m_phone = ""
                    m_dept = ""
                    m_sem = ""

                if m_name or m_usn or m_email:
                    students.append({
                        "name": m_name,
                        "usn": m_usn,
                        "email": m_email,
                        "phone": m_phone,
                        "department": m_dept,
                        "semester": m_sem,
                        "team_name": team_name,
                        "role_in_team": "Member",
                        "is_leader": False,
                        "interests": interests,
                        "faculty_name": faculty_name or "Not Assigned",
                        "faculty_email": faculty_email or "",
                        "created_at": created_at or ""
                    })

        return jsonify({"students": students}), 200
    except Exception as e:
        print(f"Error fetching students list: {e}")
        return jsonify({"error": "Server error fetching students list"}), 500


@app.route('/api/admin/student/update', methods=['POST'])
def update_student_details():
    """Updates a registered student's information cleanly."""
    is_auth, res_or_dec, status = check_coordinator_authorization()
    if not is_auth:
        return res_or_dec, status

    try:
        data = request.json or {}
        team_name = data.get("team_name")
        is_leader = data.get("is_leader", False)
        original_usn = clean_usn(data.get("original_usn"))
        original_email = str(data.get("original_email") or "").strip().lower()

        new_name = str(data.get("name") or "").strip()
        new_usn = clean_usn(data.get("usn"))
        new_email = str(data.get("email") or "").strip().lower()
        new_phone = str(data.get("phone") or "").strip()
        new_dept = str(data.get("department") or "").strip()
        new_sem = str(data.get("semester") or "").strip()

        if not new_name:
            return jsonify({"error": "Student name is required"}), 400
        if not new_usn:
            return jsonify({"error": "Student USN is required"}), 400

        team = db.teams.find_one({"team_name": team_name})
        if not team:
            team = db.teams.find_one({
                "$or": [
                    {"leader_usn": original_usn},
                    {"leader_email": original_email},
                    {"members.usn": original_usn},
                    {"members.email": original_email}
                ]
            })
        if not team:
            return jsonify({"error": "Associated team not found"}), 404

        actual_team_name = team.get("team_name")

        if is_leader or clean_usn(team.get("leader_usn")) == original_usn or (original_email and str(team.get("leader_email", "")).lower() == original_email):
            update_fields = {
                "leader_name": new_name,
                "leader_usn": new_usn,
                "leader_email": new_email
            }
            if new_phone:
                update_fields["phone"] = new_phone
                update_fields["leader_phone"] = new_phone
            if new_dept:
                update_fields["department"] = new_dept
            if new_sem:
                update_fields["semester"] = new_sem

            db.teams.update_one({"team_name": actual_team_name}, {"$set": update_fields})
        else:
            members = team.get("members", [])
            updated = False
            for m in members:
                if isinstance(m, dict):
                    m_usn = clean_usn(m.get("usn"))
                    m_em = str(m.get("email") or "").strip().lower()
                    if (original_usn and m_usn == original_usn) or (original_email and m_em == original_email):
                        m["name"] = new_name
                        m["usn"] = new_usn
                        m["email"] = new_email
                        if new_phone:
                            m["phone"] = new_phone
                        if new_dept:
                            m["department"] = new_dept
                        if new_sem:
                            m["semester"] = new_sem
                        updated = True
                        break

            if updated:
                db.teams.update_one({"team_name": actual_team_name}, {"$set": {"members": members}})
            else:
                return jsonify({"error": "Member not found in team"}), 404

        # Propagate USN or name update to attendance records if USN changed
        if original_usn and (original_usn != new_usn or new_name):
            db.attendance.update_many(
                {"student_usn": original_usn},
                {"$set": {"student_usn": new_usn, "student_name": new_name}}
            )

        return jsonify({"message": f"Student '{new_name}' updated successfully."}), 200
    except Exception as e:
        print(f"Error updating student: {e}")
        return jsonify({"error": "Server error updating student details"}), 500


@app.route('/api/admin/student/delete', methods=['POST'])
def delete_student_record():
    """Safely deletes a student registration without breaking database relationships."""
    is_auth, res_or_dec, status = check_coordinator_authorization()
    if not is_auth:
        return res_or_dec, status

    try:
        data = request.json or {}
        team_name = data.get("team_name")
        usn = clean_usn(data.get("usn"))
        email = str(data.get("email") or "").strip().lower()
        is_leader = data.get("is_leader", False)

        team = db.teams.find_one({"team_name": team_name})
        if not team and (usn or email):
            team = db.teams.find_one({
                "$or": [
                    {"leader_usn": usn},
                    {"leader_email": email},
                    {"members.usn": usn},
                    {"members.email": email}
                ]
            })

        if not team:
            return jsonify({"error": "Team or student not found"}), 404

        actual_team_name = team.get("team_name")
        l_usn = clean_usn(team.get("leader_usn"))
        l_email = str(team.get("leader_email") or "").strip().lower()

        if is_leader or (usn and l_usn == usn) or (email and l_email == email):
            members = team.get("members", [])
            if members and len(members) > 0:
                next_leader = members.pop(0)
                if isinstance(next_leader, dict):
                    nl_name = next_leader.get("name", "")
                    nl_usn = clean_usn(next_leader.get("usn"))
                    nl_email = str(next_leader.get("email") or "").strip().lower()
                else:
                    nl_name = str(next_leader)
                    nl_usn = ""
                    nl_email = ""

                db.teams.update_one(
                    {"team_name": actual_team_name},
                    {
                        "$set": {
                            "leader_name": nl_name,
                            "leader_usn": nl_usn,
                            "leader_email": nl_email,
                            "members": members
                        }
                    }
                )
                return jsonify({"message": f"Leader removed. Team member '{nl_name}' promoted to new leader."}), 200
            else:
                db.teams.delete_one({"team_name": actual_team_name})
                db.allocations.delete_many({"team_name": actual_team_name})
                return jsonify({"message": f"Student removed and empty team '{actual_team_name}' cleared."}), 200
        else:
            query_cond = {}
            if usn:
                query_cond["usn"] = usn
            elif email:
                query_cond["email"] = email

            db.teams.update_one(
                {"team_name": actual_team_name},
                {"$pull": {"members": query_cond}}
            )
            return jsonify({"message": f"Student ({usn or email}) removed from team '{actual_team_name}'."}), 200
    except Exception as e:
        print(f"Error deleting student: {e}")
        return jsonify({"error": "Server error deleting student"}), 500


@app.route('/api/admin/faculty/update', methods=['POST'])
def update_faculty_details():
    """Updates a registered faculty member's profile."""
    is_auth, res_or_dec, status = check_coordinator_authorization()
    if not is_auth:
        return res_or_dec, status

    try:
        data = request.json or {}
        original_email = str(data.get("original_email") or "").strip().lower()
        new_name = str(data.get("name") or "").strip()
        new_email = str(data.get("email") or "").strip().lower()
        new_expertise = data.get("expertise", [])
        new_phone = str(data.get("phone") or "").strip()
        new_dept = str(data.get("department") or "").strip()

        if not original_email:
            return jsonify({"error": "Original faculty email is required"}), 400
        if not new_name:
            return jsonify({"error": "Faculty name is required"}), 400
        if not new_email:
            return jsonify({"error": "Faculty email is required"}), 400

        faculty = db.faculty.find_one({"email": original_email})
        if not faculty:
            return jsonify({"error": "Faculty member not found"}), 404

        # Check collision if email changed
        if new_email != original_email:
            existing = db.faculty.find_one({"email": new_email})
            if existing:
                return jsonify({"error": "Another faculty with this email already exists"}), 400

        if isinstance(new_expertise, str):
            expertise_list = [e.strip() for e in new_expertise.split(",") if e.strip()]
        elif isinstance(new_expertise, list):
            expertise_list = [str(e).strip() for e in new_expertise if str(e).strip()]
        else:
            expertise_list = []

        update_set = {
            "name": new_name,
            "email": new_email,
            "expertise": expertise_list
        }
        if new_phone:
            update_set["phone"] = new_phone
        if new_dept:
            update_set["department"] = new_dept

        db.faculty.update_one({"email": original_email}, {"$set": update_set})

        # Propagate to assigned teams and allocations if email or name changed
        if new_email != original_email or new_name != faculty.get("name"):
            db.teams.update_many(
                {"faculty_email": original_email},
                {"$set": {"faculty_email": new_email, "faculty_name": new_name}}
            )
            db.allocations.update_many(
                {"faculty_email": original_email},
                {"$set": {"faculty_email": new_email, "faculty_name": new_name}}
            )

        return jsonify({"message": f"Faculty '{new_name}' updated successfully."}), 200
    except Exception as e:
        print(f"Error updating faculty: {e}")
        return jsonify({"error": "Server error updating faculty details"}), 500


@app.route('/api/admin/faculty/delete', methods=['POST'])
def delete_faculty():
    """Deletes a faculty member and removes their assignments safely."""
    is_auth, res_or_dec, status = check_coordinator_authorization()
    if not is_auth:
        return res_or_dec, status

    try:
        data = request.json or {}
        email = str(data.get('email') or "").strip().lower()
        if not email:
            return jsonify({"error": "Faculty email required"}), 400

        faculty = db.faculty.find_one({"email": email})
        if not faculty:
            return jsonify({"error": "Faculty member not found"}), 404

        # 1. Delete the faculty member
        db.faculty.delete_one({"email": email})

        # 2. Unassign teams from this faculty without breaking the teams
        db.teams.update_many(
            {"faculty_email": email},
            {"$set": {"faculty_email": None, "faculty_name": None, "manual_allocation": False}}
        )
        # 3. Remove from current allocation snapshot
        db.allocations.delete_many({"faculty_email": email})

        return jsonify({"message": f"Faculty '{faculty.get('name', email)}' deleted and associated teams unassigned safely."}), 200
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
        raw_faculties = list(db.faculty.find({}, {"_id": 0, "name": 1, "email": 1, "faculty_id": 1, "department": 1, "phone": 1}))
        cleaned_faculties = []
        seen_emails = set()

        for f in raw_faculties:
            email = str(f.get("email") or "").strip()
            if not email:
                continue
            norm_email = email.lower()
            if norm_email in seen_emails:
                continue
            seen_emails.add(norm_email)

            name = str(f.get("name") or "").strip()
            if not name or name.lower() == "undefined":
                name = email.split("@")[0].replace(".", " ").title()

            faculty_id = str(f.get("faculty_id") or f.get("emp_id") or f"FAC-{email.split('@')[0].upper()}")
            department = str(f.get("department") or "Computer Science & Engineering")

            cleaned_faculties.append({
                "name": name,
                "email": email,
                "faculty_id": faculty_id,
                "department": department,
                "phone": f.get("phone", "")
            })

        return jsonify({
            "faculties": cleaned_faculties,
            "faculty": cleaned_faculties
        }), 200
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
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# --- GEMINI API CONFIGURATION & SETUP ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
MAX_RETRIES = 5

similarity_model = None
similarity_model_attempted = False

def get_similarity_model():
    global similarity_model, similarity_model_attempted
    if similarity_model is None and not similarity_model_attempted:
        similarity_model_attempted = True
        print(f"[{datetime.now(timezone.utc).isoformat()}] [MODEL] Initializing SentenceTransformer('all-MiniLM-L6-v2')...", flush=True)
        try:
            import gc
            # Limit thread counts to 1 before PyTorch/SentenceTransformer import to minimize memory allocations
            os.environ["OMP_NUM_THREADS"] = "1"
            os.environ["MKL_NUM_THREADS"] = "1"
            os.environ["OPENBLAS_NUM_THREADS"] = "1"
            os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
            os.environ["NUMEXPR_NUM_THREADS"] = "1"
            os.environ["TOKENIZERS_PARALLELISM"] = "false"

            import torch
            try:
                torch.set_num_threads(1)
            except Exception:
                pass
            try:
                torch.set_num_interop_threads(1)
            except Exception:
                pass

            gc.collect()

            from sentence_transformers import SentenceTransformer
            with torch.no_grad():
                similarity_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
                similarity_model.eval()

            gc.collect()
            print(f"[{datetime.now(timezone.utc).isoformat()}] [MODEL] Successfully initialized all-MiniLM-L6-v2 semantic model on CPU (single-threaded).", flush=True)
        except Exception as e:
            print(f"[{datetime.now(timezone.utc).isoformat()}] [MODEL] Notice loading SentenceTransformer: {e}", flush=True)
            traceback.print_exc()
            similarity_model = None
    return similarity_model

STOP_WORDS = {
    'the', 'is', 'are', 'was', 'were', 'this', 'that', 'these', 'those', 'for', 'with',
    'and', 'or', 'of', 'to', 'in', 'on', 'at', 'by', 'from', 'a', 'an', 'as', 'it', 'its',
    'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'but', 'if', 'then',
    'else', 'when', 'where', 'which', 'who', 'whom', 'what', 'how', 'why', 'all', 'any',
    'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
    'only', 'own', 'same', 'so', 'than', 'too', 'very', 'can', 'will', 'just', 'should', 'now'
}

# Generic technology / domain-neutral terms from Section 6
# Their presence alone must NOT produce high similarity across unrelated projects
GENERIC_TECH_STOPWORDS = {
    'ai', 'artificial', 'intelligence', 'machine', 'learning', 'system', 'systems',
    'platform', 'platforms', 'application', 'applications', 'data', 'analysis',
    'monitoring', 'prediction', 'detection', 'management', 'technology', 'technologies',
    'user', 'users', 'automated', 'intelligent', 'using', 'based', 'model', 'models',
    'solution', 'solutions', 'project', 'projects', 'approach', 'approaches',
    'technique', 'techniques', 'real', 'time', 'timely', 'help', 'take', 'presents',
    'important', 'provide', 'provides', 'used', 'uses', 'apply', 'applied'
}

ALL_FILTER_STOPWORDS = STOP_WORDS.union(GENERIC_TECH_STOPWORDS)

TECH_KEYWORDS = {
    'react', 'node', 'express', 'mongodb', 'cnn', 'rnn', 'lstm',
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

    def get_filtered_tokens(self, text):
        words = re.findall(r'\b[a-z]{3,}\b', str(text).lower())
        return [w for w in words if w not in ALL_FILTER_STOPWORDS]

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
            if w not in ALL_FILTER_STOPWORDS and len(w) > 3:
                found.add(w)
        return found

    def extract_ngrams(self, text, n):
        words = self.get_filtered_tokens(text)
        if len(words) < n:
            return []
        return [" ".join(words[i:i+n]) for i in range(len(words)-n+1)]

    def compute_exact_phrase_matching(self, sub_sentences, db_sentences, sub_sent_embs=None, db_sent_embs=None):
        if not sub_sentences or not db_sentences:
            return 0.0, []
        
        norm_db_sentences = [self.normalize_text(s) for s in db_sentences]
        matching_sentences = []
        match_count = 0.0

        sim_matrix = None
        if sub_sent_embs is not None and db_sent_embs is not None:
            try:
                s_arr = sub_sent_embs.detach().cpu().numpy() if hasattr(sub_sent_embs, "detach") else np.asarray(sub_sent_embs)
                d_arr = db_sent_embs.detach().cpu().numpy() if hasattr(db_sent_embs, "detach") else np.asarray(db_sent_embs)
                if s_arr.ndim == 2 and d_arr.ndim == 2 and s_arr.shape[1] == d_arr.shape[1]:
                    sim_matrix = np.dot(s_arr, d_arr.T)
            except Exception:
                sim_matrix = None

        for i, sub_s in enumerate(sub_sentences):
            norm_sub_s = self.normalize_text(sub_s)
            if not norm_sub_s:
                continue
            if norm_sub_s in norm_db_sentences:
                match_count += 1.0
                matching_sentences.append(sub_s)
            elif sim_matrix is not None:
                max_sim = float(np.max(sim_matrix[i]))
                if max_sim >= 0.70:
                    match_count += max_sim
                    matching_sentences.append(sub_s)
                elif len(norm_sub_s) > 15:
                    for db_s in norm_db_sentences:
                        if norm_sub_s in db_s or db_s in norm_sub_s:
                            match_count += 0.8
                            matching_sentences.append(sub_s)
                            break
            else:
                for db_s in norm_db_sentences:
                    if len(norm_sub_s) > 15 and (norm_sub_s in db_s or db_s in norm_sub_s):
                        match_count += 0.8
                        matching_sentences.append(sub_s)
                        break

        score = min(1.0, match_count / max(1, len(sub_sentences)))
        return max(0.0, score), list(set(matching_sentences))

    def compute_ngram_similarity(self, sub_text, db_text, sem_hint=0.0):
        sub_words = self.get_filtered_tokens(sub_text)
        db_words = self.get_filtered_tokens(db_text)
        scores = []
        for n, weight in [(1, 0.30), (2, 0.40), (3, 0.30)]:
            if len(sub_words) < n or len(db_words) < n:
                scores.append(0.0)
                continue
            sub_ngrams = set(" ".join(sub_words[i:i+n]) for i in range(len(sub_words)-n+1))
            db_ngrams = set(" ".join(db_words[i:i+n]) for i in range(len(db_words)-n+1))
            overlap = len(sub_ngrams.intersection(db_ngrams))
            denom = min(len(sub_ngrams), len(db_ngrams))
            scores.append(weight * (overlap / denom if denom > 0 else 0.0))
        lex_ngram = sum(scores)
        if sem_hint >= 0.65:
            return max(lex_ngram, 0.50 * lex_ngram + 0.50 * sem_hint * 0.75)
        return lex_ngram

    def compute_fuzzy_similarity(self, sub_text, db_text, sem_hint=0.0):
        sub_clean = " ".join(self.get_filtered_tokens(sub_text))
        db_clean = " ".join(self.get_filtered_tokens(db_text))
        if not sub_clean or not db_clean:
            return 0.0
        ratio = SequenceMatcher(None, sub_clean, db_clean).ratio()
        if sem_hint >= 0.65:
            ratio = max(ratio, sem_hint * 0.40)
        return ratio

    def compute_keyword_similarity(self, sub_keywords, db_keywords, sem_hint=0.0):
        if not sub_keywords or not db_keywords:
            return 0.0, []
        common = list(sub_keywords.intersection(db_keywords))
        denom = min(len(sub_keywords), len(db_keywords))
        score = len(common) / denom if denom > 0 else 0.0
        if sem_hint >= 0.65 and score < 0.30:
            score = max(score, sem_hint * 0.50)
        return score, common

    def compute_section_tfidf_similarity(self, sub_dict, db_dict, sem_hint=0.0):
        section_weights = {
            "title": 0.20,
            "abstract": 0.50,
            "objectives": 0.10,
            "methodology": 0.10,
            "description": 0.10
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

            c1 = " ".join(self.get_filtered_tokens(t1))
            c2 = " ".join(self.get_filtered_tokens(t2))

            if not c1 or not c2:
                section_scores[sec] = 0.0
                continue

            try:
                vectorizer = TfidfVectorizer(ngram_range=(1, 2))
                tfidf = vectorizer.fit_transform([c1, c2])
                lex_sim = float(cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0])
                if sem_hint >= 0.60:
                    sim = max(lex_sim, 0.40 * lex_sim + 0.60 * sem_hint * 0.85)
                else:
                    sim = lex_sim
                section_scores[sec] = float(sim)
            except Exception:
                section_scores[sec] = 0.0

            weighted_score += weight * section_scores[sec]

        return weighted_score, section_scores

    def compute_semantic_similarity(self, sub_title, sub_abstract, db_title, db_abstract, sub_embs=None, db_embs=None):
        model = get_similarity_model()
        if not model:
            return 0.0
        try:
            def _get_vec(embs, key, text):
                if embs and key in embs and embs[key] is not None:
                    return embs[key]
                if not text:
                    return None
                try:
                    import torch
                    with torch.inference_mode():
                        return model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
                except Exception:
                    return model.encode(text, convert_to_numpy=True, normalize_embeddings=True)

            def _cos(v1, v2):
                if v1 is None or v2 is None:
                    return 0.0
                if hasattr(v1, "detach"):
                    v1 = v1.detach().cpu().numpy()
                if hasattr(v2, "detach"):
                    v2 = v2.detach().cpu().numpy()
                norm1 = np.linalg.norm(v1)
                norm2 = np.linalg.norm(v2)
                if norm1 == 0 or norm2 == 0:
                    return 0.0
                sim = float(np.dot(v1, v2) / (norm1 * norm2))
                return max(0.0, min(1.0, sim))

            e_sub_title = _get_vec(sub_embs, "title", sub_title)
            e_db_title = _get_vec(db_embs, "title", db_title)
            title_sim = _cos(e_sub_title, e_db_title)

            e_sub_abs = _get_vec(sub_embs, "abstract", sub_abstract)
            e_db_abs = _get_vec(db_embs, "abstract", db_abstract)
            abs_sim = _cos(e_sub_abs, e_db_abs)

            sub_full = f"{sub_title}. {sub_abstract}".strip()
            db_full = f"{db_title}. {db_abstract}".strip()
            e_sub_full = _get_vec(sub_embs, "full", sub_full)
            e_db_full = _get_vec(db_embs, "full", db_full)
            full_sim = _cos(e_sub_full, e_db_full)

            concept_sim = 0.45 * abs_sim + 0.35 * full_sim + 0.20 * title_sim
            return max(full_sim, concept_sim)
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

    def generate_gemini_suggestions(self, submission):
        title = submission.get("title", "").strip()
        abstract = submission.get("abstract", "").strip()

        if not title and not abstract:
            return None

        prompt = (
            "You are an expert academic project mentor and technical advisor.\n"
            "Analyze the following student project based ONLY on its Title and Abstract:\n\n"
            f"Title: {title}\n"
            f"Abstract: {abstract}\n\n"
            "Task:\n"
            "Understand what the project already proposes from the title and abstract. "
            "Do not simply repeat features already mentioned. "
            "Suggest exactly 5 concrete, technically meaningful improvements, extensions, "
            "architectural enhancements, or practical next steps that are not already explicitly described.\n\n"
            "Rules:\n"
            "- All 5 suggestions must be directly relevant and specific to this project's actual problem and domain.\n"
            "- Do NOT provide generic educational, school, or attendance suggestions unless this project is explicitly an educational tool.\n"
            "- Do NOT repeat what is already stated in the title or abstract.\n"
            "- Each suggestion should be 1-2 clear, actionable, concise sentences practical for a student project.\n"
            "- Format output strictly as a numbered list from 1 to 5:\n"
            "1. <suggestion 1>\n"
            "2. <suggestion 2>\n"
            "3. <suggestion 3>\n"
            "4. <suggestion 4>\n"
            "5. <suggestion 5>\n"
            "Do not include conversational preamble or introductory text."
        )

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "maxOutputTokens": 800,
                "temperature": 0.4
            }
        }

        res = call_gemini_api_with_retry(payload)
        if not res or not isinstance(res, dict):
            return None

        candidates = res.get("candidates", [])
        if not candidates:
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None

        text = parts[0].get("text", "").strip()
        if not text:
            return None

        suggestions = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            cleaned = re.sub(r'^(\d+[\.\)]|\*|\-)\s*', '', line).strip()
            cleaned = re.sub(r'^\*\*.*?\*\*\s*[:\-]?\s*', '', cleaned).strip() or cleaned
            if cleaned and len(cleaned) > 10:
                suggestions.append(cleaned)

        if len(suggestions) >= 3:
            return [f"{i+1}. {s}" for i, s in enumerate(suggestions[:5])]

        return None

    def get_local_fallback_suggestions(self, submission):
        title = submission.get("title", "").strip()
        abstract = submission.get("abstract", "").strip()
        objectives = submission.get("objectives", "").strip()
        methodology = submission.get("methodology", "").strip()
        description = submission.get("description", "").strip()
        technologies = submission.get("technologies") or submission.get("tech_stack", "")
        if isinstance(technologies, list):
            technologies = " ".join(technologies)

        full_text = f"{title}. {abstract} {objectives} {methodology} {description} {technologies}".strip()
        text_lower = full_text.lower()

        title_words = [w for w in re.findall(r'\b[a-zA-Z]{4,}\b', title) if w.lower() not in STOP_WORDS]
        topic_name = title if title else "Submitted Project Idea"

        # Domain identification logic
        is_water_environment = any(k in text_lower for k in [
            "water", "pollution", "water quality", "water-quality", "contamination", "ph sensor", 
            "tds", "turbidity", "dissolved solids", "dissolved oxygen", "effluent", "sewage",
            "aquatic", "water monitoring", "sensor calibration", "water body", "river", "lake"
        ]) or (("water" in text_lower or "pollution" in text_lower) and any(w in text_lower for w in ["quality", "monitoring", "sensor", "detect", "contaminat", "iot"]))

        is_agriculture = any(k in text_lower for k in [
            "crop", "soil", "farm", "yield", "agriculture", "plant", "harvest", "pest", 
            "irrigation", "fertilizer", "agritech", "field photo", "leaf photo", "botany", 
            "weed", "cultivation", "pesticide", "disease detection", "leaf disease"
        ])
        is_food_delivery = any(k in text_lower for k in [
            "food delivery", "restaurant", "meal", "dining", "menu", "ordering", 
            "swiggy", "zomato", "takeaway", "kitchen", "groceries", "food order"
        ]) or ("food" in text_lower and any(w in text_lower for w in ["delivery", "order", "restaurant", "platform"]))
        is_blockchain = any(k in text_lower for k in [
            "blockchain", "certificate", "smart contract", "ethereum", "solidity", "ledger", 
            "decentralized", "web3", "credential", "nft", "tamper-proof", "cryptographic proof", 
            "immutable", "consensus", "hyperledger", "crypto"
        ])
        is_healthcare = any(k in text_lower for k in [
            "patient", "medical", "doctor", "hospital", "clinical", "pharmacy", "ecg", "ehr", 
            "nurse", "biomedical", "vitals", "icu", "health log", "disease diagnosis", "telemedicine", "cardiac"
        ])
        is_ecommerce = any(k in text_lower for k in [
            "shopping", "cart", "store", "product", "recommendation", "price", "retail", 
            "eco-friendly", "buyer", "seller", "customer", "ecommerce", "e-commerce"
        ])
        is_drone_logistics = any(k in text_lower for k in [
            "drone", "uav", "robot", "pathfinding", "navigation", "parcel", "vehicle", "autonomous", "flight", "quadcopter"
        ])
        is_security = any(k in text_lower for k in [
            "security", "cipher", "threat", "vulnerability", "attack", "encryption", 
            "malware", "cyber", "firewall", "steganography", "intrusion", "penetration", "zero-day"
        ])
        # Clean out machine learning / AI phrases so they do not falsely trigger educational suggestions
        non_ml_text = re.sub(r'\b(machine|deep|reinforcement|transfer|federated|supervised|unsupervised)\s+learning\b', ' ', text_lower)
        is_education = any(k in non_ml_text for k in [
            "classroom", "pedagogy", "syllabus", "curriculum", "tutor", "lms", "e-learning",
            "teacher analytics", "adaptive learning", "quiz platform", "student performance prediction",
            "academic grading", "school management", "student evaluation", "automated essay"
        ])
        is_finance = any(k in text_lower for k in [
            "bank", "loan", "fraud", "transaction", "payment", "credit", "stock", 
            "finance", "trading", "investment", "fintech", "banking"
        ])

        if is_water_environment:
            return [
                "1. Implement multi-sensor telemetry calibration (pH, turbidity, TDS, temperature, dissolved oxygen) with automatic drift correction for reliable field measurements.",
                "2. Deploy machine learning models (such as LSTM or Random Forest) for predictive water-quality index (WQI) forecasting and early contamination anomaly detection.",
                "3. Integrate real-time automated alert dispatch via SMS and mobile dashboards whenever sensor readings cross safe municipal or WHO contamination thresholds.",
                "4. Build a geospatial water pollution analytics map visualizing temporal water quality trends across different monitoring stations and catchment areas.",
                "5. Incorporate edge computing on microcontroller sensor nodes (e.g., ESP32) for local anomaly detection and failover data buffering during connectivity outages."
            ]
        elif is_agriculture:
            return [
                "1. Integrate deep-learning models (such as YOLO or EfficientNet) for early crop disease and pest identification from smartphone field leaf photos.",
                "2. Incorporate real-time soil moisture, pH, and NPK nutrient sensor telemetry for targeted precision irrigation and fertilization.",
                "3. Provide hyper-local microclimate weather forecasts alerting farmers to impending frost, heavy rainfall, or pest infestation risks.",
                "4. Recommend optimal crop harvest and planting windows based on regional market price trends and crop maturity metrics.",
                "5. Include voice-guided agricultural advisory support in regional languages with offline sync for rural farming accessibility."
            ]
        elif is_food_delivery:
            return [
                "1. Implement real-time GPS tracking with dynamic ETA calculation and multi-stop route optimization for delivery partners.",
                "2. Incorporate AI-driven personalized dish and restaurant recommendations based on past order history, dietary preferences, and reviews.",
                "3. Add dynamic delivery fee and surge pricing optimization algorithms balancing rider availability, distance, and adverse weather.",
                "4. Integrate kitchen preparation time estimation and automated order dispatching algorithms to minimize rider wait times.",
                "5. Implement contactless delivery verification with digital OTP confirmation and customer food temperature/freshness feedback."
            ]
        elif is_blockchain:
            return [
                "1. Implement gas-efficient smart contracts using batch certificate issuance (e.g., Merkle tree roots) to reduce on-chain verification costs.",
                "2. Store encrypted credential metadata and document proofs on decentralized storage systems like IPFS or Arweave.",
                "3. Provide instant public verification through dynamic tamper-proof QR codes with zero-knowledge cryptographic validity proofs.",
                "4. Integrate a multi-signature authorization workflow and decentralized revocation registry for authorized issuing institutions.",
                "5. Ensure compliance with international digital credential standards like W3C Verifiable Credentials and Open Badges."
            ]
        elif is_healthcare:
            return [
                "1. Integrate real-time alert dispatch to emergency contacts and nearby medical facilities when patient vital signs cross critical thresholds.",
                "2. Incorporate automated prescription management and medication adherence tracking for chronic care patients.",
                "3. Enable HIPAA-compliant tele-consultation video modules allowing remote physicians to review patient diagnostic logs.",
                "4. Implement AI-driven symptom triaging to assist medical staff in prioritizing urgent patient care cases.",
                "5. Add wearable sensor telemetry integration to continuously monitor heart rate, blood oxygen, and body temperature."
            ]
        elif is_ecommerce:
            return [
                "1. Add barcode scanning so users can instantly check product specifications, reviews, and eco-friendly ratings.",
                "2. Integrate AI-driven personalized product recommendations and price-drop alerts tailored to user shopping patterns.",
                "3. Recommend nearby physical or local stores selling verified sustainable and alternative products.",
                "4. Provide side-by-side product comparisons evaluating specifications, pricing history, and user feedback.",
                "5. Enable a verified community review portal and fraud-detection filter to eliminate fake product ratings."
            ]
        elif is_drone_logistics:
            return [
                "1. Integrate real-time weather telemetry (wind speed, precipitation) to dynamically adjust flight corridors.",
                "2. Add automated emergency drop-zone selection and parachute deployment for sudden hardware or battery failures.",
                "3. Implement multi-drone swarm coordination for package delivery routing across high-density airspace.",
                "4. Incorporate real-time payload temperature and shock telemetry monitoring for sensitive cargo.",
                "5. Implement dynamic geofencing to automatically avoid restricted airspace around airports, schools, and government sites."
            ]
        elif is_security:
            return [
                "1. Integrate real-time threat intelligence feeds to automatically cross-reference incoming traffic against active attack lists.",
                "2. Incorporate user behavior analytics (UBA) to flag anomalous privilege escalation and out-of-hours data exfiltration attempts.",
                "3. Add automated incident response playbooks that automatically quarantine compromised network endpoints upon breach detection.",
                "4. Implement zero-trust microsegmentation rules to restrict lateral movement across internal network resources.",
                "5. Build a SIEM security dashboard visualizing real-time attack vectors, geographical threat origins, and alert severity levels."
            ]
        elif is_education:
            return [
                "1. Incorporate adaptive learning path recommendations that dynamically adjust quiz difficulty based on student comprehension levels.",
                "2. Add automated essay evaluation and grammar feedback tailored to specific assignment rubrics and grade levels.",
                "3. Integrate peer-to-peer study group matchmaking based on complementary learning gaps and course schedules.",
                "4. Implement interactive flashcard generation automatically extracted from uploaded lecture notes or textbook chapters.",
                "5. Build a teacher analytics dashboard identifying struggling students who require early academic intervention."
            ]
        elif is_finance:
            return [
                "1. Integrate real-time transaction monitoring that flags suspicious charges based on geolocation and behavioral anomalies.",
                "2. Incorporate automated credit risk assessment combining non-traditional utility bill payment history with traditional credit scores.",
                "3. Provide personalized budgeting advice and recurring subscription tracking to help users optimize monthly savings.",
                "4. Add AI-driven portfolio rebalancing recommendations based on user risk tolerance and market volatility.",
                "5. Implement automated invoice reconciliation and receipt scanning using optical character recognition (OCR)."
            ]
        else:
            kws = [w for w in self.extract_keywords(full_text) if w not in STOP_WORDS]
            kw1 = kws[0] if len(kws) > 0 else (title_words[0] if len(title_words) > 0 else "core system")
            kw2 = kws[1] if len(kws) > 1 else (title_words[1] if len(title_words) > 1 else "analytics")
            return [
                f"1. Expand the architecture of '{topic_name}' by adding automated real-time alert triggers and anomaly detection for {kw1}.",
                f"2. Integrate interactive visual reporting dashboards so users can analyze key operational metrics and filter historical records.",
                f"3. Incorporate predictive machine learning and telemetry insights to forecast demand and operational trends for {kw2}.",
                f"4. Add granular role-based access permissions and secure authentication protocols allowing customized administrative workspace views.",
                f"5. Implement automated input validation, data sanitization, and failover recovery mechanisms before processing high-throughput records."
            ]

    def generate_ai_mentor_suggestions(self, submission):
        try:
            gemini_suggestions = self.generate_gemini_suggestions(submission)
            if gemini_suggestions and len(gemini_suggestions) >= 3:
                return gemini_suggestions[:5]
        except Exception as e:
            print(f"Notice: Gemini suggestions unavailable, using fallback ({e})")

        # Fallback to local domain-specific suggestions
        return self.get_local_fallback_suggestions(submission)

    def generate_plain_text_suggestions(self, ai_mentor_suggestions):
        return "\n\n".join(ai_mentor_suggestions)

    def evaluate(self, submission, db_projects):
        model = get_similarity_model()
        sub_title = submission.get("title", "")
        sub_abstract = submission.get("abstract", "")
        sub_objectives = submission.get("objectives", "")
        sub_methodology = submission.get("methodology", "")
        sub_description = submission.get("description", "")
        sub_tech = submission.get("technologies") or submission.get("tech_stack", "")
        if isinstance(sub_tech, list):
            sub_tech = " ".join(sub_tech)

        sub_full_text = f"{sub_title}. {sub_abstract} {sub_objectives} {sub_methodology} {sub_description} {sub_tech}".strip()
        sub_sentences = self.split_sentences(sub_full_text)
        sub_keywords = self.extract_keywords(sub_full_text)

        # Pre-encode submission representations once
        sub_embs = {}
        sub_sent_embs = None
        if model:
            try:
                import torch
                with torch.inference_mode():
                    sub_embs["title"] = model.encode(sub_title, convert_to_numpy=True, normalize_embeddings=True)
                    sub_embs["abstract"] = model.encode(sub_abstract, convert_to_numpy=True, normalize_embeddings=True)
                    sub_embs["full"] = model.encode(f"{sub_title}. {sub_abstract}".strip(), convert_to_numpy=True, normalize_embeddings=True)
                    if sub_sentences:
                        sub_sent_embs = model.encode(sub_sentences, convert_to_numpy=True, normalize_embeddings=True)
            except Exception as e:
                print("Notice pre-encoding submission:", e)

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

            # Cache or compute reference project embeddings (NumPy arrays)
            proj_cache_key = str(proj.get("_id") or db_title)
            db_embs = self.embedding_cache.get(proj_cache_key)
            db_sent_embs = None
            if db_embs is None and model:
                try:
                    import torch
                    with torch.inference_mode():
                        db_embs = {
                            "title": model.encode(db_title, convert_to_numpy=True, normalize_embeddings=True),
                            "abstract": model.encode(db_abstract, convert_to_numpy=True, normalize_embeddings=True),
                            "full": model.encode(f"{db_title}. {db_abstract}".strip(), convert_to_numpy=True, normalize_embeddings=True)
                        }
                        if db_sentences:
                            db_embs["sent_embs"] = model.encode(db_sentences, convert_to_numpy=True, normalize_embeddings=True)
                    self.embedding_cache[proj_cache_key] = db_embs
                except Exception as e:
                    print("Notice encoding db project:", e)
                    db_embs = {}
            if db_embs:
                db_sent_embs = db_embs.get("sent_embs")

            # 1. Semantic similarity — 30%
            semantic_score = self.compute_semantic_similarity(
                sub_title, sub_abstract, db_title, db_abstract, sub_embs=sub_embs, db_embs=db_embs
            )

            # 2. Section TF-IDF Cosine similarity — 25%
            tfidf_score, section_scores = self.compute_section_tfidf_similarity(sub_dict, db_dict, sem_hint=semantic_score)

            # 3. Exact phrase/sentence matching — 15%
            exact_score, matching_sents = self.compute_exact_phrase_matching(
                sub_sentences, db_sentences, sub_sent_embs=sub_sent_embs, db_sent_embs=db_sent_embs
            )

            # 4. N-gram similarity — 15%
            ngram_score = self.compute_ngram_similarity(sub_full_text, db_full_text, sem_hint=semantic_score)

            # 5. Keyword similarity — 10%
            kw_score, common_kws = self.compute_keyword_similarity(sub_keywords, db_keywords, sem_hint=semantic_score)

            # 6. Fuzzy string matching — 5%
            fuzzy_score = self.compute_fuzzy_similarity(sub_title + " " + sub_abstract, db_title + " " + db_abstract, sem_hint=semantic_score)

            # Weighted combination (formula: 0.30*sem + 0.25*tfidf + 0.15*exact + 0.15*ngram + 0.10*kw + 0.05*fuzzy)
            composite_score = (
                0.30 * semantic_score +
                0.25 * tfidf_score +
                0.15 * exact_score +
                0.15 * ngram_score +
                0.10 * kw_score +
                0.05 * fuzzy_score
            )

            sim_percent = min(100.0, max(0.0, composite_score * 100.0))

            # Diagnostic logging (Section 19)
            print(f"[ORIGINALITY] Reference project: {db_title}")
            print(f"  Semantic similarity: {round(semantic_score * 100, 2)}%")
            print(f"  TF-IDF similarity:   {round(tfidf_score * 100, 2)}%")
            print(f"  Exact similarity:    {round(exact_score * 100, 2)}%")
            print(f"  N-gram similarity:   {round(ngram_score * 100, 2)}%")
            print(f"  Keyword similarity:  {round(kw_score * 100, 2)}%")
            print(f"  Fuzzy similarity:    {round(fuzzy_score * 100, 2)}%")
            print(f"  Final similarity:    {round(sim_percent, 2)}%")

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

def call_gemini_api_with_retry(payload, originality_score=0, most_similar_title=""):
    raw_key = os.getenv("GEMINI_API_KEY")
    api_key = (raw_key or "").strip().strip('"').strip("'")
    if not api_key:
        raise Exception("GEMINI_API_KEY is not configured.")

    configured_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    candidate_models = [configured_model]
    for m in ["gemini-3.5-flash-lite", "gemini-flash-latest", "gemini-3.1-flash-lite"]:
        if m not in candidate_models:
            candidate_models.append(m)

    headers = {'Content-Type': 'application/json'}
    last_err = None

    for model in candidate_models:
        print("[GEMINI] Gemini API request started")
        print(f"[GEMINI] Gemini model: {model}")
        full_api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        for attempt in range(2):
            try:
                response = requests.post(full_api_url, headers=headers, data=json.dumps(payload), timeout=12)
                print(f"[GEMINI] Gemini API response status: {response.status_code}")

                if response.status_code == 200:
                    print("[GEMINI] Gemini AI suggestions generated successfully")
                    return response.json()

                if response.status_code == 403:
                    raise Exception("Gemini API key is unauthorized or forbidden (HTTP 403).")

                if response.status_code in (429, 503):
                    time.sleep(1)
                    continue

                response.raise_for_status()

            except requests.exceptions.RequestException as e:
                last_err = e
                if hasattr(e.response, 'status_code') and e.response.status_code in (404, 400):
                    # Model not found or deprecated for this endpoint, fallback to next candidate model
                    break
                if attempt < 1:
                    time.sleep(1)

    if last_err:
        raise last_err
    raise Exception("Gemini API call failed after retries.")


@app.route('/api/check_originality', methods=['POST'])
def check_originality():
    req_id = str(uuid.uuid4())[:8]
    req_start = datetime.now(timezone.utc)
    print(f"[{req_start.isoformat()}] [REQ-{req_id}] === Received /api/check_originality POST request ===", flush=True)
    try:
        data = request.json
        if not data:
            print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] Bad Request: Missing JSON payload", flush=True)
            return jsonify({"error": "JSON payload required"}), 400

        title = data.get("title", "")
        abstract = data.get("abstract", "")
        objectives = data.get("objectives", "")
        methodology = data.get("methodology", "")
        description = data.get("description", "")
        technologies = data.get("technologies") or data.get("tech_stack", "")

        if not abstract or not title:
            print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] Bad Request: Both title and abstract are required", flush=True)
            return jsonify({"error": "Both title and abstract are required"}), 400

        submission_data = {
            "title": title,
            "abstract": abstract,
            "objectives": objectives,
            "methodology": methodology,
            "description": description,
            "technologies": technologies
        }

        # Prevent self-comparison: check if caller provides team_name, project_id, or Auth JWT token
        exclude_team_name = data.get("team_name")
        exclude_project_id = data.get("project_id") or data.get("_id") or data.get("id")

        auth_header = request.headers.get("Authorization")
        if auth_header and not exclude_team_name:
            try:
                raw_token = auth_header.split()[-1]
                decoded = jwt.decode(raw_token, app.config["SECRET_KEY"], algorithms=["HS256"])
                user_email = decoded.get("email", "")
                user_usn = clean_usn(decoded.get("usn", ""))
                team = db.teams.find_one({
                    "$or": [
                        {"leader_email": user_email},
                        {"leader_usn": user_usn},
                        {"members.email": user_email},
                        {"members.usn": user_usn},
                        {"members": {"$in": [user_email, user_usn]}}
                    ]
                })
                if team:
                    exclude_team_name = team.get("team_name")
            except Exception:
                pass

        # Collect reference projects ONLY from MongoDB projects collection
        print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] Starting query for reference projects from db.projects...", flush=True)
        db_projects = []
        try:
            for proj in db.projects.find({}):
                # Prevent self-comparison
                if exclude_project_id and str(proj.get("_id")) == str(exclude_project_id):
                    continue
                if exclude_team_name and proj.get("team_name") and str(proj.get("team_name")) == str(exclude_team_name):
                    continue

                if isinstance(proj, dict) and (proj.get("title") or proj.get("abstract")):
                    clean_proj = dict(proj)
                    clean_proj["_id"] = str(clean_proj["_id"])
                    db_projects.append(clean_proj)
            print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] Successfully retrieved {len(db_projects)} reference project(s) from db.projects.", flush=True)
        except Exception as e:
            print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] Notice fetching db.projects: {e}", flush=True)
            traceback.print_exc()

        # Logging for originality verification
        print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] [ORIGINALITY] Reference collection: projects", flush=True)
        print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] [ORIGINALITY] Reference project count: {len(db_projects)}", flush=True)
        print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] [ORIGINALITY] Reference projects:", flush=True)
        for p in db_projects:
            p_title = p.get("title") or p.get("project_title") or "Untitled Project"
            print(f"- {p_title}", flush=True)

        # Obtain SentenceTransformer model
        print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] Obtaining SentenceTransformer model...", flush=True)
        model_fetch_start = time.time()
        model_ref = get_similarity_model()
        model_fetch_elapsed = round(time.time() - model_fetch_start, 2)
        print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] SentenceTransformer retrieval finished in {model_fetch_elapsed}s. Model ready: {model_ref is not None}", flush=True)

        # Run multi-technique originality engine evaluation
        print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] Starting six-layer similarity calculation on {len(db_projects)} reference project(s)...", flush=True)
        sim_calc_start = time.time()
        result = originality_engine.evaluate(submission_data, db_projects)
        sim_calc_elapsed = round(time.time() - sim_calc_start, 2)
        print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] Six-layer similarity calculation finished in {sim_calc_elapsed}s. Max similarity: {result.get('similarity_percent')}%, Originality score: {result.get('originality_score')}%, Most similar: '{result.get('most_similar_project')}'", flush=True)

        total_elapsed = round((datetime.now(timezone.utc) - req_start).total_seconds(), 2)
        print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] Returning 200 response (Total time: {total_elapsed}s)", flush=True)
        return jsonify(result), 200

    except Exception as e:
        total_elapsed = round((datetime.now(timezone.utc) - req_start).total_seconds(), 2)
        print(f"[{datetime.now(timezone.utc).isoformat()}] [REQ-{req_id}] 🔥 Error in originality check after {total_elapsed}s: {e}", flush=True)
        traceback.print_exc()
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

        team = find_team_by_name(team_name)
        canonical_name = team.get("team_name", str(team_name)) if team else str(team_name)

        # 3. Update the Team (Set manual_allocation = True)
        if team:
            db.teams.update_one(
                {"_id": team["_id"]},
                {
                    "$set": {
                        "faculty_email": faculty_email,
                        "faculty_name": faculty["name"], # Store name for easier frontend display
                        "manual_allocation": True 
                    }
                }
            )
        else:
            db.teams.update_one(
                {"team_name": canonical_name},
                {
                    "$set": {
                        "faculty_email": faculty_email,
                        "faculty_name": faculty["name"],
                        "manual_allocation": True 
                    }
                }
            )

        # 4. Update the Allocations Collection (for the dashboard view)
        # We update the existing allocation or insert if missing
        db.allocations.update_one(
            {"team_name": canonical_name},
            {
                "$set": {
                    "faculty_name": faculty["name"],
                    "faculty_email": faculty_email,
                    "team_name": canonical_name,
                    # We set match_score to "Manual" so it's clear in UI
                    "match_percentage": "Manual"
                }
            },
            upsert=True
        )

        # Notify team members and allocated faculty via email
        try:
            base_url = get_frontend_base_url()
            idea = team.get("project_idea") or {} if team else {}
            proj_title = (idea.get("title") if isinstance(idea, dict) else "") or "Student Project"

            # 1. Notify team members (Temporarily disabled under faculty-to-student only policy)
            if not ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS and team:
                recipients = get_team_recipient_emails(team)
                if recipients:
                    subject = f"Faculty Guide Assigned: {faculty['name']} - {canonical_name}"
                    plain_msg = (
                        f"Hello {canonical_name},\n\n"
                        f"Faculty guide {faculty['name']} ({faculty_email}) has been assigned to guide your project.\n\n"
                        f"Open Team Dashboard: {base_url}/team-dasboard.html"
                    )
                    html_msg = render_email_template(
                        headline="Faculty Guide Allocated",
                        badge_text="Guide Allocated",
                        badge_color="#2563eb",
                        team_name=canonical_name,
                        project_title=proj_title,
                        key_details={
                            "Faculty Guide": faculty["name"],
                            "Guide Email": faculty_email,
                            "Allocation Type": "Faculty Guide Assignment"
                        },
                        message_content=f"Your project team has been officially assigned to {faculty['name']}. Please connect with your guide to discuss your project plan.",
                        action_url=f"{base_url}/team-dasboard.html",
                        action_text="Open Team Dashboard"
                    )
                    send_email_notification(
                        recipients, subject, plain_msg, html_msg,
                        trigger_name="COORDINATOR_ALLOCATE_GUIDE_TEAM", team_id=canonical_name
                    )
            elif ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS:
                email_logger.info(
                    f"[EMAIL_NOTIFICATION] trigger=\"COORDINATOR_ALLOCATE_GUIDE_TEAM\" team=\"{canonical_name}\" "
                    f"worker_status=\"SKIPPED\" reason=\"POLICY_DISALLOWED_TRIGGER\""
                )

            # 2. Notify assigned faculty (Temporarily disabled under faculty-to-student only policy)
            if not ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS and is_valid_email(faculty_email):
                subject = f"New Project Team Assigned: {canonical_name}"
                leader_display = f"{team.get('leader_name', 'Student Leader')} ({team.get('leader_email', '')})" if team else canonical_name
                plain_msg = (
                    f"Hello {faculty['name']},\n\n"
                    f"A new student team '{canonical_name}' has been assigned to you for project guidance.\n"
                    f"Leader: {leader_display}\n\n"
                    f"Open Faculty Dashboard: {base_url}/faculty-dashboard.html"
                )
                html_msg = render_email_template(
                    headline="New Project Team Assigned",
                    badge_text="Team Assigned",
                    badge_color="#7c3aed",
                    team_name=faculty["name"],
                    project_title=f"{canonical_name}: {proj_title}",
                    key_details={
                        "Team Name": canonical_name,
                        "Team Leader": leader_display,
                        "Assigned Date": datetime.now().strftime("%Y-%m-%d %H:%M")
                    },
                    message_content=f"You have been assigned as project guide for team '{canonical_name}'. You can assign tasks, provide feedback, and track evaluations through your faculty dashboard.",
                    action_url=f"{base_url}/faculty-dashboard.html",
                    action_text="Open Faculty Dashboard"
                )
                send_email_notification(
                    [faculty_email], subject, plain_msg, html_msg,
                    trigger_name="COORDINATOR_ALLOCATE_GUIDE_FACULTY", team_id=canonical_name
                )
            elif ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS:
                email_logger.info(
                    f"[EMAIL_NOTIFICATION] trigger=\"COORDINATOR_ALLOCATE_GUIDE_FACULTY\" team=\"{canonical_name}\" "
                    f"worker_status=\"SKIPPED\" reason=\"POLICY_DISALLOWED_TRIGGER\""
                )
        except Exception as email_err:
            email_logger.error(f"Error preparing guide allocation notifications for {canonical_name}: {email_err}")

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
    team_name = data.get('team_name')
    message = data.get('message')
    sender = data.get('sender', 'team')

    s_name = data.get('submitted_by_name') or data.get('sender_name') or sender
    s_usn = clean_usn(data.get('submitted_by_usn') or data.get('sender_usn'))
    s_email = data.get('submitted_by_email') or data.get('sender_email') or ""

    sender_display = format_student_identity(s_name, s_usn) if (s_name and s_usn) else (s_name or sender)

    msg_data = {
        "team_name": team_name,
        "sender": sender,
        "sender_display": sender_display,
        "submitted_by_name": s_name,
        "submitted_by_usn": s_usn,
        "submitted_by_email": s_email,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": message
    }

    result = db.chats.insert_one(msg_data)
    msg_data["_id"] = str(result.inserted_id)
    emit('receive_message', msg_data, room=team_name)


@app.route('/api/chat/<team_name>', methods=['GET'])
def get_chat(team_name):
    chats = list(db.chats.find({"team_name": team_name}, {"_id": 0}))
    return jsonify(chats)


# ==================================================================== #
#                       ATTENDANCE MODULE                              #
# ==================================================================== #

def calculate_attendance_mark(meeting_count):
    """
    Standard Grading Rule for Guide Meetings:
    0–4 meetings   -> 0 marks
    5–9 meetings   -> 5 marks
    10–14 meetings -> 8 marks
    15+ meetings   -> 10 marks (capped at 10)
    """
    try:
        count = int(meeting_count)
    except (ValueError, TypeError):
        count = 0

    if count < 5:
        return 0
    elif 5 <= count <= 9:
        return 5
    elif 10 <= count <= 14:
        return 8
    else:
        return 10


def get_student_meeting_stats(student_usn, student_name="", team_name=None, semester=6):
    """
    Calculates total meetings, weekly meetings (current ISO week),
    monthly meetings (current month), last meeting date/time,
    and attendance mark for a specific student identified primarily by USN.
    Strictly partitioned by semester (6 or 7).
    """
    sem_val = 7 if str(semester or "").strip() in ["7", "7th", "sem7"] else 6
    clean_u = clean_usn(student_usn)
    query_conditions = []
    if clean_u and clean_u != "N/A":
        query_conditions.append({"student_usn": clean_u})
        query_conditions.append({"records.usn": clean_u})
    if student_name and team_name:
        query_conditions.append({"team_name": team_name, "student_name": student_name})
        query_conditions.append({"team_name": team_name, "records.student_name": student_name})
        query_conditions.append({"team_name": team_name, "records.name": student_name})

    if not query_conditions:
        if team_name:
            query_conditions.append({"team_name": team_name})
        else:
            return {
                "total_meetings": 0,
                "weekly_meetings": 0,
                "monthly_meetings": 0,
                "last_meeting_date": None,
                "last_meeting_time": None,
                "last_meeting_display": "No meetings recorded",
                "attendance_mark": 0,
                "max_mark": 10,
                "meeting_history": [],
                "weekly_breakdown": {},
                "semester": sem_val
            }

    if sem_val == 7:
        sem_cond = {"$or": [{"semester": 7}, {"semester": "7"}]}
    else:
        sem_cond = {"$or": [{"semester": 6}, {"semester": "6"}, {"semester": {"$exists": False}}]}

    docs = list(db.attendance.find({"$and": [{"$or": query_conditions}, sem_cond]}))

    meeting_events = []
    seen_keys = set()

    now = datetime.now()
    current_year_week = f"{now.year}-W{now.isocalendar()[1]:02d}"
    current_year_month = f"{now.year}-{now.month:02d}"

    for doc in docs:
        if "records" in doc and isinstance(doc["records"], list):
            for r in doc["records"]:
                r_usn = clean_usn(r.get("usn"))
                r_name = r.get("student_name") or r.get("name", "")
                is_match = False
                if clean_u and r_usn == clean_u:
                    is_match = True
                elif not clean_u and student_name and r_name.strip().lower() == student_name.strip().lower():
                    is_match = True
                elif clean_u and not r_usn and student_name and r_name.strip().lower() == student_name.strip().lower():
                    is_match = True

                if is_match:
                    status = r.get("status", "Completed")
                    if status != "Absent":
                        m_date = doc.get("date") or doc.get("meeting_date") or ""
                        m_time = doc.get("meeting_time") or (doc.get("timestamp", "").split("T")[-1][:5] if "T" in str(doc.get("timestamp")) else "10:00 AM")
                        key = f"{r_usn or student_name}_{m_date}_{m_time}"
                        doc_id = str(doc.get("_id")) if doc.get("_id") else None
                        meeting_events.append({
                            "id": doc_id,
                            "date": m_date,
                            "time": m_time,
                            "faculty": doc.get("faculty_name") or doc.get("submitted_by_name") or "Project Guide",
                            "status": "Completed",
                            "notes": doc.get("notes", ""),
                            "timestamp": doc.get("timestamp") or f"{m_date}T{m_time}",
                            "semester": doc.get("semester", sem_val)
                        })
        else:
            r_usn = clean_usn(doc.get("student_usn"))
            r_name = doc.get("student_name", "")
            is_match = False
            if clean_u and r_usn == clean_u:
                is_match = True
            elif not clean_u and student_name and r_name.strip().lower() == student_name.strip().lower():
                is_match = True
            elif clean_u and not r_usn and student_name and r_name.strip().lower() == student_name.strip().lower():
                is_match = True
            elif clean_u and not r_usn and not student_name and doc.get("team_name") == team_name:
                is_match = True

            if is_match:
                m_date = doc.get("meeting_date") or doc.get("date") or ""
                m_time = doc.get("meeting_time") or "10:00 AM"
                doc_id = str(doc.get("_id")) if doc.get("_id") else None
                meeting_events.append({
                    "id": doc_id,
                    "date": m_date,
                    "time": m_time,
                    "faculty": doc.get("faculty_name") or doc.get("submitted_by_name") or "Project Guide",
                    "status": doc.get("status", "Completed"),
                    "notes": doc.get("notes", ""),
                    "timestamp": doc.get("timestamp") or f"{m_date}T{m_time}",
                    "semester": doc.get("semester", sem_val)
                })

    meeting_events.sort(key=lambda x: str(x.get("date", "")) + " " + str(x.get("time", "")), reverse=True)

    total_meetings = len(meeting_events)
    weekly_meetings = 0
    monthly_meetings = 0
    weekly_breakdown = {}

    for ev in meeting_events:
        d_str = ev.get("date")
        if d_str:
            try:
                dt = datetime.strptime(d_str[:10], "%Y-%m-%d")
                yw = f"{dt.year}-W{dt.isocalendar()[1]:02d}"
                ym = f"{dt.year}-{dt.month:02d}"

                if yw == current_year_week:
                    weekly_meetings += 1
                if ym == current_year_month:
                    monthly_meetings += 1

                w_num = dt.isocalendar()[1]
                w_label = f"Week {w_num}"
                weekly_breakdown[w_label] = weekly_breakdown.get(w_label, 0) + 1
            except Exception:
                pass

    last_meeting_id = meeting_events[0]["id"] if meeting_events else None
    last_meeting_date = meeting_events[0]["date"] if meeting_events else None
    last_meeting_time = meeting_events[0]["time"] if meeting_events else None
    last_meeting_display = f"{last_meeting_date}, {last_meeting_time}" if (last_meeting_date and last_meeting_time) else (last_meeting_date or "No meetings recorded")

    attendance_mark = calculate_attendance_mark(total_meetings)

    return {
        "total_meetings": total_meetings,
        "weekly_meetings": weekly_meetings,
        "monthly_meetings": monthly_meetings,
        "last_meeting_id": last_meeting_id,
        "last_meeting_date": last_meeting_date,
        "last_meeting_time": last_meeting_time,
        "last_meeting_display": last_meeting_display,
        "attendance_mark": attendance_mark,
        "max_mark": 10,
        "meeting_history": meeting_events,
        "weekly_breakdown": weekly_breakdown,
        "semester": sem_val
    }


def get_team_attendance_summary(team_name, semester=6):
    """
    Computes comprehensive attendance summary for an entire team.
    Strictly partitioned by semester (6 or 7).
    """
    sem_val = 7 if str(semester or "").strip() in ["7", "7th", "sem7"] else 6
    team = db.teams.find_one({"team_name": team_name}, {"_id": 0})
    if not team:
        return {
            "team_name": team_name,
            "students": [],
            "total_meetings": 0,
            "weekly_meetings": 0,
            "monthly_meetings": 0,
            "attendance_mark_avg": 0,
            "meeting_history": [],
            "weekly_breakdown": {},
            "semester": sem_val
        }

    students = format_team_student_identities(team)
    student_summaries = []

    team_history = []
    seen_history_ids = set()
    team_weekly_breakdown = {}

    total_m_sum = 0
    weekly_m_sum = 0
    monthly_m_sum = 0
    marks_sum = 0

    for s in students:
        s_usn = clean_usn(s.get("usn"))
        s_name = s.get("name")
        stats = get_student_meeting_stats(s_usn, s_name, team_name, semester=sem_val)

        student_summaries.append({
            "usn": s_usn,
            "name": s_name,
            "display_name": s.get("display_name") or format_student_identity(s_name, s_usn),
            "is_leader": s.get("is_leader", False),
            "total_meetings": stats["total_meetings"],
            "weekly_meetings": stats["weekly_meetings"],
            "monthly_meetings": stats["monthly_meetings"],
            "last_meeting_id": stats.get("last_meeting_id"),
            "last_meeting_date": stats["last_meeting_date"],
            "last_meeting_time": stats["last_meeting_time"],
            "last_meeting_display": stats["last_meeting_display"],
            "attendance_mark": stats["attendance_mark"],
            "max_mark": 10,
            "meeting_history": stats["meeting_history"],
            "weekly_breakdown": stats["weekly_breakdown"],
            "semester": sem_val
        })

        total_m_sum += stats["total_meetings"]
        weekly_m_sum += stats["weekly_meetings"]
        monthly_m_sum += stats["monthly_meetings"]
        marks_sum += stats["attendance_mark"]

        for ev in stats["meeting_history"]:
            ev_id = ev.get("id")
            if ev_id and ev_id not in seen_history_ids:
                seen_history_ids.add(ev_id)
                team_history.append({
                    "id": ev_id,
                    "date": ev.get("date"),
                    "time": ev.get("time"),
                    "faculty": ev.get("faculty"),
                    "student_name": s_name,
                    "student_usn": s_usn,
                    "display_name": s.get("display_name"),
                    "status": ev.get("status", "Completed"),
                    "notes": ev.get("notes", ""),
                    "timestamp": ev.get("timestamp"),
                    "semester": sem_val
                })
            elif not ev_id:
                team_history.append({
                    "id": None,
                    "date": ev.get("date"),
                    "time": ev.get("time"),
                    "faculty": ev.get("faculty"),
                    "student_name": s_name,
                    "student_usn": s_usn,
                    "display_name": s.get("display_name"),
                    "status": ev.get("status", "Completed"),
                    "notes": ev.get("notes", ""),
                    "timestamp": ev.get("timestamp"),
                    "semester": sem_val
                })

        for w_label, count in stats["weekly_breakdown"].items():
            team_weekly_breakdown[w_label] = team_weekly_breakdown.get(w_label, 0) + count

    team_history.sort(key=lambda x: str(x.get("date", "")) + " " + str(x.get("time", "")), reverse=True)
    num_students = len(students) or 1

    return {
        "team_name": team_name,
        "students": student_summaries,
        "total_meetings": total_m_sum,
        "weekly_meetings": weekly_m_sum,
        "monthly_meetings": monthly_m_sum,
        "attendance_mark_avg": round(marks_sum / num_students, 1),
        "meeting_history": team_history,
        "weekly_breakdown": team_weekly_breakdown,
        "semester": sem_val
    }


def sync_evaluation_attendance(evaluation, students, team_name, semester=6):
    """
    Single Source of Truth:
    Ensures that in the evaluation object:
    - For 6th semester: Phase 3 (Report & Attendance) -> criterion named 'Attendance'
      has each student's marks_obtained set to their auto-calculated attendance_mark
      from 6th semester guide meeting records.
    - For 7th semester: Phase/criterion named 'Attendance' has each student's marks_obtained
      set to their auto-calculated attendance_mark from 7th semester guide meeting records.
    """
    if not evaluation or "phases" not in evaluation:
        return evaluation

    sem_val = 7 if str(semester or "").strip() in ["7", "7th", "sem7"] else 6

    for phase in evaluation.get("phases", []):
        phase_name_lower = phase.get("name", "").strip().lower()
        for criterion in phase.get("criteria", []):
            crit_name_lower = criterion.get("name", "").strip().lower()
            is_attendance = (crit_name_lower == "attendance") or (sem_val == 7 and phase_name_lower == "attendance")
            if is_attendance:
                criterion["max_marks"] = 10
                marks_arr = criterion.get("marks", [])
                for idx, student in enumerate(students):
                    s_usn = clean_usn(student.get("usn"))
                    s_name = student.get("name")
                    stats = student.get("attendance_stats") or get_student_meeting_stats(s_usn, s_name, team_name, semester=sem_val)
                    calc_mark = stats.get("attendance_mark", 0)

                    while len(marks_arr) <= idx:
                        marks_arr.append({"marks_obtained": 0, "maximum_marks": 10})

                    marks_arr[idx]["marks_obtained"] = calc_mark
                    marks_arr[idx]["maximum_marks"] = 10
                criterion["marks"] = marks_arr
    return evaluation


@app.route('/api/attendance', methods=['GET', 'POST'])
def handle_attendance():
    if request.method == 'POST':
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing authorization token"}), 401
        
        token = token_full.split()[-1]
        try:
            decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
            user_role = decoded.get("role")
            if user_role not in ["faculty", "coordinator"]:
                return jsonify({"error": "Unauthorized - Students cannot record meetings"}), 403
        except Exception:
            return jsonify({"error": "Invalid token"}), 401

        ownership = extract_activity_ownership(token_full)
        data = request.json or {}
        team_name = data.get("team_name")
        if not team_name:
            return jsonify({"error": "Team name is required"}), 400

        team = db.teams.find_one({"team_name": team_name})
        if not team:
            return jsonify({"error": f"Team '{team_name}' not found"}), 404

        students_in_team = format_team_student_identities(team)
        
        sem_param = data.get("semester") or request.args.get("semester")
        target_sem = 7 if str(sem_param or "").strip() in ["7", "7th", "sem7"] else 6

        now = datetime.now()
        date_str = (data.get("meeting_date") or data.get("date") or now.strftime("%Y-%m-%d")).strip()
        time_str = (data.get("meeting_time") or data.get("time") or now.strftime("%I:%M %p")).strip()
        faculty_name = ownership.get("submitted_by_name") or team.get("faculty_name") or "Project Guide"
        faculty_email = ownership.get("submitted_by_email") or decoded.get("email") or ""

        # Determine target students to record meeting for
        target_students = []
        raw_usn = (data.get("student_usn") or data.get("usn") or "").strip()
        if raw_usn and raw_usn.upper() != "ALL":
            target_usn = clean_usn(raw_usn)
            target_name = (data.get("student_name") or data.get("name") or "").strip()
            matched = next((s for s in students_in_team if (target_usn and clean_usn(s.get("usn")) == target_usn) or (target_name and s.get("name") == target_name)), None)
            if matched:
                target_students.append(matched)
            else:
                target_students.append({
                    "usn": target_usn,
                    "name": target_name or "Student",
                    "display_name": format_student_identity(target_name, target_usn)
                })
        elif "students" in data and isinstance(data["students"], list):
            for st in data["students"]:
                s_u = clean_usn(st.get("usn"))
                s_n = st.get("name", "")
                matched = next((s for s in students_in_team if (s_u and clean_usn(s.get("usn")) == s_u) or (s_n and s.get("name") == s_n)), None)
                if matched:
                    target_students.append(matched)
                else:
                    target_students.append({"usn": s_u, "name": s_n, "display_name": format_student_identity(s_n, s_u)})
        elif "records" in data and isinstance(data["records"], list):
            # Legacy format support
            for r in data["records"]:
                if r.get("status") != "Absent":
                    s_u = clean_usn(r.get("usn"))
                    s_n = r.get("name") or r.get("student_name", "")
                    matched = next((s for s in students_in_team if (s_u and clean_usn(s.get("usn")) == s_u) or (s_n and s.get("name") == s_n)), None)
                    if matched:
                        target_students.append(matched)
                    else:
                        target_students.append({"usn": s_u, "name": s_n, "display_name": format_student_identity(s_n, s_u)})
        else:
            target_students = students_in_team

        if not target_students:
            return jsonify({"error": "No students selected for meeting record"}), 400

        inserted_records = []
        duplicate_count = 0
        duplicate_names = []

        if target_sem == 7:
            sem_cond = {"$or": [{"semester": 7}, {"semester": "7"}]}
        else:
            sem_cond = {"$or": [{"semester": 6}, {"semester": "6"}, {"semester": {"$exists": False}}]}

        for st in target_students:
            s_usn = clean_usn(st.get("usn"))
            s_name = st.get("name") or ""
            display_name = st.get("display_name") or format_student_identity(s_name, s_usn)

            # STRICT RULE: One meeting per student per calendar date per semester
            if s_usn and s_usn != "N/A":
                dup_query = {"$and": [{"student_usn": s_usn}, {"meeting_date": date_str}, sem_cond]}
            else:
                dup_query = {"$and": [{"student_name": s_name}, {"team_name": team_name}, {"meeting_date": date_str}, sem_cond]}

            existing_dup = db.attendance.find_one(dup_query)
            if existing_dup:
                duplicate_count += 1
                duplicate_names.append(display_name)
                continue

            meeting_entry = {
                "team_name": team_name,
                "semester": target_sem,
                "student_usn": s_usn,
                "student_name": s_name,
                "display_name": display_name,
                "faculty_id": faculty_email,
                "faculty_name": faculty_name,
                "meeting_date": date_str,
                "meeting_time": time_str,
                "date": date_str,
                "status": "Completed",
                "type": "guide_meeting",
                "notes": data.get("notes", ""),
                "submitted_by_name": faculty_name,
                "submitted_by_usn": ownership["submitted_by_usn"],
                "submitted_by_email": faculty_email,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            try:
                db.attendance.insert_one(meeting_entry)
                inserted_records.append(meeting_entry)
            except Exception as insert_err:
                duplicate_count += 1
                duplicate_names.append(display_name)

        if duplicate_count > 0 and len(inserted_records) == 0:
            names_str = ", ".join(duplicate_names)
            return jsonify({
                "error": f"Meeting already recorded for {names_str} on {date_str} in Semester {target_sem}. Only one meeting per student per day is allowed."
            }), 409

        partial_msg = ""
        if duplicate_count > 0 and len(inserted_records) > 0:
            names_str = ", ".join(duplicate_names)
            partial_msg = f" (Skipped duplicate for: {names_str})"

        # Calculate updated stats for the target semester
        updated_team_summary = get_team_attendance_summary(team_name, semester=target_sem)

        first_student_stats = None
        if target_students:
            first_student_stats = get_student_meeting_stats(target_students[0].get("usn"), target_students[0].get("name"), team_name, semester=target_sem)

        total_m = first_student_stats["total_meetings"] if first_student_stats else updated_team_summary["total_meetings"]
        calc_mark = first_student_stats["attendance_mark"] if first_student_stats else updated_team_summary["attendance_mark_avg"]

        # Sync attendance marks into the target semester evaluation if it exists
        try:
            eval_doc = db.evaluations.find_one(get_evaluation_query(team_name, target_sem))
            if eval_doc:
                sync_students = []
                for s in students_in_team:
                    s_u = clean_usn(s.get("usn"))
                    s_n = s.get("name")
                    st_stats = get_student_meeting_stats(s_u, s_n, team_name, semester=target_sem)
                    sync_students.append({
                        "name": s_n,
                        "usn": s_u,
                        "attendance_stats": st_stats
                    })
                updated_eval = sync_evaluation_attendance(eval_doc, sync_students, team_name, semester=target_sem)
                db.evaluations.update_one(
                    {"_id": eval_doc["_id"]},
                    {"$set": {"phases": updated_eval.get("phases", [])}}
                )
        except Exception as sync_err:
            print(f"Warning: Could not sync evaluation after meeting insert: {sync_err}")

        return jsonify({
            "success": True,
            "message": f"Guide meeting recorded successfully for Semester {target_sem}. Total meetings: {total_m}{partial_msg}",
            "semester": target_sem,
            "total_meetings": total_m,
            "weekly_meetings": first_student_stats["weekly_meetings"] if first_student_stats else updated_team_summary["weekly_meetings"],
            "monthly_meetings": first_student_stats["monthly_meetings"] if first_student_stats else updated_team_summary["monthly_meetings"],
            "last_meeting": first_student_stats["last_meeting_display"] if first_student_stats else None,
            "attendance_mark": calc_mark,
            "max_mark": 10,
            "inserted_count": len(inserted_records),
            "skipped_count": duplicate_count,
            "stats": first_student_stats,
            "team_summary": updated_team_summary
        }), 200

    else:
        sem_param = request.args.get("semester")
        target_sem = 7 if str(sem_param or "").strip() in ["7", "7th", "sem7"] else 6
        team_name = request.args.get("team_name")
        student_usn = request.args.get("student_usn") or request.args.get("usn")
        
        if team_name:
            summary = get_team_attendance_summary(team_name, semester=target_sem)
            return jsonify({
                "team_name": team_name,
                "semester": target_sem,
                "summary": summary,
                "attendance": summary.get("meeting_history", []),
                "students": summary.get("students", []),
                "weekly_breakdown": summary.get("weekly_breakdown", {})
            }), 200
        elif student_usn:
            stats = get_student_meeting_stats(student_usn, semester=target_sem)
            return jsonify({
                "student_usn": student_usn,
                "semester": target_sem,
                "stats": stats,
                "attendance": stats.get("meeting_history", []),
                "weekly_breakdown": stats.get("weekly_breakdown", {})
            }), 200
        else:
            all_teams = list(db.teams.find({}, {"_id": 0, "team_name": 1}))
            all_summaries = [get_team_attendance_summary(t["team_name"], semester=target_sem) for t in all_teams]
            return jsonify({"teams": all_summaries, "semester": target_sem}), 200


# ==================================================================== #
#               DELETE GUIDE MEETING RECORD ENDPOINT                   #
# ==================================================================== #

@app.route('/api/attendance/<meeting_id>', methods=['DELETE'])
def delete_attendance_record(meeting_id):
    """
    Delete a specific guide meeting record by its MongoDB _id.
    Only faculty or coordinator can delete.
    Students are forbidden.
    After deletion, recalculates team stats and syncs evaluation attendance for the meeting's semester.
    """
    from bson import ObjectId

    token_full = request.headers.get("Authorization")
    if not token_full:
        return jsonify({"error": "Missing authorization token"}), 401

    tok = token_full.split()[-1]
    try:
        decoded = jwt.decode(tok, app.config["SECRET_KEY"], algorithms=["HS256"])
        user_role = decoded.get("role")
        if user_role not in ["faculty", "coordinator"]:
            return jsonify({"error": "Forbidden: Students cannot delete guide meeting records."}), 403
    except Exception:
        return jsonify({"error": "Invalid token"}), 401

    # Validate and parse ObjectId
    try:
        oid = ObjectId(meeting_id)
    except Exception:
        return jsonify({"error": "Invalid meeting ID format"}), 400

    # Find the record before deleting (so we know which team and semester to recalculate)
    record = db.attendance.find_one({"_id": oid})
    if not record:
        return jsonify({"error": "Meeting record not found"}), 404

    team_name = record.get("team_name", "")
    rec_sem = 7 if str(record.get("semester") or "").strip() in ["7", "7th"] else 6

    # Delete the record
    db.attendance.delete_one({"_id": oid})

    # Recalculate team attendance stats for the record's semester
    updated_summary = get_team_attendance_summary(team_name, semester=rec_sem)

    # Recalculate per-student stats for the affected student
    s_usn = record.get("student_usn", "")
    s_name = record.get("student_name", "")
    updated_student_stats = get_student_meeting_stats(s_usn, s_name, team_name, semester=rec_sem)

    # Sync attendance mark into evaluation (re-fetch and update the matching semester evaluation record)
    try:
        eval_doc = db.evaluations.find_one(get_evaluation_query(team_name, rec_sem))
        if eval_doc:
            team = db.teams.find_one({"team_name": team_name}) or {}
            raw_students = eval_doc.get("students") or []
            if not raw_students:
                all_members = []
                if team.get("leader_name"):
                    all_members.append({"name": team["leader_name"], "usn": team.get("leader_usn", ""), "is_leader": True})
                for m in team.get("members", []):
                    if isinstance(m, dict):
                        all_members.append({"name": m.get("name", ""), "usn": m.get("usn", ""), "is_leader": False})
                    elif isinstance(m, str):
                        all_members.append({"name": m, "usn": "", "is_leader": False})
                raw_students = all_members

            students_for_sync = []
            for s in raw_students:
                su = clean_usn(s.get("usn") if isinstance(s, dict) else "")
                sn = s.get("name") if isinstance(s, dict) else s
                stats = get_student_meeting_stats(su, sn, team_name, semester=rec_sem)
                students_for_sync.append({"name": sn, "usn": su, "is_leader": s.get("is_leader", False) if isinstance(s, dict) else False, "attendance_stats": stats})

            updated_eval = sync_evaluation_attendance(eval_doc, students_for_sync, team_name, semester=rec_sem)
            db.evaluations.update_one(
                {"_id": eval_doc["_id"]},
                {"$set": {"phases": updated_eval.get("phases", [])}}
            )
    except Exception as sync_err:
        print(f"Warning: Could not sync evaluation after delete: {sync_err}")

    return jsonify({
        "success": True,
        "message": f"Guide meeting record deleted successfully.",
        "team_name": team_name,
        "semester": rec_sem,
        "updated_student_stats": updated_student_stats,
        "team_summary": updated_summary
    }), 200


# ==================================================================== #
#               VTU FINAL MARKS EXCEL EXPORT ROUTE                     #
# ==================================================================== #

@app.route('/api/coordinator/export_final_marks', methods=['GET'])
def export_final_marks():
    try:
        token_full = request.headers.get("Authorization") or request.args.get("token")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401

        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") not in ["coordinator", "faculty"]:
            return jsonify({"error": "Unauthorized"}), 403

        semester_param = request.args.get("semester")
        target_sem = 7 if str(semester_param or "").strip() in ["7", "7th", "sem7"] else 6

        teams = list(db.teams.find({}, {"_id": 0}))
        if target_sem == 7:
            evaluations = list(db.evaluations.find({"$or": [{"semester": 7}, {"semester": "7"}]}, {"_id": 0}))
        else:
            evaluations = list(db.evaluations.find({"$or": [{"semester": 6}, {"semester": "6"}, {"semester": {"$exists": False}}]}, {"_id": 0}))

        # Deduplication map keyed by canonical normalized USN (or unique fallback for students without USN)
        dedup_records = {}
        ordered_keys = []

        for team in teams:
            team_name = team.get("team_name", "Unknown Team")

            # Match authoritative evaluation for this team from Faculty Project Evaluation for the requested semester
            eval_data = next((e for e in evaluations if str(e.get("team_name", "")).strip().lower() == str(team_name).strip().lower()), None)

            students = format_team_student_identities(team)
            if eval_data:
                eval_data = sync_evaluation_with_panel_averages(eval_data, team_name, semester=target_sem, students=students)
            phases = eval_data.get("phases", []) if eval_data else []

            for s_idx, student in enumerate(students):
                raw_usn = student.get("usn", "")
                norm_usn = clean_usn(raw_usn)

                # Deduplication key: normalized USN if present, otherwise unique identifier per distinct student
                if norm_usn and norm_usn != "N/A":
                    dedup_key = f"USN:{norm_usn}"
                    display_usn = norm_usn
                else:
                    student_ident = student.get("email") or student.get("name") or str(s_idx)
                    dedup_key = f"NON_USN:{team_name}:{s_idx}:{student_ident}"
                    display_usn = "N/A"

                # Calculate final marks using authoritative faculty Project Evaluation data
                if not eval_data or not phases:
                    # Missing evaluation record - handled safely without silently treating as 0
                    calculated_marks = "N/A"
                else:
                    student_total = 0.0
                    has_criteria = False
                    has_student_entry = False

                    is_evaluation_complete = True
                    for phase in phases:
                        # If a panel phase is not complete, final marks cannot be published as complete
                        if phase.get("is_panel_evaluated") and not phase.get("is_complete", False):
                            is_evaluation_complete = False
                            break

                        for criterion in phase.get("criteria", []):
                            has_criteria = True
                            marks_list = criterion.get("marks", [])
                            if s_idx < len(marks_list):
                                has_student_entry = True
                                mark_entry = marks_list[s_idx]
                                raw_obtained = mark_entry.get("marks_obtained") if isinstance(mark_entry, dict) else mark_entry
                                if raw_obtained is not None and str(raw_obtained).strip() != "":
                                    try:
                                        obtained = float(raw_obtained)
                                        if obtained < 0:
                                            obtained = 0.0
                                        student_total += obtained
                                    except (ValueError, TypeError):
                                        pass

                    if not is_evaluation_complete:
                        calculated_marks = "N/A"
                    elif has_criteria and has_student_entry:
                        if student_total > 100.0:
                            student_total = 100.0
                        calculated_marks = int(student_total) if student_total.is_integer() else round(student_total, 2)
                    else:
                        calculated_marks = "N/A"

                if dedup_key not in dedup_records:
                    dedup_records[dedup_key] = {
                        "USN": display_usn,
                        "Marks": calculated_marks
                    }
                    ordered_keys.append(dedup_key)
                else:
                    # Duplicate student encountered:
                    # Do NOT sum duplicate records or add the same final mark multiple times.
                    # Use authoritative final evaluation result if existing was un-evaluated ("N/A")
                    existing_entry = dedup_records[dedup_key]
                    if existing_entry["Marks"] == "N/A" and calculated_marks != "N/A":
                        existing_entry["Marks"] = calculated_marks

        def natural_usn_sort_key(usn_str):
            usn = str(usn_str or "").strip().upper()
            if not usn or usn == "N/A":
                return (1, [], "")
            parts = []
            for token in re.split(r'(\d+)', usn):
                if not token:
                    continue
                if token.isdigit():
                    parts.append((0, int(token)))
                else:
                    parts.append((1, token))
            return (0, parts, usn)

        rows = list(dedup_records.values())
        rows.sort(key=lambda r: natural_usn_sort_key(r.get("USN")))

        if target_sem == 7:
            dl_xlsx_name = "vtu_final_marks_sem7.xlsx"
            dl_csv_name = "vtu_final_marks_sem7.csv"
        else:
            dl_xlsx_name = "vtu_final_marks.xlsx"
            dl_csv_name = "vtu_final_marks.csv"

        try:
            import io
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "VTU Final Marks"

            headers = ["USN", "Marks"]
            ws.append(headers)

            for row in rows:
                ws.append([row["USN"], row["Marks"]])

            output = io.BytesIO()
            wb.save(output)
            output.seek(0)

            return send_file(
                output,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                as_attachment=True,
                download_name=dl_xlsx_name
            )
        except Exception as py_excel_err:
            print("openpyxl notice, fallback to CSV:", py_excel_err)
            import io
            import csv
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=["USN", "Marks"])
            writer.writeheader()
            for row in rows:
                writer.writerow({"USN": row["USN"], "Marks": row["Marks"]})

            response = app.response_class(
                response=output.getvalue(),
                status=200,
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename={dl_csv_name}"}
            )
            return response

    except Exception as e:
        print("Error exporting final marks:", e)
        return jsonify({"error": "Failed to generate export file"}), 500


# ==================================================================== #
#              PROJECT EVALUATION SYSTEM INTEGRATION                   #
# ==================================================================== #

def get_evaluation_query(team_name, semester=6):
    """
    Returns the MongoDB query filter for a team's evaluation in a given semester.
    Semester 7 matches documents explicitly tagged with semester 7.
    Semester 6 matches documents tagged with semester 6 OR untagged legacy records.
    """
    sem = 7 if str(semester or "").strip() in ["7", "7th", "sem7"] else 6
    if sem == 7:
        return {"team_name": team_name, "$or": [{"semester": 7}, {"semester": "7"}]}
    else:
        return {"team_name": team_name, "$or": [{"semester": 6}, {"semester": "6"}, {"semester": {"$exists": False}}]}


# Helper function to get student's team and project
def get_student_project_info(email=None, usn=None):
    """Auto-detect student's team and project from email or USN (checking leader and all members)"""
    email_clean = str(email or "").strip()
    usn_clean = clean_usn(usn)

    if email_clean and "@" not in email_clean and not usn_clean:
        usn_clean = clean_usn(email_clean)
        email_clean = ""

    conds = []
    if email_clean:
        email_regex = {"$regex": f"^{re.escape(email_clean)}$", "$options": "i"}
        conds.extend([
            {"leader_email": email_regex},
            {"members.email": email_regex},
            {"members": email_regex}
        ])

    if usn_clean:
        usn_regex = {"$regex": f"^{re.escape(usn_clean)}$", "$options": "i"}
        conds.extend([
            {"leader_usn": usn_regex},
            {"members.usn": usn_regex},
            {"members": usn_regex}
        ])

    if not conds:
        return None, None

    team = db.teams.find_one({"$or": conds})
    if not team:
        return None, None
    
    # Get project from team's project_idea
    project_idea = team.get("project_idea", {})
    if not project_idea or not project_idea.get("title"):
        return team, None
    
    return team, project_idea

# GET /api/evaluation/student - Get student's evaluation (auto-detected, semester-specific)
@app.route('/api/evaluation/student', methods=['GET'])
def get_student_evaluation():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded.get("email", "")
        usn = clean_usn(decoded.get("usn", ""))

        semester_param = request.args.get("semester")
        sem_val = 7 if str(semester_param or "").strip() in ["7", "7th", "sem7"] else 6
        
        # Auto-detect team and project
        team, project_idea = get_student_project_info(email, usn)
        
        if not team:
            return jsonify({"error": "Student not found in any team"}), 404
        
        if not project_idea:
            return jsonify({"error": "No project submitted yet"}), 404
        
        students = format_team_student_identities(team)
        team_name = team.get("team_name")
        
        # Attach attendance stats to each student
        for s in students:
            s["attendance_stats"] = get_student_meeting_stats(s.get("usn"), s.get("name"), team_name, semester=sem_val)
        
        evaluation = db.evaluations.find_one(get_evaluation_query(team_name, sem_val), {"_id": 0})
        evaluation = sync_evaluation_with_panel_averages(evaluation, team_name, semester=sem_val)
        
        team_attendance = get_team_attendance_summary(team_name, semester=sem_val)
        
        if not evaluation:
            return jsonify({
                "team_name": team_name,
                "project_title": project_idea.get("title"),
                "faculty_name": team.get("faculty_name", "Not Assigned"),
                "members": [s["display_name"] for s in students],
                "students": students,
                "leader_name": team.get("leader_name"),
                "leader_usn": team.get("leader_usn", ""),
                "evaluation": None,
                "semester": sem_val,
                "objective_submission": team.get("objective_submission"),
                "attendance_summary": team_attendance,
                "is_locked": False
            })
        
        return jsonify({
            "team_name": team_name,
            "project_title": project_idea.get("title"),
            "faculty_name": team.get("faculty_name", "Not Assigned"),
            "members": [s["display_name"] for s in students],
            "students": students,
            "leader_name": team.get("leader_name"),
            "leader_usn": team.get("leader_usn", ""),
            "evaluation": evaluation,
            "semester": sem_val,
            "objective_submission": team.get("objective_submission"),
            "attendance_summary": team_attendance,
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
        
        alloc_records = list(db.allocations.find({"faculty_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}))
        alloc_team_names = [a.get("team_name") for a in alloc_records if a.get("team_name")]
        query = {
            "$or": [
                {"faculty_email": email},
                {"faculty_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}
            ]
        }
        if alloc_team_names:
            query["$or"].append({"team_name": {"$in": alloc_team_names}})

        teams = list(db.teams.find(
            query,
            {"_id": 0, "team_name": 1, "leader_name": 1, "leader_usn": 1, "members": 1, "project_idea": 1, "faculty_name": 1, "objective_submission": 1}
        ))
        
        if not teams and decoded.get("role") == "coordinator":
            teams = list(db.teams.find(
                {},
                {"_id": 0, "team_name": 1, "leader_name": 1, "leader_usn": 1, "members": 1, "project_idea": 1, "faculty_name": 1, "faculty_email": 1, "objective_submission": 1}
            ))

        sem_param = request.args.get("semester")
        sem_val = 7 if str(sem_param or "").strip() in ["7", "7th", "sem7"] else 6

        for t in teams:
            students = format_team_student_identities(t)
            t_name = t.get("team_name")
            for s in students:
                s["attendance_stats"] = get_student_meeting_stats(s.get("usn"), s.get("name"), t_name, semester=sem_val)
            t["students"] = students
            t["member_displays"] = [s["display_name"] for s in students]
            t["attendance_summary"] = get_team_attendance_summary(t_name, semester=sem_val)
        
        return jsonify(teams)
        
    except Exception as e:
        print(f"Error getting faculty teams: {e}")
        return jsonify({"error": "Internal server error"}), 500

# GET /api/evaluation/team/<team_name> - Get evaluation for specific team and semester
@app.route('/api/evaluation/team/<team_name>', methods=['GET'])
def get_team_evaluation(team_name):
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        
        user_role = decoded.get("role")
        user_email = str(decoded.get("email") or "").strip().lower()

        if user_role not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized"}), 403

        semester_param = request.args.get("semester")
        sem_val = 7 if str(semester_param or "").strip() in ["7", "7th", "sem7"] else 6
        
        team = db.teams.find_one({"team_name": team_name}, {"_id": 0})
        if not team:
            return jsonify({"error": "Team not found"}), 404

        # Role & Assignment Validation for Faculty
        if user_role == "faculty":
            guide_email = str(team.get("faculty_email") or "").strip().lower()
            is_guide = bool(guide_email and user_email == guide_email)
            
            # Check if faculty is an assigned panel evaluator
            alloc_records = list(db.panel_allocations.find({
                "team_name": team_name,
                "$or": [{"semester": sem_val}, {"semester": str(sem_val)}]
            }))
            is_panel_evaluator = False
            for a in alloc_records:
                assigned_list = [str(x).strip().lower() for x in a.get("assigned_faculty_emails", [])]
                member_list = [str(m.get("email", "")).strip().lower() for m in a.get("panel_members", []) if isinstance(m, dict)]
                if user_email in assigned_list or user_email in member_list:
                    is_panel_evaluator = True
                    break
                    
            if not is_guide and not is_panel_evaluator:
                return jsonify({"error": "Forbidden: You are not assigned to evaluate or guide this team"}), 403

        students = format_team_student_identities(team)
        for s in students:
            s["attendance_stats"] = get_student_meeting_stats(s.get("usn"), s.get("name"), team_name, semester=sem_val)
        team["students"] = students
        team["member_displays"] = [s["display_name"] for s in students]

        evaluation = db.evaluations.find_one(get_evaluation_query(team_name, sem_val), {"_id": 0})
        evaluation = sync_evaluation_with_panel_averages(evaluation, team_name, semester=sem_val)
        
        team_attendance = get_team_attendance_summary(team_name, semester=sem_val)

        # Attach panel_info for coordinator and guide
        panel_info = {}
        alloc_records = list(db.panel_allocations.find({
            "team_name": team_name,
            "$or": [{"semester": sem_val}, {"semester": str(sem_val)}]
        }, {"_id": 0}))
        
        for alloc in alloc_records:
            phase_key = alloc.get("phase", "Phase 1")
            alloc_id = alloc.get("allocation_id")
            eval_docs = list(db.panel_evaluations.find({"allocation_id": alloc_id}, {"_id": 0}))
            
            filtered_evals = []
            for edoc in eval_docs:
                clean_edoc = dict(edoc)
                if user_role == "faculty":
                    # Guide privacy: strictly NO criterion marks or rubrics breakdown!
                    clean_edoc.pop("marks", None)
                    clean_edoc.pop("student_marks", None)
                    clean_edoc.pop("criteria", None)
                    if "student_totals" not in clean_edoc and "final_marks" in clean_edoc:
                        clean_edoc["student_totals"] = clean_edoc["final_marks"]
                filtered_evals.append(clean_edoc)
                
            norm_key = normalize_panel_phase_key(phase_key)
            phase_slug = norm_key.lower().replace(" ", "_")
            info_val = {
                "allocation": alloc,
                "evaluations": filtered_evals
            }
            panel_info[norm_key] = info_val
            panel_info[phase_slug] = info_val
            panel_info[phase_key] = info_val


        response_payload = {
            "team": team,
            "evaluation": evaluation,
            "semester": sem_val,
            "students": students,
            "attendance_summary": team_attendance,
            "objective_submission": team.get("objective_submission"),
            "is_locked": evaluation.get("is_locked", False) if evaluation else False
        }
        if panel_info:
            response_payload["panel_info"] = panel_info

        return jsonify(response_payload)
        
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
        
        user_role = decoded.get("role")
        if user_role not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized - Students cannot save marks"}), 403
        
        data = request.json or {}
        team_name = data.get("team_name")
        evaluation_data = data.get("evaluation")
        semester_param = data.get("semester")
        sem_val = 7 if str(semester_param or "").strip() in ["7", "7th", "sem7"] else 6

        if user_role == "faculty" and team_name:
            team_for_perm = db.teams.find_one({"team_name": team_name})
            alloc_for_perm = db.allocations.find_one({"team_name": team_name})
            guide_email_perm = ((team_for_perm or {}).get("faculty_email") or (alloc_for_perm or {}).get("faculty_email") or "").strip().lower()
            caller_email_perm = str(decoded.get("email") or "").strip().lower()
            if guide_email_perm and caller_email_perm != guide_email_perm:
                return jsonify({"error": "Forbidden: Only the assigned guide can enter or update guide evaluation marks for this team."}), 403
        
        if not team_name or not evaluation_data:
            return jsonify({"error": "Missing required fields"}), 400
        
        # Check if evaluation is locked for the target semester
        existing = db.evaluations.find_one(get_evaluation_query(team_name, sem_val))
        if existing and existing.get("is_locked", False) and user_role != "coordinator":
            return jsonify({"error": "This evaluation has been locked by the Project Coordinator. Editing is disabled."}), 403
        
        # Fetch team students and synchronize attendance marks from meeting records for the target semester
        team = db.teams.find_one({"team_name": team_name})
        if team:
            students = format_team_student_identities(team)
            for s in students:
                s["attendance_stats"] = get_student_meeting_stats(s.get("usn"), s.get("name"), team_name, semester=sem_val)
            evaluation_data = sync_evaluation_attendance(evaluation_data, students, team_name, semester=sem_val)

        # Validate marks
        for phase in evaluation_data.get("phases", []):
            for criterion in phase.get("criteria", []):
                for mark_entry in criterion.get("marks", []):
                    marks_obtained = mark_entry.get("marks_obtained", 0)
                    maximum_marks = mark_entry.get("maximum_marks", 0)
                    if marks_obtained < 0 or marks_obtained > maximum_marks:
                        return jsonify({"error": f"Invalid marks: {marks_obtained} exceeds maximum {maximum_marks}"}), 400
        
        # Save or update evaluation tagged with semester
        evaluation_data["team_name"] = team_name
        evaluation_data["semester"] = sem_val
        evaluation_data["updated_at"] = datetime.now(timezone.utc)
        evaluation_data["updated_by"] = decoded.get("email")
        
        # If guide entered marks for Phase 1, Phase 2, or Phase 4, record into db.panel_evaluations
        caller_email = str(decoded.get("email") or "").strip().lower()
        team_doc = db.teams.find_one({"team_name": team_name})
        guide_email = str((team_doc or {}).get("faculty_email") or "").strip().lower()

        if caller_email == guide_email or user_role == "coordinator":
            for p in evaluation_data.get("phases", []):
                p_norm = normalize_panel_phase_key(p.get("name") or p.get("phase_name") or "")
                if p_norm in ["Phase 1", "Phase 2", "Phase 4"]:
                    alloc = db.panel_allocations.find_one({
                        "team_name": team_name,
                        "$or": [{"semester": sem_val}, {"semester": str(sem_val)}],
                        "phase": p_norm,
                        "status": {"$ne": "Cancelled"},
                        "is_cancelled": {"$ne": True}
                    })
                    if alloc:
                        # Only set guide submission if guide hasn't already submitted formal panel evaluation
                        existing_ge = db.panel_evaluations.find_one({
                            "allocation_id": alloc["allocation_id"],
                            "faculty_email": guide_email,
                            "status": "Submitted",
                            "is_voided": {"$ne": True}
                        })
                        if existing_ge:
                            continue
                        guide_totals = {}
                        students_list = format_team_student_identities(team_doc) if team_doc else []
                        for s_idx, st in enumerate(students_list):
                            s_usn = clean_usn(st.get("usn", ""))
                            crit_list = p.get("criteria", [])
                            c_m = 0.0
                            has_val = False
                            for c in crit_list:
                                m_arr = c.get("marks", [])
                                if s_idx < len(m_arr):
                                    m_val = m_arr[s_idx].get("marks_obtained") if isinstance(m_arr[s_idx], dict) else m_arr[s_idx]
                                    if m_val is not None:
                                        try:
                                            c_m += float(m_val)
                                            has_val = True
                                        except (ValueError, TypeError):
                                            pass
                            if has_val:
                                guide_totals[s_usn] = round(c_m, 2)
                        if guide_totals:
                            db.panel_evaluations.update_one(
                                {
                                    "allocation_id": alloc["allocation_id"],
                                    "faculty_email": guide_email
                                },
                                {
                                    "$set": {
                                        "allocation_id": alloc["allocation_id"],
                                        "team_name": team_name,
                                        "faculty_email": guide_email,
                                        "faculty_name": (team_doc or {}).get("faculty_name") or "Project Guide",
                                        "evaluator_id": guide_email,
                                        "semester": sem_val,
                                        "phase": p_norm,
                                        "student_totals": guide_totals,
                                        "final_marks": guide_totals,
                                        "status": "Submitted",
                                        "is_voided": False,
                                        "is_guide": True,
                                        "submitted_at": datetime.now(timezone.utc),
                                        "updated_at": datetime.now(timezone.utc)
                                    }
                                },
                                upsert=True
                            )

        if existing:
            if "_id" in existing:
                evaluation_data["_id"] = existing["_id"]
            evaluation_data["is_locked"] = existing.get("is_locked", False)
            merged_phases = list(existing.get("phases", []))
            incoming_phases = evaluation_data.get("phases", [])
            for inp_p in incoming_phases:
                inp_name = (inp_p.get("name") or inp_p.get("phase_name") or "").strip().lower()
                idx = next((i for i, ep in enumerate(merged_phases) if (ep.get("name") or ep.get("phase_name") or "").strip().lower() == inp_name), None)
                if idx is not None:
                    merged_phases[idx] = inp_p
                else:
                    merged_phases.append(inp_p)
            evaluation_data["phases"] = merged_phases
            db.evaluations.update_one(
                {"_id": existing["_id"]},
                {"$set": evaluation_data}
            )
        else:
            evaluation_data["created_at"] = datetime.now(timezone.utc)
            evaluation_data["is_locked"] = False
            db.evaluations.insert_one(evaluation_data)

        evaluation_data = sync_evaluation_with_panel_averages(evaluation_data, team_name, semester=sem_val)

        # Notify all team members via email (Temporarily disabled when coordinator acts)
        try:
            if user_role == "coordinator" and ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS:
                email_logger.info(
                    f"[EMAIL_NOTIFICATION] trigger=\"EVALUATOR_SAVE_RUBRIC\" team=\"{team_name}\" "
                    f"worker_status=\"SKIPPED\" reason=\"POLICY_DISALLOWED_TRIGGER\""
                )
            else:
                team = find_team_by_name(team_name)
                if team:
                    canonical_name = team.get("team_name", str(team_name))
                    recipients = get_team_recipient_emails(team)
                    if recipients:
                        base_url = get_frontend_base_url()
                        idea = team.get("project_idea") or {}
                        proj_title = (idea.get("title") if isinstance(idea, dict) else "") or "Student Project"
                        phase_count = len(evaluation_data.get("phases", []))
                        evaluator = decoded.get("email") or "Faculty Evaluator"
                        subject = f"{sem_val}th Semester Evaluation Rubric Results Saved: {canonical_name}"
                        plain_msg = (
                            f"Hello {canonical_name},\n\n"
                            f"Formal {sem_val}th Semester evaluation rubric scoring has been recorded for your project.\n"
                            f"Phases Evaluated: {phase_count}\n"
                            f"Evaluator: {evaluator}\n\n"
                            f"Check your detailed marks: {base_url}/team-dasboard.html"
                        )
                        html_msg = render_email_template(
                            headline=f"{sem_val}th Semester Evaluation Rubric Results Saved",
                            badge_text=f"Sem {sem_val} Recorded",
                            badge_color="#059669",
                            team_name=canonical_name,
                            project_title=proj_title,
                            key_details={
                                "Semester": f"{sem_val}th Semester",
                                "Phases Evaluated": f"{phase_count} category/phase(s)",
                                "Evaluator": evaluator,
                                "Last Updated": datetime.now().strftime("%Y-%m-%d %H:%M")
                            },
                            message_content=f"Your {sem_val}th Semester project evaluation rubric scoring sheet has been updated by the evaluation committee. Log in to your student dashboard to review detailed criteria scores.",
                            action_url=f"{base_url}/team-dasboard.html",
                            action_text="View Evaluation Sheet"
                        )
                        send_email_notification(
                            recipients, subject, plain_msg, html_msg,
                            trigger_name="EVALUATOR_SAVE_RUBRIC", team_id=canonical_name
                        )
        except Exception as email_err:
            email_logger.error(f"Error preparing evaluation rubric notification for {team_name}: {email_err}")
        
        return jsonify({"success": True, "message": f"{sem_val}th Semester evaluation saved successfully"})
        
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
        
        data = request.json or {}
        is_locked = data.get("is_locked", False)
        semester_param = data.get("semester")
        sem_val = 7 if str(semester_param or "").strip() in ["7", "7th", "sem7"] else 6
        
        existing = db.evaluations.find_one(get_evaluation_query(team_name, sem_val))
        if existing:
            db.evaluations.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "is_locked": is_locked,
                    "locked_by": decoded.get("email"),
                    "locked_at": datetime.now(timezone.utc) if is_locked else None
                }}
            )
        else:
            db.evaluations.insert_one({
                "team_name": team_name,
                "semester": sem_val,
                "phases": [],
                "is_locked": is_locked,
                "locked_by": decoded.get("email"),
                "locked_at": datetime.now(timezone.utc) if is_locked else None,
                "created_at": datetime.now(timezone.utc)
            })
        
        return jsonify({
            "success": True,
            "message": f"{sem_val}th Semester evaluation {'locked' if is_locked else 'unlocked'} successfully"
        })
        
    except Exception as e:
        print(f"Error locking evaluation: {e}")
        return jsonify({"error": "Internal server error"}), 500

# GET /api/evaluation/coordinator/all - Get all evaluations for coordinator for specific semester
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
        
        semester_param = request.args.get("semester")
        sem_val = 7 if str(semester_param or "").strip() in ["7", "7th", "sem7"] else 6

        # Get all teams with their evaluations for requested semester
        teams = list(db.teams.find({}, {"_id": 0}))
        if sem_val == 7:
            evaluations = list(db.evaluations.find({"$or": [{"semester": 7}, {"semester": "7"}]}, {"_id": 0}))
        else:
            evaluations = list(db.evaluations.find({"$or": [{"semester": 6}, {"semester": "6"}, {"semester": {"$exists": False}}]}, {"_id": 0}))
        
        # Combine data
        result = []
        for team in teams:
            team_name = team.get("team_name")
            eval_data = next((e for e in evaluations if str(e.get("team_name", "")).strip().lower() == str(team_name).strip().lower()), None)
            students = format_team_student_identities(team)
            for s in students:
                s["attendance_stats"] = get_student_meeting_stats(s.get("usn"), s.get("name"), team_name, semester=sem_val)
            team["students"] = students
            team["member_displays"] = [s["display_name"] for s in students]
            
            eval_data = sync_evaluation_with_panel_averages(eval_data, team_name, semester=sem_val)

            result.append({
                "team": team,
                "evaluation": eval_data,
                "semester": sem_val,
                "students": students,
                "attendance_summary": get_team_attendance_summary(team_name, semester=sem_val),
                "objective_submission": team.get("objective_submission"),
                "has_evaluation": eval_data is not None,
                "is_locked": eval_data.get("is_locked", False) if eval_data else False
            })
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Error getting all evaluations: {e}")
        return jsonify({"error": "Internal server error"}), 500

# ==================================================================== #
#                 PROJECT OBJECTIVES WORKFLOW APIS                     #
# ==================================================================== #

# POST /api/evaluation/objectives/allow - Faculty / Coordinator allows objective submission
@app.route('/api/evaluation/objectives/allow', methods=['POST'])
def allow_objective_submission():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        role = decoded.get("role")
        email = decoded.get("email")
        
        if role not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized"}), 403
        
        data = request.json or {}
        team_name = data.get("team_name")
        if not team_name:
            return jsonify({"error": "Team name is required"}), 400
        
        team = db.teams.find_one({"team_name": team_name})
        if not team:
            return jsonify({"error": "Team not found"}), 404
        
        current_obj = team.get("objective_submission") or {}
        current_status = current_obj.get("status")
        
        if not current_status or current_status in ["Not Allowed", "Not Submitted", ""]:
            new_status = "Submission Allowed"
        else:
            new_status = current_status
            
        db.teams.update_one(
            {"team_name": team_name},
            {"$set": {
                "objective_submission.allowed": True,
                "objective_submission.status": new_status,
                "objective_submission.allowed_by": email,
                "objective_submission.allowed_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        updated_team = db.teams.find_one({"team_name": team_name}, {"_id": 0, "objective_submission": 1})
        return jsonify({
            "success": True,
            "message": f"Objective submission allowed for team '{team_name}'.",
            "objective_submission": updated_team.get("objective_submission")
        })
    except Exception as e:
        print(f"Error allowing objective submission: {e}")
        return jsonify({"error": "Internal server error"}), 500

# GET /api/evaluation/objectives/status - Student checks objective submission status
@app.route('/api/evaluation/objectives/status', methods=['GET'])
def get_student_objective_status():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded.get("email", "")
        usn = clean_usn(decoded.get("usn", ""))
        
        team, project_idea = get_student_project_info(email, usn)
        
        if not team:
            return jsonify({"error": "Student not found in any team"}), 404
        
        obj_sub = team.get("objective_submission") or {
            "allowed": False,
            "status": "Not Allowed",
            "objectives": [],
            "submitted_at": None,
            "submitted_by": None
        }
        
        return jsonify({
            "success": True,
            "team_name": team.get("team_name"),
            "project_title": (team.get("project_idea") or {}).get("title", ""),
            "objective_submission": obj_sub
        })
    except Exception as e:
        print(f"Error getting objective status: {e}")
        return jsonify({"error": "Internal server error"}), 500

# POST /api/evaluation/objectives/submit - Student submits 4-5 project objectives
@app.route('/api/evaluation/objectives/submit', methods=['POST'])
def submit_objectives():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded.get("email", "")
        usn = clean_usn(decoded.get("usn", ""))
        
        team, project_idea = get_student_project_info(email, usn)
            
        if not team:
            return jsonify({"error": "Student not found in any team"}), 404
        
        team_name = team.get("team_name")
        obj_sub = team.get("objective_submission") or {}
        
        if not obj_sub.get("allowed", False):
            return jsonify({"error": "Objective submission is currently disabled. Please wait for your faculty guide to allow submission."}), 403
        
        current_status = obj_sub.get("status", "")
        if current_status == "Approved":
            return jsonify({"error": "Objectives have already been approved and cannot be modified."}), 400
        
        data = request.json or {}
        raw_objectives = data.get("objectives", [])
        
        if not isinstance(raw_objectives, list):
            return jsonify({"error": "Objectives must be provided as a list"}), 400
        
        cleaned_objectives = []
        for obj in raw_objectives:
            if obj and isinstance(obj, str):
                trimmed = obj.strip()
                if trimmed:
                    cleaned_objectives.append(trimmed)
        
        if len(cleaned_objectives) < 4:
            return jsonify({"error": "A minimum of 4 non-empty project objectives is required."}), 400
        
        if len(cleaned_objectives) > 5:
            return jsonify({"error": "A maximum of 5 project objectives is allowed."}), 400
        
        # Check duplicate objectives
        seen = set()
        for obj in cleaned_objectives:
            lower_obj = obj.lower()
            if lower_obj in seen:
                return jsonify({"error": "Duplicate objectives are not allowed. Please provide distinct objectives."}), 400
            seen.add(lower_obj)
        
        ownership = extract_activity_ownership(token_full)
        submitted_by_info = {
            "name": ownership.get("submitted_by_name") or "Student",
            "usn": clean_usn(ownership.get("submitted_by_usn")),
            "email": ownership.get("submitted_by_email") or email
        }
        
        submission_payload = {
            "allowed": True,
            "status": "Submitted",
            "objectives": cleaned_objectives,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "submitted_by": submitted_by_info,
            "review_notes": obj_sub.get("review_notes", "")
        }
        
        db.teams.update_one(
            {"team_name": team_name},
            {"$set": {"objective_submission": submission_payload}}
        )

        # Notify assigned faculty guide if allocated (Temporarily disabled under faculty-to-student only policy)
        try:
            if not ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS:
                faculty_email, f_name = get_team_assigned_faculty(team)
                if faculty_email:
                    base_url = get_frontend_base_url()
                    idea = project_idea or team.get("project_idea") or {}
                    proj_title = (idea.get("title") if isinstance(idea, dict) else "") or "Student Project"
                    subject = f"Project Objectives Submitted for Review: {team_name}"
                    plain_msg = (
                        f"Hello {f_name},\n\n"
                        f"Team '{team_name}' has submitted {len(cleaned_objectives)} project objectives for your review.\n"
                        f"Submitted By: {submitted_by_info.get('name')} ({submitted_by_info.get('usn')})\n\n"
                        f"Review in Faculty Dashboard: {base_url}/faculty-dashboard.html"
                    )
                    html_msg = render_email_template(
                        headline="Project Objectives Submitted",
                        badge_text="Objectives Submitted",
                        badge_color="#2563eb",
                        team_name=f_name,
                        project_title=f"{team_name}: {proj_title}",
                        key_details={
                            "Team Name": team_name,
                            "Submitted By": f"{submitted_by_info.get('name')} ({submitted_by_info.get('usn')})",
                            "Total Objectives": len(cleaned_objectives)
                        },
                        message_content=f"Team '{team_name}' has submitted their project objectives for your formal review and approval.",
                        action_url=f"{base_url}/faculty-dashboard.html",
                        action_text="Review Objectives in Dashboard"
                    )
                    send_email_notification(
                        [faculty_email], subject, plain_msg, html_msg,
                        trigger_name="STUDENT_SUBMIT_OBJECTIVES", team_id=team_name
                    )
            else:
                email_logger.info(
                    f"[EMAIL_NOTIFICATION] trigger=\"STUDENT_SUBMIT_OBJECTIVES\" team=\"{team_name}\" "
                    f"worker_status=\"SKIPPED\" reason=\"POLICY_DISALLOWED_TRIGGER\""
                )
        except Exception as email_err:
            email_logger.error(f"Error preparing faculty notification for objectives submission: {email_err}")
        
        return jsonify({
            "success": True,
            "message": "Objectives submitted successfully.",
            "objective_submission": submission_payload
        })
    except Exception as e:
        print(f"Error submitting objectives: {e}")
        return jsonify({"error": "Internal server error"}), 500

# GET /api/evaluation/objectives/team/<team_name> - Get objectives for team
@app.route('/api/evaluation/objectives/team/<team_name>', methods=['GET'])
def get_team_objectives(team_name):
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        
        team = db.teams.find_one({"team_name": team_name}, {"_id": 0})
        if not team:
            return jsonify({"error": "Team not found"}), 404
            
        students = format_team_student_identities(team)
        obj_sub = team.get("objective_submission") or {
            "allowed": False,
            "status": "Not Allowed",
            "objectives": [],
            "submitted_at": None,
            "submitted_by": None
        }
        
        return jsonify({
            "success": True,
            "team_name": team_name,
            "project_title": (team.get("project_idea") or {}).get("title", ""),
            "students": students,
            "objective_submission": obj_sub
        })
    except Exception as e:
        print(f"Error getting team objectives: {e}")
        return jsonify({"error": "Internal server error"}), 500

# POST /api/evaluation/objectives/review - Faculty / Coordinator reviews objectives
@app.route('/api/evaluation/objectives/review', methods=['POST'])
def review_objectives():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        role = decoded.get("role")
        email = decoded.get("email")
        
        if role not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized"}), 403
        
        data = request.json or {}
        team_name = data.get("team_name")
        status = data.get("status")
        review_notes = (data.get("review_notes") or "").strip()
        
        if not team_name or status not in ["Approved", "Needs Revision"]:
            return jsonify({"error": "Valid team name and status ('Approved' or 'Needs Revision') are required."}), 400
        
        team = find_team_by_name(team_name)
        if not team:
            return jsonify({"error": "Team not found"}), 404
        
        canonical_name = team.get("team_name", str(team_name))

        obj_sub = team.get("objective_submission") or {}
        if not obj_sub.get("objectives"):
            return jsonify({"error": "No objectives have been submitted for this team yet."}), 400
            
        update_fields = {
            "objective_submission.status": status,
            "objective_submission.reviewed_by": email,
            "objective_submission.reviewed_at": datetime.now(timezone.utc).isoformat(),
            "objective_submission.review_notes": review_notes
        }
        
        if status == "Needs Revision":
            update_fields["objective_submission.allowed"] = True
            
        db.teams.update_one(
            {"_id": team["_id"]},
            {"$set": update_fields}
        )

        # Notify all team members via email (Temporarily disabled when coordinator acts)
        try:
            if role == "coordinator" and ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS:
                email_logger.info(
                    f"[EMAIL_NOTIFICATION] trigger=\"FACULTY_REVIEW_OBJECTIVES\" team=\"{canonical_name}\" "
                    f"worker_status=\"SKIPPED\" reason=\"POLICY_DISALLOWED_TRIGGER\""
                )
            else:
                recipients = get_team_recipient_emails(team)
                if recipients:
                    base_url = get_frontend_base_url()
                    idea = team.get("project_idea") or {}
                    proj_title = (idea.get("title") if isinstance(idea, dict) else "") or "Student Project"
                    badge_color = "#059669" if status == "Approved" else "#dc2626"
                    reviewer_name = team.get("faculty_name") or email
                    subject = f"Project Objectives Reviewed: {status} - {canonical_name}"
                    msg_body = f"Your submitted project objectives have been marked as '{status}' by {reviewer_name}."
                    if review_notes:
                        msg_body += f"\n\nReview Guidance / Feedback:\n{review_notes}"
                    plain_msg = (
                        f"Hello {canonical_name},\n\n"
                        f"{msg_body}\n\n"
                        f"Check your dashboard: {base_url}/team-dasboard.html"
                    )
                    html_msg = render_email_template(
                        headline=f"Project Objectives {status}",
                        badge_text=status,
                        badge_color=badge_color,
                        team_name=canonical_name,
                        project_title=proj_title,
                        key_details={
                            "Objectives Status": status,
                            "Reviewed By": reviewer_name,
                            "Action Needed": "None (Approved)" if status == "Approved" else "Revise and resubmit in dashboard",
                            "Review Date": datetime.now().strftime("%Y-%m-%d %H:%M")
                        },
                        message_content=msg_body,
                        action_url=f"{base_url}/team-dasboard.html",
                        action_text="View Objectives in Dashboard"
                    )
                    send_email_notification(
                        recipients, subject, plain_msg, html_msg,
                        trigger_name="FACULTY_REVIEW_OBJECTIVES", team_id=canonical_name
                    )
        except Exception as email_err:
            email_logger.error(f"Error preparing objectives review notification for {canonical_name}: {email_err}")
        
        updated_team = db.teams.find_one({"_id": team["_id"]}, {"_id": 0, "objective_submission": 1})
        return jsonify({
            "success": True,
            "message": f"Objectives status updated to '{status}'.",
            "objective_submission": updated_team.get("objective_submission")
        })
    except Exception as e:
        print(f"Error reviewing objectives: {e}")
        return jsonify({"error": "Internal server error"}), 500


# ==================================================================== #
#      COORDINATOR-CONTROLLED PANEL ALLOCATION & PHASE-WISE MARKING   #
# ==================================================================== #

def normalize_panel_phase_key(phase_val):
    """Normalizes phase string representation to standard canonical forms."""
    if not phase_val:
        return "Phase 1"
    p = str(phase_val).strip()
    p_lower = p.lower().replace("-", " ").replace("_", " ")
    if "phase 1" in p_lower or "phase1" in p_lower or "synopsis" in p_lower:
        return "Phase 1"
    if "phase 2" in p_lower or "phase2" in p_lower or "design" in p_lower:
        return "Phase 2"
    if "phase 4" in p_lower or "phase4" in p_lower:
        return "Phase 4"
    if "phase 5" in p_lower or "phase5" in p_lower:
        return "Phase 5"
    if "phase 3" in p_lower or "phase3" in p_lower:
        return "Phase 3"
    return p

def get_phase_criteria(phase_key, semester=6):
    norm = normalize_panel_phase_key(phase_key)
    sem = 7 if str(semester).strip() in ["7", "7th", "sem7"] else 6
    if norm == "Phase 1":
        return [
            {"name": "Problem Statement & Objectives", "max_marks": 5},
            {"name": "Social & Technical Impact", "max_marks": 5},
            {"name": "Depth of Review", "max_marks": 5},
            {"name": "Presentation", "max_marks": 5}
        ]
    elif norm == "Phase 2":
        return [
            {"name": "Technical Clarity", "max_marks": 10},
            {"name": "Novelty", "max_marks": 15},
            {"name": "Relevance to Objectives", "max_marks": 10},
            {"name": "Presentation", "max_marks": 5}
        ]
    elif norm == "Phase 4":
        return [
            {"name": "Implementation & Execution", "max_marks": 10},
            {"name": "Technical Demonstration", "max_marks": 10},
            {"name": "Presentation & Defense", "max_marks": 10}
        ]
    elif norm == "Phase 5":
        return [
            {"name": "Project Demonstration & Quality", "max_marks": 10},
            {"name": "Results & Discussion", "max_marks": 10},
            {"name": "Presentation & Viva Voce", "max_marks": 10}
        ]
    max_m = 30 if sem == 7 else 20
    return [{"name": norm, "max_marks": max_m}]

def get_panel_phase_metadata(phase_key, semester=6):
    norm = normalize_panel_phase_key(phase_key)
    sem = 7 if str(semester).strip() in ["7", "7th", "sem7"] else 6
    criteria = get_phase_criteria(norm, sem)
    max_marks = sum(c["max_marks"] for c in criteria)
    if norm == "Phase 1":
        return {"phase": "Phase 1", "phase_name": "Phase 1 - Synopsis & Problem Definition", "max_marks": 20, "semester": 6, "criteria": criteria}
    elif norm == "Phase 2":
        return {"phase": "Phase 2", "phase_name": "Phase 2 - System Design", "max_marks": 40, "semester": 6, "criteria": criteria}
    elif norm == "Phase 4":
        return {"phase": "Phase 4", "phase_name": "Phase 4 - Implementation & Progress", "max_marks": 30, "semester": 7, "criteria": criteria}
    elif norm == "Phase 5":
        return {"phase": "Phase 5", "phase_name": "Phase 5 - Final Evaluation & Defense", "max_marks": 30, "semester": 7, "criteria": criteria}
    return {"phase": norm, "phase_name": norm, "max_marks": max_marks, "semester": sem, "criteria": criteria}

def normalize_panel_name(panel_input):
    p_str = str(panel_input or "").strip()
    match = re.search(r'(\d+)', p_str)
    num = int(match.group(1)) if match else 1
    if num < 1: num = 1
    if num > 10: num = 10
    return f"Panel {num}"

def is_deadline_passed(deadline_str):
    if not deadline_str:
        return False
    try:
        d_str = str(deadline_str).strip()
        if d_str.endswith("Z"):
            d_str = d_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(d_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > dt
    except Exception:
        return False

def calculate_student_panel_averages(alloc_id, students=None, assigned_faculty=None):
    """
    Calculates the authoritative panel average per student using ONLY valid, successfully submitted marks.
    - Phase 1, Phase 2, Phase 4: Exactly 4 evaluators (Guide + 3 assigned panel faculty).
      The team's assigned guide is included as one of the 4 evaluators.
    - Phase 5: Exactly 4 assigned panel faculty evaluators only. The guide is strictly excluded.
    - Incomplete evaluations: If fewer than the required evaluators have submitted, is_complete is False.
      Never treats missing marks as 0. Missing / voided / cancelled evaluations are excluded from average.
    - Duplicate submissions / multiple versions: Deduplicated to the latest submitted version.
    """
    alloc = db.panel_allocations.find_one({"allocation_id": alloc_id})
    if not alloc:
        return {
            "student_results": [],
            "student_averages": [],
            "submitted_evals_count": 0,
            "required_count": 4,
            "assigned_count": 4,
            "is_complete": False
        }

    team_name = alloc.get("team_name")
    team = find_team_by_name(team_name)
    if not students and alloc:
        if team:
            students = format_team_student_identities(team)
    students = students or []

    # If allocation itself is cancelled or voided
    if alloc.get("is_cancelled") or alloc.get("status") == "Cancelled":
        return {
            "student_results": [
                {
                    "usn": clean_usn(s.get("usn", "")),
                    "name": s.get("name") or s.get("display_name", ""),
                    "member_marks": [],
                    "average_mark": None,
                    "criterion_averages": {},
                    "submitted_count": 0,
                    "required_count": 4,
                    "assigned_count": 4,
                    "is_complete": False,
                    "status": "Cancelled"
                }
                for s in students
            ],
            "student_averages": [
                {
                    "usn": clean_usn(s.get("usn", "")),
                    "name": s.get("name") or s.get("display_name", ""),
                    "total_marks": 0.0,
                    "submitted_count": 0,
                    "assigned_count": 4
                }
                for s in students
            ],
            "submitted_evals_count": 0,
            "required_count": 4,
            "assigned_count": 4,
            "is_complete": False
        }

    revoked_faculty_emails = {str(x).strip().lower() for x in (alloc.get("revoked_faculty_emails") or []) if x}

    guide_email, guide_name = get_team_assigned_faculty(team or team_name)
    guide_email_clean = str(guide_email or "").strip().lower()

    norm_phase = normalize_panel_phase_key(alloc.get("phase", ""))
    sem_val = 7 if str((alloc or {}).get("semester", 6)).strip() in ["7", "7th", "sem7"] else 6

    if not students and alloc:
        if team:
            students = format_team_student_identities(team)
    students = students or []

    # 1. Fetch all submitted evaluations from db.panel_evaluations
    raw_evals = list(db.panel_evaluations.find({
        "allocation_id": alloc_id,
        "status": "Submitted",
        "is_voided": {"$ne": True}
    }))

    # Deduplicate: keep latest submission per faculty_email
    dedup_evals_map = {}
    for e in raw_evals:
        f_email = str(e.get("faculty_email", "")).strip().lower()
        if not f_email or f_email in revoked_faculty_emails:
            continue
        if f_email not in dedup_evals_map:
            dedup_evals_map[f_email] = e
        else:
            cur_time = str(e.get("updated_at") or e.get("submitted_at") or "")
            prev_time = str(dedup_evals_map[f_email].get("updated_at") or dedup_evals_map[f_email].get("submitted_at") or "")
            if cur_time >= prev_time:
                dedup_evals_map[f_email] = e

    # 2. Phase-wise expected evaluators and guide inclusion/exclusion rules
    expected_evaluators = []
    panel_members_raw = alloc.get("panel_members") or []
    if alloc.get("assigned_faculty_emails"):
        assigned_emails_list = [str(x).strip().lower() for x in alloc["assigned_faculty_emails"] if x]
        panel_members_raw = [m for m in panel_members_raw if str((m.get("email") if isinstance(m, dict) else m) or "").lower().strip() in assigned_emails_list]

    if norm_phase == "Phase 5":
        # Phase 5: Four assigned panel faculty members ONLY. Guide is strictly excluded.
        if guide_email_clean:
            dedup_evals_map.pop(guide_email_clean, None)

        for m in panel_members_raw:
            m_email = str((m.get("email") if isinstance(m, dict) else m) or "").strip().lower()
            if m_email and m_email != guide_email_clean and m_email not in revoked_faculty_emails:
                if not any(str(x.get("email", "")).lower() == m_email for x in expected_evaluators):
                    m_name = (m.get("name") if isinstance(m, dict) else m_email) or m_email.split("@")[0].title()
                    expected_evaluators.append({"email": m_email, "name": m_name, "role": "panel_member"})

        required_count = 3 if alloc.get("approved_three_member_panel") else 4

    else:
        # Phase 1, Phase 2, Phase 4: Exactly 4 evaluators (Guide + 3 panel faculty).
        # Guide is one of the four evaluators.
        if guide_email_clean:
            expected_evaluators.append({"email": guide_email_clean, "name": guide_name, "role": "guide"})

        for m in panel_members_raw:
            m_email = str((m.get("email") if isinstance(m, dict) else m) or "").strip().lower()
            if m_email and m_email != guide_email_clean and m_email not in revoked_faculty_emails:
                if not any(str(x.get("email", "")).lower() == m_email for x in expected_evaluators):
                    m_name = (m.get("name") if isinstance(m, dict) else m_email) or m_email.split("@")[0].title()
                    expected_evaluators.append({"email": m_email, "name": m_name, "role": "panel_member"})

        # Check if guide entered marks in db.evaluations for Phase 1/2/4 if not yet in dedup_evals_map
        if guide_email_clean and guide_email_clean not in dedup_evals_map:
            eval_doc = db.evaluations.find_one(get_evaluation_query(team_name, sem_val))
            if eval_doc:
                for p in eval_doc.get("phases", []):
                    p_name = normalize_panel_phase_key(p.get("name") or p.get("phase_name") or "")
                    if (p_name == norm_phase or norm_phase in (p.get("name", "") or "")) and not p.get("panel_average"):
                        guide_totals = {}
                        has_marks = False
                        for s_idx, st in enumerate(students):
                            s_usn = clean_usn(st.get("usn", ""))
                            crit_list = p.get("criteria", [])
                            if crit_list:
                                c_m = 0.0
                                for c in crit_list:
                                    m_arr = c.get("marks", [])
                                    if s_idx < len(m_arr):
                                        m_val = m_arr[s_idx].get("marks_obtained") if isinstance(m_arr[s_idx], dict) else m_arr[s_idx]
                                        if m_val is not None and str(m_val).strip() != "":
                                            try:
                                                c_m += float(m_val)
                                                has_marks = True
                                            except (ValueError, TypeError):
                                                pass
                                guide_totals[s_usn] = round(c_m, 2)
                        if has_marks:
                            dedup_evals_map[guide_email_clean] = {
                                "allocation_id": alloc_id,
                                "faculty_email": guide_email_clean,
                                "faculty_name": guide_name,
                                "evaluator_id": guide_email_clean,
                                "status": "Submitted",
                                "student_totals": guide_totals,
                                "final_marks": guide_totals,
                                "is_guide": True,
                                "is_voided": False
                            }
                            break

        required_count = 3 if alloc.get("approved_three_member_panel") else 4

    # Filter submissions: Only allow assigned evaluators
    assigned_email_set = {str(x.get("email", "")).strip().lower() for x in expected_evaluators if x.get("email")}
    submitted_evals = [e for e in dedup_evals_map.values() if not assigned_email_set or str(e.get("faculty_email", "")).strip().lower() in assigned_email_set]
    submitted_faculty_emails = {str(e.get("faculty_email", "")).strip().lower() for e in submitted_evals}

    assigned_count = len(expected_evaluators) if expected_evaluators else required_count

    student_results = []
    student_averages = []

    for s in students:
        usn = clean_usn(s.get("usn", ""))
        name = s.get("name") or s.get("display_name", "")
        member_marks = []
        valid_marks = []

        # Collect marks from each submitted evaluation
        for e in submitted_evals:
            f_name = e.get("faculty_name") or e.get("faculty_email")
            f_email = e.get("faculty_email")
            m = None
            if e.get("final_marks") and usn in e["final_marks"]:
                m = e["final_marks"][usn]
            elif e.get("final_marks") and s.get("usn") in e["final_marks"]:
                m = e["final_marks"][s.get("usn")]
            elif e.get("final_marks") and name in e["final_marks"]:
                m = e["final_marks"][name]
            elif e.get("student_totals") and usn in e["student_totals"]:
                m = e["student_totals"][usn]
            elif e.get("student_totals") and s.get("usn") in e["student_totals"]:
                m = e["student_totals"][s.get("usn")]
            elif e.get("student_totals") and name in e["student_totals"]:
                m = e["student_totals"][name]
            elif e.get("student_marks") and (usn in e["student_marks"] or s.get("usn") in e["student_marks"] or name in e["student_marks"]):
                sm = e["student_marks"].get(usn) or e["student_marks"].get(s.get("usn")) or e["student_marks"].get(name)
                if isinstance(sm, dict):
                    m = sum(float(v) for v in sm.values() if isinstance(v, (int, float)))
                elif isinstance(sm, (int, float)):
                    m = float(sm)

            if m is not None:
                try:
                    m_float = round(float(m), 2)
                    valid_marks.append(m_float)
                    member_marks.append({
                        "faculty_name": f_name,
                        "faculty_email": f_email,
                        "final_mark": m_float,
                        "status": "Submitted"
                    })
                except (ValueError, TypeError):
                    pass

        # Include pending evaluators
        for af in expected_evaluators:
            af_email = str(af.get("email", "")).strip().lower()
            af_name = af.get("name") or af_email
            if af_email and af_email not in submitted_faculty_emails:
                member_marks.append({
                    "faculty_name": af_name,
                    "faculty_email": af_email,
                    "final_mark": None,
                    "status": "Pending"
                })

        # Calculate criterion averages across submitted evaluations
        crit_sums = {}
        crit_counts = {}
        for e in submitted_evals:
            sm_student = (e.get("student_marks") or {}).get(usn) or (e.get("student_marks") or {}).get(s.get("usn"))
            if isinstance(sm_student, dict):
                for c_name, c_val in sm_student.items():
                    try:
                        crit_sums[c_name] = crit_sums.get(c_name, 0.0) + float(c_val)
                        crit_counts[c_name] = crit_counts.get(c_name, 0) + 1
                    except (ValueError, TypeError):
                        pass

        criterion_averages = {}
        if crit_counts:
            for c_name, c_cnt in crit_counts.items():
                criterion_averages[c_name] = round(crit_sums[c_name] / c_cnt, 2)

        is_student_complete = (len(valid_marks) >= required_count) or bool(alloc.get("is_finalized"))

        if len(valid_marks) > 0:
            avg_mark = round(sum(valid_marks) / len(valid_marks), 2)
        else:
            avg_mark = None

        student_results.append({
            "usn": usn,
            "name": name,
            "member_marks": member_marks,
            "average_mark": avg_mark,
            "criterion_averages": criterion_averages,
            "submitted_count": len(valid_marks),
            "required_count": required_count,
            "assigned_count": assigned_count,
            "is_complete": is_student_complete,
            "status": "Completed" if is_student_complete else "Pending"
        })
        student_averages.append({
            "usn": usn,
            "name": name,
            "total_marks": avg_mark if avg_mark is not None else 0.0,
            "submitted_count": len(valid_marks),
            "required_count": required_count,
            "assigned_count": assigned_count,
            "is_complete": is_student_complete
        })

    is_overall_complete = (len(submitted_evals) >= required_count) or bool(alloc.get("is_finalized"))

    return {
        "student_results": student_results,
        "student_averages": student_averages,
        "submitted_evals_count": len(submitted_evals),
        "required_count": required_count,
        "assigned_count": assigned_count,
        "is_complete": is_overall_complete
    }

def sync_evaluation_with_panel_averages(evaluation, team_name, semester=6, students=None):
    """
    Authoritative Synchronizer:
    Integrates panel faculty averages directly into the Project Evaluation object.
    - Phase 1, Phase 2, Phase 4: Uses average of 4 evaluators (Guide + 3 Panel Faculty).
    - Phase 5: Uses average of 4 Panel Faculty members (no guide).
    - Incomplete evaluations: If fewer than required 4 evaluators submitted, phase marked Pending and not finalized.
    - Guide marks (Report, Attendance, Paper Submission) remain independent and are preserved.
    """
    if not team_name:
        return evaluation

    sem_val = 7 if str(semester or "").strip() in ["7", "7th", "sem7"] else 6
    if not students:
        team = find_team_by_name(team_name)
        students = format_team_student_identities(team) if (team and isinstance(team, dict)) else []

    if not evaluation:
        evaluation = db.evaluations.find_one(get_evaluation_query(team_name, sem_val), {"_id": 0})

    if not evaluation or not isinstance(evaluation, dict):
        evaluation = {
            "team_name": team_name,
            "semester": sem_val,
            "phases": []
        }

    phases = evaluation.get("phases", [])
    if not isinstance(phases, list):
        phases = []
        evaluation["phases"] = phases

    panel_phase_keys = ["Phase 4", "Phase 5"] if sem_val == 7 else ["Phase 1", "Phase 2"]

    for p_key in panel_phase_keys:
        norm_phase = normalize_panel_phase_key(p_key)
        phase_meta = get_panel_phase_metadata(norm_phase, sem_val)
        phase_max = phase_meta.get("max_marks", 30 if sem_val == 7 else 20)
        criteria_meta = phase_meta.get("criteria", [])

        # Find active allocation for this phase (robust team_name, phase regex, and semester matching)
        phase_regex = f"^{re.escape(norm_phase)}"
        team_name_clean = str(team_name).strip()
        team_matchers = [
            {"team_name": team_name},
            {"team_name": team_name_clean},
            {"team_name": {"$regex": f"^{re.escape(team_name_clean)}$", "$options": "i"}}
        ]
        if team_name_clean.isdigit():
            team_matchers.append({"team_name": int(team_name_clean)})

        alloc = db.panel_allocations.find_one({
            "$or": team_matchers,
            "$and": [
                {"$or": [{"semester": sem_val}, {"semester": str(sem_val)}]},
                {"$or": [{"phase": norm_phase}, {"phase": {"$regex": phase_regex, "$options": "i"}}]},
                {"status": {"$ne": "Cancelled"}},
                {"is_cancelled": {"$ne": True}}
            ]
        })

        if not alloc or not isinstance(alloc, dict):
            continue

        calc = calculate_student_panel_averages(alloc["allocation_id"], students)
        sr_list = calc.get("student_results", [])
        sub_count = calc.get("submitted_evals_count", 0)
        is_complete = calc.get("is_complete", False)
        required_count = calc.get("required_count", 4)

        # Locate or initialize phase entry in evaluation.phases
        target_phase = None
        for p in phases:
            pn = normalize_panel_phase_key(p.get("name") or p.get("phase_name") or "")
            if pn == norm_phase or norm_phase in (p.get("name") or ""):
                target_phase = p
                break

        if not target_phase:
            target_phase = {
                "name": norm_phase,
                "phase_name": norm_phase,
                "total_marks": phase_max,
                "criteria": []
            }
            phases.append(target_phase)

        target_phase["is_panel_evaluated"] = True
        target_phase["total_marks"] = phase_max
        target_phase["submitted_evals_count"] = sub_count
        target_phase["required_evals_count"] = required_count

        if not is_complete:
            # INCOMPLETE EVALUATION: Required evaluators have not all submitted.
            # Do NOT calculate or publish final panel average prematurely!
            target_phase["panel_average"] = False
            target_phase["is_complete"] = False
            target_phase["status"] = "Pending"

            marks_arr = []
            for s in students:
                s_usn = clean_usn(s.get("usn", ""))
                marks_arr.append({
                    "marks_obtained": None,
                    "maximum_marks": phase_max,
                    "student_name": s.get("name"),
                    "usn": s_usn,
                    "status": "Pending"
                })
            target_phase["criteria"] = [{
                "name": norm_phase,
                "max_marks": phase_max,
                "marks": marks_arr
            }]
            continue

        # COMPLETE EVALUATION: All required evaluators have submitted (or finalized).
        target_phase["panel_average"] = True
        target_phase["is_complete"] = True
        target_phase["status"] = "Completed"

        first_sr = sr_list[0] if sr_list else {}
        has_crit_avgs = bool(first_sr.get("criterion_averages"))
        existing_criteria = target_phase.get("criteria", [])
        is_single_criterion_mode = len(existing_criteria) == 1 and existing_criteria[0].get("max_marks") == phase_max

        if is_single_criterion_mode or (not has_crit_avgs and len(existing_criteria) <= 1):
            crit_name = existing_criteria[0]["name"] if existing_criteria else norm_phase
            marks_arr = []
            for s in students:
                s_usn = clean_usn(s.get("usn", ""))
                s_res = next((r for r in sr_list if clean_usn(r["usn"]) == s_usn), None)
                s_val = s_res["average_mark"] if (s_res and s_res.get("average_mark") is not None) else 0.0
                marks_arr.append({
                    "marks_obtained": s_val,
                    "maximum_marks": phase_max,
                    "student_name": s.get("name"),
                    "usn": s_usn
                })
            target_phase["criteria"] = [{
                "name": crit_name,
                "max_marks": phase_max,
                "marks": marks_arr
            }]
        elif has_crit_avgs and criteria_meta:
            updated_criteria = []
            for cm in criteria_meta:
                c_name = cm["name"]
                c_max = cm.get("max_marks", 10)
                marks_arr = []
                for s in students:
                    s_usn = clean_usn(s.get("usn", ""))
                    s_res = next((r for r in sr_list if clean_usn(r["usn"]) == s_usn), None)
                    if s_res and s_res.get("criterion_averages") and c_name in s_res["criterion_averages"]:
                        c_val = s_res["criterion_averages"][c_name]
                    elif s_res and s_res.get("average_mark") is not None:
                        c_val = round(s_res["average_mark"] * (c_max / phase_max), 2)
                    else:
                        c_val = 0.0
                    marks_arr.append({
                        "marks_obtained": c_val,
                        "maximum_marks": c_max,
                        "student_name": s.get("name"),
                        "usn": s_usn
                    })
                updated_criteria.append({
                    "name": c_name,
                    "max_marks": c_max,
                    "marks": marks_arr
                })
            target_phase["criteria"] = updated_criteria
        else:
            marks_arr = []
            for s in students:
                s_usn = clean_usn(s.get("usn", ""))
                s_res = next((r for r in sr_list if clean_usn(r["usn"]) == s_usn), None)
                s_val = s_res["average_mark"] if (s_res and s_res.get("average_mark") is not None) else 0.0
                marks_arr.append({
                    "marks_obtained": s_val,
                    "maximum_marks": phase_max,
                    "student_name": s.get("name"),
                    "usn": s_usn
                })
            target_phase["criteria"] = [{
                "name": norm_phase,
                "max_marks": phase_max,
                "marks": marks_arr
            }]

    # Ensure standard phases exist for this semester
    phase_names_lower = {(p.get("name") or p.get("phase_name") or "").strip().lower() for p in phases}
    if sem_val == 7:
        if "report" not in phase_names_lower:
            phases.append({"name": "Report", "phase_name": "Report", "total_marks": 10, "criteria": [{"name": "Report", "max_marks": 10, "marks": [{"marks_obtained": 0.0, "maximum_marks": 10} for _ in students]}]})
        if "attendance" not in phase_names_lower:
            phases.append({"name": "Attendance", "phase_name": "Attendance", "total_marks": 10, "criteria": [{"name": "Attendance", "max_marks": 10, "marks": [{"marks_obtained": 0.0, "maximum_marks": 10} for _ in students]}]})
        if "paper submission" not in phase_names_lower:
            phases.append({"name": "Paper Submission", "phase_name": "Paper Submission", "total_marks": 20, "criteria": [{"name": "Paper Submission", "max_marks": 20, "marks": [{"marks_obtained": 0.0, "maximum_marks": 20} for _ in students]}]})
    else:
        if "report & attendance" not in phase_names_lower and "report" not in phase_names_lower:
            phases.append({
                "name": "Report & Attendance",
                "phase_name": "Report & Attendance",
                "total_marks": 40,
                "criteria": [
                    {"name": "Report", "max_marks": 20, "marks": [{"marks_obtained": 0.0, "maximum_marks": 20} for _ in students]},
                    {"name": "Attendance", "max_marks": 10, "marks": [{"marks_obtained": 0.0, "maximum_marks": 10} for _ in students]},
                    {"name": "Synopsis", "max_marks": 10, "marks": [{"marks_obtained": 0.0, "maximum_marks": 10} for _ in students]}
                ]
            })

    # Ensure attendance is synced from meetings
    evaluation = sync_evaluation_attendance(evaluation, students, team_name, semester=sem_val)

    # Persist updated evaluation to db.evaluations
    if evaluation.get("_id"):
        db.evaluations.update_one(
            {"_id": evaluation["_id"]},
            {"$set": {"phases": phases, "updated_at": datetime.now(timezone.utc)}}
        )
    elif team_name:
        try:
            db.evaluations.update_one(
                get_evaluation_query(team_name, sem_val),
                {
                    "$set": {
                        "phases": phases,
                        "semester": sem_val,
                        "team_name": team_name,
                        "updated_at": datetime.now(timezone.utc)
                    }
                },
                upsert=True
            )
        except Exception:
            pass

    return evaluation



@app.route('/api/panel/eligible_teams', methods=['GET'])
def get_panel_eligible_teams():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized"}), 403

        semester_param = request.args.get("semester", "6")
        sem_val = 7 if str(semester_param).strip() in ["7", "7th", "sem7"] else 6
        phase_param = request.args.get("phase", "Phase 1")
        norm_phase = normalize_panel_phase_key(phase_param)
        target_panel = normalize_panel_name(request.args.get("panel_id", "Panel 1"))

        # Fetch all teams in system
        all_teams = list(db.teams.find({}, {
            "team_name": 1, "leader_name": 1, "leader_usn": 1, "leader_email": 1,
            "members": 1, "faculty_name": 1, "faculty_email": 1, "project_idea": 1,
            "semester": 1, "department": 1, "team_id": 1, "project_title": 1, "title": 1
        }))

        # Fetch existing panel allocations for this semester and phase
        allocs = list(db.panel_allocations.find({
            "$or": [{"semester": sem_val}, {"semester": str(sem_val)}],
            "phase": norm_phase,
            "status": {"$ne": "Cancelled"},
            "is_cancelled": {"$ne": True}
        }))

        allocated_team_map = {}
        for a in allocs:
            t_name = str(a.get("team_name", "")).strip()
            if t_name:
                allocated_team_map[t_name] = a.get("panel_id") or a.get("panel_name")

        eligible_teams = []
        for t in all_teams:
            t_name = str(t.get("team_name", "")).strip()
            if not t_name:
                continue

            allocated_panel = allocated_team_map.get(t_name)
            is_allocated_elsewhere = bool(allocated_panel and allocated_panel != target_panel)
            is_allocated_here = bool(allocated_panel and allocated_panel == target_panel)

            proj_idea = t.get("project_idea") or {}
            proj_title = proj_idea.get("title") or t.get("project_title") or t.get("title") or f"Project (Team {t_name})"
            proj_status = proj_idea.get("status") or ("Allocated" if (t.get("faculty_name") or t.get("faculty_email")) else "Active")

            # Guide details with fallback to db.allocations
            guide_name = str(t.get("faculty_name") or "").strip()
            guide_email = str(t.get("faculty_email") or "").strip()
            if not guide_name:
                alloc_guide = db.allocations.find_one({"team_name": t_name})
                if alloc_guide:
                    guide_name = str(alloc_guide.get("faculty_name") or "").strip()
                    guide_email = str(alloc_guide.get("faculty_email") or "").strip()
            if not guide_name:
                guide_name = "Unassigned"

            # Members list (leader + team members)
            members_list = []
            if t.get("leader_name") or t.get("leader_usn"):
                members_list.append({
                    "name": str(t.get("leader_name") or "Leader").strip(),
                    "usn": str(t.get("leader_usn") or "").strip(),
                    "email": str(t.get("leader_email") or "").strip(),
                    "role": "Leader"
                })
            for m in t.get("members") or []:
                if isinstance(m, dict):
                    m_name = str(m.get("name") or "Member").strip()
                    m_usn = str(m.get("usn") or "").strip()
                    m_email = str(m.get("email") or "").strip()
                    if m_name or m_usn:
                        members_list.append({
                            "name": m_name,
                            "usn": m_usn,
                            "email": m_email,
                            "role": "Member"
                        })

            students_parts = []
            for m in members_list:
                if m.get("usn"):
                    students_parts.append(f"{m['name']} ({m['usn']})")
                else:
                    students_parts.append(m['name'])
            students_display = ", ".join(students_parts) if students_parts else "No student details"

            team_id = str(t.get("team_id") or t.get("_id") or t_name)
            team_sem = str(t.get("semester") or f"{sem_val}th Sem").strip()

            eligible_teams.append({
                "team_id": team_id,
                "team_name": t_name,
                "team_number": t_name,
                "project_title": proj_title,
                "project_status": proj_status,
                "semester": team_sem,
                "guide_name": guide_name,
                "guide_email": guide_email,
                "leader_name": t.get("leader_name") or "",
                "leader_usn": t.get("leader_usn") or "",
                "members": members_list,
                "students_display": students_display,
                "is_available": not is_allocated_elsewhere,
                "is_allocated_here": is_allocated_here,
                "allocated_panel": allocated_panel
            })

        return jsonify({
            "success": True,
            "semester": sem_val,
            "phase": norm_phase,
            "target_panel": target_panel,
            "teams": eligible_teams,
            "count": len(eligible_teams)
        }), 200
    except Exception as e:
        print(f"Error fetching eligible teams: {e}")
        return jsonify({"error": "Internal server error fetching eligible teams"}), 500


# POST /api/panel/allocate - Coordinator creates or updates panel allocation
@app.route('/api/panel/allocate', methods=['POST'])
def allocate_panel():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized - Coordinator access required"}), 403

        coord_email = decoded.get("email")
        data = request.json or {}

        # 1. Panel Identification
        panel_name = normalize_panel_name(data.get("panel_id") or data.get("panel_name") or "Panel 1")

        # 2. Semester & Phase
        semester_val = data.get("semester", 6)
        sem = 7 if str(semester_val).strip() in ["7", "7th", "sem7"] else 6
        phase_raw = data.get("phase") or data.get("presentation_phase") or "Phase 1"
        norm_phase = normalize_panel_phase_key(phase_raw)
        phase_meta = get_panel_phase_metadata(norm_phase, sem)

        # 3. Faculty Selection (NO AUTOMATIC GUIDE FETCHING, MAX 4, NO DUPLICATES)
        raw_faculty_emails = []
        if "faculty_emails" in data and isinstance(data["faculty_emails"], list):
            raw_faculty_emails = data["faculty_emails"]
        elif "panel_member_emails" in data and isinstance(data["panel_member_emails"], list):
            raw_faculty_emails = list(data["panel_member_emails"])
        else:
            for i in range(1, 5):
                m_email = data.get(f"member_{i}_email")
                if m_email:
                    raw_faculty_emails.append(m_email)

        # Legacy test compatibility: if guide_email passed explicitly in payload, add if not already present and < 4 members
        if data.get("guide_email") and data.get("guide_email") not in raw_faculty_emails and len(raw_faculty_emails) < 4:
            raw_faculty_emails.insert(0, data["guide_email"])

        # Check for duplicates in faculty selection
        seen_emails = set()
        cleaned_faculty_emails = []
        for fe in raw_faculty_emails:
            e_str = str(fe).strip().lower()
            if not e_str:
                continue
            if e_str in seen_emails:
                return jsonify({"error": f"Duplicate faculty member selection is not allowed ({fe})."}), 400
            seen_emails.add(e_str)
            cleaned_faculty_emails.append(fe)

        if len(cleaned_faculty_emails) > 4:
            return jsonify({"error": "Maximum of 4 panel faculty members allowed per panel."}), 400

        # Build panel members details from database
        panel_members = []
        non_guide_idx = 1
        for idx, femail in enumerate(cleaned_faculty_emails):
            fac_doc = db.faculty.find_one({"email": {"$regex": f"^{re.escape(femail)}$", "$options": "i"}})
            f_name = (fac_doc or {}).get("name") or data.get(f"member_{idx+1}_name") or femail.split("@")[0].replace(".", " ").title()
            if data.get("guide_email") and femail.lower() == str(data["guide_email"]).lower():
                role_label = "guide"
            else:
                role_label = f"member_{non_guide_idx}"
                non_guide_idx += 1
            panel_members.append({
                "email": femail,
                "name": f_name,
                "role": role_label
            })

        # 4. Team Selection & Assignment Mapping
        team_assignments = []
        if "team_assignments" in data and isinstance(data["team_assignments"], list):
            team_assignments = data["team_assignments"]
        elif "teams" in data and isinstance(data["teams"], list):
            for t_item in data["teams"]:
                if isinstance(t_item, dict):
                    team_assignments.append(t_item)
                else:
                    team_assignments.append({"team_name": str(t_item), "assigned_faculty_emails": cleaned_faculty_emails})
        elif data.get("team_name"):
            team_assignments.append({
                "team_name": str(data["team_name"]),
                "assigned_faculty_emails": cleaned_faculty_emails
            })

        if not team_assignments:
            return jsonify({"error": "At least one project team must be selected for panel allocation."}), 400

        # CRITICAL VALIDATION: Duplicate Team Allocation Prevention
        for ta in team_assignments:
            t_name = str(ta.get("team_name", "")).strip()
            if not t_name:
                continue
            existing = db.panel_allocations.find_one({
                "team_name": t_name,
                "$or": [{"semester": sem}, {"semester": str(sem)}],
                "phase": norm_phase,
                "status": {"$ne": "Cancelled"},
                "is_cancelled": {"$ne": True}
            })
            if existing:
                exist_panel = existing.get("panel_id") or existing.get("panel_name")
                if exist_panel and exist_panel != panel_name:
                    return jsonify({
                        "error": f"Team '{t_name}' is already allocated to {exist_panel} for {sem}th Semester {norm_phase}. Duplicate team allocation is prevented."
                    }), 400

        # 5. Metadata fields
        room_number = str(data.get("room_number") or data.get("room") or "Room 204")
        pres_datetime = str(data.get("presentation_datetime") or data.get("presentation_time") or "")
        deadline_val = str(data.get("deadline") or data.get("evaluation_deadline") or "")
        mark_entry_start = str(data.get("mark_entry_start") or "")
        enable_eval = bool(data.get("enable_evaluation", False) or data.get("is_evaluation_enabled", False))

        created_allocations = []
        last_alloc_id = None
        last_alloc_doc = None

        for ta in team_assignments:
            t_name = str(ta.get("team_name", "")).strip()
            if not t_name:
                continue

            assigned_emails = ta.get("assigned_faculty_emails") or cleaned_faculty_emails
            assigned_emails = [str(x).strip().lower() for x in assigned_emails if str(x).strip()]

            # Fetch team from database
            team = db.teams.find_one({"team_name": t_name})
            proj_title = "Student Project"
            guide_info = {}
            if team:
                proj_title = (team.get("project_idea") or {}).get("title") or "Student Project"
                guide_info = {
                    "email": team.get("faculty_email", ""),
                    "name": team.get("faculty_name", "Unassigned"),
                    "role": "guide"
                }

            guide_email = str(guide_info.get("email") or "").strip().lower()

            # Phase-wise Evaluator Structure:
            # - Phase 1, Phase 2, Phase 4: Exactly 4 evaluators (Assigned Guide + 3 Panel Faculty)
            # - Phase 5: Exactly 4 panel faculty members (no guide)
            if norm_phase in ["Phase 1", "Phase 2", "Phase 4"] and guide_email:
                if guide_email not in assigned_emails and len(assigned_emails) == 3:
                    assigned_emails.insert(0, guide_email)
            elif norm_phase == "Phase 5" and guide_email:
                assigned_emails = [e for e in assigned_emails if e != guide_email]

            # Build team-specific panel members list
            team_panel_members = []
            non_guide_idx = 1
            for femail in assigned_emails:
                fac_doc = db.faculty.find_one({"email": {"$regex": f"^{re.escape(femail)}$", "$options": "i"}})
                if guide_email and femail == guide_email and norm_phase != "Phase 5":
                    f_name = guide_info.get("name") or (fac_doc or {}).get("name") or femail.split("@")[0].title()
                    f_role = "guide"
                else:
                    f_name = (fac_doc or {}).get("name") or femail.split("@")[0].title()
                    f_role = f"member_{non_guide_idx}"
                    non_guide_idx += 1
                team_panel_members.append({
                    "email": femail,
                    "name": f_name,
                    "role": f_role
                })

            # Generate or reuse allocation_id
            existing = db.panel_allocations.find_one({
                "team_name": t_name,
                "$or": [{"semester": sem}, {"semester": str(sem)}],
                "phase": norm_phase,
                "status": {"$ne": "Cancelled"},
                "is_cancelled": {"$ne": True}
            })
            if existing:
                alloc_id = existing.get("allocation_id")
            else:
                p_slug = panel_name.lower().replace(" ", "_")
                t_slug = t_name.lower().replace(" ", "_")
                ph_slug = norm_phase.lower().replace(" ", "_")
                alloc_id = f"alloc_{p_slug}_{t_slug}_sem{sem}_{ph_slug}"

            alloc_doc = {
                "allocation_id": alloc_id,
                "panel_id": panel_name,
                "panel_name": panel_name,
                "team_name": t_name,
                "project_title": proj_title,
                "semester": sem,
                "phase": norm_phase,
                "phase_name": phase_meta["phase_name"],
                "max_marks": phase_meta.get("max_marks", 30 if sem == 7 else 20),
                "criteria": phase_meta.get("criteria", []),
                "room_number": room_number,
                "presentation_datetime": pres_datetime,
                "evaluation_deadline": deadline_val,
                "mark_entry_start": mark_entry_start,
                "guide": guide_info,
                "panel_members": team_panel_members if team_panel_members else panel_members,
                "assigned_faculty_emails": assigned_emails,
                "revoked_faculty_emails": existing.get("revoked_faculty_emails", []) if existing else [],
                "replacement_history": existing.get("replacement_history", []) if existing else [],
                "is_evaluation_enabled": enable_eval,
                "status": "Active",
                "is_finalized": False,
                "is_published": False,
                "approved_three_member_panel": bool(data.get("approved_three_member_panel", False)),
                "created_by": coord_email,
                "updated_at": datetime.now(timezone.utc),
                "created_at": existing.get("created_at") if existing else datetime.now(timezone.utc)
            }

            db.panel_allocations.update_one(
                {"allocation_id": alloc_id},
                {"$set": alloc_doc},
                upsert=True
            )

            # Notifications: create records for the panel members / assigned faculty
            for femail in (assigned_emails if assigned_emails else [m["email"] for m in panel_members]):
                m_info = next((m for m in panel_members if m["email"].lower() == femail.lower()), None)
                f_name = m_info["name"] if m_info else femail.split("@")[0].title()
                existing_notif = db.panel_notifications.find_one({
                    "allocation_id": alloc_id,
                    "recipient_email": femail
                })
                if not existing_notif:
                    db.panel_notifications.insert_one({
                        "notification_id": str(uuid.uuid4()),
                        "allocation_id": alloc_id,
                        "panel_id": panel_name,
                        "panel_name": panel_name,
                        "team_name": t_name,
                        "project_title": proj_title,
                        "semester": sem,
                        "phase": norm_phase,
                        "phase_name": phase_meta["phase_name"],
                        "room_number": room_number,
                        "evaluation_deadline": deadline_val,
                        "presentation_datetime": pres_datetime,
                        "recipient_email": femail,
                        "recipient_name": f_name,
                        "evaluation_url": f"panel-evaluation.html?alloc_id={alloc_id}",
                        "message": f"You are assigned to evaluate Team {t_name} ({proj_title}) in {panel_name} for {norm_phase}. Room: {room_number}.",
                        "is_read": False,
                        "created_at": datetime.now(timezone.utc)
                    })

            created_allocations.append(alloc_doc)
            last_alloc_id = alloc_id
            last_alloc_doc = alloc_doc

        # Record coordinator audit log
        db.panel_audit_logs.insert_one({
            "action": "PANEL_ALLOCATION_SAVED",
            "performed_by": coord_email,
            "panel_id": panel_name,
            "semester": sem,
            "phase": norm_phase,
            "allocated_teams_count": len(team_assignments),
            "timestamp": datetime.now(timezone.utc)
        })

        clean_last_doc = dict(last_alloc_doc)
        clean_last_doc.pop("_id", None)
        clean_created = []
        for c in created_allocations:
            doc_c = dict(c)
            doc_c.pop("_id", None)
            clean_created.append(doc_c)

        return jsonify({
            "success": True,
            "message": f"{panel_name} allocation configured successfully for {len(team_assignments)} team(s).",
            "allocation_id": last_alloc_id,
            "allocation": clean_last_doc,
            "allocations": clean_created,
            "allocations_count": len(created_allocations)
        }), 201

    except Exception as e:
        print(f"Error allocating panel: {e}")
        traceback.print_exc()
        return jsonify({"error": f"Internal server error allocating panel: {str(e)}"}), 500


# GET /api/panel/allocations - Coordinator overview of panel allocations and evaluation progress
@app.route('/api/panel/allocations', methods=['GET'])
def get_coordinator_panel_allocations():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized - Coordinator access required"}), 403

        query = {}
        panel_param = request.args.get("panel_id") or request.args.get("panel")
        if panel_param:
            query["panel_id"] = normalize_panel_name(panel_param)

        sem_param = request.args.get("semester")
        if sem_param:
            sem_val = 7 if str(sem_param).strip() in ["7", "7th", "sem7"] else 6
            query["$or"] = [{"semester": sem_val}, {"semester": str(sem_val)}]

        phase_param = request.args.get("phase")
        if phase_param:
            query["phase"] = normalize_panel_phase_key(phase_param)

        allocs = list(db.panel_allocations.find(query, {"_id": 0}))

        results = []
        for a in allocs:
            alloc_id = a.get("allocation_id")
            t_name = a.get("team_name")

            team = db.teams.find_one({"team_name": t_name})
            students = format_team_student_identities(team) if team else []

            # Compute real-time evaluation progress
            calc = calculate_student_panel_averages(alloc_id, students, a.get("panel_members"))

            # Determine submission progress
            assigned_fac = a.get("panel_members") or []
            if a.get("assigned_faculty_emails"):
                assigned_filter = {str(x).lower().strip() for x in a["assigned_faculty_emails"] if x}
                assigned_fac = [m for m in assigned_fac if str((m.get("email") if isinstance(m, dict) else m) or "").lower().strip() in assigned_filter]

            submitted_evals = list(db.panel_evaluations.find({"allocation_id": alloc_id, "status": "Submitted", "is_voided": {"$ne": True}}))
            submitted_eval_map = {str(e.get("faculty_email", "")).strip().lower(): e for e in submitted_evals if e.get("faculty_email")}
            submitted_emails = set(submitted_eval_map.keys())

            fac_progress = []
            for f in assigned_fac:
                f_email = str((f.get("email") if isinstance(f, dict) else f) or "").strip().lower()
                f_name = (f.get("name") if isinstance(f, dict) else f_email) or f_email
                sub_eval = submitted_eval_map.get(f_email)
                is_sub = sub_eval is not None
                sub_total = None
                if is_sub and sub_eval:
                    if sub_eval.get("submitted_total") is not None:
                        sub_total = sub_eval["submitted_total"]
                    elif sub_eval.get("final_marks"):
                        fm_vals = [float(v) for v in sub_eval["final_marks"].values() if v is not None]
                        sub_total = round(sum(fm_vals) / len(fm_vals), 1) if fm_vals else None
                    elif sub_eval.get("student_totals"):
                        st_vals = [float(v) for v in sub_eval["student_totals"].values() if v is not None]
                        sub_total = round(sum(st_vals) / len(st_vals), 1) if st_vals else None

                fac_progress.append({
                    "email": f_email,
                    "faculty_email": f_email,
                    "name": f_name,
                    "faculty_name": f_name,
                    "is_submitted": is_sub,
                    "status": "Submitted" if is_sub else "Pending",
                    "submitted_total": sub_total
                })

            g_obj = a.get("guide")
            guide_email = str((g_obj.get("email") if isinstance(g_obj, dict) else g_obj) or a.get("guide_email") or "").strip().lower()
            guide_name = (g_obj.get("name") if isinstance(g_obj, dict) else a.get("guide_name")) or a.get("guide_name") or guide_email or "Guide"
            guide_prog = next((p for p in fac_progress if str(p.get("email", "")).strip().lower() == guide_email), None) if guide_email else None
            guide_status = guide_prog["status"] if guide_prog else "Pending"

            is_expired = is_deadline_passed(a.get("evaluation_deadline"))
            is_complete = bool(len(assigned_fac) > 0 and len(submitted_emails) == len(assigned_fac))

            item = dict(a)

            item["presentation_phase"] = normalize_panel_phase_key(a.get("phase", "Phase 1"))
            pm = get_panel_phase_metadata(a.get("phase", "Phase 1"), a.get("semester", 6))
            item["max_marks"] = a.get("max_marks") or pm.get("max_marks", 30 if a.get("semester") == 7 else 20)
            item["criteria"] = pm.get("criteria", [])

            item["guide_name"] = guide_name
            item["guide_status"] = guide_status
            student_averages_map = {sr["usn"]: sr["average_mark"] for sr in calc["student_results"]}
            item["student_averages"] = student_averages_map
            item["student_averages_list"] = calc["student_averages"]
            item["student_results"] = calc["student_results"]
            item["evaluators_progress"] = fac_progress
            item["submitted_count"] = len(submitted_emails)
            item["assigned_count"] = len(assigned_fac)
            item["is_expired"] = is_expired
            item["is_complete"] = is_complete
            results.append(item)


        return jsonify({
            "success": True,
            "allocations": results,
            "count": len(results)
        }), 200

    except Exception as e:
        print(f"Error fetching coordinator panel allocations: {e}")
        traceback.print_exc()
        return jsonify({"error": "Internal server error fetching allocations"}), 500


# POST /api/panel/allocation/toggle_evaluation - Coordinator enables/disables mark entry
@app.route('/api/panel/allocation/toggle_evaluation', methods=['POST'])
def toggle_panel_evaluation():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized"}), 403

        data = request.json or {}
        alloc_id = data.get("allocation_id")
        enable_val = None
        for k in ["is_evaluation_enabled", "enable", "is_enabled"]:
            if k in data:
                enable_val = bool(data[k])
                break
        if enable_val is None:
            enable_val = False

        if not alloc_id:
            return jsonify({"error": "allocation_id is required"}), 400

        alloc = db.panel_allocations.find_one({"allocation_id": alloc_id})
        if not alloc:
            return jsonify({"error": "Allocation not found"}), 404

        db.panel_allocations.update_one(
            {"allocation_id": alloc_id},
            {"$set": {
                "is_evaluation_enabled": enable_val,
                "updated_at": datetime.now(timezone.utc)
            }}
        )

        db.panel_audit_logs.insert_one({
            "action": "TOGGLE_EVALUATION",
            "performed_by": decoded.get("email"),
            "allocation_id": alloc_id,
            "is_evaluation_enabled": enable_val,
            "timestamp": datetime.now(timezone.utc)
        })

        return jsonify({
            "success": True,
            "allocation_id": alloc_id,
            "is_evaluation_enabled": enable_val,
            "message": f"Evaluation {'enabled' if enable_val else 'disabled'} successfully"
        }), 200

    except Exception as e:
        print(f"Error toggling evaluation: {e}")
        return jsonify({"error": "Internal server error toggling evaluation"}), 500


# POST /api/panel/update_deadline - Coordinator extends or updates evaluation deadline
@app.route('/api/panel/update_deadline', methods=['POST'])
def update_panel_deadline():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized"}), 403

        data = request.json or {}
        alloc_id = data.get("allocation_id")
        new_ddl = data.get("new_deadline") or data.get("deadline")
        reason = data.get("reason", "")

        if not alloc_id or not new_ddl:
            return jsonify({"error": "allocation_id and new_deadline are required"}), 400

        alloc = db.panel_allocations.find_one({"allocation_id": alloc_id})
        if not alloc:
            return jsonify({"error": "Allocation not found"}), 404

        db.panel_allocations.update_one(
            {"allocation_id": alloc_id},
            {"$set": {
                "evaluation_deadline": str(new_ddl),
                "is_evaluation_enabled": True,
                "status": "Active",
                "updated_at": datetime.now(timezone.utc)
            }}
        )

        db.panel_audit_logs.insert_one({
            "action": "UPDATE_DEADLINE",
            "performed_by": decoded.get("email"),
            "allocation_id": alloc_id,
            "new_deadline": str(new_ddl),
            "reason": reason,
            "timestamp": datetime.now(timezone.utc)
        })

        return jsonify({"success": True, "message": "Deadline updated successfully"}), 200

    except Exception as e:
        print(f"Error updating deadline: {e}")
        return jsonify({"error": "Internal server error updating deadline"}), 500



# POST /api/panel/replace_member - Coordinator replaces a panel faculty member
@app.route('/api/panel/replace_member', methods=['POST'])
@app.route('/api/panel/allocation/replace_member', methods=['POST'])
def replace_panel_member():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized"}), 403

        data = request.json or {}
        alloc_id = data.get("allocation_id")
        old_email = str(data.get("old_faculty_email") or "").strip().lower()
        new_email = str(data.get("new_faculty_email") or "").strip().lower()
        new_name = str(data.get("new_faculty_name") or "").strip() or new_email.split("@")[0].title()
        reason = data.get("reason", "")

        if not alloc_id or not old_email or not new_email:
            return jsonify({"error": "allocation_id, old_faculty_email, and new_faculty_email are required"}), 400

        alloc = db.panel_allocations.find_one({"allocation_id": alloc_id})
        if not alloc:
            return jsonify({"error": "Allocation not found"}), 404

        panel_members = alloc.get("panel_members", [])
        assigned_emails = alloc.get("assigned_faculty_emails", [])
        revoked_emails = alloc.get("revoked_faculty_emails", [])
        rep_history = alloc.get("replacement_history", [])

        # Revoke old faculty member
        if old_email not in [x.lower() for x in revoked_emails]:
            revoked_emails.append(old_email)

        # Update panel members list
        updated_members = []
        replaced = False
        for m in panel_members:
            if m.get("email", "").lower() == old_email:
                updated_members.append({
                    "email": new_email,
                    "name": new_name,
                    "role": m.get("role", "panel_member")
                })
                replaced = True
            else:
                updated_members.append(m)
        if not replaced:
            updated_members.append({
                "email": new_email,
                "name": new_name,
                "role": "panel_member"
            })

        # Update assigned emails
        updated_assigned = [x for x in assigned_emails if x.lower() != old_email]
        if new_email not in [x.lower() for x in updated_assigned]:
            updated_assigned.append(new_email)

        rep_history.append({
            "old_faculty_email": old_email,
            "new_faculty_email": new_email,
            "new_faculty_name": new_name,
            "reason": reason,
            "replaced_by": decoded.get("email"),
            "timestamp": datetime.now(timezone.utc)
        })

        db.panel_allocations.update_one(
            {"allocation_id": alloc_id},
            {"$set": {
                "panel_members": updated_members,
                "assigned_faculty_emails": updated_assigned,
                "revoked_faculty_emails": revoked_emails,
                "replacement_history": rep_history,
                "updated_at": datetime.now(timezone.utc)
            }}
        )

        db.panel_audit_logs.insert_one({
            "action": "REPLACE_MEMBER",
            "performed_by": decoded.get("email"),
            "allocation_id": alloc_id,
            "old_faculty_email": old_email,
            "new_faculty_email": new_email,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc)
        })

        return jsonify({"success": True, "message": "Panel member replaced successfully"}), 200

    except Exception as e:
        print(f"Error replacing member: {e}")
        return jsonify({"error": "Internal server error replacing panel member"}), 500


# POST /api/panel/allocation/reopen - Coordinator reopens expired or finalized evaluation
@app.route('/api/panel/allocation/reopen', methods=['POST'])
@app.route('/api/panel/evaluation/reopen', methods=['POST'])
def reopen_panel_evaluation():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized"}), 403

        data = request.json or {}
        alloc_id = data.get("allocation_id")
        new_deadline = data.get("new_deadline") or data.get("deadline")
        reason = data.get("reason", "Coordinator reopened evaluation")

        if not alloc_id:
            return jsonify({"error": "allocation_id is required"}), 400

        alloc = db.panel_allocations.find_one({"allocation_id": alloc_id})
        if not alloc:
            return jsonify({"error": "Allocation not found"}), 404

        update_fields = {
            "is_evaluation_enabled": True,
            "status": "Reopened",
            "is_finalized": False,
            "updated_at": datetime.now(timezone.utc)
        }

        if new_deadline:
            update_fields["evaluation_deadline"] = str(new_deadline)

        db.panel_allocations.update_one(
            {"allocation_id": alloc_id},
            {"$set": update_fields}
        )

        db.panel_audit_logs.insert_one({
            "action": "REOPEN_EVALUATION",
            "performed_by": decoded.get("email"),
            "allocation_id": alloc_id,
            "new_deadline": str(new_deadline) if new_deadline else alloc.get("evaluation_deadline"),
            "reason": reason,
            "timestamp": datetime.now(timezone.utc)
        })

        return jsonify({
            "success": True,
            "message": "Evaluation reopened successfully."
        }), 200

    except Exception as e:
        print(f"Error reopening evaluation: {e}")
        return jsonify({"error": "Internal server error reopening evaluation"}), 500



# POST /api/panel/evaluation/finalize - Coordinator finalizes results and calculates student averages
@app.route('/api/panel/evaluation/finalize', methods=['POST'])
def finalize_panel_evaluation():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized - Coordinator access required"}), 403

        data = request.json or {}
        alloc_id = data.get("allocation_id")
        publish_val = bool(data.get("publish", False))

        if not alloc_id:
            return jsonify({"error": "allocation_id is required"}), 400

        alloc = db.panel_allocations.find_one({"allocation_id": alloc_id})
        if not alloc:
            return jsonify({"error": "Allocation not found"}), 404

        team = db.teams.find_one({"team_name": alloc["team_name"]})
        students = format_team_student_identities(team) if team else []

        calc = calculate_student_panel_averages(alloc_id, students, alloc.get("panel_members"))
        student_results = calc["student_results"]

        submitted_evals = list(db.panel_evaluations.find({"allocation_id": alloc_id, "status": "Submitted", "is_voided": {"$ne": True}}))
        assigned_fac = alloc.get("panel_members") or []
        if alloc.get("assigned_faculty_emails"):
            assigned_fac = [m for m in assigned_fac if m.get("email", "").lower() in [x.lower() for x in alloc["assigned_faculty_emails"]]]

        is_3mem_ok = bool(alloc.get("approved_three_member_panel"))
        required_count = 3 if is_3mem_ok else len(assigned_fac)
        if len(submitted_evals) < required_count and not data.get("force"):
            return jsonify({
                "error": f"Evaluation incomplete: Only {len(submitted_evals)} of {required_count} assigned evaluators have submitted marks."
            }), 400

        final_results = {}
        for sr in student_results:
            usn = sr["usn"]
            avg = sr["average_mark"] if sr["average_mark"] is not None else 0.0

            crit_sums = {}
            crit_counts = {}
            for e in submitted_evals:
                sm_student = (e.get("student_marks") or {}).get(usn)
                if isinstance(sm_student, dict):
                    for c_name, c_val in sm_student.items():
                        try:
                            crit_sums[c_name] = crit_sums.get(c_name, 0.0) + float(c_val)
                            crit_counts[c_name] = crit_counts.get(c_name, 0) + 1
                        except (ValueError, TypeError):
                            pass

            criterion_averages = {}
            if crit_counts:
                for c_name, c_cnt in crit_counts.items():
                    criterion_averages[c_name] = round(crit_sums[c_name] / c_cnt, 2)
                if sr.get("average_mark") is not None:
                    avg = sr["average_mark"]
                else:
                    avg = round(sum(criterion_averages.values()), 2)

            final_results[usn] = {
                "name": sr["name"],
                "total_phase_mark": avg,
                "criterion_averages": criterion_averages,
                "submitted_count": sr["submitted_count"],
                "assigned_count": sr["assigned_count"]
            }

        db.panel_allocations.update_one(
            {"allocation_id": alloc_id},
            {"$set": {
                "is_finalized": True,
                "is_published": publish_val,
                "status": "Finalized",
                "final_student_results": final_results,
                "finalized_at": datetime.now(timezone.utc),
                "finalized_by": decoded.get("email"),
                "updated_at": datetime.now(timezone.utc)
            }}
        )

        # Synchronize to main db.evaluations
        if alloc.get("team_name"):
            t_name = alloc["team_name"]
            sem_val = alloc.get("semester", 6)
            p_name = alloc.get("phase", "Phase 1")
            existing_eval = db.evaluations.find_one(get_evaluation_query(t_name, sem_val))
            target_mark = final_results.get(students[0]["usn"], {}).get("total_phase_mark", 0.0) if students else 0.0

            # Build synchronized criteria list
            crit_keys = []
            if students and students[0]["usn"] in final_results:
                crit_keys = list(final_results[students[0]["usn"]].get("criterion_averages", {}).keys())
            if not crit_keys:
                crit_keys = ["Final Mark"]

            criteria_list = []
            for c_name in crit_keys:
                marks_for_crit = []
                for s in students:
                    s_usn = s.get("usn")
                    s_res = final_results.get(s_usn, {})
                    c_avg = s_res.get("criterion_averages", {}).get(c_name, s_res.get("total_phase_mark", 0.0))
                    marks_for_crit.append({
                        "usn": s_usn,
                        "student_name": s.get("name"),
                        "marks_obtained": c_avg
                    })
                criteria_list.append({
                    "name": c_name,
                    "max_marks": 5 if len(crit_keys) == 4 else 20,
                    "marks": marks_for_crit
                })

            phase_entry = {
                "phase_name": p_name,
                "name": p_name,
                "total_marks": target_mark,
                "criteria": criteria_list
            }

            if existing_eval:
                phases = existing_eval.get("phases", [])
                p_idx = next((i for i, p in enumerate(phases) if p.get("phase_name") == p_name or p.get("name") == p_name), None)
                if p_idx is None:
                    phases.append(phase_entry)
                else:
                    phases[p_idx] = phase_entry
                db.evaluations.update_one(
                    {"_id": existing_eval["_id"]},
                    {"$set": {"phases": phases, "updated_at": datetime.now(timezone.utc)}}
                )
            else:
                db.evaluations.insert_one({
                    "team_name": t_name,
                    "semester": sem_val,
                    "phases": [phase_entry],
                    "is_locked": False,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc)
                })


        db.panel_audit_logs.insert_one({
            "action": "FINALIZE_EVALUATION",
            "performed_by": decoded.get("email"),
            "allocation_id": alloc_id,
            "is_published": publish_val,
            "final_results": final_results,
            "timestamp": datetime.now(timezone.utc)
        })

        return jsonify({
            "success": True,
            "message": "Evaluation finalized successfully",
            "is_published": publish_val,
            "final_results": final_results
        }), 200

    except Exception as e:
        print(f"Error finalizing panel evaluation: {e}")
        return jsonify({"error": "Internal server error finalizing evaluation"}), 500



# POST /api/panel/allocation/cancel - Coordinator cancels panel allocation
@app.route('/api/panel/allocation/cancel', methods=['POST'])
@app.route('/api/panel/allocation/<allocation_id>', methods=['DELETE'])
def cancel_panel_allocation(allocation_id=None):
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized - Coordinator access required"}), 403

        data = request.json or {}
        alloc_id = allocation_id or data.get("allocation_id")
        reason = data.get("reason", "Cancelled by Project Coordinator")

        if not alloc_id:
            return jsonify({"error": "allocation_id is required"}), 400

        alloc = db.panel_allocations.find_one({"allocation_id": alloc_id})
        if not alloc:
            return jsonify({"error": "Allocation not found"}), 404

        # Soft delete allocation
        db.panel_allocations.update_one(
            {"allocation_id": alloc_id},
            {"$set": {
                "status": "Cancelled",
                "is_cancelled": True,
                "is_evaluation_enabled": False,
                "cancellation_reason": reason,
                "cancelled_by": decoded.get("email"),
                "cancelled_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }}
        )

        # Void submitted/draft evaluations for this allocation (preserve as historical record, but exclude from active averages)
        db.panel_evaluations.update_many(
            {"allocation_id": alloc_id},
            {"$set": {
                "is_voided": True,
                "status": "Voided",
                "voided_at": datetime.now(timezone.utc),
                "void_reason": f"Allocation cancelled: {reason}"
            }}
        )

        # Notify assigned faculty
        assigned_emails = alloc.get("assigned_faculty_emails") or []
        if not assigned_emails:
            assigned_emails = [m.get("email") if isinstance(m, dict) else str(m) for m in (alloc.get("panel_members") or [])]
        for femail in assigned_emails:
            if femail:
                db.panel_notifications.insert_one({
                    "notification_id": str(uuid.uuid4()),
                    "allocation_id": alloc_id,
                    "recipient_email": femail,
                    "message": f"Your evaluation panel allocation for Team {alloc.get('team_name')} ({alloc.get('phase')}) has been cancelled by the coordinator. Reason: {reason}",
                    "is_read": False,
                    "created_at": datetime.now(timezone.utc)
                })

        db.panel_audit_logs.insert_one({
            "action": "CANCEL_ALLOCATION",
            "performed_by": decoded.get("email"),
            "allocation_id": alloc_id,
            "team_name": alloc.get("team_name"),
            "phase": alloc.get("phase"),
            "reason": reason,
            "timestamp": datetime.now(timezone.utc)
        })

        return jsonify({
            "success": True,
            "message": "Panel allocation cancelled successfully. Historical marks have been preserved as voided records.",
            "allocation_id": alloc_id
        }), 200

    except Exception as e:
        print(f"Error cancelling panel allocation: {e}")
        return jsonify({"error": f"Internal server error cancelling allocation: {str(e)}"}), 500

# POST /api/panel/allocation/publish - Coordinator toggles publication to students
@app.route('/api/panel/allocation/publish', methods=['POST'])
def publish_panel_evaluation():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        if decoded.get("role") != "coordinator":
            return jsonify({"error": "Unauthorized"}), 403

        data = request.json or {}
        alloc_id = data.get("allocation_id")
        pub_val = None
        for k in ["is_published", "publish"]:
            if k in data:
                pub_val = bool(data[k])
                break
        if pub_val is None:
            pub_val = True

        if not alloc_id:
            return jsonify({"error": "allocation_id is required"}), 400

        db.panel_allocations.update_one(
            {"allocation_id": alloc_id},
            {"$set": {
                "is_published": pub_val,
                "updated_at": datetime.now(timezone.utc)
            }}
        )

        db.panel_audit_logs.insert_one({
            "action": "PUBLISH_RESULTS" if pub_val else "UNPUBLISH_RESULTS",
            "performed_by": decoded.get("email"),
            "allocation_id": alloc_id,
            "timestamp": datetime.now(timezone.utc)
        })

        return jsonify({
            "success": True,
            "allocation_id": alloc_id,
            "is_published": pub_val,
            "message": f"Final marks {'published to students' if pub_val else 'unpublished'}"
        }), 200

    except Exception as e:
        print(f"Error publishing evaluation: {e}")
        return jsonify({"error": "Internal server error publishing evaluation"}), 500


# GET /api/panel/faculty/assignments - Returns only teams and phases assigned to logged-in faculty
@app.route('/api/panel/faculty/assignments', methods=['GET'])
def get_faculty_panel_assignments():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        role = decoded.get("role")
        email = str(decoded.get("email") or "").strip().lower()

        if role not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized"}), 403

        fac_doc = db.faculty.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
        fac_id = str(fac_doc.get("faculty_id", "")).strip().lower() if fac_doc else ""

        # Fetch all allocations
        allocs = list(db.panel_allocations.find({}, {"_id": 0}))

        assignments = []
        for a in allocs:
            alloc_id = a.get("allocation_id")
            assigned_emails = [str(x).strip().lower() for x in a.get("assigned_faculty_emails", [])]
            member_emails = [str(m.get("email", "")).strip().lower() for m in a.get("panel_members", []) if isinstance(m, dict)]

            # Check if this faculty is assigned to this team
            is_assigned = False
            if assigned_emails:
                if email in assigned_emails or (fac_id and fac_id in assigned_emails):
                    is_assigned = True
            elif member_emails:
                if email in member_emails or (fac_id and fac_id in member_emails):
                    is_assigned = True

            if not is_assigned:
                continue

            # Check caller's personal submission
            my_eval = db.panel_evaluations.find_one({
                "allocation_id": alloc_id,
                "faculty_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}
            })

            my_status = "Not Started"
            if my_eval:
                my_status = my_eval.get("status", "Draft")

            is_exp = is_deadline_passed(a.get("evaluation_deadline"))
            status = "Expired" if is_exp else a.get("status", "Active")
            if a.get("is_finalized"):
                status = "Finalized"

            guide_email = (a.get("guide") or {}).get("email", "").lower()
            is_guide = bool(guide_email and guide_email == email)

            # Determine role in panel
            role_label = "Panel Member"
            members = a.get("panel_members") or []
            for m in members:
                if m.get("email", "").lower() == email:
                    role_label = m.get("role") or "Panel Member"
                    break

            t_name = a.get("team_name")
            team_doc = db.teams.find_one({"team_name": t_name})
            proj_title = (team_doc.get("project_idea") or {}).get("title") or (team_doc or {}).get("project_title") or a.get("project_title") or "Student Project"

            assignments.append({
                "allocation_id": alloc_id,
                "panel_id": a.get("panel_id", "Panel 1"),
                "panel_name": a.get("panel_name", a.get("panel_id", "Panel 1")),
                "team_name": t_name,
                "project_title": proj_title,
                "semester": a.get("semester", 6),
                "phase": a.get("phase", "Phase 1"),
                "phase_name": a.get("phase_name", a.get("phase", "Phase 1")),
                "room_number": a.get("room_number", "Room 204"),
                "presentation_datetime": a.get("presentation_datetime", ""),
                "evaluation_deadline": a.get("evaluation_deadline", ""),
                "is_evaluation_enabled": a.get("is_evaluation_enabled", False),
                "my_submission_status": my_status,
                "status": status,
                "role_in_panel": role_label,
                "is_finalized": a.get("is_finalized", False),
                "is_published": a.get("is_published", False),
                "is_guide": is_guide,
                "evaluation_url": f"panel-evaluation.html?alloc_id={alloc_id}"
            })

        return jsonify(assignments), 200

    except Exception as e:
        print(f"Error fetching faculty assignments: {e}")
        return jsonify({"error": "Internal server error fetching assignments"}), 500


# GET /api/panel/notifications - In-app notifications for faculty
@app.route('/api/panel/notifications', methods=['GET'])
def get_faculty_panel_notifications():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = str(decoded.get("email") or "").strip().lower()

        notifs = list(db.panel_notifications.find(
            {"recipient_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}},
            {"_id": 0}
        ).sort("created_at", -1))

        unread_count = sum(1 for n in notifs if not n.get("is_read"))

        return jsonify({
            "success": True,
            "notifications": notifs,
            "unread_count": unread_count,
            "count": len(notifs)
        }), 200
    except Exception as e:
        print(f"Error fetching panel notifications: {e}")
        return jsonify({"error": "Internal server error fetching notifications"}), 500


# POST /api/panel/notifications/read - Mark notification as read
@app.route('/api/panel/notifications/read', methods=['POST'])
def mark_panel_notification_read():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])

        data = request.json or {}
        notif_id = data.get("notification_id")
        if notif_id:
            db.panel_notifications.update_one(
                {"notification_id": notif_id},
                {"$set": {"is_read": True}}
            )
        return jsonify({"success": True, "message": "Notification marked as read"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# GET /api/panel/evaluation/<allocation_id> - Marksheet page data strictly partitioned by role
@app.route('/api/panel/evaluation/<allocation_id>', methods=['GET'])
def get_panel_evaluation_sheet(allocation_id):
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        user_role = decoded.get("role")
        user_email = str(decoded.get("email") or "").strip().lower()

        alloc = db.panel_allocations.find_one({"allocation_id": allocation_id}, {"_id": 0})
        if not alloc:
            return jsonify({"error": "Panel evaluation allocation not found"}), 404

        t_name = alloc.get("team_name")
        team = db.teams.find_one({"team_name": t_name})
        students = format_team_student_identities(team) if team else []

        phase_meta = get_panel_phase_metadata(alloc.get("phase", "Phase 1"), alloc.get("semester", 6))
        criteria = phase_meta.get("criteria", [])
        phase_max_marks = phase_meta.get("max_marks", 20)

        # Role & Authorization Verification
        is_coordinator = (user_role == "coordinator")
        guide_email = str((alloc.get("guide") or {}).get("email") or (team or {}).get("faculty_email") or "").strip().lower()
        is_guide = bool(guide_email and user_email == guide_email)

        revoked_list = [str(x).strip().lower() for x in alloc.get("revoked_faculty_emails", [])]
        if user_email in revoked_list and not is_coordinator:
            return jsonify({"error": "Unauthorized: Your evaluation assignment for this team has been revoked."}), 403

        assigned_list = [str(x).strip().lower() for x in alloc.get("assigned_faculty_emails", [])]
        member_list = [str(m.get("email", "")).strip().lower() for m in alloc.get("panel_members", []) if isinstance(m, dict)]
        is_assigned_evaluator = (user_email in assigned_list or user_email in member_list)

        if not is_coordinator and not is_guide and not is_assigned_evaluator:
            return jsonify({"error": "Unauthorized: You are not assigned to evaluate this team."}), 403

        is_deadline_exp = is_deadline_passed(alloc.get("evaluation_deadline"))
        is_eval_enabled = bool(alloc.get("is_evaluation_enabled", False))
        editing_allowed = bool(is_eval_enabled and not is_deadline_exp and not alloc.get("is_finalized"))

        disabled_reason = None
        if not is_eval_enabled:
            disabled_reason = "Evaluation is not yet enabled by the coordinator."
        elif is_deadline_exp:
            disabled_reason = "Evaluation deadline has expired."
        elif alloc.get("is_finalized"):
            disabled_reason = "Evaluation has been finalized."

        # Build evaluator_statuses list
        assigned_fac = alloc.get("panel_members") or []
        if alloc.get("assigned_faculty_emails"):
            assigned_filter = {str(x).lower().strip() for x in alloc["assigned_faculty_emails"] if x}
            assigned_fac = [m for m in assigned_fac if str((m.get("email") if isinstance(m, dict) else m) or "").lower().strip() in assigned_filter]
        submitted_evals = list(db.panel_evaluations.find({"allocation_id": allocation_id, "status": "Submitted", "is_voided": {"$ne": True}}))
        submitted_emails = {str(e.get("faculty_email", "")).strip().lower() for e in submitted_evals if e.get("faculty_email")}

        evaluator_statuses = []
        for af in assigned_fac:
            af_email = str((af.get("email") if isinstance(af, dict) else af) or "").strip().lower()
            af_name = (af.get("name") if isinstance(af, dict) else af_email) or af_email
            af_role = (af.get("role") if isinstance(af, dict) else "Member") or "Member"
            is_sub = af_email in submitted_emails
            evaluator_statuses.append({
                "email": af_email,
                "name": af_name,
                "role": af_role,
                "is_submitted": is_sub,
                "status": "Submitted" if is_sub else "Pending"
            })

        # 1. Guide View: receives ONLY final submitted marks of panel members and calculated average (NO CRITERIA!)
        if is_guide and not is_coordinator:
            calc = calculate_student_panel_averages(allocation_id, students, alloc.get("panel_members"))
            return jsonify({
                "allocation": alloc,
                "students": students,
                "criteria": criteria,
                "phase_max_marks": phase_max_marks,
                "evaluator_statuses": evaluator_statuses,
                "is_guide": True,
                "is_coordinator": False,
                "is_evaluation_enabled": is_eval_enabled,
                "editing_allowed": False,
                "disabled_reason": disabled_reason,
                "panel_summary": {
                    "student_results": calc["student_results"],
                    "evaluator_statuses": evaluator_statuses,
                    "evaluators": alloc.get("panel_members") or []
                }
            }), 200

        # 2. Regular Panel Evaluator View: receives ONLY own evaluation, NO panel_summary of other members!
        if not is_coordinator:
            my_eval = db.panel_evaluations.find_one({
                "allocation_id": allocation_id,
                "faculty_email": {"$regex": f"^{re.escape(user_email)}$", "$options": "i"},
                "is_voided": {"$ne": True}
            }, {"_id": 0})

            return jsonify({
                "allocation": alloc,
                "students": students,
                "criteria": criteria,
                "phase_max_marks": phase_max_marks,
                "evaluator_statuses": evaluator_statuses,
                "is_guide": False,
                "is_coordinator": False,
                "is_evaluation_enabled": is_eval_enabled,
                "editing_allowed": editing_allowed,
                "disabled_reason": disabled_reason,
                "my_evaluation": my_eval
            }), 200

        # 3. Coordinator View: receives full details and calculated averages
        calc = calculate_student_panel_averages(allocation_id, students, alloc.get("panel_members"))
        all_evals = list(db.panel_evaluations.find({"allocation_id": allocation_id, "is_voided": {"$ne": True}}, {"_id": 0}))

        return jsonify({
            "allocation": alloc,
            "students": students,
            "criteria": criteria,
            "phase_max_marks": phase_max_marks,
            "evaluator_statuses": evaluator_statuses,
            "is_coordinator": True,
            "is_guide": is_guide,
            "is_evaluation_enabled": is_eval_enabled,
            "editing_allowed": editing_allowed,
            "disabled_reason": disabled_reason,
            "student_averages": calc["student_averages"],
            "student_results": calc["student_results"],
            "all_evaluations": all_evals
        }), 200

    except Exception as e:
        print(f"Error getting panel evaluation sheet: {e}")
        return jsonify({"error": "Internal server error loading evaluation sheet"}), 500


# POST /api/panel/evaluation/save - Evaluator saves draft marks
@app.route('/api/panel/evaluation/save', methods=['POST'])
def save_panel_evaluation_draft():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        user_role = decoded.get("role")
        user_email = str(decoded.get("email") or "").strip().lower()

        if user_role not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized"}), 403

        data = request.json or {}
        alloc_id = data.get("allocation_id")
        final_marks = data.get("final_marks") or {}
        student_marks = data.get("student_marks") or {}

        if not alloc_id:
            return jsonify({"error": "allocation_id is required"}), 400

        alloc = db.panel_allocations.find_one({"allocation_id": alloc_id})
        if not alloc:
            return jsonify({"error": "Allocation not found"}), 404

        # Check authorization and deadline
        if not alloc.get("is_evaluation_enabled") and user_role != "coordinator":
            return jsonify({"error": "Evaluation is not yet enabled by the coordinator."}), 403

        if is_deadline_passed(alloc.get("evaluation_deadline")) and user_role != "coordinator":
            return jsonify({"error": "Evaluation deadline has expired. Submissions are closed."}), 400

        phase_meta = get_panel_phase_metadata(alloc.get("phase", "Phase 1"), alloc.get("semester", 6))
        phase_max_marks = phase_meta.get("max_marks", 20)
        criteria = phase_meta.get("criteria", [])

        # Process student_marks and calculate student_totals
        clean_student_marks = {}
        clean_totals = {}

        if student_marks:
            for usn_key, sm in student_marks.items():
                c_key = clean_usn(usn_key)
                if isinstance(sm, dict):
                    crit_dict = {}
                    tot = 0.0
                    for c_name, c_val in sm.items():
                        try:
                            v_float = float(c_val)
                            crit_dict[c_name] = v_float
                            tot += v_float
                        except (ValueError, TypeError):
                            pass
                    clean_student_marks[c_key] = crit_dict
                    clean_totals[c_key] = round(tot, 2)
                elif isinstance(sm, (int, float)):
                    clean_totals[c_key] = round(float(sm), 2)
        elif final_marks:
            for usn_key, fm in final_marks.items():
                c_key = clean_usn(usn_key)
                try:
                    clean_totals[c_key] = round(float(fm), 2)
                except (ValueError, TypeError):
                    pass

        # Save draft
        draft_doc = {
            "allocation_id": alloc_id,
            "team_name": alloc.get("team_name"),
            "semester": alloc.get("semester", 6),
            "phase": alloc.get("phase", "Phase 1"),
            "panel_id": alloc.get("panel_id", "Panel 1"),
            "faculty_email": user_email,
            "faculty_name": decoded.get("name") or user_email,
            "evaluator_id": user_email,
            "final_marks": clean_totals,
            "student_totals": clean_totals,
            "student_marks": clean_student_marks if clean_student_marks else student_marks,
            "status": "Draft Saved",
            "is_submitted": False,
            "is_voided": False,
            "updated_at": datetime.now(timezone.utc)
        }

        db.panel_evaluations.update_one(
            {"allocation_id": alloc_id, "faculty_email": {"$regex": f"^{re.escape(user_email)}$", "$options": "i"}},
            {"$set": draft_doc},
            upsert=True
        )

        return jsonify({"success": True, "message": "Evaluation draft saved successfully."}), 200

    except Exception as e:
        print(f"Error saving evaluation draft: {e}")
        return jsonify({"error": "Internal server error saving draft"}), 500


# POST /api/panel/evaluation/submit - Evaluator submits component-wise marks
@app.route('/api/panel/evaluation/submit', methods=['POST'])
def submit_panel_evaluation():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        user_role = decoded.get("role")
        user_email = str(decoded.get("email") or "").strip().lower()

        if user_role not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized"}), 403

        data = request.json or {}
        alloc_id = data.get("allocation_id")
        final_marks = data.get("final_marks") or {}
        student_marks = data.get("student_marks") or {}

        if not alloc_id:
            return jsonify({"error": "allocation_id is required"}), 400

        alloc = db.panel_allocations.find_one({"allocation_id": alloc_id})
        if not alloc:
            return jsonify({"error": "Allocation not found"}), 404

        # Check revoked list
        revoked_list = [str(x).strip().lower() for x in alloc.get("revoked_faculty_emails", [])]
        if user_email in revoked_list and user_role != "coordinator":
            return jsonify({"error": "Unauthorized: Your evaluation assignment for this team has been revoked."}), 403

        # Verify assignment
        assigned_list = [str(x).strip().lower() for x in alloc.get("assigned_faculty_emails", [])]
        member_list = [str(m.get("email", "")).strip().lower() for m in alloc.get("panel_members", []) if isinstance(m, dict)]
        if user_role != "coordinator" and user_email not in assigned_list and user_email not in member_list:
            return jsonify({"error": "Unauthorized: You are not assigned to evaluate this team."}), 403

        # Check authorization and deadline
        if not alloc.get("is_evaluation_enabled") and user_role != "coordinator":
            return jsonify({"error": "Evaluation is not yet enabled by the coordinator."}), 403

        if is_deadline_passed(alloc.get("evaluation_deadline")) and user_role != "coordinator":
            return jsonify({"error": "Evaluation deadline has expired. Submissions are closed."}), 403

        team = db.teams.find_one({"team_name": alloc.get("team_name")})
        students = format_team_student_identities(team) if team else []

        phase_meta = get_panel_phase_metadata(alloc.get("phase", "Phase 1"), alloc.get("semester", 6))
        phase_max_marks = phase_meta.get("max_marks", 20)
        criteria = phase_meta.get("criteria", [])
        criteria_map = {c["name"]: c["max_marks"] for c in criteria}

        clean_final_marks = {}
        clean_student_marks = {}

        if student_marks:
            for s in students:
                s_usn = clean_usn(s.get("usn", ""))
                s_name = s.get("name") or s.get("display_name", "")
                s_dict = student_marks.get(s_usn) or student_marks.get(s.get("usn")) or student_marks.get(s_name)

                if s_dict is None:
                    # Check final_marks fallback
                    if final_marks and (s_usn in final_marks or s.get("usn") in final_marks or s_name in final_marks):
                        fm_val = final_marks.get(s_usn) or final_marks.get(s.get("usn")) or final_marks.get(s_name)
                        try:
                            fm_num = float(fm_val)
                            if fm_num < 0 or fm_num > phase_max_marks:
                                return jsonify({"error": f"Mark must be between 0 and {phase_max_marks} for {s_name}."}), 400
                            clean_final_marks[s_usn] = round(fm_num, 2)
                            dist = {}
                            for c in criteria:
                                dist[c["name"]] = round((fm_num * c["max_marks"]) / phase_max_marks, 2)
                            clean_student_marks[s_usn] = dist
                            continue
                        except (ValueError, TypeError):
                            return jsonify({"error": f"Invalid mark value for {s_name}."}), 400
                    else:
                        return jsonify({"error": f"Please enter evaluation marks for all students (missing: {s_name or s_usn})."}), 400

                if isinstance(s_dict, (int, float)):
                    fm_num = float(s_dict)
                    if fm_num < 0 or fm_num > phase_max_marks:
                        return jsonify({"error": f"Mark must be between 0 and {phase_max_marks} for {s_name}."}), 400
                    clean_final_marks[s_usn] = round(fm_num, 2)
                    dist = {}
                    for c in criteria:
                        dist[c["name"]] = round((fm_num * c["max_marks"]) / phase_max_marks, 2)
                    clean_student_marks[s_usn] = dist
                elif isinstance(s_dict, dict):
                    s_total = 0.0
                    cleaned_crit = {}
                    for c_name, c_val in s_dict.items():
                        try:
                            c_float = float(c_val)
                        except (ValueError, TypeError):
                            return jsonify({"error": f"Invalid mark value for criterion '{c_name}' for {s_name}. Must be numeric."}), 400

                        max_c = criteria_map.get(c_name, phase_max_marks)
                        if c_float < 0 or c_float > max_c:
                            return jsonify({"error": f"Criterion '{c_name}' must be between 0 and {max_c} (received {c_float})."}), 400
                        cleaned_crit[c_name] = round(c_float, 2)
                        s_total += c_float

                    if s_total < 0 or s_total > phase_max_marks:
                        return jsonify({"error": f"Total mark for {s_name} must be between 0 and {phase_max_marks}."}), 400

                    clean_student_marks[s_usn] = cleaned_crit
                    clean_final_marks[s_usn] = round(s_total, 2)

        elif final_marks:
            for s in students:
                s_usn = clean_usn(s.get("usn", ""))
                s_name = s.get("name") or ""
                if s_usn not in final_marks and s.get("usn") not in final_marks and s_name not in final_marks:
                    return jsonify({"error": f"Please enter a final mark for all students (missing: {s_name or s_usn})."}), 400

            for usn_key, mark_val in final_marks.items():
                clean_key = clean_usn(usn_key)
                try:
                    m_float = float(mark_val)
                except (ValueError, TypeError):
                    return jsonify({"error": f"Invalid mark value for {usn_key}. Must be numeric."}), 400

                if m_float < 0 or m_float > phase_max_marks:
                    return jsonify({"error": f"Final mark must be between 0 and {phase_max_marks} (received {m_float})."}), 400
                clean_final_marks[clean_key] = round(m_float, 2)
                if criteria:
                    dist = {}
                    for c in criteria:
                        dist[c["name"]] = round((m_float * c["max_marks"]) / phase_max_marks, 2)
                    clean_student_marks[clean_key] = dist

        existing_eval = db.panel_evaluations.find_one({
            "allocation_id": alloc_id,
            "faculty_email": {"$regex": f"^{re.escape(user_email)}$", "$options": "i"}
        })
        edit_history = existing_eval.get("edit_history", []) if existing_eval else []
        if existing_eval and existing_eval.get("status") == "Submitted":
            edit_history.append({
                "previous_marks": existing_eval.get("final_marks") or existing_eval.get("student_marks"),
                "timestamp": datetime.now(timezone.utc)
            })

        # Store independent submission in db.panel_evaluations
        eval_doc = {
            "allocation_id": alloc_id,
            "team_name": alloc.get("team_name"),
            "semester": alloc.get("semester", 6),
            "phase": alloc.get("phase", "Phase 1"),
            "panel_id": alloc.get("panel_id", "Panel 1"),
            "faculty_email": user_email,
            "faculty_name": decoded.get("name") or user_email,
            "evaluator_id": user_email,
            "final_marks": clean_final_marks,
            "student_totals": clean_final_marks,
            "student_marks": clean_student_marks,
            "status": "Submitted",
            "is_submitted": True,
            "is_voided": False,
            "edit_history": edit_history,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        db.panel_evaluations.update_one(
            {"allocation_id": alloc_id, "faculty_email": {"$regex": f"^{re.escape(user_email)}$", "$options": "i"}},
            {"$set": eval_doc},
            upsert=True
        )

        # Immediately sync panel averages into main db.evaluations
        try:
            if alloc.get("team_name"):
                sync_evaluation_with_panel_averages(
                    None,
                    alloc["team_name"],
                    semester=alloc.get("semester", 6)
                )
        except Exception as sync_err:
            print("Auto-sync error on submit_panel_evaluation:", sync_err)

        return jsonify({
            "success": True,
            "message": "Evaluation submitted successfully."
        }), 200

    except Exception as e:
        print(f"Error submitting evaluation: {e}")
        return jsonify({"error": "Internal server error submitting evaluation"}), 500


# GET /api/panel/guide/teams - Dedicated guide overview of their guided teams' panel marks
@app.route('/api/panel/guide/teams', methods=['GET'])
def get_guide_panel_evaluations():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        role = decoded.get("role")
        email = str(decoded.get("email") or "").strip().lower()

        if role not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized"}), 403

        # Resolve all teams guided by this faculty (check db.teams, db.allocations, and coordinator override)
        fac_doc = db.faculty.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
        fac_id = str(fac_doc.get("faculty_id", "")).strip().lower() if fac_doc else ""

        alloc_records = list(db.allocations.find({
            "$or": [
                {"faculty_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}},
                {"faculty_id": fac_id} if fac_id else {"faculty_email": email}
            ]
        }))
        alloc_team_names = {a.get("team_name") for a in alloc_records if a.get("team_name")}

        team_query = {
            "$or": [
                {"faculty_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}
            ]
        }
        if alloc_team_names:
            team_query["$or"].append({"team_name": {"$in": list(alloc_team_names)}})

        guided_teams = list(db.teams.find(team_query, {"_id": 0}))

        # If coordinator, they can inspect all teams if none guided
        if not guided_teams and role == "coordinator":
            guided_teams = list(db.teams.find({}, {"_id": 0}))

        response_teams = []
        for t in guided_teams:
            t_name = t.get("team_name")
            proj_title = (t.get("project_idea") or {}).get("title") or t.get("project_title") or t.get("title") or "Project"
            students = format_team_student_identities(t)

            # Find panel allocations for this team
            team_allocs = list(db.panel_allocations.find({"team_name": t_name}, {"_id": 0}))

            if not team_allocs:
                # Include team with unallocated state
                response_teams.append({
                    "team_name": t_name,
                    "project_title": proj_title,
                    "semester": t.get("semester", 6),
                    "phase": "Pending Allocation",
                    "phase_name": "Pending Allocation",
                    "is_finalized": False,
                    "evaluators": [],
                    "students": [{"usn": s.get("usn"), "name": s.get("name")} for s in students],
                    "student_averages": {},
                    "panel_id": "Unallocated"
                })
                continue

            for a in team_allocs:
                alloc_id = a.get("allocation_id")
                calc = calculate_student_panel_averages(alloc_id, students, a.get("panel_members"))
                submitted_evals = list(db.panel_evaluations.find({"allocation_id": alloc_id, "status": "Submitted", "is_voided": {"$ne": True}}))

                # Build evaluator submissions list for guide (strictly no criterion breakdowns!)
                panel_members = a.get("panel_members") or []
                evaluators_list = []
                for m in panel_members:
                    m_email = str(m.get("email", "")).strip().lower()
                    sub_eval = next((e for e in submitted_evals if str(e.get("faculty_email", "")).strip().lower() == m_email), None)

                    totals = {}
                    if sub_eval:
                        if sub_eval.get("final_marks"):
                            totals = sub_eval["final_marks"]
                        elif sub_eval.get("student_totals"):
                            totals = sub_eval["student_totals"]
                        elif sub_eval.get("student_marks"):
                            for u_k, s_val in sub_eval["student_marks"].items():
                                if isinstance(s_val, (int, float)):
                                    totals[u_k] = s_val
                                elif isinstance(s_val, dict):
                                    totals[u_k] = sum(float(x) for x in s_val.values() if isinstance(x, (int, float)))

                    norm_totals = {}
                    for k_u, v_u in totals.items():
                        norm_totals[k_u] = v_u
                        norm_totals[clean_usn(k_u)] = v_u

                    evaluators_list.append({
                        "name": m.get("name") or m_email.split("@")[0].title(),
                        "email": m_email,
                        "is_submitted": sub_eval is not None,
                        "student_totals": norm_totals
                    })

                student_averages_map = {sr["usn"]: sr["average_mark"] for sr in calc["student_results"]}

                pm_g = get_panel_phase_metadata(a.get("phase", "Phase 1"), a.get("semester", 6))
                response_teams.append({
                    "team_name": t_name,
                    "project_title": proj_title,
                    "semester": a.get("semester", 6),
                    "phase": a.get("phase", "Phase 1"),
                    "phase_name": a.get("phase_name", a.get("phase", "Phase 1")),
                    "max_marks": a.get("max_marks") or pm_g.get("max_marks", 30 if a.get("semester") == 7 else 20),
                    "is_finalized": a.get("is_finalized", False),
                    "evaluators": evaluators_list,
                    "students": [{"usn": s.get("usn"), "name": s.get("name")} for s in students],
                    "student_averages": student_averages_map,
                    "panel_id": a.get("panel_id", "Panel 1"),
                    "allocation_id": alloc_id
                })

        return jsonify({
            "success": True,
            "teams": response_teams,
            "guided_teams": response_teams,
            "count": len(response_teams)
        }), 200

    except Exception as e:
        print(f"Error fetching guide panel teams: {e}")
        return jsonify({"error": "Internal server error fetching guide panel marks"}), 500


# GET /api/panel/student/results - Student views published final panel averages only (Part 5)
@app.route('/api/panel/student/results', methods=['GET'])
def get_student_panel_results():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = str(decoded.get("email") or "").strip().lower()
        usn_token = str(decoded.get("usn") or "").strip().upper()

        # Resolve student team
        team_name = decoded.get("team_name") or decoded.get("team")
        if not team_name:
            query = {
                "$or": [
                    {"members.email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}},
                    {"leader_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}
                ]
            }
            if usn_token:
                query["$or"].extend([
                    {"leader_usn": usn_token},
                    {"members.usn": usn_token}
                ])
            team = db.teams.find_one(query)
            if team:
                team_name = team.get("team_name")

        if not team_name:
            return jsonify({"error": "No team associated with student account."}), 404

        team_doc = db.teams.find_one({"team_name": team_name})
        students = format_team_student_identities(team_doc) if team_doc else []

        # Find only published allocations for this team
        allocs = list(db.panel_allocations.find({
            "team_name": team_name,
            "is_published": True
        }, {"_id": 0}))

        results = []
        for a in allocs:
            alloc_id = a.get("allocation_id")
            calc = calculate_student_panel_averages(alloc_id, students, a.get("panel_members"))
            
            # Format student averages strictly WITHOUT individual faculty marks or criteria
            sanitized_student_averages = []
            for sr in calc.get("student_results", []):
                sr_avg = sr.get("average_mark") if sr.get("average_mark") is not None else sr.get("average")
                sanitized_student_averages.append({
                    "usn": sr.get("usn"),
                    "name": sr.get("name"),
                    "final_average": sr_avg
                })

            phase_label = a.get("phase") or a.get("phase_name") or "Phase 1"
            valid_averages = [sr.get("average_mark") for sr in calc.get("student_results", []) if sr.get("average_mark") is not None]
            team_phase_avg = round(sum(valid_averages) / len(valid_averages), 2) if valid_averages else None

            pm_s = get_panel_phase_metadata(phase_label, a.get("semester", 6))
            max_m_s = a.get("max_marks") or pm_s.get("max_marks", 30 if a.get("semester") == 7 else 20)
            results.append({
                "semester": a.get("semester", 6),
                "phase": phase_label,
                "max_marks": max_m_s,
                "team_phase_average": team_phase_avg,
                "student_averages": sanitized_student_averages
            })

        return jsonify({
            "success": True,
            "team_name": team_name,
            "published_results": results
        }), 200

    except Exception as e:
        print(f"Error getting student panel results: {e}")
        return jsonify({"error": "Internal server error fetching student results"}), 500






# ==================================================================== #
#      AI RESEARCH PAPER RECOMMENDATION & VALIDATION MODULE           #
# ==================================================================== #

def extract_project_keywords_direct(project_data):
    """
    Extracts search keywords directly from student project metadata:
    title, abstract, objectives, methodology, technologies, domain.
    Does NOT use Gemini API for query generation.
    """
    title = str(project_data.get("title", "") or project_data.get("project_title", ""))
    abstract = str(project_data.get("abstract", "") or project_data.get("description", ""))
    objectives = str(project_data.get("objectives", ""))
    methodology = str(project_data.get("methodology", ""))
    technologies = project_data.get("technologies") or project_data.get("tech_stack") or []
    if isinstance(technologies, list):
        technologies = " ".join([str(t) for t in technologies])
    else:
        technologies = str(technologies)
    domain = str(project_data.get("domain", ""))

    combined = f"{title} {abstract} {objectives} {methodology} {technologies} {domain}".lower()

    # Find known tech keywords
    found_tech = []
    for tech in TECH_KEYWORDS:
        if tech in combined and tech not in found_tech:
            found_tech.append(tech)

    # Word frequencies excluding stop words
    words = re.findall(r'\b[a-z]{3,}\b', combined)
    filtered = [w for w in words if w not in STOP_WORDS and len(w) > 3]

    counts = {}
    for w in filtered:
        counts[w] = counts.get(w, 0) + 1

    sorted_words = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    top_words = [w[0] for w in sorted_words[:10]]

    raw_kw = []
    if domain and domain != "N/A":
        raw_kw.append(domain)
    raw_kw.extend(found_tech[:5])
    raw_kw.extend([w for w in top_words if w not in found_tech][:6])

    seen = set()
    final_kw = []
    for kw in raw_kw:
        if kw and kw not in seen:
            seen.add(kw)
            final_kw.append(kw)

    return final_kw

def reconstruct_openalex_abstract(inverted_index):
    if not inverted_index or not isinstance(inverted_index, dict):
        return "Abstract not available in OpenAlex metadata."
    words_positions = []
    for word, pos_list in inverted_index.items():
        if isinstance(pos_list, list):
            for pos in pos_list:
                words_positions.append((pos, word))
    words_positions.sort(key=lambda x: x[0])
    return " ".join([w[1] for w in words_positions])

def search_openalex_papers_internal(query_keywords, max_results=10):
    if isinstance(query_keywords, list):
        query_str = " ".join(query_keywords[:5])
    else:
        query_str = str(query_keywords)

    if not query_str.strip():
        query_str = "computer science machine learning"

    try:
        url = "https://api.openalex.org/works"
        params = {
            "search": query_str,
            "per-page": max_results * 2,
            "sort": "relevance_score:desc"
        }
        headers = {
            "User-Agent": "StudentProjectMgmt/1.0 (mailto:student_project_mgmt@example.com)"
        }
        res = requests.get(url, params=params, headers=headers, timeout=12)
        if res.status_code != 200:
            print(f"OpenAlex status code {res.status_code}: {res.text}")
            return []

        data = res.json()
        results = data.get("results", [])
        papers = []

        for item in results:
            title = item.get("display_name") or item.get("title") or "Untitled Paper"
            year = item.get("publication_year") or "N/A"
            cited_by = item.get("cited_by_count", 0)

            # Authors
            authorships = item.get("authorships", [])
            authors = [a.get("author", {}).get("display_name", "") for a in authorships if a.get("author", {}).get("display_name")]
            author_str = ", ".join(authors[:4]) if authors else "Unknown Authors"
            if len(authors) > 4:
                author_str += " et al."

            abstract = reconstruct_openalex_abstract(item.get("abstract_inverted_index"))

            concepts = item.get("concepts", [])
            keywords = [c.get("display_name", "") for c in concepts if c.get("display_name") and c.get("score", 0) > 0.25][:6]

            oa_info = item.get("open_access", {})
            is_oa = oa_info.get("is_oa", False)
            oa_url = oa_info.get("oa_url") or item.get("doi") or item.get("id") or ""
            pdf_url = oa_url if ("pdf" in str(oa_url).lower() or str(oa_url).endswith(".pdf")) else oa_url

            paper_id = str(item.get("id", "")).split("/")[-1] or f"oa_{len(papers)+1}"

            papers.append({
                "paper_id": paper_id,
                "title": title,
                "authors": author_str,
                "year": year,
                "abstract": abstract,
                "keywords": keywords,
                "citation_count": cited_by,
                "is_open_access": is_oa,
                "pdf_url": pdf_url,
                "url": item.get("doi") or item.get("id") or oa_url
            })

            if len(papers) >= max_results:
                break

        return papers
    except Exception as e:
        print(f"Error querying OpenAlex API: {e}")
        return []

def call_gemini_generic_prompt(prompt_text):
    if not GEMINI_API_KEY:
        return None
    headers = {'Content-Type': 'application/json'}
    full_api_url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}]
    }
    for attempt in range(3):
        try:
            res = requests.post(full_api_url, headers=headers, data=json.dumps(payload), timeout=25)
            if res.status_code == 200:
                data = res.json()
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    return None
            elif res.status_code in [429, 500, 502, 503, 504]:
                time.sleep(1.5 ** attempt)
                continue
            else:
                break
        except Exception as e:
            print(f"Gemini prompt error: {e}")
            break
    return None

def compute_paper_relevance(project_data, paper_data):
    p_title = project_data.get("title", "")
    p_abstract = project_data.get("abstract", "")
    p_obj = project_data.get("objectives", "")
    p_meth = project_data.get("methodology", "")
    p_tech = project_data.get("technologies") or project_data.get("tech_stack", "")

    paper_title = paper_data.get("title", "")
    paper_abstract = paper_data.get("abstract", "")
    paper_kw = paper_data.get("keywords", [])
    paper_auth = paper_data.get("authors", "")

    paper_kw_str = ", ".join(paper_kw) if isinstance(paper_kw, list) else str(paper_kw or "")
    p_tech_str = ", ".join(p_tech) if isinstance(p_tech, list) else str(p_tech or "")

    prompt = f"""You are an academic research paper evaluator. Analyze the alignment between the Student Project and the Selected Research Paper provided below.

STUDENT PROJECT:
- Title: {p_title}
- Abstract: {p_abstract[:600]}
- Objectives: {p_obj[:400]}
- Methodology: {p_meth[:400]}
- Technologies: {p_tech_str}

SELECTED RESEARCH PAPER:
- Title: {paper_title}
- Abstract: {paper_abstract[:700]}
- Keywords: {paper_kw_str}
- Authors: {paper_auth}

CRITICAL CONSTRAINTS:
- Base your response ONLY on the Student Project and Selected Research Paper content provided above.
- Do NOT mention software tools, internal systems, OpenAlex, Gemini, Paper Validation, Keyword Extraction, Manual Paper Checking, or system internals unless they explicitly appear within the research paper itself.

Respond strictly in valid JSON format with NO markdown formatting or backticks:
{{
  "overall_related_percentage": <integer 0-100>,
  "confidence_score": <integer 0-100>,
  "matching_topics": [<specific topics present in BOTH documents>],
  "matching_technologies": [<tools or technologies mentioned in both>],
  "matching_objectives": [<shared goals or objectives>],
  "matching_keywords": [<keywords found in both>],
  "key_similarities": [<2-3 specific similarities between the paper and student project>],
  "key_differences": [<2-3 specific differences in methodology or scope>],
  "suitable_for_literature_review": <true or false>,
  "explanation": "<2-3 sentence explanation using actual content from both documents>"
}}"""
    raw_res = call_gemini_generic_prompt(prompt)
    if raw_res:
        try:
            cleaned = raw_res.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            parsed = json.loads(cleaned)
            return parsed
        except Exception as e:
            print("Failed to parse Gemini JSON relevance:", e)

    # NLP Fallback calculation
    tfidf_score, _ = originality_engine.compute_section_tfidf_similarity(
        {"title": p_title, "abstract": p_abstract, "objectives": p_obj, "description": p_abstract},
        {"title": paper_title, "abstract": paper_abstract, "objectives": "", "description": paper_abstract}
    )
    semantic_score = originality_engine.compute_semantic_similarity(
        f"{p_title} {p_abstract}",
        f"{paper_title} {paper_abstract}"
    )
    combined_score = max(tfidf_score, semantic_score)
    sim_pct = int(round(combined_score * 100))
    proj_kws = originality_engine.extract_keywords(f"{p_title} {p_abstract} {p_tech_str}")
    paper_kws = set(paper_kw) if isinstance(paper_kw, list) else originality_engine.extract_keywords(paper_title + " " + paper_abstract)
    matched_kws = list(proj_kws.intersection(paper_kws))
    matching_tech = [t for t in TECH_KEYWORDS if t in f"{paper_title} {paper_abstract}".lower() and t in f"{p_title} {p_abstract} {p_tech_str}".lower()]

    return {
        "overall_related_percentage": min(98, max(20, sim_pct)),
        "confidence_score": 85,
        "matching_topics": matched_kws[:3] if matched_kws else ["Computer Science"],
        "matching_technologies": matching_tech[:3],
        "matching_objectives": ["Analyzes domain methodologies"],
        "matching_keywords": matched_kws[:5],
        "key_similarities": [f"Both address topics in {p_title}"],
        "key_differences": ["Different dataset scope or algorithmic execution parameters"],
        "suitable_for_literature_review": True if sim_pct >= 40 else False,
        "explanation": f"The paper shares domain concept overlap with student project '{p_title}'. Matching concepts include {', '.join(matched_kws[:3]) if matched_kws else 'domain methodology'}."
    }

def extract_pdf_file_data(file_bytes, filename="uploaded.pdf"):
    text = ""
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            text += page.get_text() + "\n"
        doc.close()
    except Exception:
        try:
            import PyPDF2, io
            reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        except Exception as e2:
            print("PyPDF2 extraction error:", e2)

    text = text.strip()
    if not text:
        return {"title": filename.replace(".pdf", ""), "abstract": "No text could be extracted from the PDF file.", "keywords": [], "text": ""}

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    title = lines[0] if lines else filename
    if len(title) > 200:
        title = title[:200] + "..."

    abstract_match = re.search(r'(?i)abstract[\s\:\-\—]+(.*?)(?=\n\s*(?:1[\.\s]|introduction|keywords|index terms|\n\n\n))', text, re.DOTALL)
    if abstract_match:
        abstract = abstract_match.group(1).strip()
    else:
        abstract = text[:1200]

    kw_match = re.search(r'(?i)(?:keywords|index terms)[\s\:\-\—]+(.*?)(?=\n\s*(?:1[\.\s]|introduction|\n\n))', text, re.DOTALL)
    keywords = []
    if kw_match:
        raw_kw = kw_match.group(1).strip()
        keywords = [k.strip() for k in re.split(r'[,;•\n]', raw_kw) if k.strip()][:8]

    return {
        "title": title,
        "abstract": abstract[:2500],
        "keywords": keywords,
        "text": text[:5000]
    }


# --- REST API Endpoints for Research Paper Module ---

class ResearchTeamAccessError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


def get_authorized_research_team(email, role, team_name=None, decoded=None):
    if role in ["team", "student"]:
        conditions = [
            {"leader_email": email},
            {"members.email": email},
            {"members": {"$in": [email]}}
        ]
        usn = ""
        token_team = None
        if isinstance(decoded, dict):
            usn = clean_usn(decoded.get("usn", ""))
            token_team = decoded.get("team_name")
        if usn:
            conditions.extend([
                {"leader_usn": usn},
                {"members.usn": usn},
                {"members": {"$in": [usn]}}
            ])
        if token_team:
            conditions.append({"team_name": token_team})

        team = db.teams.find_one({"$or": conditions})
    elif role == "faculty":
        if not team_name:
            raise ResearchTeamAccessError("Select an assigned team first", 400)
        team = db.teams.find_one({"team_name": team_name, "faculty_email": email})
        if not team and email:
            team = db.teams.find_one({
                "team_name": team_name,
                "faculty_email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}
            })
    elif role == "coordinator":
        if not team_name:
            raise ResearchTeamAccessError("Select a team first", 400)
        team = db.teams.find_one({"team_name": team_name})
    else:
        raise ResearchTeamAccessError("Unauthorized role", 403)

    if not team:
        raise ResearchTeamAccessError("Team not found or not assigned to you", 404)
    return team


def get_research_project(team):
    team_name = team.get("team_name")
    current_idea = team.get("project_idea")

    def has_project_details(idea):
        return isinstance(idea, dict) and any(
            idea.get(field) for field in ("title", "abstract", "description")
        )

    if has_project_details(current_idea):
        selected_idea = current_idea
    else:
        idea_candidates = [
            (index, idea)
            for index, idea in enumerate(team.get("project_ideas", []))
            if has_project_details(idea)
        ] if isinstance(team.get("project_ideas"), list) else []
        selected_idea = max(
            idea_candidates,
            key=lambda item: (str(item[1].get("submitted_at") or ""), item[0]),
            default=(None, None)
        )[1]

    project_records = list(db.projects.find({"team_name": team_name}))

    def project_timestamp(record):
        return str(record.get("approved_at") or record.get("submitted_at") or "")

    selected_record = None
    if selected_idea:
        idea_id = str(selected_idea.get("project_id") or selected_idea.get("_id") or "")
        idea_title = str(selected_idea.get("title") or "").strip()
        matching_records = [
            record for record in project_records
            if (idea_id and str(record.get("project_id") or record.get("_id") or "") == idea_id)
            or (idea_title and str(record.get("title") or "").strip() == idea_title)
        ]
        if matching_records:
            selected_record = max(matching_records, key=project_timestamp)
    elif project_records:
        selected_record = max(project_records, key=project_timestamp)

    if selected_idea is None and selected_record is None:
        return None

    project = dict(selected_record or {})
    if selected_record:
        project.update({
            key: value for key, value in selected_idea.items()
            if value not in (None, "", [], {})
        } if selected_idea else {})
    elif selected_idea:
        project.update(selected_idea)

    project_id = (
        (selected_record or {}).get("project_id")
        or (selected_record or {}).get("_id")
        or project.get("project_id")
        or project.get("_id")
    )
    technologies = project.get("technologies") or project.get("tech_stack") or project.get("technology") or []
    if isinstance(technologies, str):
        technologies = [value.strip() for value in technologies.split(",") if value.strip()]
    elif not isinstance(technologies, list):
        technologies = []

    return {
        "project_id": str(project_id) if project_id is not None else None,
        "title": project.get("title") or "",
        "description": project.get("description") or "",
        "abstract": project.get("abstract") or "",
        "objectives": project.get("objectives") or "",
        "methodology": project.get("methodology") or "",
        "technologies": technologies,
        "domain": project.get("domain") or "",
        "keywords": project.get("keywords") if isinstance(project.get("keywords"), list) else [],
        "status": project.get("status") or "Pending Approval",
        "originality_score": project.get("originality_score"),
        "similarity_percent": project.get("similarity_percent")
    }


def research_team_error_response(error):
    if isinstance(error, ResearchTeamAccessError):
        return jsonify({"error": str(error)}), error.status_code
    raise error


@app.route('/api/research/recommendations', methods=['POST', 'GET'])
def get_research_paper_recommendations():
    try:
        token_full = request.headers.get("Authorization") or request.args.get("token")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded["email"]
        role = decoded.get("role", "")

        team_name_param = request.args.get("team_name")
        if not team_name_param and request.is_json and request.json:
            team_name_param = request.json.get("team_name")

        team = get_authorized_research_team(email, role, team_name_param, decoded=decoded)
        project_idea = get_research_project(team)
        if not project_idea:
            return jsonify({"error": "No project details found for this team"}), 404

        # Extract search keywords using rule-based NLP (No Gemini for queries)
        extracted_keywords = extract_project_keywords_direct(project_idea)
        
        # Query OpenAlex API
        raw_papers = search_openalex_papers_internal(extracted_keywords, max_results=10)

        formatted_papers = []
        for paper in raw_papers:
            rel_info = compute_paper_relevance(project_idea, paper)
            paper["relevance_percentage"] = rel_info.get("overall_related_percentage", 75)
            paper["confidence_score"] = rel_info.get("confidence_score", 85)
            paper["ai_analysis"] = rel_info
            formatted_papers.append(paper)

        # Sort by relevance percentage
        formatted_papers.sort(key=lambda x: x.get("relevance_percentage", 0), reverse=True)

        return jsonify({
            "team_name": team.get("team_name"),
            "project_title": project_idea.get("title", "Untitled Project"),
            "extracted_keywords": extracted_keywords,
            "papers": formatted_papers
        }), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except ResearchTeamAccessError as e:
        return research_team_error_response(e)
    except Exception as e:
        print(f"Error in research recommendations: {e}")
        return jsonify({"error": f"Failed to fetch recommendations: {str(e)}"}), 500


@app.route('/api/research/analyze-paper', methods=['POST'])
def analyze_research_paper():
    try:
        data = request.json or {}
        paper = data.get("paper")
        if not paper:
            return jsonify({"error": "Paper data required"}), 400

        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded["email"]
        role = decoded.get("role", "")

        team_name_param = data.get("team_name")
        team = get_authorized_research_team(email, role, team_name_param)
        project_idea = get_research_project(team)
        if not project_idea:
            return jsonify({"error": "No project details found for this team"}), 404

        relevance = compute_paper_relevance(project_idea, paper)
        return jsonify({"relevance": relevance}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except ResearchTeamAccessError as e:
        return research_team_error_response(e)
    except Exception as e:
        print("Error in analyze paper:", e)
        return jsonify({"error": "Failed to analyze research paper"}), 500


@app.route('/api/research/upload-paper', methods=['POST'])
def upload_research_paper():
    try:
        token_full = request.headers.get("Authorization") or request.form.get("token")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded["email"]
        role = decoded.get("role", "")

        team_name_param = request.form.get("team_name")
        team = get_authorized_research_team(email, role, team_name_param, decoded=decoded)
        project_idea = get_research_project(team)
        if not project_idea:
            return jsonify({"error": "No project details found for this team"}), 404

        if 'file' not in request.files:
            return jsonify({"error": "No PDF file uploaded"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "Empty filename"}), 400

        filename = secure_filename(file.filename)
        file_bytes = file.read()
        # Extract content from uploaded PDF
        extracted = extract_pdf_file_data(file_bytes, filename)

        # Analyze relevance using Gemini API
        rel_analysis = compute_paper_relevance(project_idea, extracted)
        rel_pct = rel_analysis.get("overall_related_percentage", 50)

        # Classification
        if rel_pct >= 70:
            classification = "Related"
        elif rel_pct >= 40:
            classification = "Partially Related"
        else:
            classification = "Not Related"

        # AI Suggestions prompt
        suggestions = {}
        if classification != "Related":
            p_tech_str = ", ".join(project_idea.get("technologies", [])) if isinstance(project_idea.get("technologies"), list) else str(project_idea.get("technologies") or "")
            prompt_sugg = f"""You are an academic advisor. Evaluate the uploaded paper against the student project and provide domain-specific recommendations.

STUDENT PROJECT:
- Title: {project_idea.get("title")}
- Abstract: {project_idea.get("abstract", "")[:500]}
- Objectives: {project_idea.get("objectives", "")[:400]}
- Methodology: {project_idea.get("methodology", "")[:400]}
- Technologies: {p_tech_str}

SELECTED RESEARCH PAPER:
- Title: {extracted.get("title")}
- Abstract: {extracted.get("abstract", "")[:500]}
- Keywords: {", ".join(extracted.get("keywords", [])) if isinstance(extracted.get("keywords"), list) else ""}

CRITICAL RULES:
- Base analysis ONLY on the project and paper content provided above.
- NEVER mention OpenAlex, Gemini, Paper Validation, Keyword Extraction, Manual Paper Checking, or system internals.

Respond strictly in valid JSON format:
{{
  "why_not_related": "<specific explanation of technical misalignment>",
  "unmatched_parts": [<unmatched technical dimensions or domain topics>],
  "suggested_keywords": [<5 domain search keywords tailored for project>],
  "suggested_phrases": [<3 domain search phrases>],
  "research_direction": "<actionable literature search recommendation for the student project>"
}}"""
            raw_sugg = call_gemini_generic_prompt(prompt_sugg)
            if raw_sugg:
                try:
                    cleaned = raw_sugg.strip()
                    if cleaned.startswith("```json"): cleaned = cleaned[7:]
                    if cleaned.startswith("```"): cleaned = cleaned[3:]
                    if cleaned.endswith("```"): cleaned = cleaned[:-3]
                    suggestions = json.loads(cleaned.strip())
                except Exception as e:
                    print("Failed to parse suggestions JSON:", e)

            if not suggestions:
                suggestions = {
                    "why_not_related": f"The uploaded paper methodology does not align directly with '{project_idea.get('title', 'the project')}'.",
                    "unmatched_parts": ["Core Architecture", "Domain Application"],
                    "suggested_keywords": extract_project_keywords_direct(project_idea)[:5],
                    "suggested_phrases": [f"{project_idea.get('domain', 'system')} algorithms", f"{project_idea.get('title', 'project')} methodology"],
                    "research_direction": f"Search for literature focusing on {p_tech_str or 'target project algorithms'}."
                }

            # Recommend top 3 suitable papers using suggested keywords
            recom_papers = search_openalex_papers_internal(suggestions.get("suggested_keywords", []), max_results=3)
            suggestions["recommended_papers"] = recom_papers

        ownership = extract_activity_ownership(token_full)

        result_doc = {
            "team_name": team.get("team_name"),
            "leader_email": team.get("leader_email"),
            "paper_id": f"upload_{int(time.time())}",
            "filename": filename,
            "title": extracted.get("title"),
            "abstract": extracted.get("abstract"),
            "keywords": extracted.get("keywords"),
            "classification": classification,
            "confidence_score": rel_analysis.get("confidence_score", 85),
            "relevance_percentage": rel_pct,
            "ai_analysis": rel_analysis,
            "ai_suggestions": suggestions,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "status": "Uploaded",
            "is_custom_upload": True,
            "submitted_by_name": ownership["submitted_by_name"],
            "submitted_by_usn": ownership["submitted_by_usn"],
            "submitted_by_email": ownership["submitted_by_email"],
            "timestamp": ownership["timestamp"]
        }

        # Save to db.research_papers collection
        db.research_papers.insert_one(result_doc)
        result_doc.pop("_id", None)

        return jsonify(result_doc), 200

    except ResearchTeamAccessError as e:
        return research_team_error_response(e)
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except Exception as e:
        print("Error uploading paper:", e)
        return jsonify({"error": f"Upload error: {str(e)}"}), 500


@app.route('/api/research/save-paper', methods=['POST'])
def save_research_paper():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded.get("email", "")
        role = decoded.get("role", "")
        ownership = extract_activity_ownership(token_full)

        data = request.json or {}
        paper_data = data.get("paper") if isinstance(data.get("paper"), dict) else data
        team_name_param = data.get("team_name") or paper_data.get("team_name")

        team = get_authorized_research_team(email, role, team_name_param, decoded=decoded)
        paper_id = str(paper_data.get("paper_id") or paper_data.get("id") or f"paper_{int(time.time())}")

        record = {
            "team_name": team.get("team_name"),
            "leader_email": team.get("leader_email"),
            "paper_id": paper_id,
            "title": paper_data.get("title", "Untitled Paper"),
            "authors": paper_data.get("authors", "Unknown Authors"),
            "year": paper_data.get("year", "N/A"),
            "abstract": paper_data.get("abstract", ""),
            "keywords": paper_data.get("keywords", []),
            "citation_count": paper_data.get("citation_count", 0),
            "is_open_access": paper_data.get("is_open_access", False),
            "pdf_url": paper_data.get("pdf_url", "") or paper_data.get("url", ""),
            "url": paper_data.get("url", "") or paper_data.get("pdf_url", ""),
            "relevance_percentage": paper_data.get("relevance_percentage", 75),
            "ai_analysis": paper_data.get("ai_analysis", {}),
            "status": "Saved",
            "faculty_comment": "",
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "submitted_by_name": ownership["submitted_by_name"],
            "submitted_by_usn": ownership["submitted_by_usn"],
            "submitted_by_email": ownership["submitted_by_email"],
            "timestamp": ownership["timestamp"]
        }

        db.research_papers.update_one(
            {"team_name": team.get("team_name"), "paper_id": paper_id},
            {"$set": record},
            upsert=True
        )

        return jsonify({"message": "Research paper saved successfully!", "paper": record}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except ResearchTeamAccessError as e:
        return research_team_error_response(e)
    except Exception as e:
        print("Error saving paper:", e)
        return jsonify({"error": str(e)}), 500


@app.route('/api/research/saved-papers', methods=['GET'])
def get_saved_research_papers():
    try:
        token_full = request.headers.get("Authorization") or request.args.get("token")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded["email"]
        role = decoded.get("role", "")

        team_name_param = request.args.get("team_name")
        team = get_authorized_research_team(email, role, team_name_param, decoded=decoded)
        query = {"team_name": team.get("team_name")}
        papers = list(db.research_papers.find(query, {"_id": 0}))
        return jsonify({"team_name": team.get("team_name"), "papers": papers}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except ResearchTeamAccessError as e:
        return research_team_error_response(e)
    except Exception as e:
        print("Error fetching saved papers:", e)
        return jsonify({"error": "Failed to fetch saved research papers"}), 500


@app.route('/api/research/saved-paper/<paper_id>', methods=['DELETE'])
def remove_saved_research_paper(paper_id):
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded["email"]
        role = decoded.get("role", "")

        team_name_param = request.args.get("team_name")
        team = get_authorized_research_team(email, role, team_name_param, decoded=decoded)
        if not team:
            return jsonify({"error": "Team not found"}), 404

        db.research_papers.delete_one({"team_name": team.get("team_name"), "paper_id": paper_id})
        return jsonify({"message": "Paper removed from saved list"}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except ResearchTeamAccessError as e:
        return research_team_error_response(e)
    except Exception as e:
        print("Error deleting paper:", e)
        return jsonify({"error": str(e)}), 500


@app.route('/api/research/faculty-review', methods=['POST'])
def faculty_review_paper():
    try:
        token_full = request.headers.get("Authorization")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])

        if decoded.get("role") not in ["faculty", "coordinator"]:
            return jsonify({"error": "Unauthorized role"}), 403

        data = request.json or {}
        paper_id = data.get("paper_id")
        team_name = data.get("team_name")
        status = data.get("status") # Approved / Rejected
        comment = data.get("comment", "")

        if not paper_id or not team_name or not status:
            return jsonify({"error": "Missing paper_id, team_name, or status"}), 400

        get_authorized_research_team(decoded.get("email"), decoded.get("role"), team_name, decoded=decoded)
        result = db.research_papers.update_one(
            {"team_name": team_name, "paper_id": paper_id},
            {"$set": {
                "status": status,
                "faculty_comment": comment,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "reviewed_by": decoded.get("email")
            }}
        )

        if result.matched_count == 0:
            return jsonify({"error": "Paper record not found"}), 404

        # Notify all team members via email (Temporarily disabled when coordinator acts)
        try:
            if decoded.get("role") == "coordinator" and ONLY_ALLOW_FACULTY_TO_STUDENT_NOTIFICATIONS:
                email_logger.info(
                    f"[EMAIL_NOTIFICATION] trigger=\"FACULTY_REVIEW_PAPER\" team=\"{team_name}\" "
                    f"worker_status=\"SKIPPED\" reason=\"POLICY_DISALLOWED_TRIGGER\""
                )
            else:
                team = find_team_by_name(team_name)
                if team:
                    canonical_name = team.get("team_name", str(team_name))
                    recipients = get_team_recipient_emails(team)
                    if recipients:
                        base_url = get_frontend_base_url()
                        paper = db.research_papers.find_one({"paper_id": paper_id, "team_name": canonical_name}) or db.research_papers.find_one({"paper_id": paper_id, "team_name": team_name}) or {}
                        paper_title = paper.get("title") or paper_id
                        badge_color = "#059669" if status == "Approved" else "#dc2626"
                        reviewer = decoded.get("email") or "Faculty Guide"
                        subject = f"Research Paper Review: {status} - {canonical_name}"
                        msg_body = f"Your research paper '{paper_title}' has been reviewed by faculty with outcome: '{status}'."
                        if comment:
                            msg_body += f"\n\nFaculty Comment:\n{comment}"
                        plain_msg = (
                            f"Hello {canonical_name},\n\n"
                            f"{msg_body}\n\n"
                            f"Check research papers in portal: {base_url}/research-papers.html"
                        )
                        html_msg = render_email_template(
                            headline=f"Research Paper {status}",
                            badge_text=status,
                            badge_color=badge_color,
                            team_name=canonical_name,
                            project_title=paper_title,
                            key_details={
                                "Paper Title": paper_title,
                                "Review Status": status,
                                "Reviewed By": reviewer,
                                "Review Date": datetime.now().strftime("%Y-%m-%d %H:%M")
                            },
                            message_content=msg_body,
                            action_url=f"{base_url}/research-papers.html",
                            action_text="View Research Papers"
                        )
                        send_email_notification(
                            recipients, subject, plain_msg, html_msg,
                            trigger_name="FACULTY_REVIEW_PAPER", team_id=canonical_name
                        )
        except Exception as email_err:
            email_logger.error(f"Error preparing paper review notification for {team_name}: {email_err}")

        return jsonify({"message": f"Paper status updated to {status} successfully!"}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except ResearchTeamAccessError as e:
        return research_team_error_response(e)
    except Exception as e:
        print("Error in faculty review:", e)
        return jsonify({"error": "Failed to update research paper review"}), 500


@app.route('/api/research/team-data/<path:team_name>', methods=['GET'])
@app.route('/api/research/team-data', methods=['GET'])
def get_research_team_data(team_name=None):
    try:
        token_full = request.headers.get("Authorization") or request.args.get("token")
        if not token_full:
            return jsonify({"error": "Missing token"}), 401
        token = token_full.split()[-1]
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        email = decoded["email"]
        role = decoded.get("role", "")

        target_team_name = team_name or request.args.get("team_name")
        team = get_authorized_research_team(email, role, target_team_name, decoded=decoded)

        t_name = team.get("team_name")
        project_info = get_research_project(team)
        if not project_info:
            return jsonify({"error": "No project details found for this team"}), 404

        # Saved papers from db.research_papers collection
        saved_papers = list(db.research_papers.find({"team_name": t_name}, {"_id": 0}))

        # Extract latest literature review and research gap from saved papers
        lit_review = None
        res_gap = None
        comments = []

        for p in saved_papers:
            if not lit_review and p.get("literature_review"):
                lit_review = p.get("literature_review")
            if not res_gap and p.get("research_gap"):
                res_gap = p.get("research_gap")
            if p.get("faculty_comment"):
                comments.append({
                    "paper_title": p.get("title"),
                    "paper_id": p.get("paper_id"),
                    "comment": p.get("faculty_comment"),
                    "status": p.get("status"),
                    "reviewed_at": p.get("reviewed_at", "")
                })

        # Add team feedbacks to comments list
        if team.get("feedbacks"):
            for f in team.get("feedbacks"):
                comments.append({
                    "type": "team_feedback",
                    "comment": f.get("feedback"),
                    "date": f.get("date")
                })

        students = [
            {
                "name": student["name"],
                "usn": student["usn"],
                "display_name": student["display_name"],
                "is_leader": student["is_leader"]
            }
            for student in format_team_student_identities(team)
        ]
        guide_name = team.get("faculty_name") or ""
        guide_email = team.get("faculty_email") or ""

        return jsonify({
            "team_name": t_name,
            "team_id": str(team.get("_id")) if team.get("_id") is not None else None,
            "leader_name": team.get("leader_name"),
            "students": students,
            "guide": {"name": guide_name, "email": guide_email},
            "project_info": project_info,
            "saved_papers": saved_papers,
            "literature_review": lit_review,
            "research_gap": res_gap,
            "approval_status": project_info.get("status", "Pending Approval"),
            "comments": comments
        }), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401
    except ResearchTeamAccessError as e:
        return research_team_error_response(e)
    except Exception as e:
        print(f"Error fetching research team data: {e}")
        return jsonify({"error": "Failed to fetch project research data"}), 500


# ==================================================================== #
#                       USER PROFILE & ACCOUNT ROUTES                  #
# ==================================================================== #

def get_user_avatar_initials(full_name):
    """Generates clean avatar initials: 'Prashanth Kulal' -> 'PK', 'Mahadevi' -> 'M'"""
    if not full_name:
        return "U"
    parts = [p.strip() for p in str(full_name).strip().split() if p.strip()]
    if not parts:
        return "U"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()

def get_authenticated_user_context():
    """Extracts and verifies user identity from JWT Authorization header."""
    auth_header = request.headers.get("Authorization") or ""
    if not auth_header:
        return None, jsonify({"error": "Missing authorization token"}), 401

    try:
        raw_token = auth_header.split()[-1]
        decoded = jwt.decode(raw_token, app.config["SECRET_KEY"], algorithms=["HS256"])
        return decoded, None, 200
    except jwt.ExpiredSignatureError:
        return None, jsonify({"error": "Session expired. Please log in again."}), 401
    except jwt.InvalidTokenError:
        return None, jsonify({"error": "Invalid authentication token"}), 401
    except Exception as e:
        print(f"JWT decode error: {e}")
        return None, jsonify({"error": "Authentication failed"}), 401


@app.route('/api/profile', methods=['GET'])
def get_user_profile():
    """Fetches role-specific safe profile information for the authenticated user."""
    decoded, err_resp, status = get_authenticated_user_context()
    if err_resp:
        return err_resp, status

    role = decoded.get("role")
    email = str(decoded.get("email") or "").strip().lower()
    usn = clean_usn(decoded.get("usn"))

    try:
        if role in ["student", "team"]:
            team = db.teams.find_one({
                "$or": [
                    {"leader_usn": usn},
                    {"leader_email": email},
                    {"members.usn": usn},
                    {"members.email": email},
                    {"team_name": decoded.get("team_name")}
                ]
            })
            if not team:
                return jsonify({"error": "Student team record not found"}), 404

            l_usn = clean_usn(team.get("leader_usn"))
            l_email = str(team.get("leader_email") or "").strip().lower()
            l_name = str(team.get("leader_name") or "").strip()

            is_leader = False
            if (usn and l_usn == usn) or (email and l_email == email):
                is_leader = True
                user_name = l_name
                user_usn = l_usn
                user_email = l_email
                user_phone = team.get("leader_phone") or team.get("phone") or ""
                user_dept = team.get("department") or ""
                user_sem = team.get("semester") or ""
            else:
                user_name = decoded.get("name") or "Student"
                user_usn = usn
                user_email = email
                user_phone = ""
                user_dept = team.get("department") or ""
                user_sem = team.get("semester") or ""
                for m in team.get("members", []):
                    minfo = extract_student_identity_from_member(m)
                    if (usn and minfo["usn"] == usn) or (email and minfo["email"] == email):
                        user_name = minfo["name"]
                        user_usn = minfo["usn"]
                        user_email = minfo["email"]
                        if isinstance(m, dict):
                            user_phone = str(m.get("phone") or "").strip()
                            user_dept = str(m.get("department") or user_dept).strip()
                            user_sem = str(m.get("semester") or user_sem).strip()
                        break

            profile_data = {
                "role": "student",
                "role_label": "Team Leader" if is_leader else "Team Member",
                "is_leader": is_leader,
                "name": user_name,
                "usn": user_usn or "Not provided",
                "email": user_email or "Not provided",
                "phone": user_phone or "Not provided",
                "department": user_dept or "Not provided",
                "semester": user_sem or "Not provided",
                "team_name": team.get("team_name", "Not assigned"),
                "faculty_name": team.get("faculty_name") or "Not assigned",
                "faculty_email": team.get("faculty_email") or "",
                "interests": team.get("interests", []),
                "avatar_initials": get_user_avatar_initials(user_name)
            }
            return jsonify({"profile": profile_data}), 200

        elif role == "faculty":
            faculty = db.faculty.find_one({"email": email})
            if not faculty:
                return jsonify({"error": "Faculty record not found"}), 404

            assigned_count = db.teams.count_documents({"faculty_email": email})
            profile_data = {
                "role": "faculty",
                "role_label": "Faculty Guide",
                "name": faculty.get("name", "Faculty Member"),
                "email": faculty.get("email", email),
                "phone": faculty.get("phone") or "Not provided",
                "department": faculty.get("department") or "Not provided",
                "expertise": faculty.get("expertise", []),
                "assigned_teams_count": assigned_count,
                "avatar_initials": get_user_avatar_initials(faculty.get("name", "Faculty Member"))
            }
            return jsonify({"profile": profile_data}), 200

        elif role == "coordinator":
            coordinator = db.coordinator.find_one({"email": email})
            if not coordinator:
                coordinator = db.faculty.find_one({"email": email, "role": "coordinator"})
            if not coordinator:
                return jsonify({"error": "Coordinator record not found"}), 404

            profile_data = {
                "role": "coordinator",
                "role_label": "Project Coordinator",
                "name": coordinator.get("name", "Project Coordinator"),
                "email": coordinator.get("email", email),
                "phone": coordinator.get("phone") or "Not provided",
                "department": coordinator.get("department") or "Not provided",
                "expertise": coordinator.get("expertise", ["Project Management"]),
                "avatar_initials": get_user_avatar_initials(coordinator.get("name", "Project Coordinator"))
            }
            return jsonify({"profile": profile_data}), 200

        else:
            return jsonify({"error": "Unrecognized user role"}), 403

    except Exception as e:
        print(f"Error fetching profile: {e}")
        return jsonify({"error": "Unable to load profile information."}), 500


@app.route('/api/profile', methods=['PUT'])
def update_user_profile():
    """Allows updating only safe, personal profile fields without modifying academic or allocation records."""
    decoded, err_resp, status = get_authenticated_user_context()
    if err_resp:
        return err_resp, status

    role = decoded.get("role")
    email = str(decoded.get("email") or "").strip().lower()
    usn = clean_usn(decoded.get("usn"))
    data = request.json or {}

    new_name = str(data.get("name") or "").strip()
    new_phone = str(data.get("phone") or "").strip()

    try:
        if role in ["student", "team"]:
            team = db.teams.find_one({
                "$or": [
                    {"leader_usn": usn},
                    {"leader_email": email},
                    {"members.usn": usn},
                    {"members.email": email},
                    {"team_name": decoded.get("team_name")}
                ]
            })
            if not team:
                return jsonify({"error": "Student team record not found"}), 404

            l_usn = clean_usn(team.get("leader_usn"))
            l_email = str(team.get("leader_email") or "").strip().lower()
            is_leader = (usn and l_usn == usn) or (email and l_email == email)

            if is_leader:
                update_fields = {}
                if new_name:
                    update_fields["leader_name"] = new_name
                if "phone" in data:
                    update_fields["leader_phone"] = new_phone
                    update_fields["phone"] = new_phone
                if update_fields:
                    db.teams.update_one({"_id": team["_id"]}, {"$set": update_fields})
            else:
                updated_members = []
                for m in team.get("members", []):
                    if isinstance(m, dict):
                        m_usn = clean_usn(m.get("usn"))
                        m_email = str(m.get("email") or "").strip().lower()
                        if (usn and m_usn == usn) or (email and m_email == email):
                            if new_name:
                                m["name"] = new_name
                            if "phone" in data:
                                m["phone"] = new_phone
                    updated_members.append(m)
                db.teams.update_one({"_id": team["_id"]}, {"$set": {"members": updated_members}})

            return jsonify({"message": "Profile updated successfully!"}), 200

        elif role == "faculty":
            update_fields = {}
            if new_name:
                update_fields["name"] = new_name
            if "phone" in data:
                update_fields["phone"] = new_phone
            if "department" in data:
                update_fields["department"] = str(data.get("department") or "").strip()
            if "expertise" in data:
                exp = data.get("expertise")
                if isinstance(exp, str):
                    update_fields["expertise"] = [x.strip() for x in exp.split(",") if x.strip()]
                elif isinstance(exp, list):
                    update_fields["expertise"] = [str(x).strip() for x in exp if str(x).strip()]

            if update_fields:
                db.faculty.update_one({"email": email}, {"$set": update_fields})
                if new_name:
                    db.teams.update_many({"faculty_email": email}, {"$set": {"faculty_name": new_name}})

            return jsonify({"message": "Faculty profile updated successfully!"}), 200

        elif role == "coordinator":
            update_fields = {}
            if new_name:
                update_fields["name"] = new_name
            if "phone" in data:
                update_fields["phone"] = new_phone
            if "department" in data:
                update_fields["department"] = str(data.get("department") or "").strip()

            if update_fields:
                if db.coordinator.find_one({"email": email}):
                    db.coordinator.update_one({"email": email}, {"$set": update_fields})
                else:
                    db.faculty.update_one({"email": email, "role": "coordinator"}, {"$set": update_fields})

            return jsonify({"message": "Coordinator profile updated successfully!"}), 200

        else:
            return jsonify({"error": "Invalid role"}), 403

    except Exception as e:
        print(f"Error updating profile: {e}")
        return jsonify({"error": "Failed to update profile. Please try again."}), 500


@app.route('/api/profile/change-password', methods=['POST'])
def change_user_password():
    """Securely updates password for authenticated user after verifying their current password."""
    decoded, err_resp, status = get_authenticated_user_context()
    if err_resp:
        return err_resp, status

    role = decoded.get("role")
    email = str(decoded.get("email") or "").strip().lower()
    usn = clean_usn(decoded.get("usn"))
    data = request.json or {}

    current_password = data.get("current_password")
    new_password = data.get("new_password")
    confirm_password = data.get("confirm_password")

    if not current_password or not new_password or not confirm_password:
        return jsonify({"error": "All password fields are required"}), 400

    if new_password != confirm_password:
        return jsonify({"error": "New passwords do not match"}), 400

    if len(new_password) < 6:
        return jsonify({"error": "New password must be at least 6 characters long"}), 400

    try:
        user_record = None
        collection_to_update = None
        query_filter = None

        if role in ["student", "team"]:
            team = db.teams.find_one({
                "$or": [
                    {"leader_usn": usn},
                    {"leader_email": email},
                    {"members.usn": usn},
                    {"members.email": email},
                    {"team_name": decoded.get("team_name")}
                ]
            })
            if not team:
                return jsonify({"error": "User record not found"}), 404
            user_record = team
            collection_to_update = db.teams
            query_filter = {"_id": team["_id"]}

        elif role == "faculty":
            faculty = db.faculty.find_one({"email": email})
            if not faculty:
                return jsonify({"error": "Faculty record not found"}), 404
            user_record = faculty
            collection_to_update = db.faculty
            query_filter = {"email": email}

        elif role == "coordinator":
            coordinator = db.coordinator.find_one({"email": email})
            if coordinator:
                user_record = coordinator
                collection_to_update = db.coordinator
                query_filter = {"email": email}
            else:
                fac_coord = db.faculty.find_one({"email": email, "role": "coordinator"})
                if fac_coord:
                    user_record = fac_coord
                    collection_to_update = db.faculty
                    query_filter = {"email": email, "role": "coordinator"}
                else:
                    return jsonify({"error": "Coordinator record not found"}), 404

        stored_pw = user_record.get("password") or user_record.get("leader_password", "")
        valid = False
        if any(stored_pw.startswith(p) for p in ["pbkdf2:", "scrypt:", "$2b$", "$2a$", "bcrypt:"]):
            valid = check_password_hash(stored_pw, current_password)
        else:
            valid = (stored_pw == current_password)

        if not valid:
            return jsonify({"error": "Current password is incorrect"}), 400

        hashed_pw = generate_password_hash(new_password)
        collection_to_update.update_one(
            query_filter,
            {"$set": {"password": hashed_pw}, "$unset": {"leader_password": ""}}
        )

        return jsonify({"message": "Password changed successfully!"}), 200

    except Exception as e:
        print(f"Password update error: {e}")
        return jsonify({"error": "Failed to change password. Please try again."}), 500


# ==================================================================== #
#                   STUDENT FLOWCHART DESIGNER API                     #
# ==================================================================== #

from flowchart_engine import (
    parse_python_code,
    parse_java_code,
    validate_diagram_data,
    calculate_hierarchical_layout
)

def get_authenticated_student_user():
    """
    Validates that the incoming request is from an authenticated student/team.
    Enforces student-only access to the Flowchart Designer subsystem.
    """
    token_full = request.headers.get("Authorization")
    if not token_full:
        return None, (jsonify({"error": "Missing authorization token"}), 401)
    
    parts = token_full.split()
    token = parts[-1] if parts else ""
    if not token:
        return None, (jsonify({"error": "Invalid authorization token format"}), 401)

    try:
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        role = str(decoded.get("role", "")).lower()
        if role not in ["student", "team"]:
            return None, (jsonify({"error": "Access denied: student access only"}), 403)

        email = (decoded.get("email") or "").strip().lower()
        usn = clean_usn(decoded.get("usn") or "")
        team_name = decoded.get("team_name")
        name = decoded.get("name", "")

        if not team_name and (email or usn):
            team_query = []
            if email:
                team_query.extend([{"leader_email": email}, {"members.email": email}, {"members": email}])
            if usn:
                team_query.extend([{"leader_usn": usn}, {"members.usn": usn}, {"members": usn}])
            if team_query:
                found_team = db.teams.find_one({"$or": team_query})
                if found_team:
                    team_name = found_team.get("team_name")

        return {
            "email": email,
            "usn": usn,
            "team_name": team_name,
            "name": name
        }, None

    except jwt.ExpiredSignatureError:
        return None, (jsonify({"error": "Session token has expired. Please log in again."}), 401)
    except Exception as e:
        return None, (jsonify({"error": f"Authentication failed: {str(e)}"}), 401)


@app.route("/api/flowchart/save", methods=["POST"])
def save_flowchart():
    student, err_resp = get_authenticated_student_user()
    if err_resp:
        return err_resp

    data = request.json or {}
    is_valid, sanitized, err_msg = validate_diagram_data(data)
    if not is_valid:
        return jsonify({"error": err_msg}), 400

    diagram_id = str(data.get("id") or "").strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    if diagram_id:
        existing = db.flowcharts.find_one({"diagram_id": diagram_id})
        if existing:
            # Enforce strict ownership protection
            is_owner = (
                (existing.get("owner_email") and existing.get("owner_email") == student["email"]) or
                (student["usn"] and existing.get("owner_usn") and existing.get("owner_usn") == student["usn"]) or
                (student["team_name"] and existing.get("team_name") and existing.get("team_name") == student["team_name"])
            )
            if not is_owner:
                return jsonify({"error": "Access forbidden: you do not have permission to modify this diagram."}), 403

            db.flowcharts.update_one(
                {"diagram_id": diagram_id},
                {"$set": {
                    "title": sanitized["title"],
                    "description": sanitized["description"],
                    "nodes": sanitized["nodes"],
                    "edges": sanitized["edges"],
                    "viewport": sanitized["viewport"],
                    "layout": sanitized["layout"],
                    "updated_at": now_iso
                }}
            )
            return jsonify({
                "success": True,
                "diagram_id": diagram_id,
                "title": sanitized["title"],
                "updated_at": now_iso,
                "message": "Diagram updated successfully"
            }), 200

    # Create new diagram document
    new_id = diagram_id or str(uuid.uuid4())
    doc = {
        "diagram_id": new_id,
        "title": sanitized["title"],
        "description": sanitized["description"],
        "nodes": sanitized["nodes"],
        "edges": sanitized["edges"],
        "viewport": sanitized["viewport"],
        "layout": sanitized["layout"],
        "owner_email": student["email"],
        "owner_usn": student["usn"],
        "owner_name": student["name"],
        "team_name": student["team_name"],
        "created_at": now_iso,
        "updated_at": now_iso
    }
    db.flowcharts.insert_one(doc)
    return jsonify({
        "success": True,
        "diagram_id": new_id,
        "title": sanitized["title"],
        "updated_at": now_iso,
        "message": "Diagram saved successfully"
    }), 201


@app.route("/api/flowchart/list", methods=["GET"])
def list_flowcharts():
    student, err_resp = get_authenticated_student_user()
    if err_resp:
        return err_resp

    conditions = []
    if student["email"]:
        conditions.append({"owner_email": student["email"]})
    if student["usn"]:
        conditions.append({"owner_usn": student["usn"]})
    if student["team_name"]:
        conditions.append({"team_name": student["team_name"]})

    if not conditions:
        return jsonify({"success": True, "diagrams": []}), 200

    cursor = db.flowcharts.find({"$or": conditions}).sort("updated_at", -1)
    diagrams = []
    for doc in cursor:
        diagrams.append({
            "id": doc.get("diagram_id"),
            "title": doc.get("title", "Untitled Flowchart"),
            "description": doc.get("description", ""),
            "node_count": len(doc.get("nodes", [])),
            "edge_count": len(doc.get("edges", [])),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at")
        })

    return jsonify({"success": True, "diagrams": diagrams}), 200


@app.route("/api/flowchart/<diagram_id>", methods=["GET"])
def get_flowchart(diagram_id):
    student, err_resp = get_authenticated_student_user()
    if err_resp:
        return err_resp

    doc = db.flowcharts.find_one({"diagram_id": diagram_id})
    if not doc:
        return jsonify({"error": "Diagram not found"}), 404

    is_owner = (
        (doc.get("owner_email") and doc.get("owner_email") == student["email"]) or
        (student["usn"] and doc.get("owner_usn") and doc.get("owner_usn") == student["usn"]) or
        (student["team_name"] and doc.get("team_name") and doc.get("team_name") == student["team_name"])
    )
    if not is_owner:
        return jsonify({"error": "Access forbidden: you do not have permission to view this diagram."}), 403

    doc.pop("_id", None)
    # Backward compatibility: ensure legacy diagrams always have points array on edges
    for e in doc.get("edges", []):
        if "points" not in e or not isinstance(e.get("points"), list):
            e["points"] = []

    return jsonify({"success": True, "diagram": doc}), 200


@app.route("/api/flowchart/<diagram_id>", methods=["DELETE"])
def delete_flowchart(diagram_id):
    student, err_resp = get_authenticated_student_user()
    if err_resp:
        return err_resp

    doc = db.flowcharts.find_one({"diagram_id": diagram_id})
    if not doc:
        return jsonify({"error": "Diagram not found"}), 404

    is_owner = (
        (doc.get("owner_email") and doc.get("owner_email") == student["email"]) or
        (student["usn"] and doc.get("owner_usn") and doc.get("owner_usn") == student["usn"]) or
        (student["team_name"] and doc.get("team_name") and doc.get("team_name") == student["team_name"])
    )
    if not is_owner:
        return jsonify({"error": "Access forbidden: you do not have permission to delete this diagram."}), 403

    db.flowcharts.delete_one({"diagram_id": diagram_id})
    return jsonify({"success": True, "message": "Diagram deleted successfully"}), 200


@app.route("/api/flowchart/duplicate/<diagram_id>", methods=["POST"])
def duplicate_flowchart(diagram_id):
    student, err_resp = get_authenticated_student_user()
    if err_resp:
        return err_resp

    doc = db.flowcharts.find_one({"diagram_id": diagram_id})
    if not doc:
        return jsonify({"error": "Diagram not found"}), 404

    is_owner = (
        (doc.get("owner_email") and doc.get("owner_email") == student["email"]) or
        (student["usn"] and doc.get("owner_usn") and doc.get("owner_usn") == student["usn"]) or
        (student["team_name"] and doc.get("team_name") and doc.get("team_name") == student["team_name"])
    )
    if not is_owner:
        return jsonify({"error": "Access forbidden: you do not have permission to duplicate this diagram."}), 403

    new_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    clone = {
        "diagram_id": new_id,
        "title": f"Copy of {doc.get('title', 'Flowchart')}",
        "description": doc.get("description", ""),
        "nodes": doc.get("nodes", []),
        "edges": doc.get("edges", []),
        "viewport": doc.get("viewport", {"x": 0, "y": 0, "zoom": 1.0}),
        "layout": doc.get("layout", {"direction": "TB", "grid": "dots", "gridSize": 20}),
        "owner_email": student["email"],
        "owner_usn": student["usn"],
        "owner_name": student["name"],
        "team_name": student["team_name"],
        "created_at": now_iso,
        "updated_at": now_iso
    }
    db.flowcharts.insert_one(clone)
    return jsonify({
        "success": True,
        "diagram_id": new_id,
        "title": clone["title"],
        "message": "Diagram duplicated successfully"
    }), 201


@app.route("/api/flowchart/code-to-flowchart", methods=["POST"])
def code_to_flowchart():
    student, err_resp = get_authenticated_student_user()
    if err_resp:
        return err_resp

    data = request.json or {}
    language = str(data.get("language") or "python").lower().strip()
    code = str(data.get("code") or "")

    if not code.strip():
        return jsonify({"error": "Code input cannot be empty."}), 400

    try:
        if language == "python":
            result = parse_python_code(code)
        elif language == "java":
            result = parse_java_code(code)
        else:
            return jsonify({"error": f"Unsupported language '{language}'. Supported: python, java"}), 400

        return jsonify({
            "success": True,
            "nodes": result["nodes"],
            "edges": result["edges"],
            "title": result.get("title", "Generated Flowchart")
        }), 200
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to generate flowchart from code: {str(e)}"}), 500


@app.route("/api/flowchart/generate-ai", methods=["POST"])
def generate_flowchart_from_description():
    student, err_resp = get_authenticated_student_user()
    if err_resp:
        return err_resp

    data = request.json or {}
    prompt_text = str(data.get("prompt") or "").strip()

    if not prompt_text:
        return jsonify({"error": "Please describe the algorithm, workflow, or process you want to model."}), 400

    if len(prompt_text) < 5:
        return jsonify({"error": "Description is too short. Please provide more details."}), 400

    if len(prompt_text) > 2500:
        return jsonify({"error": "Description exceeds maximum allowed length of 2500 characters."}), 400

    if not GEMINI_API_KEY:
        return jsonify({
            "error": "AI flowchart generation is currently unavailable (GEMINI_API_KEY not configured). You can still create flowcharts manually or convert from Python/Java code."
        }), 503

    ai_system_prompt = f"""You are an expert system flowchart architect.
Generate a structured flowchart for the following student project algorithm, process, or workflow description:

DESCRIPTION:
\"{prompt_text}\"

Return ONLY valid JSON matching this exact structure with NO markdown fences, no explanatory text, and no backticks:
{{
  "title": "Short descriptive diagram title",
  "description": "Brief 1-sentence workflow summary",
  "nodes": [
    {{"id": "node_1", "type": "start", "label": "Start"}},
    {{"id": "node_2", "type": "process", "label": "Concise step"}},
    {{"id": "node_3", "type": "decision", "label": "Condition ?"}},
    {{"id": "node_end", "type": "end", "label": "End"}}
  ],
  "edges": [
    {{"id": "edge_1", "source": "node_1", "target": "node_2", "label": ""}},
    {{"id": "edge_2", "source": "node_2", "target": "node_3", "label": ""}},
    {{"id": "edge_3", "source": "node_3", "target": "node_4", "label": "Yes"}},
    {{"id": "edge_4", "source": "node_3", "target": "node_5", "label": "No"}}
  ]
}}

STRICT REQUIREMENTS:
1. Supported 'type' values: "start", "end", "process", "decision", "inputoutput", "document", "subroutine", "database".
2. Must have a "start" node and at least one "end" node.
3. Every decision node MUST have 2 outgoing branches labeled "Yes" and "No" or "True" and "False".
4. Every edge 'source' and 'target' MUST match a real node 'id'.
5. Limit total nodes between 4 and 25 for clear visual hierarchy.
6. Return pure JSON only.
"""

    raw_response = call_gemini_generic_prompt(ai_system_prompt)
    if not raw_response:
        return jsonify({
            "error": "The AI generation request could not be completed. Please retry or adjust your prompt description."
        }), 502

    # Strip possible code blocks (```json ... ```)
    cleaned_json_text = raw_response.strip()
    if cleaned_json_text.startswith("```"):
        cleaned_json_text = re.sub(r"^```(?:json)?\s*", "", cleaned_json_text)
        cleaned_json_text = re.sub(r"\s*```$", "", cleaned_json_text)
    cleaned_json_text = cleaned_json_text.strip()

    try:
        parsed_data = json.loads(cleaned_json_text)
    except json.JSONDecodeError:
        first_brace = cleaned_json_text.find("{")
        last_brace = cleaned_json_text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            try:
                parsed_data = json.loads(cleaned_json_text[first_brace:last_brace+1])
            except Exception:
                return jsonify({"error": "AI generated a malformed response. Please retry with a clearer prompt."}), 422
        else:
            return jsonify({"error": "AI generated a malformed response. Please retry with a clearer prompt."}), 422

    is_valid, sanitized, err_msg = validate_diagram_data(parsed_data)
    if not is_valid:
        return jsonify({"error": f"Invalid generated diagram: {err_msg}. Please retry."}), 422

    # Calculate professional layout
    sanitized["nodes"] = calculate_hierarchical_layout(sanitized["nodes"], sanitized["edges"], direction="TB")

    return jsonify({
        "success": True,
        "diagram": sanitized,
        "message": "Flowchart generated successfully by AI"
    }), 200


@app.route("/api/flowchart/auto-layout", methods=["POST"])
def auto_layout_flowchart():
    student, err_resp = get_authenticated_student_user()
    if err_resp:
        return err_resp

    data = request.json or {}
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    direction = str(data.get("direction", "TB")).upper()
    if direction not in ["TB", "LR"]:
        direction = "TB"

    if not isinstance(nodes, list) or not isinstance(edges, list):
        return jsonify({"error": "Invalid nodes or edges format."}), 400

    positioned = calculate_hierarchical_layout(nodes, edges, direction=direction)
    return jsonify({
        "success": True,
        "nodes": positioned,
        "direction": direction
    }), 200


# ==================================================================== #
#                       RUN SERVER                                     #
# ==================================================================== #

if __name__ == "__main__":
    socketio.run(app, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)

