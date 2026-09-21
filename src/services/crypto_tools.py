"""Deterministic cryptography reference and parameter-validation tools.

These checks are intentionally conservative. They help an analyst spot obviously
unsafe configurations; they are not a substitute for a protocol/security review.
"""

from __future__ import annotations

from typing import Any, Dict


PROTOCOL_CATALOG: Dict[str, Dict[str, Any]] = {
    "tls1.3": {
        "name": "TLS 1.3",
        "standard": "RFC 8446",
        "purpose": "Transport encryption with forward secrecy.",
        "core_primitives": ["(EC)DHE", "HKDF", "AEAD", "digital signatures"],
        "notes": [
            "Static RSA key exchange is not supported.",
            "0-RTT data is replayable and must be restricted to replay-safe operations.",
        ],
    },
    "signal": {
        "name": "Signal Protocol",
        "standard": "Signal specifications",
        "purpose": "Asynchronous end-to-end encrypted messaging.",
        "core_primitives": ["X3DH/PQXDH", "Double Ratchet", "X25519", "HKDF", "AEAD"],
        "notes": ["Identity-key verification remains an application responsibility."],
    },
    "aes-gcm": {
        "name": "AES-GCM",
        "standard": "NIST SP 800-38D",
        "purpose": "Authenticated encryption with associated data.",
        "core_primitives": ["AES", "GHASH"],
        "notes": ["A nonce must never repeat under the same key."],
    },
    "rsa-oaep": {
        "name": "RSAES-OAEP",
        "standard": "RFC 8017 / PKCS #1 v2.2",
        "purpose": "Public-key encryption of short secrets.",
        "core_primitives": ["RSA", "MGF1", "cryptographic hash"],
        "notes": ["Prefer hybrid encryption; do not encrypt large payloads directly."],
    },
    "ed25519": {
        "name": "Ed25519",
        "standard": "RFC 8032",
        "purpose": "Digital signatures.",
        "core_primitives": ["Edwards25519", "SHA-512"],
        "notes": ["Use a maintained library and protect signing keys."],
    },
    "x25519": {
        "name": "X25519",
        "standard": "RFC 7748",
        "purpose": "Elliptic-curve Diffie-Hellman key agreement.",
        "core_primitives": ["Curve25519"],
        "notes": ["Feed the shared secret through a protocol-bound KDF."],
    },
}


ALIASES = {
    "tls 1.3": "tls1.3",
    "tls_1_3": "tls1.3",
    "aesgcm": "aes-gcm",
    "rsa oaep": "rsa-oaep",
    "curve25519": "x25519",
}


def lookup_protocol(protocol: str) -> Dict[str, Any]:
    key = protocol.strip().lower()
    key = ALIASES.get(key, key)
    item = PROTOCOL_CATALOG.get(key)
    if item is None:
        return {
            "found": False,
            "protocol": protocol,
            "available": sorted(PROTOCOL_CATALOG),
            "guidance": "Search the bound knowledge base for the exact protocol/version.",
        }
    return {"found": True, "id": key, **item}


def validate_crypto_parameters(
    algorithm: str,
    key_size: int | None = None,
    curve: str | None = None,
    hash_name: str | None = None,
    nonce_reuse_possible: bool = False,
) -> Dict[str, Any]:
    """Return deterministic findings for common unsafe parameter choices."""

    normalized = algorithm.strip().lower().replace("_", "-")
    curve_normalized = (curve or "").strip().lower()
    hash_normalized = (hash_name or "").strip().lower().replace("-", "")
    findings = []

    if normalized.startswith("rsa"):
        if key_size is None:
            findings.append({"severity": "warning", "message": "RSA key size was not provided."})
        elif key_size < 2048:
            findings.append({"severity": "critical", "message": "RSA keys below 2048 bits are unsafe."})
        elif key_size == 2048:
            findings.append({"severity": "info", "message": "RSA-2048 is the minimum conventional baseline; consider RSA-3072 for longer-lived data."})

    if normalized in {"aes", "aes-gcm", "aes-cbc"} and key_size not in {128, 192, 256}:
        findings.append({"severity": "critical", "message": "AES key size must be 128, 192, or 256 bits."})

    if normalized in {"des", "3des", "rc4", "md5", "sha1"}:
        findings.append({"severity": "critical", "message": f"{algorithm} is deprecated for new security designs."})

    if normalized in {"aes-gcm", "chacha20-poly1305"} and nonce_reuse_possible:
        findings.append({"severity": "critical", "message": "Nonce reuse under the same AEAD key can destroy confidentiality and integrity."})

    if hash_normalized in {"md5", "sha1"}:
        findings.append({"severity": "critical", "message": f"{hash_name} is not suitable for collision-resistant signatures."})

    if curve_normalized in {"secp192r1", "prime192v1", "secp224r1"}:
        findings.append({"severity": "warning", "message": f"Curve {curve} is below the preferred modern security baseline."})

    if not findings:
        findings.append({"severity": "info", "message": "No obvious issue was found in the supplied parameters."})

    safe = not any(item["severity"] in {"critical", "high"} for item in findings)
    return {
        "algorithm": algorithm,
        "key_size": key_size,
        "curve": curve,
        "hash_name": hash_name,
        "safe_baseline": safe,
        "findings": findings,
        "disclaimer": "Validate the complete construction, implementation, threat model, and current standards before deployment.",
    }
