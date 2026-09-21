"""Deterministic metadata extraction for cryptography and protocol documents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


class MetadataExtractor:
    """Extract conservative, filterable metadata without another model call."""

    PROTOCOL_PATTERNS: List[Tuple[str, str]] = [
        (r"\bTLS\s*1\.3\b|\bRFC\s*8446\b", "TLS 1.3"),
        (r"\bTLS\s*1\.2\b|\bRFC\s*5246\b", "TLS 1.2"),
        (r"\bQUIC\b|\bRFC\s*900[01]\b", "QUIC"),
        (r"\bHPKE\b|\bRFC\s*9180\b", "HPKE"),
        (r"\bMLS\b|\bRFC\s*9420\b", "MLS"),
        (r"\bSSH\b", "SSH"),
        (r"\bIPsec\b|\bIKEv2\b", "IPsec/IKEv2"),
        (r"\bSignal Protocol\b|\bDouble Ratchet\b", "Signal Protocol"),
        (r"\bNoise Protocol\b|\bNoise_[A-Z0-9_]+\b", "Noise"),
        (r"\bKerberos\b", "Kerberos"),
        (r"\bOAuth\s*2(?:\.0)?\b", "OAuth 2.0"),
        (r"\bOpenID Connect\b|\bOIDC\b", "OpenID Connect"),
    ]
    ALGORITHM_PATTERNS: List[Tuple[str, str]] = [
        (r"\bAES[- ]?(?:128|192|256)?[- ]?GCM\b", "AES-GCM"),
        (r"\bAES[- ]?(?:128|192|256)?[- ]?CCM\b", "AES-CCM"),
        (r"\bChaCha20[- ]Poly1305\b", "ChaCha20-Poly1305"),
        (r"\bHKDF\b", "HKDF"),
        (r"\bHMAC\b", "HMAC"),
        (r"\bSHA[- ]?1\b", "SHA-1"),
        (r"\bSHA[- ]?256\b", "SHA-256"),
        (r"\bSHA[- ]?384\b", "SHA-384"),
        (r"\bSHA[- ]?512\b", "SHA-512"),
        (r"\bX25519\b", "X25519"),
        (r"\bEd25519\b", "Ed25519"),
        (r"\bECDSA\b", "ECDSA"),
        (r"\bECDH\b", "ECDH"),
        (r"\bRSA(?:[- ]?PSS)?\b", "RSA"),
        (r"\bML[- ]KEM\b|\bKyber\b", "ML-KEM"),
        (r"\bML[- ]DSA\b|\bDilithium\b", "ML-DSA"),
    ]
    TOPIC_PATTERNS: List[Tuple[str, str]] = [
        (r"forward secrecy|前向保密", "forward_secrecy"),
        (r"authentication|认证", "authentication"),
        (r"key derivation|密钥派生", "key_derivation"),
        (r"nonce reuse|nonce 重用|随机数重用", "nonce_reuse"),
        (r"side[- ]channel|侧信道", "side_channel"),
        (r"post[- ]quantum|后量子", "post_quantum"),
        (r"zero[- ]knowledge|零知识", "zero_knowledge"),
    ]

    @staticmethod
    def _matches(patterns: Iterable[Tuple[str, str]], text: str) -> List[str]:
        return [label for pattern, label in patterns if re.search(pattern, text, re.IGNORECASE)]

    @staticmethod
    def _document_type(text: str, filename: str) -> str:
        if re.search(r"\bRFC\s*\d{3,5}\b", text, re.IGNORECASE):
            return "rfc"
        if re.search(r"\b(?:NIST|FIPS)\s+(?:SP\s+)?\d", text, re.IGNORECASE):
            return "standard"
        if re.search(r"\b(?:ISO|IEC|IEEE)\s*[/:-]?\s*\d", text, re.IGNORECASE):
            return "standard"
        if re.search(r"\b(?:abstract|references|doi:)\b", text, re.IGNORECASE):
            return "academic_paper"
        if re.search(r"security definition|threat model|安全定义|威胁模型", text, re.IGNORECASE):
            return "security_definition"
        if Path(filename).suffix.casefold() in {".md", ".txt", ".html", ".htm"}:
            return "implementation_guide"
        return "document"

    @staticmethod
    def _standard_org(text: str) -> str | None:
        organizations = [
            (r"\bRFC\s*\d|\bIETF\b", "IETF"),
            (r"\bNIST\b|\bFIPS\b", "NIST"),
            (r"\bISO(?:/IEC)?\b", "ISO/IEC"),
            (r"\bIEEE\b", "IEEE"),
            (r"\bCFRG\b", "IETF CFRG"),
        ]
        for pattern, name in organizations:
            if re.search(pattern, text, re.IGNORECASE):
                return name
        return None

    @classmethod
    def extract(cls, text: str, filename: str = "") -> Dict[str, Any]:
        sample = f"{filename}\n{text or ''}"
        protocols = cls._matches(cls.PROTOCOL_PATTERNS, sample)
        algorithms = cls._matches(cls.ALGORITHM_PATTERNS, sample)
        security_topics = cls._matches(cls.TOPIC_PATTERNS, sample)
        rfc_match = re.search(r"\bRFC\s*[-:]?\s*(\d{3,5})\b", sample, re.IGNORECASE)
        years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", sample)]
        plausible_years = [year for year in years if 1970 <= year <= 2100]
        document_type = cls._document_type(sample, filename)

        metadata: Dict[str, Any] = {
            "document_type": document_type,
            "category": "protocol" if protocols else "cryptography",
            "protocols": protocols,
            "algorithms": algorithms,
            "security_topics": security_topics,
        }
        if protocols:
            metadata["protocol"] = protocols[0]
        if rfc_match:
            metadata["rfc_number"] = f"RFC {rfc_match.group(1)}"
        organization = cls._standard_org(sample)
        if organization:
            metadata["standard_org"] = organization
        if plausible_years:
            metadata["year"] = plausible_years[0]
        return metadata
