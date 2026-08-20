"""File discovery and PEP 263 source reading.

Discovery owns two properties the rest of the layer depends on: a stable, sorted,
de-duplicated file list, and a decoded ``SourceFile`` whose ``path`` is already the
canonical repo-relative POSIX form. Symlinks are never followed, so a link loop or a
link that escapes the project cannot widen the scan.
"""

from __future__ import annotations

import codecs
import io
import os
from pathlib import Path
from typing import Any, List, Tuple

import pytest

from tests._integration_support import (
    CAST_NO_EVIDENCE,
    CLEAN_SOURCE,
    make_root,
    write_bytes,
    write_file,
    write_project,
)
from typewitness.discovery import DEFAULT_EXCLUDES, discover_paths, physical_line_count, read_source
from typewitness.errors import FilesystemError
from typewitness.exit_codes import EXIT_USAGE_ERROR
from typewitness.project import Project, discover_project


def _canonicals(project: Project, paths: Tuple[Path, ...]) -> List[str]:
    return [project.canonical(path) for path in paths]


def test_default_excludes_are_a_stable_tuple_of_directory_names() -> None:
    assert isinstance(DEFAULT_EXCLUDES, tuple)
    assert DEFAULT_EXCLUDES == tuple(sorted(DEFAULT_EXCLUDES))
    assert len(set(DEFAULT_EXCLUDES)) == len(DEFAULT_EXCLUDES)
    for required in (".git", ".venv", "__pycache__", "build", "dist", "node_modules"):
        assert required in DEFAULT_EXCLUDES


def test_discovery_is_sorted_by_canonical_posix_path(tmp_path: Path) -> None:
    root = write_project(
        make_root(tmp_path),
        {
            "z.py": CLEAN_SOURCE,
            "a.py": CLEAN_SOURCE,
            "pkg/b.py": CLEAN_SOURCE,
            "pkg/a.py": CLEAN_SOURCE,
            "pkg/sub/a.py": CLEAN_SOURCE,
            "PkgUpper/a.py": CLEAN_SOURCE,
        },
    )
    project = discover_project(root)

    found = _canonicals(project, discover_paths(project, (root,), ()))

    assert found == sorted(found)
    assert found == [
        "PkgUpper/a.py",
        "a.py",
        "pkg/a.py",
        "pkg/b.py",
        "pkg/sub/a.py",
        "z.py",
    ]


def test_discovery_is_repeatable(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"a.py": CLEAN_SOURCE, "pkg/b.py": CLEAN_SOURCE})
    project = discover_project(root)

    first = discover_paths(project, (root,), ())
    second = discover_paths(project, (root,), ())

    assert first == second


def test_discovery_collects_python_and_stub_files_only(tmp_path: Path) -> None:
    root = write_project(
        make_root(tmp_path),
        {
            "mod.py": CLEAN_SOURCE,
            "stub.pyi": CLEAN_SOURCE,
            "notes.txt": "text\n",
            "data.json": "{}\n",
            "script": "#!/usr/bin/env python\n",
            "mod.pyc": "",
        },
    )
    project = discover_project(root)

    found = _canonicals(project, discover_paths(project, (root,), ()))

    assert found == ["mod.py", "stub.pyi"]


def test_discovery_dedupes_overlapping_inputs(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"pkg/a.py": CLEAN_SOURCE, "pkg/b.py": CLEAN_SOURCE})
    project = discover_project(root)

    inputs = (
        root,
        root / "pkg",
        root / "pkg" / "a.py",
        root / "pkg" / "a.py",
        root / "pkg" / ".." / "pkg" / "b.py",
    )
    found = _canonicals(project, discover_paths(project, inputs, ()))

    assert found == ["pkg/a.py", "pkg/b.py"]


def test_default_excludes_are_pruned_during_traversal(tmp_path: Path) -> None:
    root = write_project(
        make_root(tmp_path),
        {
            "keep.py": CLEAN_SOURCE,
            ".venv/lib/site.py": CLEAN_SOURCE,
            "__pycache__/cached.py": CLEAN_SOURCE,
            "build/generated.py": CLEAN_SOURCE,
            "dist/wheel.py": CLEAN_SOURCE,
            "node_modules/pkg/mod.py": CLEAN_SOURCE,
            ".mypy_cache/x.py": CLEAN_SOURCE,
            "pkg/__pycache__/nested.py": CLEAN_SOURCE,
            "pkg/keep.py": CLEAN_SOURCE,
        },
    )
    (root / ".git").mkdir()
    write_file(root, ".git/hook.py", CLEAN_SOURCE)
    project = discover_project(root)

    found = _canonicals(project, discover_paths(project, (root,), ()))

    assert found == ["keep.py", "pkg/keep.py"]


def test_user_excludes_add_to_the_defaults(tmp_path: Path) -> None:
    root = write_project(
        make_root(tmp_path),
        {
            "keep.py": CLEAN_SOURCE,
            "generated/mod.py": CLEAN_SOURCE,
            "vendor/deep/mod.py": CLEAN_SOURCE,
            "__pycache__/cached.py": CLEAN_SOURCE,
        },
    )
    project = discover_project(root)

    found = _canonicals(project, discover_paths(project, (root,), ("generated", "vendor")))

    assert found == ["keep.py"]


def test_explicit_file_arguments_honor_exclusion(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"generated/mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)

    walked = discover_paths(project, (root,), ("generated",))
    explicit = discover_paths(project, (root / "generated" / "mod.py",), ("generated",))

    assert walked == ()
    assert explicit == ()


def test_symlinked_directories_are_not_followed(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"pkg/real.py": CLEAN_SOURCE})
    outside = write_project(make_root(tmp_path, "outside"), {"secret.py": CLEAN_SOURCE})
    (root / "linked").symlink_to(outside, target_is_directory=True)
    (root / "loop").symlink_to(root, target_is_directory=True)
    project = discover_project(root)

    found = _canonicals(project, discover_paths(project, (root,), ()))

    assert found == ["pkg/real.py"]


def test_symlinked_files_are_not_yielded(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"real.py": CLEAN_SOURCE})
    (root / "alias.py").symlink_to(root / "real.py")
    project = discover_project(root)

    walked = discover_paths(project, (root,), ())
    assert _canonicals(project, walked) == ["real.py"]
    with pytest.raises(FilesystemError):
        discover_paths(project, (root / "alias.py",), ())


def test_paths_with_spaces_and_non_ascii_names(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    write_file(root, "src dir/caf\u00e9/m\u00f6d.py", CAST_NO_EVIDENCE)
    write_file(root, "src dir/two words.py", CLEAN_SOURCE)
    write_file(root, "\u65e5\u672c/mod.py", CLEAN_SOURCE)
    project = discover_project(root)

    found = _canonicals(project, discover_paths(project, (root,), ()))

    assert found == [
        "src dir/caf\u00e9/m\u00f6d.py",
        "src dir/two words.py",
        "\u65e5\u672c/mod.py",
    ]


def test_nonexistent_input_is_a_filesystem_error(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    project = discover_project(root)

    with pytest.raises(FilesystemError) as excinfo:
        discover_paths(project, (root / "missing.py",), ())

    assert excinfo.value.exit_code == EXIT_USAGE_ERROR
    assert "missing.py" in str(excinfo.value)


def test_input_outside_the_project_is_rejected(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    outsider = write_file(make_root(tmp_path, "elsewhere"), "mod.py", CLEAN_SOURCE)
    project = discover_project(root)

    with pytest.raises(FilesystemError):
        discover_paths(project, (outsider,), ())


def test_empty_input_list_scans_the_project_root(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CLEAN_SOURCE})
    project = discover_project(root)

    assert _canonicals(project, discover_paths(project, (), ())) == ["mod.py"]


def test_read_source_uses_the_canonical_relative_path(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"pkg/mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)

    result = read_source(project, root / "pkg" / "mod.py")

    assert result.error is None
    assert result.source is not None
    assert result.source.path == Path("pkg/mod.py")
    assert result.source.path.as_posix() == "pkg/mod.py"


def test_read_source_defaults_to_utf8(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": 'VALUE = "caf\u00e9"\n'})
    project = discover_project(root)

    result = read_source(project, root / "mod.py")

    assert result.source is not None
    assert codecs.lookup(result.source.encoding).name == codecs.lookup("utf-8").name
    assert result.source.text == 'VALUE = "caf\u00e9"\n'


def test_read_source_honours_a_pep263_coding_cookie(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    payload = '# -*- coding: latin-1 -*-\nVALUE = "caf\u00e9"\n'.encode("latin-1")
    write_bytes(root, "mod.py", payload)
    project = discover_project(root)

    result = read_source(project, root / "mod.py")

    assert result.error is None
    assert result.source is not None
    assert codecs.lookup(result.source.encoding).name == codecs.lookup("latin-1").name
    assert "caf\u00e9" in result.source.text


def test_read_source_honours_a_second_line_cookie(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    payload = '#!/usr/bin/env python\n# coding: cp1252\nVALUE = "caf\u00e9"\n'.encode("cp1252")
    write_bytes(root, "mod.py", payload)
    project = discover_project(root)

    result = read_source(project, root / "mod.py")

    assert result.source is not None
    assert codecs.lookup(result.source.encoding).name == codecs.lookup("cp1252").name


def test_read_source_ignores_a_third_line_cookie(tmp_path: Path) -> None:
    """PEP 263 only looks at the first two lines."""
    root = write_project(make_root(tmp_path), {})
    text = "VALUE = 1\nOTHER = 2\n# -*- coding: latin-1 -*-\n"
    write_bytes(root, "mod.py", text.encode("utf-8"))
    project = discover_project(root)

    result = read_source(project, root / "mod.py")

    assert result.source is not None
    assert codecs.lookup(result.source.encoding).name == codecs.lookup("utf-8").name


def test_read_source_handles_a_bom(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    write_bytes(root, "mod.py", codecs.BOM_UTF8 + CAST_NO_EVIDENCE.encode("utf-8"))
    project = discover_project(root)

    result = read_source(project, root / "mod.py")

    assert result.error is None
    assert result.source is not None
    assert codecs.lookup(result.source.encoding).name == codecs.lookup("utf-8-sig").name
    assert not result.source.text.startswith("\ufeff")


def test_read_source_reports_a_bom_and_cookie_conflict(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    payload = codecs.BOM_UTF8 + b"# -*- coding: latin-1 -*-\nVALUE = 1\n"
    write_bytes(root, "mod.py", payload)
    project = discover_project(root)

    result = read_source(project, root / "mod.py")

    assert result.source is None
    assert result.error is not None
    assert result.error.kind == "encode"
    assert result.error.path == Path("mod.py")


def test_read_source_reports_undecodable_bytes_as_an_analysis_error(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    write_bytes(root, "mod.py", b'VALUE = "\xff\xfe\xfd"\n')
    project = discover_project(root)

    result = read_source(project, root / "mod.py")

    assert result.source is None
    assert result.error is not None
    assert result.error.kind == "encode"


def test_read_source_reports_an_unknown_codec_as_an_analysis_error(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    write_bytes(root, "mod.py", b"# -*- coding: not-a-codec -*-\nVALUE = 1\n")
    project = discover_project(root)

    result = read_source(project, root / "mod.py")

    assert result.source is None
    assert result.error is not None
    assert result.error.kind == "encode"


def test_read_source_of_a_missing_file_is_a_filesystem_error(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    project = discover_project(root)

    with pytest.raises(FilesystemError):
        read_source(project, root / "missing.py")


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores file modes")
def test_read_source_of_an_unreadable_file_is_a_filesystem_error(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CLEAN_SOURCE})
    project = discover_project(root)
    target = root / "mod.py"
    target.chmod(0o000)
    try:
        with pytest.raises(FilesystemError):
            read_source(project, target)
    finally:
        target.chmod(0o644)


def test_read_source_of_an_empty_file_succeeds(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": ""})
    project = discover_project(root)

    result = read_source(project, root / "mod.py")

    assert result.error is None
    assert result.source is not None
    assert result.source.text == ""


def test_read_source_preserves_crlf_for_the_core_to_normalize(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    write_bytes(root, "mod.py", b"VALUE = 1\r\nOTHER = 2\r\n")
    project = discover_project(root)

    result = read_source(project, root / "mod.py")

    assert result.source is not None
    assert "\r\n" in result.source.text


def test_read_source_opens_the_file_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decoding must not cost a second pass over the file."""
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)
    target = root / "mod.py"
    opens: List[str] = []
    original_open = io.open

    def counting_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            opens.append(os.fspath(file))
        except TypeError:
            pass
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(io, "open", counting_open)
    monkeypatch.setattr("builtins.open", counting_open)

    result = read_source(project, target)

    assert result.source is not None
    assert [entry for entry in opens if entry == str(target)] == [str(target)]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", 0),
        ("only", 1),
        ("a\nb", 2),
        ("a\r\nb\r\n", 2),
        ("a\rb", 2),
        ("a\v\nb", 2),
        ("a\u2028b", 1),
        ("a\u2029b", 1),
        ("a\x85b", 1),
    ],
)
def test_physical_line_count_uses_newline_semantics_only(text: str, expected: int) -> None:
    assert physical_line_count(text) == expected


def test_read_source_counts_form_feed_inside_a_physical_line(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {})
    text = ("line\n" * 99_999) + "before\fafter\n"
    assert physical_line_count(text) == 100_000
    assert len(text.splitlines()) == 100_001
    write_bytes(root, "mod.py", text.encode("utf-8"))
    project = discover_project(root)

    result = read_source(project, root / "mod.py")

    assert result.error is None
    assert result.source is not None
