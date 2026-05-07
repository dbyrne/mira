# Contributing

Thanks for your interest. This is a small project and contributions
are welcome — whether code, documentation, bug reports, or observing
notes from a real session that surface something the test suite missed.

---

## Quick reference

```powershell
# Install in editable mode + test/lint deps
python -m pip install -e .
python -m pip install ruff mypy types-PyYAML types-requests coverage

# Run the test suite
python -m unittest discover -s tests

# Lint (zero errors expected on master)
python -m ruff check src/

# Typecheck
python -m mypy src/mira/ --ignore-missing-imports

# Coverage report
python -m coverage run --source=src -m unittest discover -s tests
python -m coverage report --skip-covered --skip-empty
```

All four should be clean before you open a PR. Master is held to
ruff-clean, mypy-clean, all tests passing.

---

## Making changes

### Branches and commits

- Branch off `master`. Use a short descriptive name
  (`fix-vsp-redirect`, `add-moon-illumination-check`).
- Commits should be coherent units. If you find yourself wanting to
  squash later, the commits weren't right in the first place.
- Commit messages: short imperative subject (under 70 chars), then a
  blank line, then a fuller body explaining the *why*. Example:

  ```
  Apply MAD-based outlier flagging to ensemble photometry

  Without it, a single contaminated comp can pull the weighted mean
  by ~0.2 mag. The 2σ rejection cutoff matches the threshold used by
  flag_outliers() in the same pipeline.
  ```

- The project uses `Co-Authored-By: ...` trailers when commits were
  generated with AI assistance. Continue that pattern if you do the
  same; flag the assistance honestly.

### Tests

Every new behavior gets a test. If you can't test it directly (network
calls, time-of-day-dependent code), mock at the module boundary the
existing tests use as a pattern:

- `tests/test_vsx_network.py` — mocking `cached_get` to simulate VSX
  responses
- `tests/test_aavso_network.py` — same pattern for AAVSO
- `tests/test_runs_thread_safety.py` — concurrency tests with real
  threads
- `tests/test_horizon.py` — pure logic tests with synthesized profiles

Tests should pass with no network access. Anything that hits a real
endpoint (the dress rehearsal CLI, for example) should be exercised
manually, not in the CI suite.

### Type annotations

The project is mypy-clean. New code should be typed:

- Public functions: full annotations on parameters and return types.
- Internal helpers: type the parts that prevent a future reader from
  guessing.
- Dataclass fields: always typed.
- `Any` is acceptable when you really mean it (e.g.,
  `record.result: Any`); prefer narrower types when you can.

If mypy complains about a third-party library that has no stubs, add
the library to the install and check with
`mypy --install-types --non-interactive`. Don't reach for `# type: ignore`
unless the alternative is genuine pain.

### Code style

- **Comments only when the WHY isn't obvious from the code.** Don't
  describe what the code does; the names should do that. Do describe
  hidden constraints, subtle invariants, or quirks (the
  `aavso_filename()` Windows-safe character list is a good example).
- **Avoid dead code.** Remove old branches when you replace them; don't
  leave them under a feature flag. Git history preserves the past.
- **No emojis** in code or docs unless explicitly asked. (This is a
  tools-and-utilities codebase, not a marketing site.)
- **`pathlib.Path`** for paths. `os.path.join` only when interfacing
  with libraries that require strings.
- **Imports** at the top of the module unless avoiding a circular
  import. Inline imports inside functions are acceptable as a
  deliberate choice but not as an unintentional side effect of fast
  prototyping.

---

## Working with AI agents

A material portion of this codebase has been written or refined with
help from AI coding assistants (Claude, primarily). The project has
made an explicit decision to *welcome* that, with guardrails:

- **Trust but verify.** Always read what an agent suggests before
  committing it. Agents sometimes hallucinate APIs, misread error
  messages, or invent file paths. The fresh-eyes audit pattern in
  `docs/troubleshooting.md` and the `tests/` suite are the
  countermeasures.
- **Honest commit attribution.** When a commit was assistant-generated,
  note it with a `Co-Authored-By:` trailer. Don't pretend solo work
  when it wasn't.
- **Tests are non-negotiable.** AI assistants are particularly prone to
  shipping changes that pass the most obvious case but fail edge
  cases. Tests catch the gap.
- **Read the diff.** Code review applies more, not less, when the
  author is non-human. Don't approve a 500-line refactor without
  reading every hunk.

---

## What kinds of changes are welcome

In rough order of preference:

1. **Real bugs from real observing**. If your first-light session
   surfaced something the system handled badly, that's the most
   valuable kind of contribution. Even a bug report (no code) is gold.
2. **Documentation improvements**. Confusing wording, missing details,
   broken instructions. The lay-person onboarding has weak spots; help
   us find them.
3. **Generalizing my JC defaults**. Hardcoded paths, gear-specific
   text, my Tailscale hostname — anything that makes the project less
   usable from someone else's machine.
4. **New site configs**. If you have a working setup for a different
   location, contributing your `config/<yoursite>.yaml` (without your
   personal observer code) is useful as a reference for others.
5. **Test coverage on under-tested modules**. `report.py` (~11% covered)
   and the network adapter modules are the obvious candidates.
6. **New scoring features, scheduler heuristics, or anomaly checks**.
   These are interesting but easy to over-engineer. Discuss in an
   issue first.

---

## What's out of scope

- **Hosting / SaaS**. The project is single-user / single-machine by
  design. The "no auth" assumption is load-bearing for the simplicity
  of the rest of the system.
- **Image stacking or pre-processing**. NINA already does this. The
  project starts from plate-solved FITS.
- **Spectroscopic photometry**. Different math, different gear, different
  workflow. Out of scope.
- **General-purpose astronomy software**. We're targeting variable-star
  observers feeding AAVSO. A proposed feature should connect to that
  workflow.

---

## Reporting bugs

If something is broken, open an issue at
[the GitHub repo][repo] with:

- The exact command you ran
- The full error output (or "expected X, got Y")
- Your Python version, OS, and any relevant config
- What you expected to happen and what actually happened

For observing-time bugs (something failed during a session), a copy of
the `data/webapp_runs/<run_id>.json` for the failed run is the most
useful single artifact you can attach. Redact your observer code if you
don't want it associated with the bug report.

[repo]: https://github.com/dbyrne/mira/issues

---

## Acknowledgments

The variable-star observing community has built freely-available
catalogs, charts, and software for decades. AAVSO, VizieR / CDS,
photutils, astropy, NINA, Stellarium — none of this would exist
without their work. Contribute your observations back to AAVSO if you
can; that's how the data trove keeps growing.
