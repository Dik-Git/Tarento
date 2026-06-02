import os
import sys
import json
from datetime import datetime, timezone, timedelta
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from azure.storage.blob import BlobServiceClient


# ── Configuration ──────────────────────────────────────────────────────────────
EXPIRY_THRESHOLD_DAYS = int(os.environ.get("EXPIRY_THRESHOLD_DAYS", "30"))
RENEW_VALIDITY_DAYS   = int(os.environ.get("RENEW_VALIDITY_DAYS", "365"))


def get_container_client():
    """Connect to Azure Blob Storage."""
    conn_str = (
        f"DefaultEndpointsProtocol=https;"
        f"AccountName={os.environ['AZURE_STORAGE_ACCOUNT']};"
        f"AccountKey={os.environ['AZURE_STORAGE_KEY']};"
        f"EndpointSuffix=core.windows.net"
    )
    client = BlobServiceClient.from_connection_string(conn_str)
    return client.get_container_client(os.environ["AZURE_STORAGE_CONTAINER"])


def download_certs(container) -> dict:
    """Download all .pem certs from Azure Blob Storage."""
    certs = {}
    print("\n📥 Downloading certs from Azure Blob Storage...")
    for blob in container.list_blobs():
        if blob.name.endswith(".pem"):
            data = container.download_blob(blob.name).readall()
            certs[blob.name] = data
            print(f"  Downloaded : {blob.name}")
    return certs


def parse_cert(pem_data: bytes):
    """Parse PEM data into a certificate object."""
    return x509.load_pem_x509_certificate(pem_data, default_backend())


def get_cert_info(cert, cert_name: str) -> dict:
    """Extract expiry info from a certificate."""
    now    = datetime.now(timezone.utc)
    expiry = cert.not_valid_after_utc
    days   = (expiry - now).days

    cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    cn       = cn_attrs[0].value if cn_attrs else cert_name.replace(".pem", "")

    return {
        "cert_name":      cert_name,
        "common_name":    cn,
        "expiry_date":    expiry.strftime("%Y-%m-%d"),
        "days_remaining": days,
        "is_expired":     days < 0,
        "is_critical":    0 <= days <= 7,
        "is_warning":     8 <= days <= EXPIRY_THRESHOLD_DAYS,
        "is_healthy":     days > EXPIRY_THRESHOLD_DAYS,
    }


def generate_new_cert(common_name: str) -> bytes:
    """
    Auto generate a new self-signed certificate.
    In production replace this with your real cert
    generation logic (e.g. call your CA API).
    """
    print(f"  🔧 Generating new cert for: {common_name}")

    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # Build certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=RENEW_VALIDITY_DAYS))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common_name)]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256(), default_backend())
    )

    # Return only the certificate in PEM format
    return cert.public_bytes(serialization.Encoding.PEM)


def upload_cert(container, cert_name: str, pem_data: bytes):
    """Upload cert to Azure Blob Storage overwriting the old one."""
    container.upload_blob(
        name=cert_name,
        data=pem_data,
        overwrite=True
    )
    print(f"  ✅ Uploaded new cert: {cert_name} to Azure Blob Storage")


def process_certs():
    """Main function — check all certs and renew if needed."""
    container = get_container_client()
    certs     = download_certs(container)

    if not certs:
        print("⚠️  No certs found in Azure Blob Storage.")
        sys.exit(0)

    results = {
        "healthy":  [],
        "renewed":  [],
        "failed":   [],
        "checked_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    }

    print(f"\n🔍 Checking {len(certs)} cert(s) "
          f"(threshold: {EXPIRY_THRESHOLD_DAYS} days)...")

    for cert_name, pem_data in certs.items():
        print(f"\n📄 {cert_name}")

        # Parse cert
        try:
            cert = parse_cert(pem_data)
            info = get_cert_info(cert, cert_name)
        except Exception as e:
            print(f"  ❌ Cannot parse: {e}")
            results["failed"].append({
                "cert_name": cert_name,
                "reason":    str(e),
                "status":    "PARSE_ERROR"
            })
            continue

        print(f"  Common Name   : {info['common_name']}")
        print(f"  Expiry Date   : {info['expiry_date']}")
        print(f"  Days Remaining: {info['days_remaining']}")

        # Decide action based on expiry
        if info["is_healthy"]:
            print(f"  ✅ HEALTHY — no action needed")
            results["healthy"].append({**info, "status": "HEALTHY"})

        else:
            # Determine status label
            if info["is_expired"]:
                status = "EXPIRED"
                print(f"  ❌ EXPIRED — auto renewing...")
            elif info["is_critical"]:
                status = "CRITICAL"
                print(f"  🔴 CRITICAL — auto renewing...")
            else:
                status = "WARNING"
                print(f"  ⚠️  WARNING — auto renewing...")

            # Auto renew
            try:
                new_pem = generate_new_cert(info["common_name"])
                upload_cert(container, cert_name, new_pem)

                # Verify new cert
                new_cert = parse_cert(new_pem)
                new_info = get_cert_info(new_cert, cert_name)

                print(f"  🎉 Renewed — new expiry: {new_info['expiry_date']} "
                      f"({new_info['days_remaining']} days)")

                results["renewed"].append({
                    **info,
                    "status":           status,
                    "new_expiry_date":  new_info["expiry_date"],
                    "new_days":         new_info["days_remaining"],
                })

            except Exception as e:
                print(f"  ❌ Failed to renew: {e}")
                results["failed"].append({
                    **info,
                    "status": "RENEWAL_FAILED",
                    "reason": str(e)
                })

    # Save results for email script
    with open("cert_results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Print summary
    print(f"\n{'─'*50}")
    print(f"📊 SUMMARY")
    print(f"{'─'*50}")
    print(f"  ✅ Healthy  : {len(results['healthy'])}")
    print(f"  🔄 Renewed  : {len(results['renewed'])}")
    print(f"  ❌ Failed   : {len(results['failed'])}")
    print(f"{'─'*50}")

    # Exit with error if any failures
    if results["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    print("🚀 Starting Certificate Auto-Renewal Check...")
    process_certs()
