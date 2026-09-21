import unittest

from src.services.crypto_tools import lookup_protocol, validate_crypto_parameters


class CryptoToolTests(unittest.TestCase):
    def test_protocol_alias_resolves(self):
        result = lookup_protocol("TLS 1.3")
        self.assertTrue(result["found"])
        self.assertEqual(result["standard"], "RFC 8446")

    def test_unknown_protocol_is_explicit(self):
        result = lookup_protocol("unknown-demo-protocol")
        self.assertFalse(result["found"])
        self.assertIn("tls1.3", result["available"])

    def test_rsa_1024_is_rejected(self):
        result = validate_crypto_parameters("RSA", key_size=1024)
        self.assertFalse(result["safe_baseline"])
        self.assertEqual(result["findings"][0]["severity"], "critical")

    def test_gcm_nonce_reuse_is_rejected(self):
        result = validate_crypto_parameters(
            "AES-GCM",
            key_size=256,
            nonce_reuse_possible=True,
        )
        self.assertFalse(result["safe_baseline"])
        self.assertTrue(any("Nonce reuse" in item["message"] for item in result["findings"]))


if __name__ == "__main__":
    unittest.main()
