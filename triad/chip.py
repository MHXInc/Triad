"""Locate the MHX-T2 reference toolchain checkout (assembler, sim, goldens).

The toolchain is private and NOT part of this repo. Point TRIAD_CHIP at a
checkout you have access to; without it, chip-backed tests are skipped
and --hex builds refuse with a clear error.
"""
from __future__ import annotations

import os


def chip_root() -> str:
    env = os.environ.get("TRIAD_CHIP")
    if env and os.path.isdir(os.path.join(env, "tools", "sdk")):
        return env
    raise FileNotFoundError(
        "MHX-T2 toolchain not found; set TRIAD_CHIP to a checkout you "
        "have access to")


def chip_path(*parts: str) -> str:
    return os.path.join(chip_root(), *parts)


def have_chip() -> bool:
    try:
        chip_root()
    except (FileNotFoundError, OSError):
        return False
    return True


TOOLCHAIN_HINT = ("MHX-T2 toolchain not found; set TRIAD_CHIP to a checkout "
                  "you have access to. Chip-backed tests are skipped.")
