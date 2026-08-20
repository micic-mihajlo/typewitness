from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from tests.conftest import analyze_source, finding_codes

ROOT = Path(__file__).resolve().parents[1]


def test_safety_on_one_candidate_does_not_change_other_fingerprints() -> None:
    without = analyze_source("from typing import cast\ncast(int, 1)\ncast(int, 2)\n")
    with_safety = analyze_source(
        "from typing import cast\ncast(int, 1)  # SAFETY: ok reason\ncast(int, 2)\n"
    )
    fp_without_second = [f for f in without.findings if f.code == "TW002"][1].fingerprint
    fp_with_second = [f for f in with_safety.findings if f.code == "TW002"][0].fingerprint
    assert fp_without_second == fp_with_second


def test_duplicate_deletion_changes_survivor_fingerprint() -> None:
    dup = analyze_source("from typing import cast\ncast(int, 1)\ncast(int, 1)\n")
    single = analyze_source("from typing import cast\ncast(int, 1)\n")
    dup_fps = sorted(f.fingerprint for f in dup.findings if f.code == "TW002")
    single_fp = next(f.fingerprint for f in single.findings if f.code == "TW002")
    assert len(dup_fps) == 2
    assert dup_fps[0] != dup_fps[1]
    assert single_fp not in dup_fps


def test_enabling_tw001_does_not_change_tw002_fingerprint() -> None:
    text = "from typing import cast\ncast(int, 1)\n"
    only_tw002 = analyze_source(text, select=frozenset({"TW002"}))
    both = analyze_source(text, select=frozenset({"TW001", "TW002"}))
    assert only_tw002.findings[0].fingerprint == both.findings[0].fingerprint


def test_crlf_and_bom_normalization() -> None:
    text = "\ufefffrom typing import cast\r\nx = cast(int, '1')\r\n"
    result = analyze_source(text, allow_errors=False)
    assert "TW002" in finding_codes(result)


def test_null_bytes_return_encode_error() -> None:
    result = analyze_source("x = 1\x00\n", allow_errors=True)
    assert result.findings == ()
    assert len(result.errors) == 1
    assert result.errors[0].kind == "encode"


def test_lone_surrogate_returns_encode_error() -> None:
    result = analyze_source("x = '\ud800'\n", allow_errors=True)
    assert result.errors[0].kind == "encode"


def test_safety_case_sensitive() -> None:
    text = "from typing import cast\nx = cast(int, '1')  # safety: nope\n"
    assert "TW002" in finding_codes(analyze_source(text))


def test_safety_rejects_unsafety_prefix() -> None:
    text = "from typing import cast\nx = cast(int, '1')  # UNSAFETY: nope\n"
    assert "TW002" in finding_codes(analyze_source(text))


def test_scoped_safety_only_suppresses_listed_rule() -> None:
    text = "from typing import cast\nx = cast(int, cast(str, '1'))  # SAFETY[TW002]: only tw002\n"
    codes = finding_codes(analyze_source(text))
    assert "TW001" in codes
    assert "TW002" not in codes


def test_keyword_cast_arguments() -> None:
    text = "from typing import cast\nx = cast(typ=int, val='1')  # SAFETY: kw form\n"
    chained = (
        "from typing import cast\n"
        "x = cast(typ=int, val=cast(typ=str, val='1'))  # SAFETY: x reason\n"
    )
    assert "TW002" not in finding_codes(analyze_source(text))
    assert "TW001" in finding_codes(analyze_source(chained))


def test_type_ignore_uppercase_not_directive() -> None:
    text = "x = 1  # TYPE: ignore[assignment] SAFETY: x\n"
    assert "TW003" not in finding_codes(analyze_source(text))


def test_type_ignore_double_hash_not_directive() -> None:
    text = "x = 1  ## type: ignore[assignment] SAFETY: x\n"
    assert "TW003" not in finding_codes(analyze_source(text))


def test_fstring_candidate_normalization() -> None:
    text = textwrap.dedent(
        """
        from typing import cast
        name = "a"
        cast(int, f"val={name}")
        """
    )
    result = analyze_source(text)
    assert any(f.code == "TW002" for f in result.findings)


def test_comprehension_cast_does_not_resolve_local_shadow() -> None:
    text = "from typing import cast\n[x for cast in 'ab' if cast(int, x)]\n"
    assert "TW002" not in finding_codes(analyze_source(text))


def test_internal_rule_failure_does_not_suppress_other_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typewitness.context import AnalysisContext
    from typewitness.rules import tw001

    def boom(self: tw001.NoChainedCastRule, context: AnalysisContext) -> tuple[()]:
        raise RuntimeError("tw001 internal")

    monkeypatch.setattr(tw001.NoChainedCastRule, "check", boom)
    text = "from typing import cast\ncast(int, 1)\n"
    result = analyze_source(text, allow_errors=True)
    assert any(error.kind == "internal" for error in result.errors)
    assert any(finding.code == "TW002" for finding in result.findings)


def test_safety_index_scales_linearly() -> None:
    header = "from typing import cast\n"
    lines = [f"x{i} = cast(int, {i})  # SAFETY: n{i}" for i in range(40)]
    text = header + "\n".join(lines)
    start = time.perf_counter()
    analyze_source(text)
    elapsed_small = time.perf_counter() - start

    lines_large = [f"y{i} = cast(int, {i})  # SAFETY: n{i}" for i in range(80)]
    text_large = header + "\n".join(lines_large)
    start = time.perf_counter()
    analyze_source(text_large)
    elapsed_large = time.perf_counter() - start

    assert elapsed_large < elapsed_small * 5 + 0.1


@pytest.mark.parametrize(
    ("comment", "expected_directive"),
    [
        ("# type: ignore", True),
        ("# type: ignore[assignment]", True),
        ("# type: ignore[assignment] SAFETY: ok", True),
        ("# TYPE: ignore[assignment]", False),
        ("## type: ignore[assignment]", False),
        ("# prototype: ignore", False),
        ("# type: ignore[]", True),
        ("# type: ignore[assignment,]", True),
    ],
)
def test_type_ignore_mypy_aligned_recognition(comment: str, expected_directive: bool) -> None:
    from typewitness.directives import is_type_ignore_comment

    assert is_type_ignore_comment(comment) is expected_directive


def test_cross_version_fingerprint_digest(tmp_path: Path) -> None:
    script = tmp_path / "fp_digest.py"
    script.write_text(
        textwrap.dedent(
            """
            import json
            from pathlib import Path
            from typewitness import SourceFile, analyze
            from typewitness.models import Config

            text = '''from typing import cast
            msg = f"hi"
            cast(int, msg)
            x = 1  # type: ignore[assignment]
            '''
            result = analyze(
                SourceFile(path=Path("mod.py"), text=text),
                config=Config(select=frozenset({"TW001", "TW002", "TW003"}), ignore=frozenset()),
            )
            payload = sorted((f.code, f.fingerprint) for f in result.findings)
            print(json.dumps(payload))
            """
        ),
        encoding="utf-8",
    )
    env = {"PYTHONPATH": str(ROOT / "src")}
    current = subprocess.check_output([sys.executable, str(script)], env=env, cwd=ROOT, text=True)
    assert json.loads(current)


def test_corpus_smoke_scan() -> None:
    files = list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py"))
    assert len(files) >= 20
    for path in files:
        result = analyze_source(path.read_text(encoding="utf-8"), path=str(path), allow_errors=True)
        assert result is not None
