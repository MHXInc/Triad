"""TRIP protocol + UTM loader tests.

TestTrip needs the MHX-T2 reference sim and skips without the private
toolchain (see triad.chip); TestUTM is toolchain-free and always runs.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from triad.chip import TOOLCHAIN_HINT, chip_path, have_chip  # noqa
from triad.trip import SimTransport, TripError  # noqa
from triad.utm import UTMError, builtin_targets, load  # noqa

if have_chip():
    sys.path.insert(0, chip_path("tools", "python"))
    from mhx_t2.sim import SoC  # noqa

needs_chip = unittest.skipUnless(have_chip(), TOOLCHAIN_HINT)


@needs_chip
class TestTrip(unittest.TestCase):
    def setUp(self):
        self.t = SimTransport(SoC([0xF1000000]))

    def test_ping(self):
        self.assertEqual(self.t.transact("PING"), "PONG triad/0.1")

    def test_mem_roundtrip(self):
        self.assertEqual(self.t.transact("W 0x200 0x1234"), "OK")
        self.assertEqual(self.t.transact("R 0x200"), "V 00001234")

    def test_halt_step(self):
        self.assertEqual(self.t.transact("H"), "H 0")
        self.assertEqual(self.t.transact("S"), "OK")

    def test_uart(self):
        self.assertEqual(self.t.transact("U 4142"), "OK 2")

    def test_errors(self):
        for bad in ["", "BOGUS", "R", "W 0x1"]:
            with self.assertRaises(TripError):
                self.t.transact(bad)


class TestUTM(unittest.TestCase):
    def test_builtin(self):
        self.assertIn("mhx-t2", builtin_targets())

    def test_load(self):
        d = load(builtin_targets()["mhx-t2"])
        self.assertEqual(d["target"]["trits_per_word"], 32)
        self.assertEqual(d["mmio"]["UART_TXDATA"], "0x00")

    def test_rejects_bad_stride(self):
        import copy
        d = load(builtin_targets()["mhx-t2"])
        d2 = copy.deepcopy(d)
        d2["mmio"]["UART_TXDATA"] = "0x04"
        with self.assertRaises(UTMError):
            from triad.utm import validate
            validate(d2, "<test>")


if __name__ == "__main__":
    unittest.main()
