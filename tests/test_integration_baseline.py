"""Baseline file contract: versioned, exact-count, fail-loud, atomically written.

The baseline records how many times each fingerprint was accepted. Exact counts matter
because duplicate candidates in one scope legitimately share a population but not a
fingerprint, and because "we accepted one of these" must not silently accept a second.

A baseline that cannot be trusted is worse than no baseline, so every ambiguity — a
duplicate entry, an unknown schema, a bad count — is a hard error rather than a shrug.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from tests._integration_support import CAST_NO_EVIDENCE, CHAINED_CAST, analyze_text, make_root
from typewitness.baseline import (
    BASELINE_SCHEMA,
    FINGERPRINT_SCHEMA,
    Baseline,
    BaselineEntry,
    apply_baseline,
    parse_baseline,
    render_baseline,
    write_baseline,
)
from typewitness.errors import BaselineError, FilesystemError
from typewitness.exit_codes import EXIT_USAGE_ERROR
from typewitness.fingerprint import FINGERPRINT_SCHEMA as CORE_FINGERPRINT_SCHEMA
from typewitness.models import Finding

DUPLICATE_CASTS = "from typing import cast\n\ncast(int, 1)\ncast(int, 1)\n"


def _findings(path: str = "pkg/mod.py", text: str = CAST_NO_EVIDENCE) -> Tuple[Finding, ...]:
    result = analyze_text(path, text)
    assert result.findings
    return result.findings


def _document(**overrides: Any) -> str:
    payload: Dict[str, Any] = {
        "schema": BASELINE_SCHEMA,
        "fingerprint_schema": FINGERPRINT_SCHEMA,
        "entries": [
            {"fingerprint": "0123456789abcdef", "code": "TW002", "path": "pkg/mod.py", "count": 1}
        ],
    }
    payload.update(overrides)
    return json.dumps(payload) + "\n"


# --------------------------------------------------------------------------- versioning


def test_fingerprint_schema_is_pinned_to_the_core_schema() -> None:
    assert FINGERPRINT_SCHEMA == "tw-fp-2"
    assert FINGERPRINT_SCHEMA == CORE_FINGERPRINT_SCHEMA


def test_baseline_schema_is_versioned() -> None:
    assert BASELINE_SCHEMA == "typewitness-baseline-1"


def test_incompatible_baseline_schema_is_an_error() -> None:
    with pytest.raises(BaselineError) as excinfo:
        parse_baseline(_document(schema="typewitness-baseline-0"))

    assert excinfo.value.exit_code == EXIT_USAGE_ERROR
    assert "typewitness-baseline-0" in str(excinfo.value)


def test_incompatible_fingerprint_schema_is_an_error() -> None:
    """A fingerprint scheme change invalidates every entry; refuse rather than mis-suppress."""
    with pytest.raises(BaselineError) as excinfo:
        parse_baseline(_document(fingerprint_schema="tw-fp-1"))

    assert "tw-fp-1" in str(excinfo.value)


@pytest.mark.parametrize("missing", ["schema", "fingerprint_schema", "entries"])
def test_missing_top_level_key_is_an_error(missing: str) -> None:
    payload = json.loads(_document())
    del payload[missing]

    with pytest.raises(BaselineError):
        parse_baseline(json.dumps(payload))


def test_unknown_top_level_key_is_an_error() -> None:
    with pytest.raises(BaselineError) as excinfo:
        parse_baseline(_document(generated_at="2026-01-01"))

    assert "generated_at" in str(excinfo.value)


def test_malformed_json_is_an_error() -> None:
    with pytest.raises(BaselineError):
        parse_baseline("{not json")


def test_non_object_document_is_an_error() -> None:
    with pytest.raises(BaselineError):
        parse_baseline("[]\n")


# ------------------------------------------------------------------------------ entries


def test_duplicate_entries_are_rejected() -> None:
    entry = {"fingerprint": "0123456789abcdef", "code": "TW002", "path": "pkg/mod.py", "count": 1}

    with pytest.raises(BaselineError) as excinfo:
        parse_baseline(_document(entries=[entry, dict(entry)]))

    assert "0123456789abcdef" in str(excinfo.value)


def test_duplicate_entries_are_rejected_even_with_different_counts() -> None:
    first = {"fingerprint": "0123456789abcdef", "code": "TW002", "path": "a.py", "count": 1}
    second = {"fingerprint": "0123456789abcdef", "code": "TW003", "path": "b.py", "count": 2}

    with pytest.raises(BaselineError):
        parse_baseline(_document(entries=[first, second]))


@pytest.mark.parametrize(
    "entry",
    [
        {"code": "TW002", "path": "a.py", "count": 1},
        {"fingerprint": "0123456789abcdef", "path": "a.py", "count": 1},
        {"fingerprint": "0123456789abcdef", "code": "TW002", "count": 1},
        {"fingerprint": "0123456789abcdef", "code": "TW002", "path": "a.py"},
        {"fingerprint": "0123456789abcdef", "code": "TW002", "path": "a.py", "count": 1, "x": 1},
    ],
)
def test_entry_key_set_is_exact(entry: Dict[str, Any]) -> None:
    with pytest.raises(BaselineError):
        parse_baseline(_document(entries=[entry]))


@pytest.mark.parametrize("count", [0, -1, 1.5, "1", True, None])
def test_invalid_count_is_an_error(count: Any) -> None:
    entry = {
        "fingerprint": "0123456789abcdef",
        "code": "TW002",
        "path": "a.py",
        "count": count,
    }

    with pytest.raises(BaselineError):
        parse_baseline(_document(entries=[entry]))


@pytest.mark.parametrize("fingerprint", ["", "xyz", "0123456789ABCDEF", "0123456789abcde", 1])
def test_invalid_fingerprint_is_an_error(fingerprint: Any) -> None:
    entry = {"fingerprint": fingerprint, "code": "TW002", "path": "a.py", "count": 1}

    with pytest.raises(BaselineError):
        parse_baseline(_document(entries=[entry]))


def test_unknown_rule_code_in_an_entry_is_an_error() -> None:
    entry = {"fingerprint": "0123456789abcdef", "code": "TW999", "path": "a.py", "count": 1}

    with pytest.raises(BaselineError) as excinfo:
        parse_baseline(_document(entries=[entry]))

    assert "TW999" in str(excinfo.value)


def test_absolute_entry_path_is_an_error() -> None:
    entry = {"fingerprint": "0123456789abcdef", "code": "TW002", "path": "/abs/a.py", "count": 1}

    with pytest.raises(BaselineError):
        parse_baseline(_document(entries=[entry]))


def test_entries_are_not_a_list_is_an_error() -> None:
    with pytest.raises(BaselineError):
        parse_baseline(_document(entries={"0123456789abcdef": 1}))


def test_empty_entries_list_is_valid() -> None:
    baseline = parse_baseline(_document(entries=[]))

    assert baseline.entries == {}


# ------------------------------------------------------------------------ render/parse


def test_render_then_parse_round_trips() -> None:
    findings = _findings(text=CHAINED_CAST)

    baseline = parse_baseline(render_baseline(findings))

    assert baseline.schema == BASELINE_SCHEMA
    assert baseline.fingerprint_schema == FINGERPRINT_SCHEMA
    assert set(baseline.entries) == {finding.fingerprint for finding in findings}


def test_rendered_document_shape_is_exact() -> None:
    payload = json.loads(render_baseline(_findings()))

    assert set(payload) == {"schema", "fingerprint_schema", "entries"}
    for entry in payload["entries"]:
        assert set(entry) == {"fingerprint", "code", "path", "count"}


def test_rendered_entries_are_sorted_by_fingerprint() -> None:
    payload = json.loads(render_baseline(_findings(text=CHAINED_CAST)))

    fingerprints = [entry["fingerprint"] for entry in payload["entries"]]

    assert fingerprints == sorted(fingerprints)


def test_render_is_byte_stable_and_order_independent() -> None:
    findings = _findings(text=CHAINED_CAST)

    forward = render_baseline(findings)

    assert forward == render_baseline(findings)
    assert forward == render_baseline(tuple(reversed(findings)))
    assert forward.endswith("\n")


def test_render_records_exact_counts_for_duplicates() -> None:
    findings = _findings(text=DUPLICATE_CASTS)
    tw002 = tuple(finding for finding in findings if finding.code == "TW002")

    baseline = parse_baseline(render_baseline(findings))

    assert len(tw002) == 2
    # Duplicate candidates receive distinct fingerprints, so each is counted once.
    assert sum(entry.count for entry in baseline.entries.values()) == len(findings)


def test_render_counts_repeated_fingerprints_exactly() -> None:
    finding = _findings()[0]
    repeated = (finding, finding, finding)

    baseline = parse_baseline(render_baseline(repeated))

    assert baseline.entries[finding.fingerprint].count == 3


def test_baseline_entry_and_baseline_are_frozen() -> None:
    baseline = parse_baseline(_document())
    entry = baseline.entries["0123456789abcdef"]

    assert isinstance(entry, BaselineEntry)
    assert isinstance(baseline, Baseline)
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.count = 5  # type: ignore[misc]


# --------------------------------------------------------------------------- suppression


def test_exact_count_subtraction_leaves_the_excess() -> None:
    finding = _findings()[0]
    baseline = parse_baseline(render_baseline((finding,)))

    remaining = apply_baseline((finding, finding), baseline)

    assert remaining == (finding,)


def test_matching_count_suppresses_everything() -> None:
    finding = _findings()[0]
    baseline = parse_baseline(render_baseline((finding, finding)))

    assert apply_baseline((finding, finding), baseline) == ()


def test_more_occurrences_than_the_baseline_reports_the_difference() -> None:
    finding = _findings()[0]
    baseline = parse_baseline(render_baseline((finding, finding)))

    remaining = apply_baseline((finding, finding, finding), baseline)

    assert remaining == (finding,)


def test_stale_entries_are_ignored_without_error() -> None:
    stale = _document(
        entries=[
            {
                "fingerprint": "ffffffffffffffff",
                "code": "TW002",
                "path": "deleted.py",
                "count": 3,
            }
        ]
    )
    baseline = parse_baseline(stale)
    findings = _findings()

    assert apply_baseline(findings, baseline) == findings


def test_stale_entries_never_resurrect_a_finding() -> None:
    baseline = parse_baseline(render_baseline(_findings()))

    assert apply_baseline((), baseline) == ()


def test_suppression_matches_on_fingerprint_only() -> None:
    """The fingerprint already encodes path and code; metadata is for human review."""
    finding = _findings()[0]
    document = json.loads(render_baseline((finding,)))
    document["entries"][0]["path"] = "moved/elsewhere.py"
    baseline = parse_baseline(json.dumps(document))

    assert apply_baseline((finding,), baseline) == ()


def test_apply_baseline_preserves_order_and_returns_a_tuple() -> None:
    findings = _findings(text=CHAINED_CAST)
    baseline = parse_baseline(_document(entries=[]))

    remaining = apply_baseline(findings, baseline)

    assert isinstance(remaining, tuple)
    assert remaining == findings


def test_apply_baseline_does_not_mutate_its_input() -> None:
    findings = _findings(text=CHAINED_CAST)
    snapshot = tuple(findings)
    baseline = parse_baseline(render_baseline(findings))

    apply_baseline(findings, baseline)

    assert findings == snapshot


def test_apply_baseline_suppresses_only_the_baselined_fingerprints() -> None:
    first, second = _findings(text=CHAINED_CAST)[:2]
    baseline = parse_baseline(render_baseline((first,)))

    assert first.fingerprint != second.fingerprint
    assert apply_baseline((first, second), baseline) == (second,)
    assert apply_baseline((second, first), baseline) == (second,)


# --------------------------------------------------------------------------- atomic write


def test_write_baseline_produces_a_parseable_file(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    target = root / "typewitness-baseline.json"
    findings = _findings(text=CHAINED_CAST)

    write_baseline(root, target, findings)

    assert parse_baseline(target.read_text(encoding="utf-8")).entries


def test_write_baseline_leaves_no_temporary_files(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    target = root / "typewitness-baseline.json"

    write_baseline(root, target, _findings())

    assert sorted(entry.name for entry in root.iterdir()) == ["typewitness-baseline.json"]


def test_write_baseline_replaces_within_the_target_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cross-filesystem temp file would make the replace non-atomic."""
    root = make_root(tmp_path)
    target = root / "typewitness-baseline.json"
    observed: List[Tuple[str, str]] = []
    original_replace = os.replace

    def recording_replace(src: Any, dst: Any, **kwargs: Any) -> None:
        observed.append((str(src), str(dst)))
        original_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "replace", recording_replace)

    write_baseline(root, target, _findings())

    assert len(observed) == 1
    source, destination = observed[0]
    assert Path(source).parent == root
    assert destination == str(target)


def test_failed_write_leaves_the_previous_baseline_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_root(tmp_path)
    target = root / "typewitness-baseline.json"
    write_baseline(root, target, _findings())
    before = target.read_text(encoding="utf-8")

    def failing_replace(src: Any, dst: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(FilesystemError):
        write_baseline(root, target, _findings(text=CHAINED_CAST))

    assert target.read_text(encoding="utf-8") == before
    assert sorted(entry.name for entry in root.iterdir()) == ["typewitness-baseline.json"]


def test_write_baseline_overwrites_an_existing_file(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    target = root / "typewitness-baseline.json"
    write_baseline(root, target, _findings())

    write_baseline(root, target, _findings(text=CHAINED_CAST))

    baseline = parse_baseline(target.read_text(encoding="utf-8"))
    assert len(baseline.entries) == len(_findings(text=CHAINED_CAST))


def test_write_baseline_into_a_missing_directory_is_a_filesystem_error(tmp_path: Path) -> None:
    root = make_root(tmp_path)

    with pytest.raises(FilesystemError):
        write_baseline(root, root / "missing" / "baseline.json", _findings())


def test_write_baseline_of_no_findings_writes_an_empty_baseline(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    target = root / "typewitness-baseline.json"

    write_baseline(root, target, ())

    assert parse_baseline(target.read_text(encoding="utf-8")).entries == {}


@pytest.mark.parametrize(
    "failure",
    ["symlink_guard", "fchmod", "replace"],
)
def test_write_baseline_closes_fd_and_removes_temp_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    import tempfile

    import typewitness.baseline as baseline_module

    root = make_root(tmp_path)
    target = root / "typewitness-baseline.json"
    findings = _findings()
    open_fds: set[int] = set()
    original_close = os.close
    original_mkstemp = tempfile.mkstemp

    def tracking_close(fd: int) -> None:
        open_fds.discard(fd)
        original_close(fd)

    monkeypatch.setattr(os, "close", tracking_close)

    def guarded_mkstemp(*args: Any, **kwargs: Any) -> tuple[int, str]:
        fd, name = original_mkstemp(*args, **kwargs)
        open_fds.add(fd)
        return fd, name

    monkeypatch.setattr(baseline_module.tempfile, "mkstemp", guarded_mkstemp)  # type: ignore[attr-defined]

    if failure == "symlink_guard":

        def symlink_temp(path: Path) -> bool:
            return path.parent == root and path.name.startswith(".typewitness-baseline.json.")

        monkeypatch.setattr(Path, "is_symlink", symlink_temp)
    elif failure == "fchmod":

        def fail_fchmod(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("mode")

        monkeypatch.setattr(os, "fchmod", fail_fchmod)
    else:

        def fail_replace(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("replace")

        monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(FilesystemError):
        write_baseline(root, target, findings)

    assert sorted(entry.name for entry in root.iterdir()) == []
    if failure != "replace":
        assert open_fds == set()
