# Triad — a universal language for ternary processors

Initial target: MHX-T2. Future chips plug in as `targets/*.utm.toml`
files, without changing the language. The reference toolchain (assembler,
simulator) is private and not part of this repo; point `TRIAD_CHIP` at a
checkout you have access to in order to run the chip-backed tests and
`--hex` builds.

## Usage

```bash
python tools/tric.py examples/and_or.tri -o build/and_or --hex
python tools/tric.py --check examples/and_or.tri   # parse + resolve only
python tools/tric.py --fmt examples/and_or.tri     # canonical formatting
python tools/repl.py                    # REPL on the simulator
python tools/repl.py --port COM3        # REPL on real hardware (TRIP over serial)
python -m unittest discover -s tests -p "test_*.py"
```

## Layout

```
triad/        lexer, parser, ast, fmt, codegen, utm, trip, chip
targets/      mhx-t2.utm.toml (only backend in v0.1)
std/          hal.tri, ml.tri
examples/     and_or.tri, classify3.tri
tools/        tric.py, repl.py
tests/        frontend, codegen e2e (via chip sim), trip, utm
docs/         spec.md, tutorial.md, trip.md
```

## Requires Python 3.11+ stdlib only (host). pyserial optional for serial.

## License and contribution

Triad is source-available under the [Tern/Triad Source-Available License](LICENSE). Non-commercial use, study, and modification are permitted; commercial use requires a separate written license. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before opening an issue or pull request.
