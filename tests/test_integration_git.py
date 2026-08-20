"""Git-scoped analysis: explicit modes only, unified=0 parsing, changed-line intersection.

Three properties matter more than convenience here:

1. Git filtering is never implicit. There is no "guess the mode" default, because a wrong
   guess silently hides findings.
2. Git failures are always reported. A missing repository, a bad ref, or a non-zero exit
   is exit code 3 — never an empty changed-line set that looks like a clean run.
3. Only the new side of a diff matters. Deletions contribute nothing to analyze.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

import pytest

from tests._integration_support import (
    CAST_NO_EVIDENCE,
    CLEAN_SOURCE,
    commit_all,
    git_available,
    git_checked,
    init_repo,
    make_root,
    stage,
    write_file,
    write_project,
)
from typewitness.errors import GitError, UsageError
from typewitness.exit_codes import EXIT_USAGE_ERROR
from typewitness.git import (
    DIFF_REF,
    STAGED,
    WORKTREE,
    GitSelection,
    changed_lines,
    diff_command,
    filter_findings_to_changed_lines,
    parse_unified_diff,
)
from typewitness.project import discover_project

requires_git = pytest.mark.skipif(not git_available(), reason="git executable not available")

TWO_CAST_LINES = "from typing import cast\n\nfirst = cast(int, 1)\n\nsecond = cast(str, 2)\n"

DIFF_BYPASS_SOURCE = '"""\n++ b/other.py\n"""\nfrom typing import cast\n\nvalue = cast(int, 1)\n'


def _diff(body: str) -> str:
    return textwrap.dedent(body).lstrip("\n")


def _repo(tmp_path: Path, files: Mapping[str, str]) -> Path:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, files)
    commit_all(root, "initial")
    return root


# ------------------------------------------------------------------- mode declarations


def test_mode_constants_are_explicit_strings() -> None:
    assert STAGED == "staged"
    assert WORKTREE == "worktree"
    assert DIFF_REF == "diff-ref"


def test_selection_requires_a_known_mode() -> None:
    with pytest.raises(UsageError) as excinfo:
        GitSelection(mode="since-yesterday")

    assert excinfo.value.exit_code == EXIT_USAGE_ERROR


def test_diff_ref_requires_a_ref() -> None:
    with pytest.raises(UsageError):
        GitSelection(mode=DIFF_REF)


def test_staged_and_worktree_reject_a_ref() -> None:
    with pytest.raises(UsageError):
        GitSelection(mode=STAGED, ref="HEAD~1")
    with pytest.raises(UsageError):
        GitSelection(mode=WORKTREE, ref="HEAD~1")


def test_empty_ref_is_rejected() -> None:
    with pytest.raises(UsageError):
        GitSelection(mode=DIFF_REF, ref="")


def test_diff_command_always_requests_zero_context() -> None:
    for selection in (
        GitSelection(mode=STAGED),
        GitSelection(mode=WORKTREE),
        GitSelection(mode=DIFF_REF, ref="main"),
    ):
        command = diff_command(selection)
        assert "--unified=0" in command
        assert "--no-color" in command
        assert command[0] == "diff"


def test_staged_mode_diffs_the_index() -> None:
    command = diff_command(GitSelection(mode=STAGED))

    assert "--cached" in command


def test_worktree_mode_does_not_diff_the_index_alone() -> None:
    command = diff_command(GitSelection(mode=WORKTREE))

    assert "--cached" not in command
    assert "--end-of-options" in command
    assert "HEAD" in command


def test_diff_ref_mode_passes_the_ref_through() -> None:
    command = diff_command(GitSelection(mode=DIFF_REF, ref="origin/main"))

    assert "origin/main" in command
    assert "--end-of-options" in command
    assert command[-1] == "--"
    assert "--cached" not in command


def test_diff_command_never_uses_a_pager_or_external_diff() -> None:
    command = diff_command(GitSelection(mode=WORKTREE))

    assert "--no-ext-diff" in command
    assert "--exit-code" not in command


# ----------------------------------------------------------------- unified=0 parsing


def test_single_added_line() -> None:
    diff = _diff(
        """
        diff --git a/pkg/mod.py b/pkg/mod.py
        index 1111111..2222222 100644
        --- a/pkg/mod.py
        +++ b/pkg/mod.py
        @@ -3,0 +3,1 @@
        +value = cast(int, 1)
        """
    )

    assert parse_unified_diff(diff) == {"pkg/mod.py": frozenset({3})}


def test_multi_line_hunk_expands_to_every_line() -> None:
    diff = _diff(
        """
        diff --git a/mod.py b/mod.py
        --- a/mod.py
        +++ b/mod.py
        @@ -12,0 +12,3 @@
        +a = 1
        +b = 2
        +c = 3
        """
    )

    assert parse_unified_diff(diff) == {"mod.py": frozenset({12, 13, 14})}


def test_several_hunks_in_one_file_are_unioned() -> None:
    diff = _diff(
        """
        diff --git a/mod.py b/mod.py
        --- a/mod.py
        +++ b/mod.py
        @@ -1,0 +1,1 @@
        +a = 1
        @@ -20,0 +21,2 @@
        +b = 2
        +c = 3
        """
    )

    assert parse_unified_diff(diff) == {"mod.py": frozenset({1, 21, 22})}


def test_pure_deletion_hunk_contributes_no_lines() -> None:
    diff = _diff(
        """
        diff --git a/mod.py b/mod.py
        --- a/mod.py
        +++ b/mod.py
        @@ -5,3 +4,0 @@
        -a = 1
        -b = 2
        -c = 3
        """
    )

    assert parse_unified_diff(diff) == {"mod.py": frozenset()}


def test_deleted_file_is_absent_from_the_result() -> None:
    diff = _diff(
        """
        diff --git a/gone.py b/gone.py
        deleted file mode 100644
        --- a/gone.py
        +++ /dev/null
        @@ -1,2 +0,0 @@
        -a = 1
        -b = 2
        """
    )

    assert parse_unified_diff(diff) == {}


def test_new_file_reports_all_of_its_lines() -> None:
    diff = _diff(
        """
        diff --git a/new.py b/new.py
        new file mode 100644
        --- /dev/null
        +++ b/new.py
        @@ -0,0 +1,3 @@
        +a = 1
        +b = 2
        +c = 3
        """
    )

    assert parse_unified_diff(diff) == {"new.py": frozenset({1, 2, 3})}


def test_rename_is_keyed_under_the_new_path() -> None:
    diff = _diff(
        """
        diff --git a/old.py b/new.py
        similarity index 90%
        rename from old.py
        rename to new.py
        --- a/old.py
        +++ b/new.py
        @@ -4,0 +4,1 @@
        +value = cast(int, 1)
        """
    )

    assert parse_unified_diff(diff) == {"new.py": frozenset({4})}


def test_rename_without_content_change_has_no_changed_lines() -> None:
    diff = _diff(
        """
        diff --git a/old.py b/new.py
        similarity index 100%
        rename from old.py
        rename to new.py
        """
    )

    assert parse_unified_diff(diff) == {"new.py": frozenset()}


def test_mode_only_change_has_no_changed_lines() -> None:
    diff = _diff(
        """
        diff --git a/mod.py b/mod.py
        old mode 100644
        new mode 100755
        """
    )

    assert parse_unified_diff(diff) == {"mod.py": frozenset()}


def test_paths_with_spaces_are_parsed() -> None:
    diff = _diff(
        """
        diff --git a/src dir/two words.py b/src dir/two words.py
        --- a/src dir/two words.py
        +++ b/src dir/two words.py
        @@ -1,0 +1,1 @@
        +a = 1
        """
    )

    assert parse_unified_diff(diff) == {"src dir/two words.py": frozenset({1})}


def test_quoted_non_ascii_paths_are_decoded() -> None:
    diff = (
        'diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"\n'
        '--- "a/caf\\303\\251.py"\n'
        '+++ "b/caf\\303\\251.py"\n'
        "@@ -1,0 +1,1 @@\n"
        "+a = 1\n"
    )

    assert parse_unified_diff(diff) == {"caf\u00e9.py": frozenset({1})}


def test_binary_files_are_ignored() -> None:
    diff = _diff(
        """
        diff --git a/logo.png b/logo.png
        index 1111111..2222222 100644
        Binary files a/logo.png and b/logo.png differ
        """
    )

    assert parse_unified_diff(diff) == {"logo.png": frozenset()}


def test_no_newline_marker_is_ignored() -> None:
    diff = _diff(
        """
        diff --git a/mod.py b/mod.py
        --- a/mod.py
        +++ b/mod.py
        @@ -1,1 +1,1 @@
        -a = 1
        \\ No newline at end of file
        +a = 2
        \\ No newline at end of file
        """
    )

    assert parse_unified_diff(diff) == {"mod.py": frozenset({1})}


def test_added_line_beginning_with_plus_is_not_a_header() -> None:
    diff = _diff(
        """
        diff --git a/mod.py b/mod.py
        --- a/mod.py
        +++ b/mod.py
        @@ -1,0 +1,2 @@
        +++weird = 1
        +normal = 2
        """
    )

    assert parse_unified_diff(diff) == {"mod.py": frozenset({1, 2})}


def test_added_diff_path_line_inside_hunk_does_not_change_current_path() -> None:
    diff = _diff(
        """
        diff --git a/mod.py b/mod.py
        --- a/mod.py
        +++ b/mod.py
        @@ -0,0 +1,4 @@
        +\"\"\"
        ++ b/other.py
        +\"\"\"
        +value = 1
        """
    )

    assert parse_unified_diff(diff) == {"mod.py": frozenset({1, 2, 3, 4})}


def test_removed_diff_path_line_inside_hunk_does_not_change_current_path() -> None:
    diff = _diff(
        """
        diff --git a/mod.py b/mod.py
        --- a/mod.py
        +++ b/mod.py
        @@ -1,1 +1,1 @@
        --- not a header
        +value = 2
        """
    )

    assert parse_unified_diff(diff) == {"mod.py": frozenset({1})}


def test_hunk_counts_must_be_consumed_exactly() -> None:
    diff = _diff(
        """
        diff --git a/mod.py b/mod.py
        --- a/mod.py
        +++ b/mod.py
        @@ -1,1 +1,2 @@
        +only one added
        """
    )

    with pytest.raises(GitError) as excinfo:
        parse_unified_diff(diff)

    assert "truncated" in str(excinfo.value).lower()


def test_unexpected_addition_when_hunk_exhausted_is_a_git_error() -> None:
    diff = _diff(
        """
        diff --git a/mod.py b/mod.py
        --- a/mod.py
        +++ b/mod.py
        @@ -1,0 +1,1 @@
        +first = 1
        +second = 2
        """
    )

    with pytest.raises(GitError):
        parse_unified_diff(diff)


def test_truncated_hunk_at_eof_is_a_git_error() -> None:
    diff = _diff(
        """
        diff --git a/mod.py b/mod.py
        --- a/mod.py
        +++ b/mod.py
        @@ -1,0 +1,3 @@
        +a = 1
        +b = 2
        """
    )

    with pytest.raises(GitError):
        parse_unified_diff(diff)


def test_empty_diff_is_an_empty_mapping() -> None:
    assert parse_unified_diff("") == {}


def test_unparseable_hunk_header_is_a_git_error() -> None:
    """Never silently degrade: an unrecognized hunk means the mapping cannot be trusted."""
    diff = _diff(
        """
        diff --git a/mod.py b/mod.py
        --- a/mod.py
        +++ b/mod.py
        @@ this is not a hunk header @@
        +a = 1
        """
    )

    with pytest.raises(GitError):
        parse_unified_diff(diff)


def test_hunk_without_a_file_header_is_a_git_error() -> None:
    with pytest.raises(GitError):
        parse_unified_diff("@@ -1 +1 @@\n+a = 1\n")


def test_parse_result_is_deterministic() -> None:
    diff = _diff(
        """
        diff --git a/b.py b/b.py
        --- a/b.py
        +++ b/b.py
        @@ -1,0 +1,1 @@
        +a = 1
        diff --git a/a.py b/a.py
        --- a/a.py
        +++ b/a.py
        @@ -2,0 +2,1 @@
        +b = 2
        """
    )

    first = parse_unified_diff(diff)
    second = parse_unified_diff(diff)

    assert first == second
    assert sorted(first) == ["a.py", "b.py"]


# --------------------------------------------------------- changed-line intersection


def test_findings_on_changed_lines_survive() -> None:
    from tests._integration_support import analyze_text

    findings = analyze_text("mod.py", TWO_CAST_LINES).findings
    assert len(findings) == 2
    lines = {finding.range.start.line for finding in findings}

    kept = filter_findings_to_changed_lines(findings, {"mod.py": frozenset({min(lines)})})

    assert len(kept) == 1
    assert kept[0].range.start.line == min(lines)


def test_findings_on_unchanged_lines_are_dropped() -> None:
    from tests._integration_support import analyze_text

    findings = analyze_text("mod.py", TWO_CAST_LINES).findings

    assert filter_findings_to_changed_lines(findings, {"mod.py": frozenset({999})}) == ()


def test_findings_in_files_absent_from_the_diff_are_dropped() -> None:
    from tests._integration_support import analyze_text

    findings = analyze_text("mod.py", CAST_NO_EVIDENCE).findings

    assert filter_findings_to_changed_lines(findings, {"other.py": frozenset({1})}) == ()


def test_intersection_covers_the_whole_finding_range() -> None:
    """A multi-line cast touched anywhere is a touched cast."""
    from tests._integration_support import analyze_text

    text = "from typing import cast\n\nvalue = cast(\n    int,\n    1,\n)\n"
    findings = analyze_text("mod.py", text).findings
    assert findings
    end_line = findings[0].range.end.line
    assert end_line > findings[0].range.start.line

    kept = filter_findings_to_changed_lines(findings, {"mod.py": frozenset({end_line})})

    assert kept == findings


def test_intersection_preserves_order_and_returns_a_tuple() -> None:
    from tests._integration_support import analyze_text

    findings = analyze_text("mod.py", TWO_CAST_LINES).findings
    lines = frozenset(finding.range.start.line for finding in findings)

    kept = filter_findings_to_changed_lines(findings, {"mod.py": lines})

    assert isinstance(kept, tuple)
    assert kept == findings


def test_empty_changed_map_drops_everything() -> None:
    from tests._integration_support import analyze_text

    findings = analyze_text("mod.py", CAST_NO_EVIDENCE).findings

    assert filter_findings_to_changed_lines(findings, {}) == ()


# ------------------------------------------------------------------- failure reporting


def test_missing_repository_is_a_git_error(tmp_path: Path) -> None:
    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)

    with pytest.raises(GitError) as excinfo:
        changed_lines(project, GitSelection(mode=WORKTREE))

    assert excinfo.value.exit_code == EXIT_USAGE_ERROR


def test_git_failure_is_reported_not_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import typewitness.git as git_module

    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)

    def failing_run(root_path: Path, args: Sequence[str]) -> str:
        raise GitError("fatal: bad revision 'nope'")

    monkeypatch.setattr(git_module, "run_git", failing_run)

    with pytest.raises(GitError) as excinfo:
        changed_lines(project, GitSelection(mode=DIFF_REF, ref="nope"))

    assert "bad revision" in str(excinfo.value)


def test_non_zero_git_exit_becomes_a_git_error_with_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    import typewitness.git as git_module

    root = write_project(make_root(tmp_path), {"mod.py": CAST_NO_EVIDENCE})

    def failing_subprocess(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["git"], returncode=128, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", failing_subprocess)

    with pytest.raises(GitError) as excinfo:
        git_module.run_git(root, ("diff", "--unified=0"))

    assert "boom" in str(excinfo.value)


# ---------------------------------------------------------------------- real git repos


@requires_git
def test_staged_mode_sees_staged_changes_only(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE, "other.py": CLEAN_SOURCE})
    project = discover_project(root)
    write_file(root, "mod.py", CLEAN_SOURCE + "STAGED = 2\n")
    stage(root, "mod.py")
    write_file(root, "other.py", CLEAN_SOURCE + "UNSTAGED = 3\n")

    changed = changed_lines(project, GitSelection(mode=STAGED)).lines

    assert set(changed) == {"mod.py"}
    assert changed["mod.py"] == frozenset({2})


@requires_git
def test_worktree_mode_sees_staged_and_unstaged_changes(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE, "other.py": CLEAN_SOURCE})
    project = discover_project(root)
    write_file(root, "mod.py", CLEAN_SOURCE + "STAGED = 2\n")
    stage(root, "mod.py")
    write_file(root, "other.py", CLEAN_SOURCE + "UNSTAGED = 2\n")

    changed = changed_lines(project, GitSelection(mode=WORKTREE)).lines

    assert set(changed) == {"mod.py", "other.py"}


@requires_git
def test_worktree_mode_includes_untracked_files_entirely(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    project = discover_project(root)
    write_file(root, "brand_new.py", "a = 1\nb = 2\nc = 3\n")

    changed = changed_lines(project, GitSelection(mode=WORKTREE)).lines

    assert changed["brand_new.py"] == frozenset({1, 2, 3})


@requires_git
@pytest.mark.parametrize(
    "relative,text,expected_lines",
    [
        ("lf.py", "a = 1\nb = 2\n", frozenset({1, 2})),
        ("crlf.py", "a = 1\r\nb = 2\r\n", frozenset({1, 2})),
        ("cr.py", "a = 1\rb = 2\r", frozenset({1, 2})),
        ("formfeed.py", "a = 1\nbefore\fafter\n", frozenset({1, 2})),
    ],
)
def test_untracked_changed_lines_use_physical_newline_semantics(
    tmp_path: Path,
    relative: str,
    text: str,
    expected_lines: frozenset[int],
) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    project = discover_project(root)
    write_file(root, relative, text)

    changed = changed_lines(project, GitSelection(mode=WORKTREE)).lines

    assert changed[relative] == expected_lines


@requires_git
@pytest.mark.parametrize(
    "relative,text",
    [
        ("lf.py", "from typing import cast\n\nvalue = cast(int, 1)\n"),
        ("crlf.py", "from typing import cast\r\n\r\nvalue = cast(int, 1)\r\n"),
        ("cr.py", "from typing import cast\r\rvalue = cast(int, 1)\r"),
    ],
)
def test_untracked_findings_survive_worktree_filter_after_each_separator(
    tmp_path: Path,
    relative: str,
    text: str,
) -> None:
    from tests._integration_support import analyze_text

    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    project = discover_project(root)
    write_file(root, relative, text)
    findings = analyze_text(relative, text).findings
    assert findings
    changed = changed_lines(project, GitSelection(mode=WORKTREE)).lines
    kept = filter_findings_to_changed_lines(findings, changed)

    assert kept == findings


@requires_git
def test_staged_mode_excludes_untracked_files(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    project = discover_project(root)
    write_file(root, "brand_new.py", "a = 1\n")

    changed = changed_lines(project, GitSelection(mode=STAGED)).lines

    assert "brand_new.py" not in changed


@requires_git
def test_gitignored_untracked_files_are_not_reported(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE, ".gitignore": "generated/\n"})
    project = discover_project(root)
    write_file(root, "generated/mod.py", "a = 1\n")

    changed = changed_lines(project, GitSelection(mode=WORKTREE)).lines

    assert "generated/mod.py" not in changed


@requires_git
def test_deleted_files_are_not_reported(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE, "doomed.py": CLEAN_SOURCE})
    project = discover_project(root)
    (root / "doomed.py").unlink()

    worktree = changed_lines(project, GitSelection(mode=WORKTREE)).lines
    stage(root, "doomed.py")
    staged = changed_lines(project, GitSelection(mode=STAGED)).lines

    assert "doomed.py" not in worktree
    assert "doomed.py" not in staged


@requires_git
def test_renamed_file_is_keyed_under_its_new_path(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"old.py": TWO_CAST_LINES})
    project = discover_project(root)
    git_checked(root, "mv", "old.py", "new.py")
    write_file(root, "new.py", TWO_CAST_LINES + "EXTRA = 1\n")
    stage(root, "new.py")

    changed = changed_lines(project, GitSelection(mode=STAGED)).lines

    assert "old.py" not in changed
    assert "new.py" in changed


@requires_git
def test_diff_ref_mode_compares_against_the_named_ref(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    project = discover_project(root)
    base = git_checked(root, "rev-parse", "HEAD").strip()
    write_file(root, "mod.py", CLEAN_SOURCE + "SECOND = 2\n")
    commit_all(root, "second")

    changed = changed_lines(project, GitSelection(mode=DIFF_REF, ref=base)).lines

    assert changed["mod.py"] == frozenset({2})


@requires_git
def test_unknown_ref_is_a_git_error(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    project = discover_project(root)

    with pytest.raises(GitError):
        changed_lines(project, GitSelection(mode=DIFF_REF, ref="no-such-ref"))


@requires_git
def test_changed_paths_are_canonical_to_the_project_root(tmp_path: Path) -> None:
    """In a monorepo the project root can sit below the repository root."""
    repo = make_root(tmp_path, "repo")
    init_repo(repo)
    write_file(repo, "outside.py", CLEAN_SOURCE)
    root = write_project(repo / "sub" / "project", {"pkg/mod.py": CLEAN_SOURCE})
    commit_all(repo, "initial")
    project = discover_project(root)
    write_file(root, "pkg/mod.py", CLEAN_SOURCE + "CHANGED = 2\n")
    write_file(repo, "outside.py", CLEAN_SOURCE + "ALSO = 2\n")

    changed = changed_lines(project, GitSelection(mode=WORKTREE)).lines

    assert set(changed) == {"pkg/mod.py"}
    assert changed["pkg/mod.py"] == frozenset({2})


@requires_git
def test_changed_lines_returns_frozensets_of_ints(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    project = discover_project(root)
    write_file(root, "mod.py", CLEAN_SOURCE + "SECOND = 2\n")

    changed = changed_lines(project, GitSelection(mode=WORKTREE)).lines

    for path, lines in changed.items():
        assert isinstance(path, str)
        assert isinstance(lines, frozenset)
        assert all(isinstance(line, int) for line in lines)


@requires_git
def test_unborn_repository_worktree_lists_untracked_python(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    init_repo(root)
    write_project(root, {"mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)

    changed = changed_lines(project, GitSelection(mode=WORKTREE)).lines

    assert changed["mod.py"]


@requires_git
def test_clean_worktree_has_no_changed_lines(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"mod.py": CAST_NO_EVIDENCE})
    project = discover_project(root)

    assert changed_lines(project, GitSelection(mode=WORKTREE)).lines == {}


@requires_git
@pytest.mark.parametrize("git_args", [["--staged"], ["--worktree"], ["--diff-ref", "HEAD"]])
def test_git_modes_keep_findings_when_diff_contains_path_like_source_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    git_args: list[str],
) -> None:
    from typewitness.cli import main

    root = _repo(tmp_path, {"mod.py": CLEAN_SOURCE})
    write_file(root, "mod.py", DIFF_BYPASS_SOURCE)
    if git_args[0] == "--staged":
        stage(root, "mod.py")
        args = ["--format", "json", *git_args]
    elif git_args[0] == "--worktree":
        args = ["--format", "json", *git_args]
    else:
        commit_all(root, "second")
        args = ["--format", "json", "--diff-ref", "HEAD~1"]
    monkeypatch.chdir(root)

    assert main(args) == 1
    captured = capsys.readouterr()
    assert captured.out
    assert "TW002" in captured.out
    assert captured.out.count('"path"') >= 1


def test_changed_lines_signature_accepts_only_a_selection() -> None:
    """There is no implicit mode: callers must name what they want compared."""
    import inspect

    parameters: Tuple[str, ...] = tuple(inspect.signature(changed_lines).parameters)

    assert parameters == ("project", "selection", "max_file_bytes", "max_line_count")
