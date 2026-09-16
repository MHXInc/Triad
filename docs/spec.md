# Triad — language specification v0.1

A universal language for ternary processors. C/Rust-style syntax.
Initial target: MHX-T2 (via the `mhx-t2` UTM backend); future chips arrive
as new `.utm.toml` files, without changing the language.

## Lexicon

- Comments `//` and `/* */`. Identifiers `[A-Za-z_][A-Za-z0-9_]*`.
- Trit literals: `+` (+1), `-` (−1), `0`. Integers: `42`, `0x2A` (signed-12
  where the ISA requires it; the compiler rejects the rest, like `mhxas`).
- Vectors: `[+, +, -, 0]` (up to 64 trits; the remainder pads with `0`).

## Types

| Type | Domain | Register |
|---|---|---|
| `trit` | -1/0/+1 | 1 bit-pair in TRF |
| `triad` | 32-trit word | 1 TRF |
| `triad[N]` | N words in DMEM | memory (static address) |
| `u32` | 32 bits | 1 GPR |
| `bit` | 0/1 | 1 GPR (low bit) |

## Declarations and statements

```c
trit t = +;
triad w = [+, +, -, 0];
triad table[4];
u32 x = 42;
x = x + 1;
w = a +~ b;      // saturating (TSADD); plain `+` wraps (TADD)
w = a * b;       // TMUL element-wise
u32 d = dot(a, b);
trit t = thresh(a[0], 0);
triad r = lut(a, b, tab);
triad s = a << x;             // TSHL by GPR value
if (x < y) { } else { }
while (c) { }
return x;
fn add(a: u32, b: u32) -> u32 { return a + b; }
halt();
asm("HALT");                  // escape hatch: raw MHX mnemonic
```

## Concurrency, IRQ, MPU

```c
hart(1) { main1(); }          // separate image for hart 1
irq(TIMER) { tick(); }        // handler; mtvec/mie/MIE automatic
irq(ECALL) { yield(); }
mpu { region(0x0, 0xFFFF0000); region(0xA0000000, 0xFFFF0000); }
task sensor() { ... }         // = fn + convention (experimental)
```

A match is `((addr ^ base) & mask) == 0`. Regions must cover everything
the program touches — code, `triad` arrays (`0x1000+`), literals
(`0x2000+`) and MMIO (`0xA0000000`) — or accesses fault. At most 4
regions in one `mpu` block; `hart(1)` images take no `irq`/`mpu` blocks.

## Peripherals (typed by the UTM)

```c
uart.print_u32(x); uart.putc(c); uart.newline();
timer.sleep_us(x); timer.compare(x); timer.now();
gpio.set(n, v); gpio.get(n);
dma.copy(dst, src, len); dma.stride(s, d); dma.start(); dma.wait();
sys.run(a0, a1, w0, w1, sc, sh); sys.out(i);   // accelerator via MMIO
halt(); yield();   // yield traps to the ECALL handler
```

## Conventions (MHX-T2 backend)

- Flat calls (no nesting/recursion): `u32` args in x10+, `triad` in
  t10+; return in x10/t10; `ra=x1`; MMIO base in x4 (generated at boot).
- Handler at `0x100`; boot at `0x0`; hart1 at `0x1000` (same map as the SoC).
- Compile errors (never silent): unknown builtins/functions, arity and
  type mismatches, unknown `irq` sources, more than 4 MPU regions,
  non-constant DMA lengths, MMIO offsets that are not multiples of 8,
  exhausted registers. Large immediates are synthesized (any 32-bit value
  works); `mstatus.MIE` is generated automatically when `irq` blocks exist.
