"""UTM target loader + validation."""
from __future__ import annotations

import os
import tomllib


class UTMError(Exception):
    pass


def load(path: str) -> dict:
    with open(path, "rb") as f:
        d = tomllib.load(f)
    validate(d, path)
    return d


def validate(d: dict, path: str) -> None:
    t = d.get("target", {})
    for k in ("name", "isa", "trits_per_word", "trf_regs", "gpr_regs"):
        if k not in t:
            raise UTMError(f"{path}: target.{k} missing")
    mm = d.get("mmio", {})
    if "mmio" not in d.get("regions", {}):
        raise UTMError(f"{path}: regions.mmio missing")
    base = int(d["regions"]["mmio"], 0)
    for name, off in mm.items():
        o = int(off, 0)
        if o % 8 != 0:
            raise UTMError(f"{path}: mmio.{name} offset {off} not 8-aligned")
        _ = base  # base applied by backend
    q = d.get("quirks", {})
    for k in ("imm12_signed", "mmio_stride_bytes", "mstatus_mie_bit"):
        if k not in q:
            raise UTMError(f"{path}: quirks.{k} missing")


def builtin_targets() -> dict[str, str]:
    here = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(here, "..", "targets")
    if not os.path.isdir(d):
        # Installed layout (pip): targets ship as package data.
        try:
            from importlib.resources import files
            d = str(files("triad.targets"))
        except (ImportError, ModuleNotFoundError, TypeError):
            return {}
    if not os.path.isdir(d):
        return {}
    return {f[:-9]: os.path.join(d, f) for f in os.listdir(d)
            if f.endswith(".utm.toml")}
