# Contributing to Triad

Triad is a language frontend with a target-description layer. Contributions must preserve clear diagnostics and deterministic code generation.

- Add tests for parser, formatter, codegen, or target behaviour as appropriate.
- Do not silently expand the language specification; update `docs/spec.md` and examples in the same change.
- Run `python -m unittest discover -s tests -p "test_*.py" -v` before a pull request.
- Target-specific assumptions belong in UTM files and target backends, not in the language grammar.
