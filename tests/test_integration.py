"""Full toolchain integration: tric --hex -> reference conformance flow.

Needs the private MHX-T2 toolchain; skips gracefully without it.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from triad.chip import TOOLCHAIN_HINT, chip_path, have_chip  # noqa


def run(cmd, cwd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    assert r.returncode == 0, r.stderr
    return r.stdout


@unittest.skipUnless(have_chip(), TOOLCHAIN_HINT)
class TestIntegration(unittest.TestCase):
    def test_and_or_through_chip(self):
        out = run([sys.executable, "tools/tric.py",
                   "examples/and_or.tri", "-o", "build/it_andor", "--hex"],
                  ROOT)
        self.assertIn("it_andor.hex", out)
        obs = run([sys.executable,
                   chip_path("tools", "conform", "run_conform.py"),
                   "--hex", os.path.join(ROOT, "build", "it_andor.hex"),
                   os.path.join(ROOT, "build", "it_andor.hexdata")],
                  chip_path())
        d = json.loads(obs)
        self.assertEqual(d["halted"], [True, False])
        self.assertEqual(bytes.fromhex(d["uart"]), b"0001\n0111\n")

    def test_classify3_through_chip(self):
        run([sys.executable, "tools/tric.py", "examples/classify3.tri",
             "-o", "build/it_cls", "--hex"], ROOT)
        obs = run([sys.executable,
                   chip_path("tools", "conform", "run_conform.py"),
                   "--hex", os.path.join(ROOT, "build", "it_cls.hex"),
                   os.path.join(ROOT, "build", "it_cls.hexdata")],
                  chip_path())
        d = json.loads(obs)
        self.assertEqual(bytes.fromhex(d["uart"]), b"00000002\n")


if __name__ == "__main__":
    unittest.main()
