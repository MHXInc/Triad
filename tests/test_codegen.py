"""Codegen e2e: .tri -> asm -> hex -> chip sim -> expected UART.

The sim-backed tests skip gracefully without the private MHX-T2 toolchain
(see triad.chip); test_hart1 needs no toolchain and always runs.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from triad.chip import TOOLCHAIN_HINT, chip_path, have_chip  # noqa
from triad.codegen import Gen  # noqa
from triad.parser import parse  # noqa
from triad.utm import load  # noqa

if have_chip():
    sys.path.insert(0, chip_path("tools", "sdk"))
    sys.path.insert(0, chip_path("tools", "python"))
    from mhxas import assemble  # noqa
    from mhx_t2.sim import SoC  # noqa

UTM = load(os.path.join(ROOT, "targets", "mhx-t2.utm.toml"))

needs_chip = unittest.skipUnless(have_chip(), TOOLCHAIN_HINT)


def build(name: str, hart: int = 0):
    with open(os.path.join(ROOT, "examples", name)) as f:
        src = f.read()
    gen = Gen(UTM)
    lines, data = gen.program(parse(src), hart=hart)
    asm_src = "\n".join(lines) + "\n"
    out, _, adata = assemble(asm_src, ".")
    imem = [0xF1000000] * ((max(pc for pc, _, _ in out) // 4) + 1)
    for pc, w, _ in out:
        imem[pc // 4] = w
    mem = {a: v for a, v in data}
    mem.update({a: v for a, v in adata})
    return imem, mem


class TestE2E(unittest.TestCase):
    @needs_chip
    def test_and_or(self):
        imem, data = build("and_or.tri")
        soc = SoC(imem)
        soc.priv[0].update(data)
        for _ in range(20000):
            if soc.cores[0].halted:
                break
            soc.cores[0].step()
            soc.periph.tick()
        self.assertTrue(soc.cores[0].halted)
        self.assertEqual(bytes(soc.periph.uart_out), b"0001\n0111\n")

    @needs_chip
    def test_classify3(self):
        imem, data = build("classify3.tri")
        soc = SoC(imem)
        soc.priv[0].update(data)
        for _ in range(20000):
            if soc.cores[0].halted:
                break
            soc.cores[0].step()
            soc.periph.tick()
        self.assertTrue(soc.cores[0].halted)
        self.assertEqual(bytes(soc.periph.uart_out), b"00000002\n")

    def test_hart1(self):
        src = "fn main() -> u32 { halt(); return 0; }\n" \
              "hart(1) { uart.newline(); halt(); }\n"
        gen = Gen(UTM)
        lines, _ = gen.program(parse(src), hart=1)
        asm_src = "\n".join(lines) + "\n"
        self.assertIn("ORG 0x1000", asm_src)

    @needs_chip
    def test_timer_irq(self):
        src = ("fn main() -> u32 {\n"
               "  timer.compare(50);\n"
               "  timer.sleep_us(100000);\n"
               "  halt();\n"
               "  return 0;\n"
               "}\n"
               "irq(TIMER) {\n"
               "  u32 c = 84;\n"
               "  uart.putc(c);\n"
               "  halt();\n"
               "}\n")
        gen = Gen(UTM)
        lines, data = gen.program(parse(src), hart=0)
        asm_src = "\n".join(lines) + "\n"
        out, _, adata = assemble(asm_src, ".")
        imem = [0xF1000000] * ((max(pc for pc, _, _ in out) // 4) + 1)
        for pc, w, _ in out:
            imem[pc // 4] = w
        mem = {a: v for a, v in data}
        mem.update({a: v for a, v in adata})
        soc = SoC(imem)
        soc.priv[0].update(mem)
        for _ in range(20000):
            if soc.cores[0].halted:
                break
            soc.cores[0].step()
            soc.periph.tick()
        self.assertTrue(soc.cores[0].halted)
        self.assertEqual(bytes(soc.periph.uart_out), b"T")

    @needs_chip
    def test_dma_copy(self):
        src = ("triad[2] src;\n"
               "triad[2] dst;\n"
               "fn main() -> u32 {\n"
               "  src[0] = [+, +, 0, 0, 0, 0, 0, 0];\n"
               "  dma.copy(4112, 4096, 1);\n"
               "  dma.start();\n"
               "  dma.wait();\n"
               "  uart.putc(dst[0]);\n"
               "  halt();\n"
               "  return 0;\n"
               "}\n")
        gen = Gen(UTM)
        lines, data = gen.program(parse(src), hart=0)
        asm_src = "\n".join(lines) + "\n"
        out, _, adata = assemble(asm_src, ".")
        imem = [0xF1000000] * ((max(pc for pc, _, _ in out) // 4) + 1)
        for pc, w, _ in out:
            imem[pc // 4] = w
        mem = {a: v for a, v in data}
        mem.update({a: v for a, v in adata})
        soc = SoC(imem)
        soc.priv[0].update(mem)
        for _ in range(20000):
            if soc.cores[0].halted:
                break
            soc.cores[0].step()
            soc.periph.tick()
        self.assertTrue(soc.cores[0].halted)
        self.assertEqual(soc.priv[0].get(0x1010), soc.priv[0].get(0x1000))
        self.assertEqual(bytes(soc.periph.uart_out), b"Z")


if __name__ == "__main__":
    unittest.main()
