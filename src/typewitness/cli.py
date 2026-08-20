from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from typewitness.discovery import MAX_MAX_FILE_BYTES
from typewitness.errors import TypeWitnessError, UsageError
from typewitness.exit_codes import resolve_exit_code
from typewitness.git import DIFF_REF, STAGED, WORKTREE, GitSelection
from typewitness.presentation import (
    PresentationContext,
    present_report,
    render_markdown,
    render_pretty,
    resolve_github_context,
)
from typewitness.project import resolve_cli_project
from typewitness.report import (
    TOOL_VERSION,
    Report,
    escape_text_output,
    render_errors_text,
    render_json,
    render_sarif,
    render_text,
)
from typewitness.runner import run_analysis
from typewitness.settings import SettingsOverlay, load_pyproject_overlay, resolve_settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="typewitness", description="TypeWitness static analyzer")
    parser.add_argument("paths", nargs="*", help="files or directories to analyze")
    parser.add_argument("--config", dest="config_path", help="path to pyproject.toml")
    parser.add_argument("--version", action="version", version=f"%(prog)s {TOOL_VERSION}")
    parser.add_argument(
        "--format",
        choices=["text", "json", "sarif", "pretty", "markdown"],
        dest="output_format",
    )
    parser.add_argument("--select", action="append", dest="select_rules")
    parser.add_argument("--ignore", action="append", dest="ignore_rules")
    parser.add_argument("--exclude", action="append", dest="exclude_patterns")
    parser.add_argument("--baseline", dest="baseline")
    parser.add_argument("--write-baseline", action="store_true", dest="write_baseline")
    parser.add_argument("--max-file-bytes", dest="max_file_bytes", type=int)
    git_group = parser.add_mutually_exclusive_group()
    git_group.add_argument("--staged", action="store_true")
    git_group.add_argument("--worktree", action="store_true")
    git_group.add_argument("--diff-ref", dest="diff_ref")
    return parser


def _parse_rule_list(values: Optional[Sequence[str]]) -> Optional[frozenset[str]]:
    if values is None:
        return None
    codes: set[str] = set()
    for value in values:
        for part in value.split(","):
            item = part.strip()
            if item:
                codes.add(item)
    return frozenset(codes)


def _parse_max_file_bytes(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    if value < 1:
        raise UsageError("max-file-bytes must be a positive integer")
    if value > MAX_MAX_FILE_BYTES:
        raise UsageError(f"max-file-bytes exceeds maximum ({MAX_MAX_FILE_BYTES})")
    return value


def _cli_overlay(args: argparse.Namespace) -> SettingsOverlay:
    return SettingsOverlay(
        select=_parse_rule_list(args.select_rules),
        ignore=_parse_rule_list(args.ignore_rules),
        exclude=tuple(args.exclude_patterns) if args.exclude_patterns else None,
        output_format=args.output_format,
        baseline=args.baseline,
        max_file_bytes=_parse_max_file_bytes(args.max_file_bytes),
    )


def _git_selection(args: argparse.Namespace) -> Optional[GitSelection]:
    if args.staged:
        return GitSelection(mode=STAGED)
    if args.worktree:
        return GitSelection(mode=WORKTREE)
    if args.diff_ref is not None:
        return GitSelection(mode=DIFF_REF, ref=args.diff_ref)
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        return 3

    try:
        project = resolve_cli_project(
            cwd=Path.cwd(),
            config_path=Path(args.config_path) if args.config_path is not None else None,
            input_paths=args.paths,
        )
        pyproject_overlay = load_pyproject_overlay(project)
        cli_overlay = _cli_overlay(args)
        settings = resolve_settings(pyproject_overlay, cli_overlay)
        output_format = settings.output_format

        baseline_path: Optional[Path] = None
        if settings.baseline is not None:
            baseline_path = project.resolve(settings.baseline)
        if args.write_baseline and settings.baseline is None:
            raise TypeWitnessError(
                "--write-baseline requires --baseline or pyproject baseline setting"
            )

        write_path = baseline_path if args.write_baseline else None
        machine_format = output_format in {"json", "sarif"}
        presentation_format = output_format in {"pretty", "markdown"}

        result = run_analysis(
            paths=args.paths,
            settings=settings,
            project=project,
            git_selection=_git_selection(args),
            baseline_path=None if args.write_baseline else baseline_path,
            write_baseline_path=write_path,
        )

        report = Report(findings=result.findings, errors=result.errors)

        if args.write_baseline:
            if machine_format:
                if output_format == "json":
                    sys.stdout.write(render_json(report))
                else:
                    sys.stdout.write(render_sarif(report))
            if result.errors:
                if not machine_format:
                    sys.stderr.write(render_errors_text(report))
                return 2
            return 0
        elif machine_format:
            if output_format == "json":
                sys.stdout.write(render_json(report))
            else:
                sys.stdout.write(render_sarif(report))
        elif presentation_format:
            context = PresentationContext(
                project=project,
                compare_url=resolve_github_context(),
                max_file_bytes=settings.max_file_bytes,
            )
            presented = present_report(report, context)
            if output_format == "pretty":
                sys.stdout.write(render_pretty(presented))
            else:
                sys.stdout.write(render_markdown(presented))
        elif result.findings:
            sys.stdout.write(render_text(report))

        if result.errors and not machine_format and not args.write_baseline:
            sys.stderr.write(render_errors_text(report))

        return resolve_exit_code(
            has_findings=bool(result.findings),
            has_analysis_errors=bool(result.errors),
        )
    except TypeWitnessError as exc:
        sys.stderr.write(f"{escape_text_output(str(exc))}\n")
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        sys.stderr.write(f"{escape_text_output(str(exc))}\n")
        return 3
