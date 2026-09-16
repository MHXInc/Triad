"""Triad AST nodes."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Type:
    name: str          # trit, triad, u32, bit
    array: int | None = None

    def __str__(self) -> str:
        return self.name if self.array is None else f"{self.name}[{self.array}]"


@dataclass
class Program:
    items: list = field(default_factory=list)


@dataclass
class Fn:
    name: str
    params: list  # [(name, Type)]
    ret: Type | None
    body: list
    kind: str = "fn"  # fn | task


@dataclass
class Hart:
    hart: int
    body: list


@dataclass
class Irq:
    src: str
    body: list


@dataclass
class Mpu:
    regions: list  # [(base_expr, mask_expr)]


@dataclass
class Global:
    typ: Type
    name: str
    init: object = None  # vector literal list | None


@dataclass
class Decl:
    typ: Type
    name: str
    init: object = None


@dataclass
class Assign:
    target: str
    index: object = None  # array store
    value: object = None


@dataclass
class If:
    cond: object
    then: list
    els: list = field(default_factory=list)


@dataclass
class While:
    cond: object
    body: list


@dataclass
class Return:
    value: object = None


@dataclass
class ExprStmt:
    expr: object


@dataclass
class Halt:
    pass


@dataclass
class Asm:
    text: str


# expressions
@dataclass
class Num:
    value: int


@dataclass
class TritLit:
    value: int  # -1, 0, +1


@dataclass
class VecLit:
    elems: list  # list of -1/0/+1 ints


@dataclass
class Var:
    name: str


@dataclass
class Index:
    name: str
    index: object


@dataclass
class Bin:
    op: str
    l: object
    r: object


@dataclass
class Un:
    op: str
    e: object


@dataclass
class Call:
    name: str  # may contain dots: uart.print
    args: list
