"""Triad pretty-printer: AST -> canonical source (roundtrip)."""
from __future__ import annotations

from . import astnodes as A

TRIT = {1: "+", -1: "-", 0: "0"}


def typ(t: A.Type) -> str:
    return str(t)


def expr(e) -> str:
    if isinstance(e, A.Num):
        return str(e.value)
    if isinstance(e, A.TritLit):
        return TRIT[e.value]
    if isinstance(e, A.VecLit):
        return "[" + ", ".join(TRIT[v] for v in e.elems) + "]"
    if isinstance(e, A.Var):
        return e.name
    if isinstance(e, A.Index):
        return f"{e.name}[{expr(e.index)}]"
    if isinstance(e, A.Bin):
        return f"({expr(e.l)} {e.op} {expr(e.r)})"
    if isinstance(e, A.Un):
        return f"(-{expr(e.e)})"
    if isinstance(e, A.Call):
        return f"{e.name}({', '.join(expr(a) for a in e.args)})"
    raise AssertionError(f"bad expr {e!r}")


def block(ss: list, ind: int) -> list[str]:
    out = []
    for s in ss:
        out.extend(stmt(s, ind))
    return out


def stmt(s, ind: int) -> list[str]:
    p = "  " * ind
    if isinstance(s, (A.Decl, A.Global)):
        t = f"{p}{s.typ} {s.name}"
        if s.init is not None:
            t += f" = {expr(s.init)}"
        return [t + ";"]
    if isinstance(s, A.Assign):
        tgt = s.target if s.index is None else f"{s.target}[{expr(s.index)}]"
        return [f"{p}{tgt} = {expr(s.value)};"]
    if isinstance(s, A.If):
        out = [f"{p}if ({expr(s.cond)}) {{"]
        out += block(s.then, ind + 1)
        if s.els:
            out.append(p + "} else {")
            out += block(s.els, ind + 1)
        out.append(p + "}")
        return out
    if isinstance(s, A.While):
        return [f"{p}while ({expr(s.cond)}) {{"] + block(s.body, ind + 1) + \
            [p + "}"]
    if isinstance(s, A.Return):
        return [f"{p}return {expr(s.value)};" if s.value is not None
                else f"{p}return;"]
    if isinstance(s, A.ExprStmt):
        return [f"{p}{expr(s.expr)};"]
    if isinstance(s, A.Halt):
        return [f"{p}halt();"]
    if isinstance(s, A.Asm):
        return [f"{p}asm(\"{s.text}\");"]
    raise AssertionError(f"bad stmt {s!r}")


def item(it) -> list[str]:
    if isinstance(it, A.Fn):
        ps = ", ".join(f"{n}: {t}" for n, t in it.params)
        head = f"{it.kind} {it.name}({ps})" if it.kind != "fn" else \
            f"fn {it.name}({ps})"
        if it.kind == "fn" and it.ret is not None:
            head += f" -> {it.ret}"
        if it.kind in ("task",):
            head = f"task {it.name}()"
        return [head + " {"] + block(it.body, 1) + ["}"]
    if isinstance(it, A.Hart):
        return [f"hart({it.hart}) {{"] + block(it.body, 1) + ["}"]
    if isinstance(it, A.Irq):
        return [f"irq({it.src}) {{"] + block(it.body, 1) + ["}"]
    if isinstance(it, A.Mpu):
        out = ["mpu {"]
        for b, m in it.regions:
            out.append(f"  region({expr(b)}, {expr(m)});")
        return out + ["}"]
    return stmt(it, 0)


def fmt(prog: A.Program) -> str:
    out = []
    for it in prog.items:
        out.extend(item(it))
    return "\n".join(out) + "\n"
