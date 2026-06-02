import os
import sys
import json
from datetime import datetime, timezone
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from azure.storage.blob import BlobServiceClient

def download_certs(account_name, account_key, container_name):
    """Download all .pem certs from Azure Blob Storage."""
    connect_str = (
        f"DefaultEndpointsProtocol=https;"
        f"AccountName={account_name};"
        f"AccountKey={account_key};"
        f"EndpointSuffix=core.windows.net"
    )
    client = BlobServiceClient.from_connection_string(connect_str)
    container = client.get_container_client(container_name)

    certs = {}
    for blob in container.list_blobs():
        if blob.name.endswith(".pem"):
            data = container.download_blob(blob.name).readall()
            certs[blob.name] = data
            print(f"Downloaded: {blob.name}")
    return certs

def check_expiry(certs, threshold_days=30):
    """Check expiry of all certs and return alerts."""
    alerts = []
    healthy = []

    for cert_name, pem_data in certs.items():
        try:
            cert = x509.load_pem_x509_certificate(pem_data, default_backend())
        except Exception as e:
            alerts.append({
                "cert_name": cert_name,
                "status": "ERROR",
                "message": f"Cannot parse cert: {e}"
            })
            continue

        now = datetime.now(timezone.utc)
        expiry = cert.not_valid_after_utc
        days = (expiry - now).days

        subject = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        cn = subject[0].value if subject else "Unknown"

        info = {
            "cert_name": cert_name,
            "common_name": cn,
            "expiry_date": expiry.strftime("%Y-%m-%d"),
            "days_remaining": days,
        }

        if days < 0:
            info["status"] = "EXPIRED"
            alerts.append(info)
        elif days <= 7:
            info["status"] = "CRITICAL"
            alerts.append(info)
        elif days <= threshold_days:
            info["status"] = "WARNING"
            alerts.append(info)
        else:
            info["status"] = "HEALTHY"
            healthy.append(info)
            print(f"✅ {cert_name}: {days} days remaining")

    return alerts, healthy

if __name__ == "__main__":
    account_name   = os.environ["AZURE_STORAGE_ACCOUNT"]
    account_key    = os.environ["AZURE_STORAGE_KEY"]
    container_name = os.environ["AZURE_STORAGE_CONTAINER"]
    threshold      = int(os.environ.get("EXPIRY_THRESHOLD_DAYS", "30"))

    certs = download_certs(account_name, account_key, container_name)

    if not certs:
        print("No certs found in storage.")
        sys.exit(0)

    alerts, healthy = check_expiry(certs, threshold)

    # Save results for next step
    with open("cert_results.json", "w") as f:
        json.dump({"alerts": alerts, "healthy": healthy}, f, indent=2)

    print(f"\nSummary: {len(healthy)} healthy, {len(alerts)} need attention")

    if alerts:
        print("\nCerts needing attention:")
        for a in alerts:
            print(f"  {a['status']}: {a['cert_name']} — {a.get('days_remaining','?')} days")
