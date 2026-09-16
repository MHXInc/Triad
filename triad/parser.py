"""Triad recursive-descent parser: tokens -> AST. Types checked in codegen."""
from __future__ import annotations

from . import astnodes as A
from .lexer import Tok


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, toks: list[Tok]):
        self.t = toks
        self.i = 0

    def peek(self) -> Tok:
        return self.t[self.i]

    def next(self) -> Tok:
        t = self.t[self.i]
        self.i += 1
        return t

    def err(self, msg: str) -> ParseError:
        t = self.peek()
        return ParseError(f"line {t.line}, col {t.col}: {msg}")

    def eat(self, kind: str, text: str | None = None) -> Tok:
        t = self.peek()
        if t.kind != kind or (text is not None and t.text != text):
            raise self.err(f"expected {text or kind}, got {t.text!r}")
        return self.next()

    def at(self, kind: str, text: str | None = None) -> bool:
        t = self.peek()
        return t.kind == kind and (text is None or t.text == text)

    # ---- program ----
    def program(self) -> A.Program:
        items = []
        while not self.at("EOF"):
            items.append(self.item())
        return A.Program(items)

    def item(self):
        if self.at("KW", "fn"):
            return self.fn("fn")
        if self.at("KW", "task"):
            self.next()
            name = self.eat("IDENT").text
            self.eat("PUNCT", "(")
            self.eat("PUNCT", ")")
            return A.Fn(name, [], None, self.block(), kind="task")
        if self.at("KW", "hart"):
            self.next()
            self.eat("PUNCT", "(")
            n = int(self.eat("NUM").text, 0)
            self.eat("PUNCT", ")")
            return A.Hart(n, self.block())
        if self.at("KW", "irq"):
            self.next()
            self.eat("PUNCT", "(")
            src = self.next().text
            self.eat("PUNCT", ")")
            return A.Irq(src, self.block())
        if self.at("KW", "mpu"):
            self.next()
            self.eat("PUNCT", "{")
            regions = []
            while not self.at("PUNCT", "}"):
                if self.at("KW", "region"):
                    self.next()
                else:
                    self.eat("IDENT")  # region
                self.eat("PUNCT", "(")
                b = self.expr()
                self.eat("PUNCT", ",")
                m = self.expr()
                self.eat("PUNCT", ")")
                self.eat("PUNCT", ";")
                regions.append((b, m))
            self.eat("PUNCT", "}")
            return A.Mpu(regions)
        return self.global_or_decl(top=True)

    def typ(self) -> A.Type:
        t = self.peek()
        if t.kind == "KW" and t.text in ("trit", "triad", "u32", "bit"):
            self.next()
            name = t.text
        elif t.kind == "IDENT" and t.text in ("trit", "triad", "u32", "bit"):
            name = self.next().text
        else:
            raise self.err(f"expected type, got {t.text!r}")
        n = None
        if self.at("PUNCT", "["):
            self.next()
            n = int(self.eat("NUM").text, 0)
            self.eat("PUNCT", "]")
        return A.Type(name, n)

    def is_type_ahead(self) -> bool:
        t = self.peek()
        if t.kind == "KW" and t.text in ("trit", "triad", "u32", "bit"):
            return True
        if t.kind != "IDENT" or t.text not in ("trit", "triad", "u32", "bit"):
            return False
        nxt = self.t[self.i + 1]
        if nxt.kind != "IDENT":
            return False
        # IDENT IDENT could be `x = ...`? no: need [ or IDENT after type name
        return True

    def global_or_decl(self, top=False):
        typ = self.typ()
        name = self.eat("IDENT").text
        init = None
        if self.at("OP1", "="):
            self.next()
            init = self.expr()
        self.eat("PUNCT", ";")
        if top:
            return A.Global(typ, name, init)
        return A.Decl(typ, name, init)

    def fn(self, kind: str) -> A.Fn:
        self.eat("KW", "fn")
        name = self.eat("IDENT").text
        self.eat("PUNCT", "(")
        params = []
        while not self.at("PUNCT", ")"):
            pn = self.eat("IDENT").text
            self.eat("PUNCT", ":")
            pt = self.typ()
            params.append((pn, pt))
            if self.at("PUNCT", ","):
                self.next()
        self.eat("PUNCT", ")")
        ret = None
        if self.at("OP2", "->"):
            self.next()
            ret = self.typ()
        return A.Fn(name, params, ret, self.block(), kind=kind)

    def block(self) -> list:
        self.eat("PUNCT", "{")
        out = []
        while not self.at("PUNCT", "}"):
            out.append(self.stmt())
        self.eat("PUNCT", "}")
        return out

    def stmt(self):
        if self.at("KW", "if"):
            return self.if_()
        if self.at("KW", "while"):
            self.next()
            self.eat("PUNCT", "(")
            c = self.expr()
            self.eat("PUNCT", ")")
            return A.While(c, self.block())
        if self.at("KW", "return"):
            self.next()
            v = None
            if not self.at("PUNCT", ";"):
                v = self.expr()
            self.eat("PUNCT", ";")
            return A.Return(v)
        if self.at("KW", "halt"):
            self.next()
            if self.at("PUNCT", "("):
                self.next()
                self.eat("PUNCT", ")")
            self.eat("PUNCT", ";")
            return A.Halt()
        if self.at("KW", "asm"):
            self.next()
            self.eat("PUNCT", "(")
            s = self.eat("STR").text
            self.eat("PUNCT", ")")
            self.eat("PUNCT", ";")
            return A.Asm(bytes(s[1:-1], "utf-8").decode("unicode_escape"))
        if self.is_type_ahead():
            return self.global_or_decl()
        # assign | index-assign | expr-stmt
        if self.at("IDENT"):
            name = self.next().text
            idx = None
            if self.at("PUNCT", "["):
                self.next()
                idx = self.expr()
                self.eat("PUNCT", "]")
            if self.at("OP1", "=") and not self.at("OP2"):
                self.next()
                v = self.expr()
                self.eat("PUNCT", ";")
                return A.Assign(name, idx, v)
            if self.at("PUNCT", "(") or self.at("PUNCT", "."):
                e = self.call_tail(name)
                self.eat("PUNCT", ";")
                return A.ExprStmt(e)
            raise self.err(f"unexpected {self.peek().text!r} after {name}")
        e = self.expr()
        self.eat("PUNCT", ";")
        return A.ExprStmt(e)

    def if_(self):
        self.eat("KW", "if")
        self.eat("PUNCT", "(")
        c = self.expr()
        self.eat("PUNCT", ")")
        then = self.block()
        els = []
        if self.at("KW", "else"):
            self.next()
            els = self.block()
        return A.If(c, then, els)

    def call_tail(self, name: str) -> A.Call:
        while self.at("PUNCT", "."):
            self.next()
            name += "." + self.eat("IDENT").text
        self.eat("PUNCT", "(")
        args = []
        while not self.at("PUNCT", ")"):
            args.append(self.expr())
            if self.at("PUNCT", ","):
                self.next()
        self.eat("PUNCT", ")")
        return A.Call(name, args)

    # ---- expressions (precedence) ----
    def expr(self):
        return self.cmp()

    def cmp(self):
        e = self.bitor()
        while self.at("OP2") and self.peek().text in ("==", "!=", "<=", ">=") \
                or self.at("OP1") and self.peek().text in "<>":
            op = self.next().text
            e = A.Bin(op, e, self.bitor())
        return e

    def bitor(self):
        e = self.bitxor()
        while self.at("OP1", "|"):
            self.next()
            e = A.Bin("|", e, self.bitxor())
        return e

    def bitxor(self):
        e = self.bitand()
        while self.at("OP1", "^"):
            self.next()
            e = A.Bin("^", e, self.bitand())
        return e

    def bitand(self):
        e = self.add()
        while self.at("OP1", "&"):
            self.next()
            e = A.Bin("&", e, self.add())
        return e

    def add(self):
        e = self.mul()
        while (self.at("OP1") and self.peek().text in "+-") or \
                self.at("OP2", "+~"):
            op = self.next().text
            e = A.Bin(op, e, self.mul())
        return e

    def mul(self):
        e = self.shift()
        while self.at("OP1", "*"):
            self.next()
            e = A.Bin("*", e, self.shift())
        return e

    def shift(self):
        e = self.unary()
        while self.at("OP2") and self.peek().text in ("<<", ">>"):
            op = self.next().text
            e = A.Bin(op, e, self.unary())
        return e

    def unary(self):
        if self.at("OP1", "-"):
            self.next()
            return A.Un("-", self.unary())
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while self.at("PUNCT", "["):
            self.next()
            idx = self.expr()
            self.eat("PUNCT", "]")
            if isinstance(e, A.Var):
                e = A.Index(e.name, idx)
            else:
                raise self.err("only array variables can be indexed")
        return e

    def primary(self):
        t = self.peek()
        if t.kind == "NUM":
            self.next()
            return A.Num(int(t.text, 0))
        if t.kind == "OP1" and t.text in "+-":
            self.next()
            return A.TritLit(1 if t.text == "+" else -1)
        if t.kind == "PUNCT" and t.text == "[":
            self.next()
            elems = []
            while not self.at("PUNCT", "]"):
                e = self.peek()
                if e.kind == "OP1" and e.text in "+-":
                    self.next()
                    elems.append(1 if e.text == "+" else -1)
                elif e.kind == "IDENT" and e.text == "0":
                    self.next()
                    elems.append(0)
                elif e.kind == "NUM" and e.text == "0":
                    self.next()
                    elems.append(0)
                else:
                    raise self.err("vector literals need +, - or 0")
                if self.at("PUNCT", ","):
                    self.next()
            self.eat("PUNCT", "]")
            return A.VecLit(elems)
        if t.kind == "IDENT":
            name = self.next().text
            if self.at("PUNCT", "(") or self.at("PUNCT", "."):
                return self.call_tail(name)
            return A.Var(name)
        if t.kind == "PUNCT" and t.text == "(":
            self.next()
            e = self.expr()
            self.eat("PUNCT", ")")
            return e
        raise self.err(f"unexpected {t.text!r} in expression")


def parse(src: str) -> A.Program:
    from .lexer import lex
    return Parser(lex(src)).program()
