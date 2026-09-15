"""TRIP: Triad Interactive Protocol (host <-> chip over UART).

Text lines, host sends commands, target replies. v0.1 commands:
  PING            -> PONG triad/0.1
  R <addr>        -> V <word32>        (DMEM word read)
  W <addr> <word> -> OK                (DMEM word write)
  H               -> H 0|1             (halted?)
  S               -> OK                (single step, debug builds)
  U <hexbytes>    -> OK <n>            (UART loopback/upload ack)
Transports: SimTransport (in-process chip sim), SerialTransport (pyserial).
"""
from __future__ import annotations


class TripError(Exception):
    pass


def parse_line(line: str) -> tuple[str, list[str]]:
    parts = line.strip().split()
    if not parts:
        raise TripError("empty line")
    return parts[0].upper(), parts[1:]


def fmt_word(v: int) -> str:
    return f"{v & 0xFFFFFFFF:08x}"


class SimTransport:
    """TRIP responder wired to the chip reference simulator (lockstep)."""

    def __init__(self, soc):
        self.soc = soc
        self.core = soc.cores[0]

    def transact(self, line: str) -> str:
        cmd, args = parse_line(line)
        if cmd == "PING":
            return "PONG triad/0.1"
        if cmd == "R":
            if len(args) != 1:
                raise TripError("R needs addr")
            return "V " + fmt_word(self.core._load(int(args[0], 0)))
        if cmd == "W":
            if len(args) != 2:
                raise TripError("W needs addr + word")
            self.core._store(int(args[0], 0), int(args[1], 0))
            return "OK"
        if cmd == "H":
            return f"H {1 if self.core.halted else 0}"
        if cmd == "S":
            self.core.step()
            self.soc.periph.tick()
            return "OK"
        if cmd == "U":
            if not args:
                raise TripError("U needs hex")
            raw = bytes.fromhex(args[0])
            self.soc.periph.uart_rx.extend(raw)
            return f"OK {len(raw)}"
        raise TripError(f"unknown command {cmd}")


class SerialTransport:
    """TRIP over a real serial port (needs pyserial)."""

    def __init__(self, port: str, baud: int = 115200, timeout: float = 1.0):
        try:
            import serial  # type: ignore
        except ImportError as e:
            raise TripError("pyserial not installed (pip install pyserial)") \
                from e
        self.ser = serial.Serial(port, baud, timeout=timeout)

    def transact(self, line: str) -> str:
        self.ser.write((line.strip() + "\n").encode())
        resp = self.ser.readline().decode(errors="replace").strip()
        if not resp:
            raise TripError("target timeout")
        return resp
