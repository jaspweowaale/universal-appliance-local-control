"""Generate a self-signed CA + server certificate for the synthetic MQTT-TLS
integration test. Entirely offline, no real CA, no real domain. This is a
*locally trusted test certificate* in the literal sense: trusted only
because our own test client is told to trust this exact CA file - it proves
nothing about what the real Q10 firmware would accept."""
from __future__ import annotations

import datetime
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def generate(out_dir: Path, hostname: str = "local-roborock-test.internal", ip: str = "127.0.0.1"):
    out_dir.mkdir(parents=True, exist_ok=True)

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Test CA - offline only")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname), x509.IPAddress(ipaddress.ip_address(ip))]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    (out_dir / "ca_cert.pem").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    (out_dir / "server_cert.pem").write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    (out_dir / "server_key.pem").write_bytes(
        server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return out_dir / "ca_cert.pem", out_dir / "server_cert.pem", out_dir / "server_key.pem"


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/q10_test_certs")
    paths = generate(out)
    print("generated:", *paths)
