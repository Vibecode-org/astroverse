"""Independent golden wire fixtures and deliberately corrupted binary payloads."""

import base64
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from data import catalog as c
from data import gen_catalog_100k as generator


class BinaryEdgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "objects.bin"
        self.fixture = json.loads((Path(__file__).parent / "fixtures/binary_catalog.json").read_text())

    def parse(self, blob, v2=False):
        self.path.write_bytes(blob)
        return (c.read_binary_catalog_v2 if v2 else c.read_binary_catalog)(self.path)

    def test_golden_wire_contract_matches_both_encoders(self):
        for version, encoder in [("v1", c.encode_binary_catalog), ("v2", c.encode_binary_catalog_v2)]:
            expected = base64.b64decode(self.fixture[version])
            self.assertEqual(encoder(self.fixture["objects"]), expected)
            self.assertEqual(self.parse(expected)["count"], 3)

    def test_v1_truncation_version_offset_size_and_parent_errors(self):
        original = base64.b64decode(self.fixture["v1"])
        corrupt = [b"", original[:7], original[:8], original[:19], original[:-1], original + b"x"]
        for offset, fmt, value in [(4, "I", 99), (12, "Q", 0), (8, "I", 100000),
                                   (len(original) - 4, "i", 3), (len(original) - 4, "i", -2)]:
            blob = bytearray(original); struct.pack_into("<" + fmt, blob, offset, value)
            corrupt.append(blob)
        for blob in corrupt:
            with self.subTest(size=len(blob)), self.assertRaises(ValueError):
                self.parse(blob)

    def test_v2_corrupt_headers_offsets_sizes_and_strings(self):
        original = base64.b64decode(self.fixture["v2"])
        good = self.parse(original)
        offsets = good["section_offsets"]
        corrupt = [b"", original[:8], original[:20], original[:100]]
        edits = [(0, "4s", b"FAIL"), (4, "I", 99), (16, "I", 0), (12, "I", 0),
                 (20, "Q", 0), (20, "Q", len(original) + 1),
                 (20, "Q", offsets["positions"] + 1),
                 (36, "Q", offsets["positions"]),
                 (28, "Q", offsets["positions"]),
                 (8, "I", 100000),
                 (offsets["id_lengths"], "I", 100000),
                 (offsets["parents"], "i", -2), (offsets["parents"], "i", 3)]
        for offset, fmt, value in edits:
            blob = bytearray(original); struct.pack_into("<" + fmt, blob, offset, value)
            corrupt.append(blob)
        for blob in corrupt:
            with self.subTest(size=len(blob)), self.assertRaises(ValueError):
                self.parse(blob, v2=True)

    def test_default_v2_path_uses_environment_and_empty_catalog_roundtrips(self):
        self.path.write_bytes(c.encode_binary_catalog_v2([]))
        with patch.dict(os.environ, {"ASTROVERSE_CATALOG_PATH": str(self.path)}):
            self.assertEqual(c.read_binary_catalog_v2()["count"], 0)

    def test_color_encoding_handles_alpha_shorthand_and_invalid_input(self):
        for color, packed in [(None, 0), ("#abc", 0xaabbccff), ("#abcd", 0xaabbccdd),
                              ("#112233", 0x112233ff), ("#11223344", 0x11223344),
                              ("#badxx", 0), ("#gggggg", 0)]:
            with self.subTest(color=color):
                self.assertEqual(c._color_to_uint32(color), packed)
        self.assertEqual(c._uint32_to_color(0x112233ff), "#112233")
        self.assertEqual(c._uint32_to_color(0x11223344), "#11223344")

    def test_all_atomic_catalog_writers_preserve_previous_file_on_replace_failure(self):
        for writer in [c.write_catalog, c.write_binary_catalog, c.write_binary_catalog_v2]:
            self.path.write_bytes(b"previous")
            with self.subTest(writer=writer.__name__), patch("data.catalog.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    writer(self.path, self.fixture["objects"])
            self.assertEqual(self.path.read_bytes(), b"previous")
            self.assertEqual(list(Path(self.tmp.name).iterdir()), [self.path])

    def test_generator_is_deterministic_and_parents_exist(self):
        output = Path(self.tmp.name) / "generated.json"
        with patch.multiple(generator, OUTPUT=output, STARS=3, EXOPLANETS=27):
            generator.main()
            first = output.read_bytes()
            generator.main()
        self.assertEqual(output.read_bytes(), first)
        self.assertEqual(len(c.load_catalog(output)), 30)
        a, b = generator.lcg(7), generator.lcg(7)
        self.assertEqual([next(a) for _ in range(20)], [next(b) for _ in range(20)])
        self.assertRegex(generator.hex_color(lambda: 0.5), r"^#[0-9a-f]{6}$")
