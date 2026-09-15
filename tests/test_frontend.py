"""Frontend tests: lexer, parser, formatter roundtrip."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from triad import astnodes as A  # noqa
from triad.fmt import fmt  # noqa
from triad.lexer import lex  # noqa
from triad.parser import parse, ParseError  # noqa


class TestLex(unittest.TestCase):
    def test_kinds(self):
        ts = lex("trit t = +; // c\n triad[4] w = [+, -, 0];")
        kinds = [t.kind for t in ts]
        self.assertIn("KW", kinds)
        self.assertIn("STR", [t.kind for t in lex('asm("HALT");')])

    def test_ops(self):
        ts = [t.text for t in lex("a +~ b << 2 -> x")]
        self.assertEqual(ts[:5], ["a", "+~", "b", "<<", "2"])

    def test_columns(self):
        ts = lex("ab\n  cd ef\nxy")
        self.assertEqual([(t.text, t.line, t.col) for t in ts if t.kind != "EOF"],
                         [("ab", 1, 1), ("cd", 2, 3), ("ef", 2, 6), ("xy", 3, 1)])


class TestParse(unittest.TestCase):
    def test_decl(self):
        p = parse("triad w = [+, -, 0];")
        g = p.items[0]
        self.assertIsInstance(g, A.Global)
        self.assertEqual(g.init.elems, [1, -1, 0])

    def test_fn(self):
        p = parse("fn add(a: u32, b: u32) -> u32 { return a + b; }")
        f = p.items[0]
        self.assertEqual(f.name, "add")
        self.assertEqual(len(f.params), 2)

    def test_task_hart_irq_mpu(self):
        src = ("task s() { halt(); } hart(1) { s(); } "
               "irq(TIMER) { halt(); } mpu { region(0x0, 0xFFFFF000); }")
        p = parse(src)
        self.assertEqual([type(i).__name__ for i in p.items],
                         ["Fn", "Hart", "Irq", "Mpu"])

    def test_bad(self):
        with self.assertRaises(ParseError):
            parse("triad 123;")

    def test_error_span(self):
        try:
            parse("fn main() -> u32 {\n  u32 x = ;\n}\n")
            self.fail("expected ParseError")
        except ParseError as e:
            self.assertIn("line 2, col 11", str(e))

    def test_bitwise_precedence(self):
        p = parse("fn main() -> u32 { u32 x = a | b ^ c & d; return x; }")
        got = fmt(p)
        # C order: | lowest, & binds tightest; fmt parenthesizes explicitly.
        self.assertIn("(a | (b ^ (c & d)))", got)


class TestFmt(unittest.TestCase):
    def test_roundtrip(self):
        src = ("fn main() -> u32 {\n  u32 x = 1;\n  x = (x + 2);\n"
               "  return x;\n}\n")
        self.assertEqual(fmt(parse(src)), src)

    def test_roundtrip_repo_sources(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in ("examples/and_or.tri", "examples/classify3.tri",
                    "std/hal.tri", "std/ml.tri"):
            with open(os.path.join(root, rel)) as f:
                src = f.read()
            once = fmt(parse(src))
            self.assertEqual(fmt(parse(once)), once, rel)


class TestCheck(unittest.TestCase):
    def test_tric_check(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, os.path.join(root, "tools"))
        import tric
        argv = sys.argv
        try:
            sys.argv = ["tric", "--check",
                        os.path.join(root, "examples", "and_or.tri")]
            tric.main()
        finally:
            sys.argv = argv
            sys.path.pop()


class TestAllocErrors(unittest.TestCase):
    def test_trf_exhaustion_names_fn(self):
        import os
        from triad.codegen import CodegenError, Gen
        from triad.utm import builtin_targets, load
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        utm = load(builtin_targets()["mhx-t2"])
        body = "".join(f"  triad v{i} = [+, 0];\n" for i in range(60))
        with self.assertRaises(CodegenError) as c:
            Gen(utm).program(parse("fn big() -> u32 {\n" + body +
                                   "  return 0;\n}\nfn main() -> u32 { return 0; }\n"))
        self.assertIn("big", str(c.exception))


if __name__ == "__main__":
    unittest.main()
