# TRIP — Triad Interactive Protocol v0.1

Text lines over UART (115200 8N1). The host sends, the target answers.

| Command | Reply | Use |
|---|---|---|
| `PING` | `PONG triad/0.1` | detect the target |
| `R <addr>` | `V <word32hex>` | read DMEM |
| `W <addr> <word>` | `OK` | write DMEM |
| `H` | `H 0\|1` | halted? |
| `S` | `OK` | single-step (debug) |
| `U <hex>` | `OK <n>` | inject bytes into RX / upload |

Errors: `ERR <msg>` (unknown command, timeout, invalid arg).

## Transports

- **SimTransport**: in-process, against the reference sim (full lockstep;
  this is what the tests use).
- **SerialTransport**: real port (`tri repl --port COM3`); requires pyserial.
  On physical silicon the TRIP monitor is still future work (v0.2): today
  the real bring-up path is JTAG plus `.hex` upload through the existing
  MHX-T2 toolchain flow.

## `tri repl`

`ping | r | w | halted | step [n] | regs | uart <text> | run <n> | help | quit`
