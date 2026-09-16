"""tric backend: Triad AST -> MHX assembly (via UTM target description).

Register model (MHX-T2): TRF t1+ vars (t0=zero, t60-t63 reserved scratch),
GPR x5+ vars (x0=0, x1=ra, x2-x4 reserved: x4=MMIO base; x30/x31 handler ABI).
Params: u32 x10+, triad t10+. Returns: x10/t10. Flat calls only.
Expression temps: bump stacks reset per statement (no aliasing bugs).
"""
from __future__ import annotations

from . import astnodes as A


class CodegenError(Exception):
    pass


class FnCtx:
    def __init__(self, gen, fn):
        self.gen = gen
        self.fn = fn
        self.vars: dict[str, tuple[str, int]] = {}
        self.next_trf = 1
        self.next_gpr = 5
        self.tmp_trf_mark = 0
        self.tmp_gpr_mark = 0
        self.tmp_trf_pool = [63, 62, 61, 60]
        self.tmp_gpr_pool = [29, 28, 27, 26]
        self.labels = 0

    def lab(self, base: str) -> str:
        self.labels += 1
        return f".L{self.fn.name}_{base}_{self.labels}"

    def mark(self):
        return (self.tmp_trf_mark, self.tmp_gpr_mark)

    def reset(self, m) -> None:
        self.tmp_trf_mark, self.tmp_gpr_mark = m

    def ttrf(self) -> int:
        if self.tmp_trf_mark >= len(self.tmp_trf_pool):
            raise CodegenError(
                f"out of TRF temps in {self.fn.name}: simplify this expression")
        r = self.tmp_trf_pool[self.tmp_trf_mark]
        self.tmp_trf_mark += 1
        return r

    def tgpr(self) -> int:
        if self.tmp_gpr_mark >= len(self.tmp_gpr_pool):
            raise CodegenError(
                f"out of GPR temps in {self.fn.name}: simplify this expression")
        r = self.tmp_gpr_pool[self.tmp_gpr_mark]
        self.tmp_gpr_mark += 1
        return r

    def alloc_trf(self) -> int:
        # t10..t17 is the param/return window: always reserved so calls
        # can never clobber locals.
        while True:
            r = self.next_trf
            self.next_trf += 1
            if r > 59:
                raise CodegenError(
                    f"out of TRF registers in {self.fn.name}: "
                    f"too many triad locals")
            if 10 <= r <= 17:
                continue
            return r

    def alloc_gpr(self) -> int:
        while True:
            r = self.next_gpr
            self.next_gpr += 1
            if r > 28:
                raise CodegenError(
                    f"out of GPR registers in {self.fn.name}: "
                    f"too many u32 locals")
            if 10 <= r <= 17:
                continue
            return r


class Gen:
    def __init__(self, utm: dict):
        self.utm = utm
        self.mm = {k: int(v, 0) for k, v in utm["mmio"].items()}
        self.mmbase = int(utm["regions"]["mmio"], 0)
        self.out: list[str] = []
        self.data: list[tuple[int, int]] = []
        self.data_next = 0x2000
        self.fns: dict[str, A.Fn] = {}
        self.in_call = False
        q = utm.get("quirks", {})
        self.mie_timer_bit = int(q.get("mie_timer_bit", 1))
        self.mstatus_mie_bit = int(q.get("mstatus_mie_bit", 0))
        self.trap_vector = int(q.get("mtvec_default", "0x100"), 0)
        rpc = utm.get("regions", {})
        if "reset_pc" in utm.get("target", {}):
            rps = [int(v, 0) for v in utm["target"]["reset_pc"]]
            if rps[0] != 0x0 or (len(rps) > 1 and rps[1] != 0x1000):
                raise CodegenError("backend assumes reset PC 0x0/0x1000")
        if self.trap_vector != 0x100:
            raise CodegenError("backend assumes trap vector 0x100")
        _ = rpc

    def mmio_base(self) -> None:
        self.const_u32(4, self.mmbase)

    # ---------- emit helpers ----------
    def e(self, line: str) -> None:
        self.out.append(line)

    def const_u32(self, xd: int, v: int) -> None:
        v &= 0xFFFFFFFF
        bs = [(v >> s) & 0xFF for s in (24, 16, 8, 0)]
        while len(bs) > 1 and bs[0] == 0:
            bs.pop(0)
        self.e(f"  ADDI x{xd}, x0, {bs[0]}")
        for b in bs[1:]:
            self.e(f"  SLLI x{xd}, x{xd}, 8")
            if b:
                self.e(f"  ADDI x{xd}, x{xd}, {b}")

    def mmio_load(self, td: int, off: str) -> None:
        o = self.mm[off]
        assert o % 8 == 0, f"MMIO {off} not 8-aligned"
        self.e(f"  TLW t{td}, {o // 8}(x4)")

    def mmio_store(self, td: int, off: str) -> None:
        o = self.mm[off]
        assert o % 8 == 0, f"MMIO {off} not 8-aligned"
        self.e(f"  TSW t{td}, {o // 8}(x4)")

    # ---------- program ----------
    def program(self, prog: A.Program, hart: int = 0) -> tuple[list[str], list]:
        fns = [i for i in prog.items if isinstance(i, A.Fn)]
        harts = [i for i in prog.items if isinstance(i, A.Hart)]
        irqs = [i for i in prog.items if isinstance(i, A.Irq)]
        mpus = [i for i in prog.items if isinstance(i, A.Mpu)]
        globarr = [i for i in prog.items if isinstance(i, A.Global)]
        for fn in fns:
            self.fns[fn.name] = fn
        if not any(f.name == "main" for f in fns):
            raise CodegenError("missing fn main()")
        self.arr_base: dict[str, int] = {}
        ab = 0x1000
        for g in globarr:
            if g.typ.name != "triad" or g.typ.array is None:
                raise CodegenError(
                    f"v1 globals must be triad[N] arrays (got {g.name})")
            self.arr_base[g.name] = ab
            ab += g.typ.array * 8
        if hart == 0:
            self.e("  ORG 0")
            self.e("  JAL x1, main_boot")
            for fn in fns:
                if fn.name != "main":
                    self.function(fn)
            self.e("main_boot:")
            self.mmio_base()
            if mpus:
                if len(mpus) > 1:
                    raise CodegenError("only one mpu{} block in v1")
                if len(mpus[0].regions) > 4:
                    raise CodegenError(
                        f"mpu needs {len(mpus[0].regions)} regions, "
                        f"only 4 slots in v1")
                for i, (b, m) in enumerate(mpus[0].regions[:4]):
                    self.const_u32(5, self.const_of(b, "mpu base"))
                    self.e(f"  CSRRW x0, {0x580 + i:#x}, x5")
                    self.const_u32(5, self.const_of(m, "mpu mask") | 1)
                    self.e(f"  CSRRW x0, {0x584 + i:#x}, x5")
            if irqs:
                self.const_u32(5, self.trap_vector)
                self.e("  CSRRW x0, 0x305, x5")
                self.const_u32(5, 1 << self.mie_timer_bit)
                self.e("  CSRRW x0, 0x304, x5")
                self.const_u32(5, 1 << self.mstatus_mie_bit)
                self.e("  CSRRW x0, 0x300, x5")
            self.e("  JAL x1, main")
            self.e("  HALT")
            self.function(next(f for f in fns if f.name == "main"))
            self.e("  HALT")
            if irqs:
                self.handler(irqs)
        else:
            hb = [h for h in harts if h.hart == hart]
            if not hb:
                raise CodegenError(f"no hart({hart}) block")
            if irqs or mpus:
                raise CodegenError("irq/mpu blocks need hart 0 in v1")
            self.e("  ORG 0x1000")
            self.e(f"  JAL x1, hart{hart}_main")
            for fn in fns:
                if fn.name != "main" and fn.name in self._reachable(hb[0].body):
                    self.function(fn)
            self.e(f"hart{hart}_main:")
            self.mmio_base()
            ctx = FnCtx(self, A.Fn(f"hart{hart}_main", [], None, []))
            self.stmts(ctx, hb[0].body)
            self.e("  HALT")
            if self.data:
                raise CodegenError(
                    "hart1 vector literals need host-loaded DATA "
                    "(v1: hoist constants to registers)")
        return self.out, self.data

    def const_of(self, e, what: str) -> int:
        if isinstance(e, A.Num):
            return e.value
        raise CodegenError(f"{what} must be a constant number")

    def _called_in_expr(self, e, out: set) -> None:
        if isinstance(e, A.Call):
            if "." not in e.name and e.name in self.fns:
                out.add(e.name)
            for a in e.args:
                self._called_in_expr(a, out)
        elif isinstance(e, A.Bin):
            self._called_in_expr(e.l, out)
            self._called_in_expr(e.r, out)
        elif isinstance(e, A.Un):
            self._called_in_expr(e.e, out)
        elif isinstance(e, A.Index):
            self._called_in_expr(e.index, out)

    def _called_in_stmts(self, ss: list, out: set) -> None:
        for s in ss:
            if isinstance(s, A.Decl):
                if s.init is not None:
                    self._called_in_expr(s.init, out)
            elif isinstance(s, A.Assign):
                if s.index is not None:
                    self._called_in_expr(s.index, out)
                if s.value is not None:
                    self._called_in_expr(s.value, out)
            elif isinstance(s, A.If):
                self._called_in_expr(s.cond, out)
                self._called_in_stmts(s.then, out)
                self._called_in_stmts(s.els, out)
            elif isinstance(s, A.While):
                self._called_in_expr(s.cond, out)
                self._called_in_stmts(s.body, out)
            elif isinstance(s, A.Return):
                if s.value is not None:
                    self._called_in_expr(s.value, out)
            elif isinstance(s, A.ExprStmt):
                self._called_in_expr(s.expr, out)

    def _reachable(self, body: list) -> set:
        """User-function names reachable from a statement list (transitive)."""
        found: set[str] = set()
        self._called_in_stmts(body, found)
        done: set[str] = set()
        while found - done:
            name = sorted(found - done)[0]
            done.add(name)
            fn = self.fns.get(name)
            if fn is not None:
                self._called_in_stmts(fn.body, found)
        return done

    def handler(self, irqs) -> None:
        for i in irqs:
            if i.src not in ("TIMER", "ECALL"):
                raise CodegenError(f"unknown irq source {i.src}")
        self.e("  ORG 0x100")
        self.e("handler:")
        bodies = {i.src: i.body for i in irqs}
        self.e("  CSRRS x30, 0x342, x0")
        self.e("  ADDI x31, x0, 7")
        if "TIMER" in bodies:
            self.e("  BEQ x30, x31, h_timer")
        if "ECALL" in bodies:
            self.e("  ADDI x31, x0, 11")
            self.e("  BEQ x30, x31, h_ecall")
        self.e("  HALT")
        ctx = FnCtx(self, A.Fn("handler", [], None, []))
        if "TIMER" in bodies:
            self.e("h_timer:")
            self.stmts(ctx, bodies["TIMER"])
            self.e("  MRET")
        if "ECALL" in bodies:
            self.e("h_ecall:")
            self.e("  CSRRS x30, 0x341, x0")
            self.e("  ADDI x30, x30, 4")
            self.e("  CSRRW x0, 0x341, x30")
            self.stmts(ctx, bodies["ECALL"])
            self.e("  MRET")

    # ---------- functions ----------
    def function(self, fn: A.Fn) -> None:
        ctx = FnCtx(self, fn)
        self.e(f"{fn.name}:")
        ai = ti = 0
        for pn, pt in fn.params:
            if pt.name in ("u32", "bit"):
                if ai >= 8:
                    raise CodegenError("too many u32 params (max 8)")
                ctx.vars[pn] = ("gpr", 10 + ai)
                ai += 1
            elif pt.name in ("triad", "trit"):
                if ti >= 8:
                    raise CodegenError("too many triad params (max 8)")
                ctx.vars[pn] = ("trf", 10 + ti)
                ti += 1
            else:
                raise CodegenError(f"bad param type {pt}")
        ctx.next_gpr = max(ctx.next_gpr, 10 + ai)
        ctx.next_trf = max(ctx.next_trf, 10 + ti)
        self.in_call = False
        self.stmts(ctx, fn.body)
        if not fn.body or not isinstance(fn.body[-1], (A.Return, A.Halt)):
            self.e("  JALR x0, x1, 0")

    # ---------- statements ----------
    def stmts(self, ctx: FnCtx, ss: list) -> None:
        for s in ss:
            m = ctx.mark()
            self.stmt(ctx, s)
            ctx.reset(m)

    def stmt(self, ctx: FnCtx, s) -> None:
        if isinstance(s, A.Decl):
            self.decl(ctx, s)
        elif isinstance(s, A.Assign):
            self.assign(ctx, s)
        elif isinstance(s, A.If):
            self.if_(ctx, s)
        elif isinstance(s, A.While):
            self.while_(ctx, s)
        elif isinstance(s, A.Return):
            self.ret(ctx, s)
        elif isinstance(s, A.ExprStmt):
            self.expr(ctx, s.expr, want=None)
        elif isinstance(s, A.Halt):
            self.e("  HALT")
        elif isinstance(s, A.Asm):
            for ln in s.text.splitlines():
                self.e(f"  {ln.strip()}" if ln.strip() else "")
        else:
            raise CodegenError(f"bad stmt {s!r}")

    def decl(self, ctx: FnCtx, s: A.Decl) -> None:
        if s.typ.name in ("u32", "bit"):
            r = ctx.alloc_gpr()
            ctx.vars[s.name] = ("gpr", r)
            if s.init is not None:
                v = self.expr(ctx, s.init, want="gpr")
                if v != r:
                    self.e(f"  ADD x{r}, x{v}, x0")
        elif s.typ.name == "trit":
            r = ctx.alloc_trf()
            ctx.vars[s.name] = ("trf1", r)
            if s.init is not None:
                self.e(f"  TLOCI t{r}, {self.trit_imm(s.init)}")
        elif s.typ.name == "triad" and s.typ.array is None:
            r = ctx.alloc_trf()
            ctx.vars[s.name] = ("trf", r)
            if s.init is not None:
                self.triad_init(ctx, r, s.init)
        else:
            raise CodegenError(f"bad decl {s.name}: {s.typ}")

    def triad_init(self, ctx: FnCtx, r: int, e) -> None:
        if isinstance(e, A.VecLit):
            if len(e.elems) > 32:
                raise CodegenError("vector literal > 32 trits (v1)")
            word = 0
            for i, v in enumerate(e.elems):
                word |= {1: 0b10, -1: 0b00, 0: 0b01}[v] << (2 * i)
            for i in range(len(e.elems), 32):
                word |= 0b01 << (2 * i)
            addr = self.data_next
            self.data_next += 8
            self.data.append((addr, word))
            gr = ctx.tgpr()
            self.const_u32(gr, addr)
            self.e(f"  TLW t{r}, 0(x{gr})")
        elif isinstance(e, A.Var):
            k, rr = self.var(ctx, e.name)
            if k != "trf":
                raise CodegenError("triad init needs triad value")
            self.e(f"  TMOV t{r}, t{rr}")
        else:
            v = self.expr(ctx, e, want="trf")
            self.e(f"  TMOV t{r}, t{v}")

    # ---------- assignment ----------
    def assign(self, ctx: FnCtx, s: A.Assign) -> None:
        if s.index is not None:
            base = self.arr_addr(ctx, s.target)
            idx = self.expr(ctx, s.index, want="gpr")
            ii = ctx.tgpr()
            self.e(f"  SLLI x{ii}, x{idx}, 3")
            self.e(f"  ADD x{ii}, x{base}, x{ii}")
            v = self.expr(ctx, s.value, want="trf")
            self.e(f"  TSW t{v}, 0(x{ii})")
            return
        k, r = self.var(ctx, s.target)
        if k == "gpr":
            v = self.expr(ctx, s.value, want="gpr")
            if v != r:
                self.e(f"  ADD x{r}, x{v}, x0")
        elif k in ("trf", "trf1"):
            v = self.expr(ctx, s.value, want="trf")
            if v != r:
                self.e(f"  TMOV t{r}, t{v}")
        else:
            raise CodegenError(f"cannot assign to {s.target}")

    def var(self, ctx: FnCtx, name: str):
        if name not in ctx.vars:
            raise CodegenError(f"undeclared variable {name}")
        return ctx.vars[name]

    def arr_addr(self, ctx: FnCtx, name: str) -> int:
        if name not in self.arr_base:
            raise CodegenError(f"undeclared array {name}")
        r = ctx.tgpr()
        self.const_u32(r, self.arr_base[name])
        return r

    # ---------- conditions / loops ----------
    def cond_jump(self, ctx: FnCtx, cond, lab_true: str) -> None:
        if isinstance(cond, A.Bin) and cond.op in ("==", "!=", "<", ">",
                                                   "<=", ">="):
            a = self.expr(ctx, cond.l, want="gpr")
            b = self.expr(ctx, cond.r, want="gpr")
            op = cond.op
            if op == "==":
                self.e(f"  BEQ x{a}, x{b}, {lab_true}")
            elif op == "!=":
                self.e(f"  BNE x{a}, x{b}, {lab_true}")
            elif op == "<":
                self.e(f"  BLT x{a}, x{b}, {lab_true}")
            elif op == ">":
                self.e(f"  BLT x{b}, x{a}, {lab_true}")
            elif op == "<=":
                t = ctx.tgpr()
                self.e(f"  SLT x{t}, x{b}, x{a}")
                self.e(f"  BEQ x{t}, x0, {lab_true}")
            elif op == ">=":
                t = ctx.tgpr()
                self.e(f"  SLT x{t}, x{a}, x{b}")
                self.e(f"  BEQ x{t}, x0, {lab_true}")
            return
        v = self.expr(ctx, cond, want="gpr")
        self.e(f"  BNE x{v}, x0, {lab_true}")

    def cond_jump_neg(self, ctx: FnCtx, cond, lab_false: str) -> None:
        if isinstance(cond, A.Bin) and cond.op in ("==", "!=", "<", ">",
                                                   "<=", ">="):
            neg = {"==": "!=", "!=": "==", "<": ">=", ">": "<=",
                   "<=": ">", ">=": "<"}[cond.op]
            self.cond_jump(ctx, A.Bin(neg, cond.l, cond.r), lab_false)
            return
        v = self.expr(ctx, cond, want="gpr")
        self.e(f"  BEQ x{v}, x0, {lab_false}")

    def if_(self, ctx: FnCtx, s: A.If) -> None:
        le = ctx.lab("endif")
        if s.els:
            lf = ctx.lab("else")
            self.cond_jump_neg(ctx, s.cond, lf)
            self.stmts(ctx, s.then)
            self.e(f"  BEQ x0, x0, {le}")
            self.e(f"{lf}:")
            self.stmts(ctx, s.els)
            self.e(f"{le}:")
        else:
            self.cond_jump_neg(ctx, s.cond, le)
            self.stmts(ctx, s.then)
            self.e(f"{le}:")

    def while_(self, ctx: FnCtx, s: A.While) -> None:
        lt, le = ctx.lab("loop"), ctx.lab("end")
        self.e(f"{lt}:")
        self.cond_jump_neg(ctx, s.cond, le)
        self.stmts(ctx, s.body)
        self.e(f"  BEQ x0, x0, {lt}")
        self.e(f"{le}:")

    def ret(self, ctx: FnCtx, s: A.Return) -> None:
        if s.value is None:
            self.e("  JALR x0, x1, 0")
            return
        rt = ctx.fn.ret
        if rt is None:
            raise CodegenError("return with value in void function")
        if rt.name in ("u32", "bit"):
            v = self.expr(ctx, s.value, want="gpr")
            if v != 10:
                self.e(f"  ADD x10, x{v}, x0")
        else:
            v = self.expr(ctx, s.value, want="trf")
            if v != 10:
                self.e(f"  TMOV t10, t{v}")
        self.e("  JALR x0, x1, 0")

    # ---------- expressions -> reg ----------
    def expr(self, ctx: FnCtx, e, want: str | None = None):
        k, r = self.ex(ctx, e)
        if want is None:
            return (k, r)
        if want == "gpr" and k == "gpr":
            return r
        if want == "trf" and k in ("trf", "trf1"):
            return r
        if want == "gpr" and k == "trf":
            t = ctx.tgpr()
            self.e(f"  TM2G x{t}, t{r}")
            return t
        if want == "trf" and k == "gpr":
            t = ctx.ttrf()
            self.e(f"  TG2T t{t}, x{r}")
            return t
        raise CodegenError(f"cannot coerce {k} to {want}")

    def ex(self, ctx: FnCtx, e):
        if isinstance(e, A.Num):
            r = ctx.tgpr()
            if -(1 << 11) <= e.value < (1 << 11):
                self.e(f"  ADDI x{r}, x0, {e.value}")
            else:
                self.const_u32(r, e.value)
            return ("gpr", r)
        if isinstance(e, A.TritLit):
            r = ctx.ttrf()
            enc = {1: "+1", -1: "-1", 0: "0"}[e.value]
            self.e(f"  TLOCI t{r}, {enc}")
            return ("trf", r)
        if isinstance(e, A.VecLit):
            r = ctx.alloc_trf()
            self.triad_init(ctx, r, e)
            return ("trf", r)
        if isinstance(e, A.Var):
            k, r = self.var(ctx, e.name)
            return ("trf", r) if k == "trf1" else (k, r)
        if isinstance(e, A.Index):
            base = self.arr_addr(ctx, e.name)
            idx = self.expr(ctx, e.index, want="gpr")
            ii = ctx.tgpr()
            self.e(f"  SLLI x{ii}, x{idx}, 3")
            self.e(f"  ADD x{ii}, x{base}, x{ii}")
            r = ctx.alloc_trf()
            self.e(f"  TLW t{r}, 0(x{ii})")
            return ("trf", r)
        if isinstance(e, A.Un):
            assert e.op == "-", "only unary -"
            v = self.expr(ctx, e.e, want="gpr")
            r = ctx.tgpr()
            self.e(f"  SUB x{r}, x0, x{v}")
            return ("gpr", r)
        if isinstance(e, A.Bin):
            return self.bin(ctx, e)
        if isinstance(e, A.Call):
            return self.call(ctx, e)
        raise CodegenError(f"bad expr {e!r}")

    def static_type(self, ctx: FnCtx, e) -> str:
        """Best-effort domain of an expression: 'trf' or 'gpr'."""
        if isinstance(e, A.Var):
            k, _ = self.var(ctx, e.name)
            return "trf" if k in ("trf", "trf1") else "gpr"
        if isinstance(e, A.Num):
            return "gpr"
        if isinstance(e, (A.TritLit, A.VecLit)):
            return "trf"
        if isinstance(e, A.Index):
            return "trf"
        if isinstance(e, A.Call):
            if e.name in ("dot", "red_sum", "red_nnz", "red_pos",
                           "red_neg", "as_u32", "timer.now", "timer.compare",
                           "gpio.get", "dma.stat", "sys.out", "yield"):
                return "gpr"
            if e.name in self.fns and self.fns[e.name].ret is not None:
                return "trf" if self.fns[e.name].ret.name in (
                    "triad", "trit") else "gpr"
            return "trf"
        if isinstance(e, A.Bin):
            if e.op in ("+", "+~", "-", "*") and \
                    self.static_type(ctx, e.l) == "trf":
                return "trf"
            if e.op in ("<<", ">>"):
                return self.static_type(ctx, e.l)
            return "gpr"
        return "gpr"

    def trit_imm(self, e) -> str:
        if isinstance(e, A.TritLit):
            return {1: "+1", -1: "-1", 0: "0"}[e.value]
        if isinstance(e, A.Num) and e.value == 0:
            return "0"
        if isinstance(e, A.Un) and e.op == "-" and isinstance(e.e, A.Num) \
                and e.e.value == 1:
            return "-1"
        raise CodegenError("need trit literal (+, -, 0)")

    def bin(self, ctx: FnCtx, e: A.Bin):
        op = e.op
        if op in ("+", "+~", "-", "*") and \
                self.static_type(ctx, e.l) == "gpr" and \
                self.static_type(ctx, e.r) == "gpr":
            if op == "*":
                raise CodegenError("u32 has no multiply (ISA has none); "
                                   "use dot() on triads")
            if op == "+~":
                raise CodegenError("+~ is triad-only; u32 + saturates? no: "
                                   "it wraps, use plain +")
            return self._arith(ctx, e, "ADD" if op == "+" else "SUB",
                               "ADDI" if op == "+" else "SUBI")
        if op in ("+", "+~", "-", "*"):
            a = self.expr(ctx, e.l, want="trf")
            try:
                imm = self.trit_imm(e.r)
                m = {"+": "TADD", "+~": "TSADD", "-": "TSUB",
                     "*": "TMUL"}[op]
                r = ctx.alloc_trf()
                self.e(f"  {m} t{r}, t{a}, {imm}")
                return ("trf", r)
            except CodegenError:
                pass
            b = self.expr(ctx, e.r, want="trf")
            m = {"+": "TADD", "+~": "TSADD", "-": "TSSUB",
                 "*": "TMUL"}[op]
            r = ctx.alloc_trf()
            self.e(f"  {m} t{r}, t{a}, t{b}")
            return ("trf", r)
        if op in ("<<", ">>"):
            if self.static_type(ctx, e.l) == "trf":
                a = self.expr(ctx, e.l, want="trf")
                b = self.expr(ctx, e.r, want="gpr")
                r = ctx.alloc_trf()
                self.e(f"  {'TSHL' if op == '<<' else 'TSHR'} t{r}, t{a}, x{b}")
                return ("trf", r)
            a = self.expr(ctx, e.l, want="gpr")
            b = self.expr(ctx, e.r, want="gpr")
            r = ctx.alloc_gpr()
            self.e(f"  {'SLL' if op == '<<' else 'SRL'} x{r}, x{a}, x{b}")
            return ("gpr", r)
        if op == "+":
            return self._arith(ctx, e, "ADD", "ADDI")
        if op == "-":
            return self._arith(ctx, e, "SUB", "SUBI")
        if op in ("&", "|", "^"):
            m = {"&": "AND", "|": "OR", "^": "XOR"}[op]
            a = self.expr(ctx, e.l, want="gpr")
            b = self.expr(ctx, e.r, want="gpr")
            r = ctx.alloc_gpr()
            self.e(f"  {m} x{r}, x{a}, x{b}")
            return ("gpr", r)
        if op in ("==", "!=", "<", ">", "<=", ">="):
            a = self.expr(ctx, e.l, want="gpr")
            b = self.expr(ctx, e.r, want="gpr")
            r = ctx.tgpr()
            if op == "<":
                self.e(f"  SLT x{r}, x{a}, x{b}")
            elif op == ">":
                self.e(f"  SLT x{r}, x{b}, x{a}")
            elif op == "==":
                # (d<1) XOR (d<0): 1 iff d==0
                t = ctx.tgpr()
                self.e(f"  SUB x{t}, x{a}, x{b}")
                self.e(f"  SLTI x{r}, x{t}, 1")
                self.e(f"  SLTI x{t}, x{t}, 0")
                self.e(f"  XOR x{r}, x{r}, x{t}")
            elif op == "!=":
                t = ctx.tgpr()
                self.e(f"  SUB x{t}, x{a}, x{b}")
                self.e(f"  SLTI x{r}, x{t}, 1")
                self.e(f"  SLTI x{t}, x{t}, 0")
                self.e(f"  XOR x{r}, x{r}, x{t}")
                self.e(f"  XORI x{r}, x{r}, 1")
            elif op == "<=":
                self.e(f"  SLT x{r}, x{b}, x{a}")
                self.e(f"  XORI x{r}, x{r}, 1")
            elif op == ">=":
                self.e(f"  SLT x{r}, x{a}, x{b}")
                self.e(f"  XORI x{r}, x{r}, 1")
            return ("gpr", r)
        raise CodegenError(f"bad binary op {op}")

    def _arith(self, ctx, e, rm, im):
        a = self.expr(ctx, e.l, want="gpr")
        if isinstance(e.r, A.Num) and -(1 << 11) <= e.r.value < (1 << 11):
            r = ctx.alloc_gpr()
            self.e(f"  {im} x{r}, x{a}, {e.r.value}")
            return ("gpr", r)
        b = self.expr(ctx, e.r, want="gpr")
        r = ctx.alloc_gpr()
        self.e(f"  {rm} x{r}, x{a}, x{b}")
        return ("gpr", r)

    # ---------- calls ----------
    def call(self, ctx: FnCtx, e: A.Call):
        if self.in_call:
            raise CodegenError("nested calls unsupported in v1 (flat ABI)")
        if "." in e.name or e.name in self.builtins():
            # Builtins are inline (no call window), but their arguments
            # still evaluate under the flag so a user call inside can never
            # silently corrupt an outer user call's window.
            self.in_call = True
            try:
                return self.builtin(ctx, e)
            finally:
                self.in_call = False
        if e.name not in self.fns:
            raise CodegenError(f"unknown function {e.name}")
        fn = self.fns[e.name]
        if len(e.args) != len(fn.params):
            raise CodegenError(f"arity of {e.name}")
        self.in_call = True
        try:
            ai = ti = 0
            for (pn, pt), a in zip(fn.params, e.args):
                if pt.name in ("u32", "bit"):
                    v = self.expr(ctx, a, want="gpr")
                    if v != 10 + ai:
                        self.e(f"  ADD x{10 + ai}, x{v}, x0")
                    ai += 1
                else:
                    v = self.expr(ctx, a, want="trf")
                    if v != 10 + ti:
                        self.e(f"  TMOV t{10 + ti}, t{v}")
                    ti += 1
            self.e(f"  JAL x1, {e.name}")
        finally:
            self.in_call = False
        rt = fn.ret
        if rt is None:
            return ("gpr", 0)
        if rt.name in ("u32", "bit"):
            return ("gpr", 10)
        return ("trf", 10)

    def builtins(self) -> set:
        return {"dot", "red_sum", "red_nnz", "red_pos", "red_neg", "relu",
                "thresh", "norm", "lnorm", "qact", "lut", "as_u32",
                "uart.putc", "uart.print_u32", "uart.newline",
                "timer.sleep_us", "timer.compare", "timer.now", "gpio.set", "gpio.get",
                "dma.copy", "dma.stride", "dma.start", "dma.wait",
                "dma.stat", "sys.run", "sys.out", "halt", "yield"}

    def builtin(self, ctx: FnCtx, e: A.Call):
        n, a = e.name, e.args
        if n == "dot":
            x = self.expr(ctx, a[0], want="trf")
            y = self.expr(ctx, a[1], want="trf")
            r = ctx.alloc_gpr()
            self.e(f"  TNDOT x{r}, t{x}, t{y}")
            return ("gpr", r)
        if n in ("red_sum", "red_nnz", "red_pos", "red_neg"):
            m = {"red_sum": "TRED_SUM", "red_nnz": "TRED_NNZ",
                 "red_pos": "TRED_POS", "red_neg": "TRED_NEG"}[n]
            x = self.expr(ctx, a[0], want="trf")
            r = ctx.alloc_gpr()
            self.e(f"  {m} x{r}, t{x}")
            return ("gpr", r)
        if n in ("relu", "norm", "qact"):
            m = {"relu": "TRELU", "norm": "TNORM", "qact": "TQACT"}[n]
            x = self.expr(ctx, a[0], want="trf")
            r = ctx.alloc_trf()
            self.e(f"  {m} t{r}, t{x}")
            return ("trf", r)
        if n == "thresh":
            x = self.expr(ctx, a[0], want="trf")
            r = ctx.alloc_trf()
            self.e(f"  TTHRESH t{r}, t{x}, {self.trit_imm(a[1])}")
            return ("trf", r)
        if n == "lnorm":
            x = self.expr(ctx, a[0], want="trf")
            y = self.expr(ctx, a[1], want="trf")
            r = ctx.alloc_trf()
            self.e(f"  TLNORM t{r}, t{x}, t{y}")
            return ("trf", r)
        if n == "lut":
            x = self.expr(ctx, a[0], want="trf")
            y = self.expr(ctx, a[1], want="trf")
            z = self.expr(ctx, a[2], want="trf")
            r = ctx.alloc_trf()
            self.e(f"  TLUT t{r}, t{x}, t{y}, t{z}")
            return ("trf", r)
        if n == "as_u32":
            x = self.expr(ctx, a[0], want="trf")
            r = ctx.alloc_gpr()
            self.e(f"  TM2G x{r}, t{x}")
            return ("gpr", r)
        if n == "uart.putc":
            x = self.expr(ctx, a[0], want="trf")
            self.e(f"  TSW t{x}, 0(x4)")
            return ("gpr", 0)
        if n == "uart.print_u32":
            return self.rt_print_u32(ctx, a[0])
        if n == "uart.newline":
            t = ctx.ttrf()
            self.e(f"  TCONST6 t{t}, 10")
            self.e(f"  TSW t{t}, 0(x4)")
            return ("gpr", 0)
        if n == "timer.sleep_us":
            return self.rt_sleep(ctx, a[0])
        if n == "timer.compare":
            return self.rt_compare(ctx, a[0])
        if n == "timer.now":
            t = ctx.ttrf()
            self.mmio_load(t, "TIMER_MTIME_LO")
            r = ctx.alloc_gpr()
            self.e(f"  TM2G x{r}, t{t}")
            return ("gpr", r)
        if n == "gpio.set":
            return self.rt_gpio_set(ctx, a[0], a[1])
        if n == "gpio.get":
            t = ctx.ttrf()
            self.mmio_load(t, "GPIO_IN")
            r = ctx.alloc_gpr()
            self.e(f"  TM2G x{r}, t{t}")
            return ("gpr", r)
        if n == "dma.copy":
            return self.rt_dma(ctx, "copy", a)
        if n == "dma.stride":
            return self.rt_dma(ctx, "stride", a)
        if n == "dma.start":
            self.e("  DMASTART")
            return ("gpr", 0)
        if n == "dma.wait":
            self.e("  DMAWAIT")
            return ("gpr", 0)
        if n == "dma.stat":
            r = ctx.alloc_gpr()
            self.e(f"  DMASTAT x{r}")
            return ("gpr", r)
        if n == "sys.run":
            return self.rt_sysrun(ctx, a)
        if n == "sys.out":
            return self.rt_sysout(ctx, a[0])
        if n == "halt":
            self.e("  HALT")
            return ("gpr", 0)
        if n == "yield":
            self.e("  ECALL")
            return ("gpr", 0)
        raise CodegenError(f"unknown builtin {n}")

    def rt_print_u32(self, ctx, arg):
        x = self.expr(ctx, arg, want="gpr")
        c = ctx.alloc_gpr()
        s = ctx.alloc_gpr()
        n = ctx.alloc_gpr()
        k = ctx.alloc_gpr()
        lt, le = ctx.lab("hex"), ctx.lab("hexend")
        la, lm = ctx.lab("alpha"), ctx.lab("emit")
        self.e(f"  ADDI x{c}, x0, 8")
        self.e(f"  ADDI x{s}, x0, 28")
        self.e(f"{lt}:")
        self.e(f"  SRL x{n}, x{x}, x{s}")
        self.e(f"  ANDI x{n}, x{n}, 15")
        self.e(f"  SLTI x{k}, x{n}, 10")
        self.e(f"  BEQ x{k}, x0, {la}")
        self.e(f"  ADDI x{n}, x{n}, 48")
        self.e(f"  BEQ x0, x0, {lm}")
        self.e(f"{la}:")
        self.e(f"  ADDI x{n}, x{n}, 55")
        self.e(f"{lm}:")
        t = ctx.ttrf()
        self.e(f"  TG2T t{t}, x{n}")
        self.e(f"  TSW t{t}, 0(x4)")
        self.e(f"  ADDI x{c}, x{c}, -1")
        self.e(f"  ADDI x{s}, x{s}, -4")
        self.e(f"  BNE x{c}, x0, {lt}")
        self.e(f"{le}:")
        return ("gpr", 0)

    def rt_sleep(self, ctx, arg):
        x = self.expr(ctx, arg, want="gpr")
        d = ctx.alloc_gpr()
        n = ctx.alloc_gpr()
        t = ctx.ttrf()
        lt = ctx.lab("tw")
        self.e(f"  SLLI x{d}, x{x}, 6")
        self.e(f"  SLLI x{n}, x{x}, 5")
        self.e(f"  ADD x{d}, x{d}, x{n}")
        self.e(f"  SLLI x{n}, x{x}, 2")
        self.e(f"  ADD x{d}, x{d}, x{n}")
        self.mmio_load(t, "TIMER_MTIME_LO")
        self.e(f"  TM2G x{n}, t{t}")
        self.e(f"  ADD x{d}, x{n}, x{d}")
        self.e(f"{lt}:")
        self.mmio_load(t, "TIMER_MTIME_LO")
        self.e(f"  TM2G x{n}, t{t}")
        self.e(f"  BLT x{n}, x{d}, {lt}")
        return ("gpr", 0)

    def rt_compare(self, ctx, arg):
        # Arm the timer compare (mcmp = mtime_lo + us*100 cycles, the same
        # scale sleep_us waits on) and return immediately, so an irq(TIMER)
        # handler fires instead of busy-waiting. CMP_HI is cleared too:
        # its reset default is all-ones, which would never match.
        x = self.expr(ctx, arg, want="gpr")
        d = ctx.alloc_gpr()
        n = ctx.alloc_gpr()
        t = ctx.ttrf()
        self.e(f"  SLLI x{d}, x{x}, 6")
        self.e(f"  SLLI x{n}, x{x}, 5")
        self.e(f"  ADD x{d}, x{d}, x{n}")
        self.e(f"  SLLI x{n}, x{x}, 2")
        self.e(f"  ADD x{d}, x{d}, x{n}")
        self.mmio_load(t, "TIMER_MTIME_LO")
        self.e(f"  TM2G x{n}, t{t}")
        self.e(f"  ADD x{d}, x{n}, x{d}")
        self.e(f"  TG2T t{t}, x{d}")
        self.mmio_store(t, "TIMER_CMP_LO")
        self.e(f"  TG2T t{t}, x0")
        self.mmio_store(t, "TIMER_CMP_HI")
        return ("gpr", 0)

    def rt_gpio_set(self, ctx, n_expr, v_expr):
        n = self.expr(ctx, n_expr, want="gpr")
        v = self.expr(ctx, v_expr, want="gpr")
        t = ctx.ttrf()
        g = ctx.alloc_gpr()
        m = ctx.alloc_gpr()
        lz, le = ctx.lab("gz"), ctx.lab("gend")
        self.mmio_load(t, "GPIO_OUT")
        self.e(f"  TM2G x{g}, t{t}")
        self.e(f"  ADDI x{m}, x0, 1")
        self.e(f"  SLL x{m}, x{m}, x{n}")
        self.e(f"  BEQ x{v}, x0, {lz}")
        self.e(f"  OR x{g}, x{g}, x{m}")
        self.e(f"  BEQ x0, x0, {le}")
        self.e(f"{lz}:")
        self.e(f"  XORI x{m}, x{m}, -1")
        self.e(f"  AND x{g}, x{g}, x{m}")
        self.e(f"{le}:")
        self.e(f"  TG2T t{t}, x{g}")
        self.mmio_store(t, "GPIO_OUT")
        return ("gpr", 0)

    def rt_dma(self, ctx, which, a):
        if which == "copy":
            if not isinstance(a[2], A.Num):
                raise CodegenError("dma.copy len must be a constant (v1)")
            ln = a[2].value
            if not 0 <= ln < 4096:
                raise CodegenError("dma.copy len out of range")
            d = self.expr(ctx, a[0], want="gpr")
            s = self.expr(ctx, a[1], want="gpr")
            self.e(f"  DMACFG x{d}, x{s}, {ln}")
        else:
            d = self.expr(ctx, a[0], want="gpr")
            s = self.expr(ctx, a[1], want="gpr")
            self.e(f"  DMASTRD x{d}, x{s}")
        return ("gpr", 0)

    def rt_sysrun(self, ctx, a):
        names = ["SYS_A0", "SYS_A1", "SYS_W0", "SYS_W1"]
        for i in range(4):
            x = self.expr(ctx, a[i], want="trf")
            self.mmio_store(x, names[i])
        sc = self.expr(ctx, a[4], want="gpr")
        t = ctx.ttrf()
        self.e(f"  TG2T t{t}, x{sc}")
        self.mmio_store(t, "SYS_SC0")
        self.mmio_store(t, "SYS_SC1")
        sh = self.expr(ctx, a[5], want="gpr")
        t = ctx.ttrf()
        shc = ctx.tgpr()
        self.e(f"  ADD x{shc}, x{sh}, x0")
        self.e(f"  SLLI x{shc}, x{shc}, 4")
        self.e(f"  ADDI x{shc}, x{shc}, 1")
        self.e(f"  TG2T t{t}, x{shc}")
        self.mmio_store(t, "SYS_CTRL")
        return ("gpr", 0)

    def rt_sysout(self, ctx, arg):
        i = self.expr(ctx, arg, want="gpr")
        base = ctx.tgpr()
        self.const_u32(base, self.mmbase + self.mm["SYS_OUT0"])
        ii = ctx.tgpr()
        self.e(f"  SLLI x{ii}, x{i}, 3")
        self.e(f"  ADD x{ii}, x{base}, x{ii}")
        t = ctx.ttrf()
        self.e(f"  TLW t{t}, 0(x{ii})")
        r = ctx.alloc_gpr()
        self.e(f"  TM2G x{r}, t{t}")
        return ("gpr", r)
