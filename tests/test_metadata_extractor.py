import unittest

from src.processors.metadata_extractor import MetadataExtractor


class MetadataExtractorTests(unittest.TestCase):
    def test_extracts_rfc_protocol_algorithms_and_topics(self):
        metadata = MetadataExtractor.extract(
            "RFC 8446, published in 2018, specifies the TLS 1.3 key derivation "
            "using HKDF and AES-128-GCM with forward secrecy.",
            filename="rfc8446.pdf",
        )

        self.assertEqual(metadata["document_type"], "rfc")
        self.assertEqual(metadata["standard_org"], "IETF")
        self.assertEqual(metadata["rfc_number"], "RFC 8446")
        self.assertEqual(metadata["protocol"], "TLS 1.3")
        self.assertIn("HKDF", metadata["algorithms"])
        self.assertIn("AES-GCM", metadata["algorithms"])
        self.assertIn("key_derivation", metadata["security_topics"])
        self.assertEqual(metadata["year"], 2018)

    def test_extracts_post_quantum_nist_standard(self):
        metadata = MetadataExtractor.extract(
            "NIST FIPS 203 defines ML-KEM (formerly Kyber) for post-quantum security.",
            filename="fips-203.pdf",
        )

        self.assertEqual(metadata["document_type"], "standard")
        self.assertEqual(metadata["standard_org"], "NIST")
        self.assertEqual(metadata["algorithms"], ["ML-KEM"])
        self.assertIn("post_quantum", metadata["security_topics"])

    def test_plain_markdown_is_an_implementation_guide(self):
        metadata = MetadataExtractor.extract("Deploy with unique nonces.", filename="guide.md")
        self.assertEqual(metadata["document_type"], "implementation_guide")


if __name__ == "__main__":
    unittest.main()
