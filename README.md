# TypeWitness

Static analysis for `typing.cast` and `# type: ignore` evidence.

Every `cast()` call and every `# type: ignore` comment is a place where a human overrode the
type checker. TypeWitness finds those places and asks a single question: **is there a written
reason?** It also flags two shapes that are almost always a mistake — chained casts, and casting
a value that was deliberately widened to `Any` or `object` a moment earlier.

TypeWitness is a library. You give it one source file, it gives you back a sorted tuple of
findings with stable fingerprints.

## Precision first

The analyzer is built so that a finding means something. When it cannot prove what a name refers
to, it stays quiet rather than guessing:

- A `cast` call is only a candidate if the callee resolves to `typing.cast` or
  `typing_extensions.cast` through the binding sites actually visible at that point in the file.
  Any shadowing — a parameter, a `def`, a `for` target, a `with … as`, an `except … as`, a walrus,
  a conflicting import — makes the name opaque and the call is skipped.
- If a name has two bindings of different kinds reaching the same use, the resolution collapses to
  opaque. Ambiguity is never resolved in favor of reporting.
- Rules never mutate the AST and never look outside the file they were handed.
- Malformed suppression syntax fails closed: it suppresses nothing, rather than silently
  suppressing more than intended.
- Unparseable or undecodable input comes back as a structured error, not an exception.

## Requirements

- Python 3.9 – 3.14
- Git 2.24 or newer (CLI git integration only)
- The analysis core uses only the standard library
- Python 3.9–3.10 install `tomli` for CLI configuration parsing

Fingerprints and findings are verified to be byte-identical across all six supported versions.

## Install with an agent skill

```bash
npx skills add micic-mihajlo/typewitness --skill install-typewitness
```

Then ask your coding agent to install or configure TypeWitness in the current Python repository. The skill adds TypeWitness as a development dependency, wires the `typewitness` CLI into the repository's existing lint or check workflow and/or pre-commit or prek setup, keeps defaults unless configuration is needed, and validates through the project's normal command.

To inspect available skills first:

```bash
npx skills add micic-mihajlo/typewitness --list
```

## Run TypeWitness

After installation, run TypeWitness from a project directory that contains `pyproject.toml`:

```bash
typewitness
typewitness --format json
typewitness --select TW002 pkg/mod.py
```

Findings go to stdout; source analysis errors go to stderr. Exit codes: `0` clean, `1` findings, `2` analysis errors, `3` usage/config/git/filesystem errors.

Configuration lives in `[tool.typewitness]` inside `pyproject.toml`. CLI flags override pyproject values. See [Command-line interface](#command-line-interface) for git scoping, baselines, and input limits.

## Manual installation

TypeWitness is not published to PyPI yet. After its first release:

```bash
pip install typewitness
```

Until then, install from the GitHub repository with your package manager's dev-dependency workflow, or from a source checkout:

```bash
pip install .
```

Pre-commit integration is available via `.pre-commit-hooks.yaml` in this repository.

## Library usage

```python
import pathlib

from typewitness import Config, SourceFile, analyze

source = SourceFile(
    path=pathlib.Path("example.py"),
    text="from typing import cast\nvalue = cast(int, payload)\n",
)

result = analyze(source, Config())

for finding in result.findings:
    start = finding.range.start
    print(f"{finding.path}:{start.line}:{start.column} {finding.code} {finding.message}")
    print(f"  fingerprint: {finding.fingerprint}")

for error in result.errors:
    print(f"{error.kind}: {error.message}")
```

```
example.py:2:8 TW002 cast call missing SAFETY evidence
  fingerprint: e0c79c0a547a93b7
```

`analyze(source, config=None)` is the whole public API. `SourceFile` carries the text you already
read (`path`, `text`, `encoding="utf-8"`); TypeWitness does no file I/O and no directory walking,
so path handling, ordering, and concurrency stay yours. CRLF line endings and a leading BOM are
normalized before parsing.

### Findings and errors

`analyze` returns an `AnalysisResult` with two tuples, `findings` and `errors`.

Each `Finding` is a frozen dataclass:

| Field | Meaning |
| --- | --- |
| `code` | `"TW001"` … `"TW013"` |
| `path` | the `SourceFile` path, unchanged |
| `range` | `SourceRange` of `SourceLocation(line, column)`; 1-based lines, 0-based UTF-8-corrected character columns |
| `message` | short human-readable description |
| `fingerprint` | 16 lowercase hex characters (see below) |

Findings are sorted by path, start line, start column, code, then fingerprint, so output is
deterministic regardless of rule registration order.

Each `AnalysisError` has a `kind`, an optional `path`, and a `message`. There are four kinds:

- `encode` — the text contains null bytes or a lone surrogate.
- `parse` — `ast.parse` rejected the text.
- `limit` — a `RecursionError` while indexing the file.
- `internal` — an unexpected failure.

`encode`, `parse`, and `limit` are terminal for the file: `findings` comes back empty. An
`internal` error raised inside one rule is isolated — that rule contributes nothing, the other
selected rules still report, and the error names the failing code (`"TW001: …"`).

### Fingerprints

Each finding carries a fingerprint: the first 16 hex characters of a SHA-256 over the schema tag
(`tw-fp-2`), the rule code, the POSIX form of the path, the candidate kind, the scope path
(`module`, `fn:f`, `class:C@fn:m`, `comp:<comp>`), a normalized token stream of the candidate, a
normalized token stream of its enclosing logical statement, and a duplicate suffix.

Line and column numbers are deliberately absent. A fingerprint survives edits elsewhere in the
file — inserting a header, deleting a sibling statement, reordering two functions, adding a
`# type: ignore` above — and is identical on Python 3.9 through 3.14. It changes when the path,
the enclosing scope, the candidate's own tokens, or the surrounding statement's tokens change.

**The duplicate tradeoff.** Two candidates that are byte-identical after normalization, in the same
scope, inside identical statements, are genuinely indistinguishable to a position-free scheme. They
are separated by a positional suffix (`dup:<group size>:<index>` in source order) so that N
duplicates yield N distinct fingerprints rather than one collision. The cost is that adding or
removing one member of a duplicate group changes the fingerprints of the survivors. Non-duplicate
findings — the overwhelming majority — are unaffected by their neighbours.

## Rules

`TW001`, `TW002`, `TW003`, `TW005`, `TW006`, `TW007`, `TW008`, `TW009`, and `TW010` are on by default.
`TW004`, `TW011`, `TW012`, and `TW013` are experimental and opt-in.
Enable opt-in rules through `Config(select=...)` or the CLI's `--select`; see
[Configuration](#configuration). Suppression requirements are centralized in
[Suppression](#suppression).

A `cast` call is only considered when its shape is unambiguous: exactly one type argument and one
value argument, positionally or as `typ=` / `val=`. Anything else — extra positionals, `*args`,
`**kwargs`, unrecognized keywords, a missing argument — is not a candidate.

### TW001 — no-chained-cast

A `cast` whose value argument is directly another resolved `cast`. Only the outermost cast in a
chain is reported, so a triple chain produces one finding, not two.

```python
value = cast(int, cast(str, raw))  # TW001
value = cast(int, helper(cast(str, raw)))  # not a chain: the inner cast is an argument to helper
```

TW001 cannot be suppressed. See [Suppression](#suppression).

Source rationale: [typing.cast](https://docs.python.org/3/library/typing.html#typing.cast) is a
type-checker directive; nesting casts usually means the inner annotation was already wrong.

### TW002 — cast-needs-evidence

A resolved `cast` call with no `SAFETY` evidence attached to its statement. A cast that is a chain
child is skipped, so a nested chain reports TW002 once, on the outermost call.

```python
value = cast(int, payload)  # TW002
value = cast(int, payload)  # SAFETY: validated upstream   # ok

# SAFETY: validated upstream
value = cast(int, payload)  # ok
```

Source rationale: [typing.cast](https://docs.python.org/3/library/typing.html#typing.cast) does not
validate at runtime; a comment records why the checker should trust the annotation.

### TW003 — typed-ignore-needs-evidence

A `# type: ignore` comment that is missing error codes, missing `SAFETY` evidence, or both. Both
are required.

```python
value = untyped()  # type: ignore                                # TW003 — no codes
value = untyped()  # type: ignore[assignment]                    # TW003 — no evidence
value = untyped()  # type: ignore[]                              # TW003 — empty codes
value = untyped()  # type: ignore[assignment,]                   # TW003 — malformed codes

value = untyped()  # type: ignore[assignment] SAFETY: upstream stubs incomplete   # ok

# SAFETY: upstream stubs incomplete
value = untyped()  # type: ignore[assignment, arg-type]                           # ok
```

Recognition matches mypy's: a single `#`, lowercase `type: ignore`, optional bracketed codes.
`## type: ignore[...]`, `# TYPE: ignore[...]`, and `# prototype: ignore` are not directives.
Occurrences inside strings and docstrings are never directives — the file is tokenized, not
scanned. Each code must match `[\w-]+`.

Source rationale: [mypy `# type: ignore`](https://mypy.readthedocs.io/en/stable/common_issues.html#disabling-a-type-check-error-on-a-line)
requires explicit error codes so suppressions stay narrow and auditable.

### TW004 — no-widen-then-cast (experimental)

A `cast` of a local name that was annotated `Any` or `object` and initialized from a literal
earlier in the same function. This is the pattern where a value is widened only so that it can be
re-narrowed to something the type checker would otherwise have rejected.

```python
from typing import Any, cast


def load():
    widened: Any = [1, 2]
    return cast(list, widened)  # TW004
```

TW004 is deliberately narrow. The binding must be the name's only binding site in the function,
must be a direct, unconditional `AnnAssign` in the function body, and must resolve to a literal
(constants, signed numbers, and lists/tuples/sets/dicts of literals), optionally through a chain of
up to eight single-assignment local aliases. A second assignment, an `+=`, a tuple-unpack, a
`nonlocal` write from a nested function, a branch-only widen, a shadowed `Any` or `object`, or a
non-literal initializer all disqualify it. It never crosses a function boundary.

It is marked experimental because its evidence model is the newest and the narrowest part of the
analyzer; treat findings as advisory and pin the ruleset if you depend on stable output.

Source rationale: [typing.Any](https://docs.python.org/3/library/typing.html#typing.Any) is
compatible with every type, so a literal widened to `Any` and immediately re-narrowed with `cast`
usually signals a checker workaround rather than a real runtime check.

### TW005 — cast-to-any

A resolved `cast` whose type argument resolves to `typing.Any` or `typing_extensions.Any`. This is
type erasure, not narrowing.

```python
from typing import Any, cast

value = cast(Any, payload)  # TW005
value = cast(int, payload)  # not TW005
```

Source rationale: [typing.cast](https://docs.python.org/3/library/typing.html#typing.cast) to
`Any` erases static information without runtime validation.

### TW006 — discarded-cast

A resolved `cast` that is the entire value of an expression statement, so its result is discarded.

```python
from typing import cast

cast(int, payload)  # TW006
x = cast(int, payload)  # not TW006
return cast(int, payload)  # not TW006
```

Source rationale: [typing.cast](https://docs.python.org/3/library/typing.html#typing.cast) returns
its second argument unchanged at runtime, so a standalone expression statement cannot affect types or
values.

### TW007 — checker-disable-needs-evidence

A scope-wide mypy or pyright weakening directive at column 0 anywhere in the module
with no immediately preceding comment-only `SAFETY` evidence. Recognized forms are exact
and case-sensitive:

```python
# mypy: ignore-errors
# mypy: disable-error-code=assignment,misc
# pyright: basic
# pyright: standard
# pyright: reportGeneralTypeIssues=false
```

```python
# SAFETY: vendored stubs incomplete
# mypy: ignore-errors
import x  # ok

# mypy: ignore-errors
import x  # TW007


import y

# mypy: ignore-errors
import z  # TW007
```

TW007 does not cover bare `# type: ignore` (TW003), `# noqa`, `# ruff:`, line-level pyright
ignores, or inline `SAFETY:` on the directive line itself.

Source rationale: [mypy inline configuration](https://mypy.readthedocs.io/en/stable/config_file.html#confval-disable_error_code)
and [Pyright file-level comments](https://microsoft.github.io/pyright/#/comments?id=file-level-diagrams)
weaken checking for an entire scope and should carry an explicit audit trail.

### TW008 — no-type-check-needs-evidence

A resolved `@no_type_check` decorator on a function, async function, or class with no `SAFETY`
evidence on the decorator's logical line or the comment-only run directly above it.

```python
from typing import no_type_check


@no_type_check
def f(): ...  # TW008


# SAFETY: legacy untyped module
@no_type_check
def f(): ...  # ok


@no_type_check()  # not TW008 — call form is ignored
def f(): ...
```

Source rationale: [typing.no_type_check](https://docs.python.org/3/library/typing.html#typing.no_type_check)
opts an entire callable or class out of static checking and should be documented like any other
scope-wide waiver.

### TW009 — mock-patch-create-needs-evidence

A resolved `unittest.mock.patch` or `patch.object` call with literal `create=True` and no `SAFETY`
evidence on its logical statement. `create=False`, a non-literal `create=` value, `patch.dict`,
`patch.multiple`, unresolved names (including pytest `mocker` fixtures), shadowed imports, and
relative imports are all silent.

```python
from unittest.mock import patch

patch("pkg.mod.target", create=True)  # TW009
patch.object(obj, "attr", create=True)  # TW009

patch("pkg.mod.target", create=False)  # not TW009
patch("pkg.mod.target", create=flag)  # not TW009 — not a literal True
patch.dict("pkg.mod", {"a": 1}, create=True)  # not TW009
```

When `create=True` is used without an explicit mock fidelity keyword, TW012 may also report on the
same call. That double report is intentional: `create=True` fabricates attributes the real target
may not have, while missing `autospec`/`spec`/`spec_set`/`new`/`new_callable`/`wraps` leaves mock
behavior unconstrained.

Source rationale: [Python `unittest.mock.patch`](https://docs.python.org/3/library/unittest.mock.html#unittest.mock.patch)
documents `create=True` as creating the attribute when it does not exist — a test can pass against
APIs that were never implemented.

### TW010 — constant-type-guard

A function or async function whose return annotation resolves to `typing.TypeGuard` or
`typing.TypeIs`, and whose body — after an optional docstring — consists of exactly one statement:
`return True` or `return False`. A narrowing function with a constant verdict cannot establish its
claimed runtime evidence.

```python
from typing import TypeGuard


def is_str(x: object) -> TypeGuard[str]:
    return True  # TW010


def is_str(x: object) -> TypeGuard[str]:
    return isinstance(x, str)  # not TW010


def is_str(x: object) -> TypeGuard[str]:
    assert x is not None
    return True  # not TW010 — more than one statement
```

TW010 is deliberately narrow. It does not infer through branches, `try`/`except`, assertions,
generators, or nested scopes. It stays silent for `@overload` groups, `Protocol` methods, stub
bodies (`...`), explicit string annotations, shadowed imports, and any body that is not exactly one
literal boolean return.

`from __future__ import annotations` does not silence TW010; postponed evaluation still leaves a
normal `TypeGuard[...]` / `TypeIs[...]` AST on the return annotation.

Source rationale: [typing.TypeGuard](https://docs.python.org/3/library/typing.html#typing.TypeGuard)
and [typing.TypeIs](https://docs.python.org/3/library/typing.html#typing.TypeIs) narrow types only
when the function's runtime logic supports the claim.

### TW011 — unvalidated-boundary-cast (experimental)

A resolved `cast` whose value is an allowlisted stdlib boundary parser call, or only
`Attribute`/`Subscript` projections rooted directly at that call, and whose target is not `Any` or
builtin `object`. An intervening call such as `validate(json.loads(...))` is not flagged.

```python
import json
from typing import Any, cast

x = cast(dict[str, int], json.loads(raw))  # TW011
x = cast(Any, json.loads(raw))  # not TW011 — target is Any
x = cast(dict[str, int], validate(json.loads(raw)))  # not TW011 — intervening call
x = cast(str, json.loads(raw)["key"])  # TW011 — subscript projection on the parse call
x = cast(list[str], json.loads(raw).keys())  # not TW011 — method call on the parse result
```

The initial allowlist covers `json.load`/`loads`, `pickle.load`/`loads`, `marshal.load`/`loads`,
`tomllib.load`/`loads`, `plistlib.load`/`loads`, and `ast.literal_eval`, resolved through the same
fail-closed `SymbolIdentity` channel as the rest of the analyzer.

Source rationale: [json.loads](https://docs.python.org/3/library/json.html#json.loads) returns
untrusted data; [Pyre's safe JSON guidance](https://pyre-check.org/docs/safe-json) treats parsing
and validation as separate steps that `cast` must not substitute for.

### TW012 — mock-patch-needs-spec (experimental)

A resolved `patch` or `patch.object` call that makes no explicit mock fidelity decision. Presence
of any of `autospec`, `spec`, `spec_set`, `new`, `new_callable`, or `wraps` exempts the call
regardless of value, matching OpenStack
[H210](https://docs.openstack.org/hacking/latest/user/hacking.html#h210-require-autospec-spec-or-spec-set-in-mock-patch-or-mock-patch-object-calls)'s
conscious-decision policy. Positional `new` also exempts: the second argument to `patch(target,
new, …)` and the third to `patch.object(target, attribute, new, …)`. Any `**kwargs` splat stays
silent because a decision may be supplied dynamically. `patch.dict`, `patch.multiple`, `Mock()`
construction, monkeypatch, and unresolved or shadowed names stay silent.

Qualified imports resolve through nested attributes: `import unittest.mock` binds `unittest` (not
`mock`), so `unittest.mock.patch(...)` and `unittest.mock.patch.object(...)` resolve, while bare
`unittest.patch(...)` stays silent.

```python
from unittest.mock import patch

patch("pkg.mod.target")  # TW012
patch("pkg.mod.target", autospec=False)  # not TW012 — autospec was chosen explicitly
patch("pkg.mod.target", spec=object)  # not TW012
patch("pkg.mod.target", mock_obj)  # not TW012 — positional new
patch("pkg.mod.target", **kwargs)  # not TW012 — kwargs may carry spec dynamically
patch("pkg.mod.target", create=True)  # TW009 and TW012 when both are enabled

import unittest.mock

unittest.mock.patch("pkg.mod.target")  # TW012
unittest.patch("pkg.mod.target")  # not TW012 — unittest has no patch attribute
```

Unscoped or scoped `SAFETY` evidence suppresses TW012 the same way as TW009.

Source rationale: H210 and the mock docs treat an explicit fidelity keyword as proof the author
considered how tightly the mock should mirror the real object. TypeWitness applies the same
presence-only rule and deliberately does not judge whether `autospec=False` is a good idea.

### TW013 — cast-to-typevar (experimental)

A resolved `cast` whose bare `Name` target is a locally bound `TypeVar` from a single
unconditional `T = TypeVar(...)` assignment. Subscripted targets such as `list[T]`, string targets,
imported `TypeVar` names, conditional or reassigned bindings, `NewType`, `ParamSpec`, and unknown
aliases stay silent. There is no cross-file inference and no PEP 695 requirement in this release.

```python
from typing import TypeVar, cast

T = TypeVar("T")


def f(x):
    return cast(T, x)  # TW013


x = cast(int, payload)  # not TW013
x = cast(list[T], payload)  # not TW013
```

Source rationale: [typing.cast](https://docs.python.org/3/library/typing.html#typing.cast) to a bare
`TypeVar` name usually papers over a generic boundary the checker cannot prove locally.

## Suppression

Evidence is a comment. The grammar is exact and case-sensitive:

```
# SAFETY: <reason>
# SAFETY[<CODES>]: <reason>
```

The comment body must *begin* with `SAFETY` — a single leading `#`, nothing before the keyword.
Whitespace around the brackets and the colon is tolerated. These are all rejected:

```python
## SAFETY: double hash rejected
# safety: lower case rejected
# UNSAFETY: prefix rejected
# TODO: a SAFETY marker mid-comment is rejected
```

**Reason requirement.** The reason must contain at least two alphanumeric words — runs of
`[A-Za-z0-9]`, so `stubs-incomplete` counts as two. `# SAFETY:` and `# SAFETY: checked` are
rejected, and the directive is discarded entirely, which means it suppresses nothing.

**Ownership is statement-level.** A directive attaches to a statement if it is a trailing comment
anywhere on that statement's logical lines, or if it sits on a contiguous run of comment-only lines
immediately above the statement's first line. Multi-line calls work either way — a directive on the
closing-paren line covers the whole statement. The consequence is that one directive covers *every*
candidate in that logical statement, including two independent casts in one tuple. Split the
statement if you want per-cast evidence.

**Scoped codes.** `SAFETY[…]` restricts a directive to the listed rules. An unscoped directive
suppresses everything suppressible.

```python
value = cast(int, cast(str, raw))  # SAFETY[TW002]: reviewed conversion   # TW001 still reported
```

Only `TW002`, `TW003`, `TW004`, `TW005`, `TW006`, `TW007`, `TW008`, `TW009`, `TW010`, `TW011`,
`TW012`, and `TW013` are suppressible. `TW001` is not: a chained cast is a structural finding, not
a judgement call, so no comment silences it.

**Fail-closed scopes.** A malformed scope list invalidates the entire directive, which then
suppresses nothing at all — not even the rules it named correctly. `SAFETY[TW001]`,
`SAFETY[TW999]`, `SAFETY[tw002]`, `SAFETY[TW03]`, `SAFETY[]`, and `SAFETY[TW001,tw002]` are all
malformed. So this line reports both TW001 *and* TW002:

```python
value = cast(int, cast(str, raw))  # SAFETY[TW001]: reviewed conversion
```

**TW004, TW005, TW006, TW010, TW011, and TW013 require an explicit scope.** Unlike TW002 and
TW003, these rules are only suppressed by a directive that names them. A bare `# SAFETY: …` does not
silence them.

```python
return cast(list, widened)  # SAFETY[TW004]: reviewed narrowing
value = cast(Any, payload)  # SAFETY[TW005]: reviewed erasure
cast(int, payload)  # SAFETY[TW006]: intentional no-op


def is_str(x: object) -> TypeGuard[str]:  # SAFETY[TW010]: reviewed guard
    return True


x = cast(dict[str, int], json.loads(raw))  # SAFETY[TW011]: schema validated upstream
x = cast(T, payload)  # SAFETY[TW013]: reviewed generic cast
```

Note that a scoped directive no longer covers other rules on that statement; list every code you
need.

### Evidence on a `type: ignore` comment

A comment body starting with `type:` is never parsed as a standalone `SAFETY` directive, so
`type: ignore` has a dedicated inline form. `SAFETY:` must follow the directive immediately,
separated only by whitespace:

```
# type: ignore SAFETY: <reason>
# type: ignore[<codes>] SAFETY: <reason>
```

```python
value = untyped()  # type: ignore[assignment] SAFETY: upstream stubs incomplete    # ok
value = untyped()  # type: ignore[assignment] why SAFETY: upstream stubs incomplete   # TW003
```

The inline form takes no `[TW00x]` scope; it is evidence for that ignore comment only. The
two-word reason requirement applies. As an alternative, put a plain `# SAFETY: …` on the line
above — it attaches to the statement and satisfies TW003 the same way.

## Configuration

```python
from typewitness import Config

Config()  # TW001, TW002, TW003, TW005, TW006, TW007, TW008, TW009, TW010
Config(select=frozenset({"TW002"}))  # TW002 only
Config(ignore=frozenset({"TW003"}))  # TW001, TW002, TW005, TW006, TW007, TW008, TW009, TW010
Config(select=frozenset())  # nothing runs; findings is always empty
Config(
    select=frozenset(
        {
            "TW001",
            "TW002",
            "TW003",
            "TW004",
            "TW005",
            "TW006",
            "TW007",
            "TW008",
            "TW009",
            "TW010",
            "TW011",
            "TW012",
            "TW013",
        }
    )
)  # everything
```

`select=None` means the default ruleset. An explicit `select` replaces it, including the empty
frozenset, which is a valid and meaningful "run no rules". `ignore` is subtracted from whichever
set `select` produced, so `ignore` always wins. `Config.resolved_select()` returns the effective
set. Unknown codes raise `ValueError` at construction, in either field.

Enabling or disabling a rule never changes another rule's fingerprints.

## Limitations

- **Alias resolution is conservative.** Only import bindings mark a name as `cast`. Re-binding it
  through an assignment (`c = cast`) leaves `c` opaque, and calls through it are not analyzed.
  `import typing as t` / `t.cast(...)`, `from typing import cast as c` / `c(...)`, `from typing
  import *`, and `typing_extensions` equivalents all resolve.
- **Mixed import shims are opaque.** A homogeneous fallback resolves, because both branches bind
  the same kind:

  ```python
  try:
      from typing import cast
  except ImportError:
      from typing_extensions import cast
  ```

  But a shim whose branches bind *different* kinds — an import in one, a local `def cast` in the
  other — collapses to opaque, and casts through that name are silently skipped.
- **TW004, TW011, TW012, and TW013 are experimental.** Their rule identity and message may change; see
  above for their eligibility conditions.
- **Narrowing and cast rules share candidate traversals.** TW010 reads `narrowing-function`
  candidates; TW013 reuses `cast-call` candidates and a lazily built TypeVar index derived from the
  binding census. Enabling one never adds a per-rule AST walk.
- **Mock patch rules share one candidate traversal.** TW009 and TW012 read the same
  `mock-patch-call` candidates built during the single AST walk. Enabling one never changes the
  other's fingerprints or those of earlier rules.
- **TW009 and TW012 can double-report.** A literal `create=True` call with no fidelity keyword
  triggers TW009 (default) and TW012 (experimental) independently when both are selected.
- **Evidence ownership is statement-level, not candidate-level.** One `SAFETY` comment covers every
  candidate in its logical statement. This is a real precision loss for statements containing
  several casts, and it is intentional: comment-to-expression attachment is not something Python's
  grammar supports unambiguously.
- **One file at a time in the library API.** The `analyze()` function accepts a single `SourceFile`; the CLI and integrations handle discovery and aggregation.

## Command-line interface

Advanced CLI usage:

```bash
typewitness --baseline typewitness-baseline.json --write-baseline
typewitness --worktree
typewitness --diff-ref origin/main
```

### Input limits

The CLI and integrations enforce bounded reads before analysis:

| Setting | Default | Precedence |
| --- | --- | --- |
| `max-file-bytes` | `1048576` (1 MiB) | defaults < `pyproject.toml` < CLI (`--max-file-bytes`) |

Before reading a source file, TypeWitness checks `stat().st_size` against the limit, then reads at most that many bytes and verifies the payload did not grow past the cap. Oversize files and files with more than 100,000 physical lines become structured analysis errors (exit code 2) naming the canonical project path and the configured limit; they are never silently skipped.

Flake8 integration is available via the `TW` extension entry point. A pre-commit hook manifest ships in `.pre-commit-hooks.yaml`.

## Development

The project uses [uv](https://docs.astral.sh/uv/). The default interpreter is pinned to 3.9, the
oldest supported version.

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

`mypy` runs in strict mode over both `typewitness` and `tests`, and needs no arguments — its
targets come from `pyproject.toml`.

### Testing across supported versions

Parts of the suite spawn each supported interpreter as a subprocess to scan a stdlib corpus and
compare fingerprint digests. Interpreters that are not installed are skipped, so install them
first for full coverage:

```bash
uv python install 3.9 3.10 3.11 3.12 3.13 3.14
uv run pytest tests/test_stdlib_corpus.py
```

These subprocesses run with `PYTHONPATH` pointed at `src/` and never install into or mutate the
project virtual environment.

## License

TypeWitness is available under the [MIT License](LICENSE).
