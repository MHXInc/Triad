#!/usr/bin/env python3
"""tric: Triad compiler driver. source.tri -> prog.asm (+ .hex/.data).

Usage: tric [--target mhx-t2] [--hart1] [--hex] [--fmt] [--check] [-o out] file.tri
  --hex    also assemble via chip mhxas and split hart images.
  --fmt    print canonical formatting and exit.
  --check  parse and resolve only; print ok/errors and exit.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from triad import chip  # noqa
from triad.codegen import Gen  # noqa
from triad.parser import parse  # noqa
from triad.utm import builtin_targets, load  # noqa


def main() -> None:
    args = sys.argv[1:]
    target = "mhx-t2"
    want_hex = False
    want_hart1 = False
    want_fmt = False
    want_check = False
    out = None
    src = None
    i = 0
    try:
        while i < len(args):
            a = args[i]
            if a == "--target":
                i += 1
                target = args[i]
            elif a == "--hex":
                want_hex = True
            elif a == "--fmt":
                want_fmt = True
            elif a == "--check":
                want_check = True
            elif a == "--hart1":
                want_hart1 = True
            elif a == "-o":
                i += 1
                out = args[i]
            elif a.startswith("-"):
                sys.exit(f"unknown flag {a}")
            else:
                src = a
            i += 1
    except IndexError:
        sys.exit(f"flag {a} needs a value\n" + __doc__)
    if src is None:
        print(__doc__)
        sys.exit(2)
    tpath = builtin_targets().get(target)
    if tpath is None:
        sys.exit(f"unknown target {target}")
    utm = load(tpath)
    prog = parse(open(src).read())
    if want_fmt:
        from triad.fmt import fmt
        print(fmt(prog), end="")
        return
    if want_check:
        # Full parse + resolve + codegen in memory; any ParseError or
        # CodegenError surfaces exactly as in a real build. Nothing is
        # written.
        from triad.codegen import Gen as _Gen
        _Gen(utm).program(prog, hart=1 if want_hart1 else 0)
        print(f"{src}: ok")
        return
    gen = Gen(utm)
    lines, data = gen.program(prog, hart=1 if want_hart1 else 0)
    if data:
        # Fold vector-literal DATA into the asm so mhxas emits one
        # self-contained .hex + .hexdata pair.
        lines.append("")
        contig = sorted(data)
        i = 0
        while i < len(contig):
            a0 = contig[i][0]
            j = i
            while j + 1 < len(contig) and contig[j + 1][0] == \
                    contig[j][0] + 8:
                j += 1
            lines.append(f"  DATA {a0:#x}")
            for _, v in contig[i:j + 1]:
                lines.append(f"  WORD {v:#x}")
            i = j + 1
    base = out or os.path.splitext(src)[0]
    if want_hart1:
        base += ".hart1"
    parent = os.path.dirname(base)
    if parent:
        os.makedirs(parent, exist_ok=True)
    asmp = base + ".asm"
    with open(asmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {asmp} ({len(lines)} lines, {len(data)} data words)")
    if data:
        with open(base + ".data", "w") as f:
            for a, v in data:
                f.write(f"{a:08x} {v:016x}\n")
        print(f"wrote {base}.data")
    if want_hex:
        from triad.chip import TOOLCHAIN_HINT
        try:
            sys.path.insert(0, chip.chip_path("tools", "sdk"))
            from mhxas import assemble
        except (ImportError, FileNotFoundError):
            sys.exit(f"tric: --hex needs the MHX-T2 toolchain. {TOOLCHAIN_HINT}")
        with open(asmp) as f:
            asm_src = f.read()
        aout, _, adata = assemble(asm_src, os.path.dirname(asmp) or ".")
        # Single positional image (mhxas gap-fills ORG holes with HALT):
        # hart0 boots at 0x0, hart1 at 0x1000, both read the same list.
        with open(base + ".hex", "w") as f:
            for pc, w, _ in aout:
                f.write(f"{w:08x}\n")
        print(f"wrote {base}.hex ({len(aout)} words)")
        if adata:
            with open(base + ".hexdata", "w") as f:
                for a, v in adata:
                    f.write(f"{a:08x} {v:016x}\n")
            print(f"wrote {base}.hexdata")


if __name__ == "__main__":
    main()
