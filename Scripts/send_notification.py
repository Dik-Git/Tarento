import os
import sys
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime


STATUS_COLORS = {
    "HEALTHY":         "#28a745",
    "RENEWED":         "#17a2b8",
    "EXPIRED":         "#dc3545",
    "CRITICAL":        "#fd7e14",
    "WARNING":         "#ffc107",
    "RENEWAL_FAILED":  "#dc3545",
    "PARSE_ERROR":     "#6c757d",
}

STATUS_ICONS = {
    "HEALTHY":         "✅",
    "RENEWED":         "🔄",
    "EXPIRED":         "❌",
    "CRITICAL":        "🔴",
    "WARNING":         "⚠️",
    "RENEWAL_FAILED":  "❌",
    "PARSE_ERROR":     "⚠️",
}


def build_html(results: dict) -> str:
    """Build HTML email body from cert results."""

    healthy  = results.get("healthy", [])
    renewed  = results.get("renewed", [])
    failed   = results.get("failed", [])
    checked  = results.get("checked_at", "N/A")

    # ── Summary banner ──────────────────────────────────────────────────────
    summary_html = f"""
    <div style="display:flex;gap:20px;margin:20px 0">
        <div style="background:#28a745;color:white;padding:15px 25px;
                    border-radius:8px;text-align:center">
            <div style="font-size:28px;font-weight:bold">{len(healthy)}</div>
            <div>Healthy</div>
        </div>
        <div style="background:#17a2b8;color:white;padding:15px 25px;
                    border-radius:8px;text-align:center">
            <div style="font-size:28px;font-weight:bold">{len(renewed)}</div>
            <div>Renewed</div>
        </div>
        <div style="background:#dc3545;color:white;padding:15px 25px;
                    border-radius:8px;text-align:center">
            <div style="font-size:28px;font-weight:bold">{len(failed)}</div>
            <div>Failed</div>
        </div>
    </div>"""

    # ── Renewed certs table ──────────────────────────────────────────────────
    renewed_html = ""
    if renewed:
        rows = ""
        for r in renewed:
            color = STATUS_COLORS.get(r["status"], "#000")
            icon  = STATUS_ICONS.get(r["status"], "")
            rows += f"""
            <tr>
                <td style="padding:10px;border:1px solid #ddd">{r['cert_name']}</td>
                <td style="padding:10px;border:1px solid #ddd">{r['common_name']}</td>
                <td style="padding:10px;border:1px solid #ddd;
                           text-decoration:line-through;color:#999">
                    {r['expiry_date']}
                </td>
                <td style="padding:10px;border:1px solid #ddd;
                           color:#28a745;font-weight:bold">
                    {r.get('new_expiry_date', 'N/A')}
                </td>
                <td style="padding:10px;border:1px solid #ddd;
                           color:{color};font-weight:bold">
                    {icon} {r['status']}
                </td>
            </tr>"""

        renewed_html = f"""
        <h3 style="color:#17a2b8">🔄 Auto Renewed Certificates</h3>
        <table style="border-collapse:collapse;width:100%;
                      font-family:Arial,sans-serif">
            <tr style="background:#f2f2f2;font-weight:bold">
                <td style="padding:10px;border:1px solid #ddd">Cert File</td>
                <td style="padding:10px;border:1px solid #ddd">Common Name</td>
                <td style="padding:10px;border:1px solid #ddd">Old Expiry</td>
                <td style="padding:10px;border:1px solid #ddd">New Expiry</td>
                <td style="padding:10px;border:1px solid #ddd">Status</td>
            </tr>
            {rows}
        </table>"""

    # ── Healthy certs table ──────────────────────────────────────────────────
    healthy_html = ""
    if healthy:
        rows = ""
        for h in healthy:
            rows += f"""
            <tr>
                <td style="padding:10px;border:1px solid #ddd">{h['cert_name']}</td>
                <td style="padding:10px;border:1px solid #ddd">{h['common_name']}</td>
                <td style="padding:10px;border:1px solid #ddd">{h['expiry_date']}</td>
                <td style="padding:10px;border:1px solid #ddd">{h['days_remaining']}</td>
                <td style="padding:10px;border:1px solid #ddd;
                           color:#28a745;font-weight:bold">✅ HEALTHY</td>
            </tr>"""

        healthy_html = f"""
        <h3 style="color:#28a745">✅ Healthy Certificates</h3>
        <table style="border-collapse:collapse;width:100%;
                      font-family:Arial,sans-serif">
            <tr style="background:#f2f2f2;font-weight:bold">
                <td style="padding:10px;border:1px solid #ddd">Cert File</td>
                <td style="padding:10px;border:1px solid #ddd">Common Name</td>
                <td style="padding:10px;border:1px solid #ddd">Expiry Date</td>
                <td style="padding:10px;border:1px solid #ddd">Days Left</td>
                <td style="padding:10px;border:1px solid #ddd">Status</td>
            </tr>
            {rows}
        </table>"""

    # ── Failed certs table ───────────────────────────────────────────────────
    failed_html = ""
    if failed:
        rows = ""
        for f in failed:
            rows += f"""
            <tr>
                <td style="padding:10px;border:1px solid #ddd">{f['cert_name']}</td>
                <td style="padding:10px;border:1px solid #ddd">
                    {f.get('expiry_date', 'N/A')}
                </td>
                <td style="padding:10px;border:1px solid #ddd;
                           color:#dc3545;font-weight:bold">
                    ❌ {f['status']}
                </td>
                <td style="padding:10px;border:1px solid #ddd;color:#999">
                    {f.get('reason', 'N/A')}
                </td>
            </tr>"""

        failed_html = f"""
        <h3 style="color:#dc3545">❌ Failed Renewals</h3>
        <table style="border-collapse:collapse;width:100%;
                      font-family:Arial,sans-serif">
            <tr style="background:#f2f2f2;font-weight:bold">
                <td style="padding:10px;border:1px solid #ddd">Cert File</td>
                <td style="padding:10px;border:1px solid #ddd">Expiry Date</td>
                <td style="padding:10px;border:1px solid #ddd">Status</td>
                <td style="padding:10px;border:1px solid #ddd">Reason</td>
            </tr>
            {rows}
        </table>"""

    return f"""
    <html>
    <body style="font-family:Arial,sans-serif;padding:30px;
                 max-width:900px;margin:auto">

        <h2 style="color:#333;border-bottom:3px solid #0078d4;
                   padding-bottom:10px">
            🔐 Certificate Auto-Renewal Report
        </h2>

        <p style="color:#666">
            Checked on <b>{checked}</b>
        </p>

        {summary_html}
        {renewed_html}
        {healthy_html}
        {failed_html}

        <hr style="margin-top:30px;border:1px solid #eee">
        <p style="color:#999;font-size:12px">
            This is an automated report from your
            Azure Certificate Monitor System.
        </p>

    </body>
    </html>"""


def send_email(results: dict):
    """Send notification email."""
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASSWORD"]           # ✅ Fixed: was SMTP_PASS
    to_list   = [e.strip() for e in
                 os.environ["SMTP_RECEIVER"].split(",")]  # ✅ Fixed: was ALERT_TO_EMAILS

    renewed = results.get("renewed", [])
    failed  = results.get("failed",  [])

    # Build subject line
    if failed:
        subject = f"❌ Cert Alert: {len(failed)} renewal(s) FAILED — action needed"
    elif renewed:
        subject = f"🔄 Cert Update: {len(renewed)} cert(s) auto renewed successfully"
    else:
        subject = f"✅ Cert Check: All {len(results.get('healthy', []))} cert(s) healthy"

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_user
    msg["To"]      = ", ".join(to_list)
    msg.attach(MIMEText(build_html(results), "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_list, msg.as_string())

    print(f"✅ Email sent to: {to_list}")
    print(f"   Subject: {subject}")


if __name__ == "__main__":
    print("\n📧 Sending notification email...")

    # ✅ Fixed: use absolute path relative to current working directory
    json_path = os.path.join(os.getcwd(), "cert_results.json")

    try:
        with open(json_path) as f:
            results = json.load(f)
    except FileNotFoundError:
        print(f"❌ cert_results.json not found at: {json_path}")
        print("   This means check_and_renew.py crashed before completing.")
        print("   Check the previous step logs for Azure connection errors.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ cert_results.json is invalid JSON: {e}")
        sys.exit(1)

    send_email(results)
