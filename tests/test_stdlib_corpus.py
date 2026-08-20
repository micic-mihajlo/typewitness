from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from typewitness import SourceFile, analyze
from typewitness.models import Config

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULESET = frozenset({"TW001", "TW002", "TW003"})
PYTHON_VERSIONS = ["3.9", "3.10", "3.11", "3.12", "3.13", "3.14"]
CORPUS_SIZE = 1000


def _isolated_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    return env


def _python_interpreter(version: str) -> str | None:
    try:
        completed = subprocess.run(
            ["uv", "python", "find", version],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _run_isolated(
    version: str,
    script: Path,
    *args: str,
    input_text: str = "",
) -> subprocess.CompletedProcess[str]:
    interpreter = _python_interpreter(version)
    if interpreter is None:
        return subprocess.CompletedProcess(
            args=[],
            returncode=72,
            stdout="",
            stderr=f"Python {version} unavailable",
        )
    return subprocess.run(
        [interpreter, str(script), *args],
        cwd=ROOT,
        env=_isolated_env(),
        capture_output=True,
        text=True,
        check=False,
        input=input_text,
    )


def _synthetic_corpus(count: int) -> list[list[str]]:
    items: list[list[str]] = []
    for index in range(count):
        if index % 5 == 0:
            text = "\n".join(
                [
                    "from typing import cast",
                    f"def f_{index}():",
                    f"    return cast(int, {index})  # SAFETY: synthetic evidence",
                ]
            )
        elif index % 5 == 1:
            text = f"x_{index} = 1  # type: ignore[assignment]\n"
        elif index % 5 == 2:
            text = f"# SAFETY: synthetic ok reason\nz_{index} = 1  # type: ignore[arg-type]\n"
        elif index % 5 == 3:
            text = f'msg = "{{}}"  # braces in string\ny_{index} = {index}\n'
        else:
            text = f"value_{index} = {index!r}\n"
        items.append([f"synthetic/case_{index:04d}.py", text])
    return items


def _stdlib_py_files(limit: int) -> list[Path]:
    root = Path(sys.executable).resolve().parent.parent / "lib"
    if not root.exists():
        root = Path(sys.base_prefix) / "lib"
    version_dir = next(root.glob("python*"), None)
    if version_dir is None:
        return []
    files = sorted(version_dir.rglob("*.py"))[:limit]
    return files


def _scan_current_interpreter(limit: int = CORPUS_SIZE) -> tuple[int, int, int]:
    files = _stdlib_py_files(limit)
    crashes = 0
    internals = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            result = analyze(
                SourceFile(path=path, text=text),
                config=Config(select=DEFAULT_RULESET, ignore=frozenset()),
            )
        except Exception:
            crashes += 1
            continue
        internals += sum(1 for error in result.errors if error.kind == "internal")
    return len(files), crashes, internals


def test_stdlib_corpus_scan_current_interpreter() -> None:
    count, crashes, internals = _scan_current_interpreter()
    assert count >= 100
    assert crashes == 0
    assert internals == 0


@pytest.mark.parametrize("version", PYTHON_VERSIONS)
def test_stdlib_corpus_scan_by_python(version: str) -> None:
    script = ROOT / "tests" / "_stdlib_scan_runner.py"
    completed = _run_isolated(version, script, str(CORPUS_SIZE))
    if completed.returncode == 72:
        pytest.skip(f"Python {version} unavailable")
    assert completed.returncode == 0, completed.stderr
    count_str, crashes_str, internals_str = completed.stdout.strip().split(",")
    assert int(count_str) >= 100
    assert int(crashes_str) == 0
    assert int(internals_str) == 0


def test_cross_version_fingerprint_equality() -> None:
    script = ROOT / "tests" / "_fingerprint_digest_runner.py"
    digests: list[str] = []
    compared_versions: list[str] = []
    for version in PYTHON_VERSIONS:
        completed = _run_isolated(version, script)
        if completed.returncode == 72:
            continue
        assert completed.returncode == 0, completed.stderr
        digests.append(completed.stdout.strip())
        compared_versions.append(version)
    assert len(digests) >= 2, f"need at least two interpreters, found {compared_versions}"
    assert len(set(digests)) == 1


def test_cross_version_corpus_finding_tuples_1000() -> None:
    script = ROOT / "tests" / "_corpus_finding_runner.py"
    path_payloads: list[list[str]] = []
    for version in ("3.9", "3.14"):
        completed = _run_isolated(version, script, "paths")
        if completed.returncode == 72:
            pytest.skip(f"Python {version} unavailable")
        assert completed.returncode == 0, completed.stderr
        path_payloads.append(json.loads(completed.stdout.strip()))
    common_paths = sorted(set(path_payloads[0]) & set(path_payloads[1]))
    digest_payloads: list[dict[str, str | None]] = []
    for version in ("3.9", "3.14"):
        completed = _run_isolated(
            version,
            script,
            "digests",
            input_text=json.dumps(common_paths),
        )
        assert completed.returncode == 0, completed.stderr
        digest_payloads.append(json.loads(completed.stdout.strip()))
    identical_paths = sorted(
        relpath
        for relpath in common_paths
        if digest_payloads[0].get(relpath) is not None
        and digest_payloads[0].get(relpath) == digest_payloads[1].get(relpath)
    )
    synthetic_count = max(0, CORPUS_SIZE - len(identical_paths))
    stdlib_paths = identical_paths[:CORPUS_SIZE]
    synthetic_entries = _synthetic_corpus(synthetic_count)
    if len(stdlib_paths) + len(synthetic_entries) < CORPUS_SIZE:
        synthetic_entries = _synthetic_corpus(CORPUS_SIZE - len(stdlib_paths))
    assert len(stdlib_paths) + len(synthetic_entries) >= CORPUS_SIZE
    manifest = {"stdlib": stdlib_paths, "synthetic": synthetic_entries}
    payloads: list[str] = []
    manifest_json = json.dumps(manifest)
    for version in ("3.9", "3.14"):
        completed = _run_isolated(
            version,
            script,
            "manifest",
            input_text=manifest_json,
        )
        if completed.returncode == 72:
            pytest.skip(f"Python {version} unavailable")
        assert completed.returncode == 0, completed.stderr
        payloads.append(completed.stdout.strip())
    left = json.loads(payloads[0])
    right = json.loads(payloads[1])
    assert left == right
