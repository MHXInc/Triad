"""Triad lexer: source -> tokens."""
from __future__ import annotations

import re
from dataclasses import dataclass

KEYWORDS = {
    "trit", "triad", "u32", "bit", "fn", "return", "if", "else", "while",
    "task", "hart", "irq", "mpu", "region", "halt", "asm", "TIMER", "ECALL",
    "true", "false",
}

TOKENS = [
    ("COMMENT", r"//[^\n]*|/\*.*?\*/"),
    ("WS", r"\s+"),
    ("STR", r'"(?:[^"\\]|\\.)*"'),
    ("NUM", r"0[xX][0-9a-fA-F]+|\d+"),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("OP2", r"\+~|==|!=|<=|>=|->|<<|>>"),
    ("OP1", r"[+\-*/<>=!&|^~]"),
    ("PUNCT", r"[(){}\[\],;.:]"),
]

MASTER = re.compile("|".join(f"(?P<{n}>{p})" for n, p in TOKENS), re.DOTALL)


@dataclass
class Tok:
    kind: str
    text: str
    line: int
    col: int


def lex(src: str) -> list[Tok]:
    out: list[Tok] = []
    line = 1
    col = 1
    for m in MASTER.finditer(src):
        kind, text = m.lastgroup, m.group()
        assert kind is not None
        if kind in ("WS", "COMMENT"):
            line += text.count("\n")
            if "\n" in text:
                col = len(text) - text.rfind("\n")
            else:
                col += len(text)
            continue
        if kind == "IDENT" and text in KEYWORDS:
            kind = "KW"
        out.append(Tok(kind, text, line, col))
        if "\n" in text:
            line += text.count("\n")
            col = len(text) - text.rfind("\n")
        else:
            col += len(text)
    out.append(Tok("EOF", "", line, col))
    return out
