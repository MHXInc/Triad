# Triad tutorial (15 minutes)

## 1. First program

```c
fn main() -> u32 {
  triad w = [+, +, -, -];
  triad v = [+, -, -, -];
  u32 d = dot(w, v);      // 2
  uart.print_u32(d);      // 00000002
  uart.newline();
  halt();
  return 0;
}
```

```bash
python tools/tric.py examples/classify3.tri -o build/cls --hex
```

## 2. Look at the simulator

```bash
python tools/repl.py
tri> ping
PONG triad/0.1
```

## 3. Rules the compiler enforces (and why)

- An integer immediate only fits in signed-12: use `x + 2000`, never `+ 3000`.
- A packed constant (`TCONST6`) cannot contain a `11` pair: use `TG2T` via GPR.
- MMIO addresses are always multiples of 8 (the bus scales `imm12` by 8).
- With IRQ on, set `mstatus.MIE` (`tric` generates it at boot when there is
  an `irq` block); without MIE, a pending IRQ never preempts.
- Calls are flat (never nest `f(g())`); `x30/x31` belong to the handler.

## 4. Multi-hart and system

```c
hart(1) { worker(); }        // second image (.hart1.hex), boot at 0x1000
irq(TIMER) { tick(); }       // handler at 0x100, dispatch by mcause
irq(ECALL) { yield(); }
mpu { region(0x0, 0xFFFFF000); }
```
