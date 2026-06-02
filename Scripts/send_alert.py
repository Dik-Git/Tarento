import os
import json
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

def build_html(alerts):
    status_colors = {
        "EXPIRED":  "#dc3545",
        "CRITICAL": "#fd7e14",
        "WARNING":  "#ffc107",
        "ERROR":    "#6c757d"
    }
    rows = ""
    for a in alerts:
        color = status_colors.get(a["status"], "#000")
        rows += f"""
        <tr>
            <td style="padding:8px;border:1px solid #ddd">{a['cert_name']}</td>
            <td style="padding:8px;border:1px solid #ddd">{a.get('common_name','N/A')}</td>
            <td style="padding:8px;border:1px solid #ddd">{a.get('expiry_date','N/A')}</td>
            <td style="padding:8px;border:1px solid #ddd">{a.get('days_remaining','N/A')}</td>
            <td style="padding:8px;border:1px solid #ddd;color:{color};font-weight:bold">
                {a['status']}
            </td>
        </tr>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif">
    <h2>🔐 Certificate Expiry Alert</h2>
    <p>Checked on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
    <table style="border-collapse:collapse;width:100%">
        <tr style="background:#f2f2f2;font-weight:bold">
            <td style="padding:8px;border:1px solid #ddd">Cert File</td>
            <td style="padding:8px;border:1px solid #ddd">Common Name</td>
            <td style="padding:8px;border:1px solid #ddd">Expiry Date</td>
            <td style="padding:8px;border:1px solid #ddd">Days Left</td>
            <td style="padding:8px;border:1px solid #ddd">Status</td>
        </tr>
        {rows}
    </table>
    <p>⚠️ Please renew expiring certificates and upload the new ones to Azure Blob Storage.</p>
    </body></html>"""

def send_email(alerts):
    smtp_host  = os.environ["SMTP_HOST"]
    smtp_port  = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user  = os.environ["SMTP_USER"]
    smtp_pass  = os.environ["SMTP_PASS"]
    to_emails  = os.environ["ALERT_TO_EMAILS"].split(",")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"⚠️ Cert Alert — {len(alerts)} certificate(s) need attention"
    msg["From"]    = smtp_user
    msg["To"]      = ", ".join(to_emails)
    msg.attach(MIMEText(build_html(alerts), "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_emails, msg.as_string())

    print(f"Alert email sent to: {to_emails}")

if __name__ == "__main__":
    with open("cert_results.json") as f:
        results = json.load(f)

    alerts = results.get("alerts", [])
    if not alerts:
        print("No alerts to send.")
        sys.exit(0)

    send_email(alerts)
