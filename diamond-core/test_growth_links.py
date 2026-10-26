"""Focused offline checks for link attribution and destination boundaries."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import parse_qsl, urlsplit

import growth_links as growth


class GrowthLinkTests(unittest.TestCase):
    def test_utm_values_round_trip_without_parameter_injection(self):
        result = growth.generate_link("beautiful-mind", "friends & family", "organic+social", "love / art?", "A=1&coupon=free")
        self.assertEqual(result["rx_id"], "HXRX-BEAUTYMND-ARTCAP")
        parts = urlsplit(result["url"])
        self.assertEqual(parts.netloc, "www.hatsrx.com")
        self.assertEqual(parts.path, "/product-page/beautiful-mind-snapback-hat")
        self.assertEqual(dict(parse_qsl(parts.query)), {
            "utm_source": "friends & family", "utm_medium": "organic+social",
            "utm_campaign": "love / art?", "utm_content": "A=1&coupon=free"})

    def test_old_tags_replaced_and_unrelated_query_preserved(self):
        result = growth._tag_url("https://hatsrx.com/product-page/example?ref=existing&blank=&utm_source=old&UTM_SOURCE=old2&utm_content=stale&utm_term=stale",
                                 "new", "organic", "test")
        self.assertEqual(parse_qsl(urlsplit(result).query, keep_blank_values=True), [
            ("ref", "existing"), ("blank", ""), ("utm_source", "new"),
            ("utm_medium", "organic"), ("utm_campaign", "test")])

    def test_lookalike_hosts_and_nonproduct_destinations_rejected(self):
        urls = [
            "http://www.hatsrx.com/product-page/hat", "https://www.hatsrx.com.evil.example/product-page/hat",
            "https://shop.hatsrx.com/product-page/hat", "https://hatsrx.com@evil.example/product-page/hat",
            "https://evil.example@hatsrx.com/product-page/hat", "https://hatsrx.com:443/product-page/hat",
            "https://hatsrx.com./product-page/hat", "https://hаtsrx.com/product-page/hat",
            "https://hatsrx.com/product-page/../checkout", "https://hatsrx.com/product-page/%2e%2e",
            "https://hatsrx.com/product-page/hat%2fcheckout", "https://hatsrx.com/checkout",
            "https://hatsrx.com/product-page/hat#checkout", "https://hatsrx.com\n/product-page/hat",
            "https://hatsrx.com\\evil.example/product-page/hat", "javascript:alert(1)",
        ]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                growth.validate_product_url(url)

    def test_invalid_campaign_fields_rejected(self):
        for value in ("", "  ", "private\nheader", "x" * 201, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                growth.generate_link("sea-heart", value, "organic", "test")
        with self.assertRaises(ValueError):
            growth.generate_link("sea-heart", "instagram", "organic", "test", " ")

    def test_unicode_attribution_and_stable_rx_selection(self):
        result = growth.generate_link("HXRX-PSILY-LOVE", "Mimi", "organic", "Magic × Wizard")
        self.assertEqual(result, growth.generate_link("psily", "Mimi", "organic", "Magic × Wizard"))
        self.assertEqual(dict(parse_qsl(urlsplit(result["url"]).query))["utm_campaign"], "Magic × Wizard")
        with self.assertRaises(ValueError):
            growth.generate_link("invented-hat", "instagram", "organic", "test")

    def test_cli_runs_from_unrelated_directory_without_writes(self):
        script = str(Path(growth.__file__).resolve())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protected = {name: b"synthetic unchanged" for name in ("memory.txt", "opportunities.json", "token.json", "credentials.json")}
            for name, data in protected.items():
                (root / name).write_bytes(data)
            before = set(root.iterdir())
            result = subprocess.run([sys.executable, script, "link", "--product", "crown-state",
                                     "--source", "instagram", "--medium", "organic_social", "--campaign", "founder-review"],
                                    cwd=directory, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)["rx_id"], "HXRX-CROWNSTATE-CORE")
            self.assertEqual(set(root.iterdir()), before)
            for name, data in protected.items():
                self.assertEqual((root / name).read_bytes(), data)
            listed = subprocess.run([sys.executable, script, "list"], cwd=directory, capture_output=True, text=True, check=True)
            self.assertEqual(len(json.loads(listed.stdout)), 4)

    def test_cli_invalid_product_returns_error_without_url(self):
        result = subprocess.run([sys.executable, str(Path(growth.__file__).resolve()), "link", "--product", "invented",
                                 "--source", "instagram", "--medium", "organic", "--campaign", "test"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("Unknown product", result.stderr)


if __name__ == "__main__":
    unittest.main()
