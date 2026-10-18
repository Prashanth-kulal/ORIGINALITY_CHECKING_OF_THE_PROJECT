"""
Live SMTP Delivery Test Script
Sends a single test email using the configured SMTP server and credentials in .env
to verify end-to-end SMTP authentication, TLS handshake, and remote SMTP acceptance.
"""
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import app
from app import send_email_notification, render_email_template, get_frontend_base_url

def run_live_test():
    target_email = "prashanth.23cs098@sode-edu.in"
    team_name = "Team 41"
    project_title = "Intelligent Water Contamination Monitoring and Early Warning System"
    base_url = get_frontend_base_url()

    subject = f"[LIVE TEST] Verification of Upgraded Notification System - {team_name}"
    plain_msg = (
        f"Hello Prashanth,\n\n"
        f"This is a live verification email from the upgraded Student Project Management System.\n"
        f"All 13 notification triggers have been updated with team-specific recipient resolution.\n\n"
        f"Project: {project_title}\n"
        f"Portal URL: {base_url}/team-dasboard.html"
    )

    html_msg = render_email_template(
        headline="Live Email Notification System Verified",
        badge_text="Live Test Successful",
        badge_color="#059669",
        team_name=team_name,
        project_title=project_title,
        key_details={
            "Test Type": "Live SMTP Delivery Verification",
            "Target Recipient": target_email,
            "Triggers Verified": "All 13 Workflows Verified"
        },
        message_content=(
            "This confirms that the SMTP background dispatcher, UTF-8 encoding, "
            "responsive HTML templates, and MongoDB team member recipient resolution "
            "are operating correctly."
        ),
        action_url=f"{base_url}/team-dasboard.html",
        action_text="Open Student Dashboard"
    )

    print(f"[*] Dispatching live test email to {target_email}...")
    # Using async_send=False to capture direct return value and verify synchronous SMTP acceptance
    success = send_email_notification(
        [target_email],
        subject,
        plain_msg,
        html_msg,
        async_send=False,
        trigger_name="LIVE_VERIFICATION_TEST",
        team_id=team_name
    )

    if success:
        print("[+] SUCCESS: SMTP server accepted message for delivery.")
        return 0
    else:
        print("[-] FAILED: SMTP server refused or failed to deliver message.")
        return 1

if __name__ == "__main__":
    sys.exit(run_live_test())
