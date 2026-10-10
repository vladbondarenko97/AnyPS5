import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import macos_launcher


def make_self(properties):
    elf = bytearray(0x40 + 0x38 * 2)
    elf[:4] = b"\x7fELF"
    struct.pack_into("<Q", elf, 0x20, 0x40)
    struct.pack_into("<HH", elf, 0x36, 0x38, 2)
    struct.pack_into("<Q", elf, 0x40 + 0x38 + 8, 0x200)
    struct.pack_into("<Q", elf, 0x40 + 0x38 + 32, 4)
    header = bytearray(0x20 + 0x20 * 2)
    header[:4] = b"\x4f\x15\x3d\x1d"
    struct.pack_into("<H", header, 0x18, 2)
    payload = len(header) + len(elf)
    struct.pack_into("<QQQ", header, 0x20, 0x110004, payload, 4)
    struct.pack_into("<QQQ", header, 0x40, properties, payload + 4, 4)
    return bytes(header + elf + b"metadata"), bytes(elf)


class UnwrapTest(unittest.TestCase):
    def test_segment_lands_at_its_program_header_offset(self):
        container, elf = make_self(0x102804)
        self.assertEqual(macos_launcher.unwrap(container), elf + bytes(0x200 - len(elf)) + b"data")

    def test_elf_is_returned_unchanged(self):
        self.assertEqual(macos_launcher.unwrap(b"\x7fELFrest"), b"\x7fELFrest")

    def test_encrypted_segment_is_refused(self):
        with self.assertRaises(RuntimeError):
            macos_launcher.unwrap(make_self(0x102806)[0])


if __name__ == "__main__":
    unittest.main()
