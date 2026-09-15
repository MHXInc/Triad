#!/usr/bin/env python3
"""tri repl: talk to a live Triad target (sim by default, serial with --port).

Commands: ping | r <addr> | w <addr> <word> | halted | step [n]
          regs | uart <text> | run <n> | help | quit
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from triad.chip import chip_path  # noqa
from triad.trip import SerialTransport, SimTransport  # noqa


def make_transport(args: list[str]):
    if "--port" in args:
        port = args[args.index("--port") + 1]
        baud = int(args[args.index("--baud") + 1]) if "--baud" in args \
            else 115200
        return SerialTransport(port, baud), True
    try:
        sys.path.insert(0, chip_path("tools", "python"))
        from mhx_t2.sim import SoC
        soc = SoC([0xF1000000])
        return SimTransport(soc), False
    except (ImportError, FileNotFoundError):
        print("MHX-T2 sim not found (set TRIAD_CHIP); use --port for serial")
        sys.exit(2)


HELP = """ping | r <addr> | w <addr> <word> | halted | step [n] | regs
uart <text> | run <n> | help | quit"""


def main() -> None:
    t, live = make_transport(sys.argv[1:])
    print("tri repl (target: %s). type help." % ("serial" if live else "sim"))
    while True:
        try:
            line = input("tri> ").strip()
        except EOFError:
            break
        if not line or line == "help":
            print(HELP)
            continue
        if line in ("quit", "exit"):
            break
        parts = line.split()
        cmd = parts[0]
        try:
            if cmd == "ping":
                print(t.transact("PING"))
            elif cmd == "r" and len(parts) == 2:
                print(t.transact(f"R {parts[1]}"))
            elif cmd == "w" and len(parts) == 3:
                print(t.transact(f"W {parts[1]} {parts[2]}"))
            elif cmd == "halted":
                print(t.transact("H"))
            elif cmd == "step":
                n = int(parts[1]) if len(parts) > 1 else 1
                for _ in range(n):
                    t.transact("S")
                print(f"OK stepped {n}")
            elif cmd == "regs":
                if live:
                    print("regs needs a debug agent on target (v0.2)")
                else:
                    c = t.core
                    print("pc=%08x instret=%d halted=%s" %
                          (c.pc, c.instret, c.halted))
            elif cmd == "uart" :
                print(t.transact("U " + "".join(
                    f"{b:02x}" for b in " ".join(parts[1:]).encode())))
            elif cmd == "run":
                n = int(parts[1]) if len(parts) > 1 else 100
                if live:
                    print("run needs target-side agent (v0.2)")
                else:
                    for _ in range(n):
                        t.transact("S")
                    print(f"OK ran {n}")
            else:
                print("unknown command (help)")
        except Exception as e:  # noqa
            print(f"ERR {e}")


if __name__ == "__main__":
    main()
