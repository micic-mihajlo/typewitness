"""Public agent skill contract for install-typewitness.

``skills/install-typewitness/SKILL.md`` is a public interface: consumers pin it by repo
and skill name, so its frontmatter and core install guidance must stay stable.
"""

from __future__ import annotations

import re

from tests._integration_support import REPO_ROOT

SKILL_PATH = REPO_ROOT / "skills" / "install-typewitness" / "SKILL.md"
REPOSITORY_URL = "https://github.com/micic-mihajlo/typewitness"
SKILL_INSTALL_COMMAND = "npx skills add micic-mihajlo/typewitness --skill install-typewitness"
FRONTMATTER_PATTERN = re.compile(
    r"^---\n(?P<body>.*?)\n---\n",
    re.DOTALL,
)


def _skill_text() -> str:
    assert SKILL_PATH.is_file(), f"{SKILL_PATH} is missing"
    return SKILL_PATH.read_text(encoding="utf-8")


def _frontmatter() -> dict[str, str]:
    match = FRONTMATTER_PATTERN.match(_skill_text())
    assert match is not None, "SKILL.md must begin with YAML frontmatter"
    entries: dict[str, str] = {}
    for line in match.group("body").splitlines():
        key, separator, value = line.partition(":")
        if separator:
            entries[key.strip()] = value.strip()
    return entries


def test_skill_file_exists_at_the_public_path() -> None:
    assert SKILL_PATH.is_file()


def test_skill_frontmatter_declares_name_and_description() -> None:
    frontmatter = _frontmatter()

    assert frontmatter["name"] == "install-typewitness"
    assert frontmatter["description"]
    assert "TypeWitness" in frontmatter["description"]


def test_skill_body_documents_the_canonical_repository() -> None:
    body = _skill_text()

    assert REPOSITORY_URL in body
    assert "typewitness" in body
    assert "pass_filenames" not in body.lower()


def test_skill_body_discourages_auto_fix_or_suppression() -> None:
    body = _skill_text().lower()

    assert "do not auto-fix" in body
    assert "suppress" in body


def test_readme_leads_with_the_skill_install_command() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    skill_heading = readme.index("## Install with an agent skill")
    run_heading = readme.index("## Run TypeWitness")
    manual_heading = readme.index("## Manual installation")
    library_heading = readme.index("## Library usage")

    assert skill_heading < run_heading < manual_heading < library_heading
    assert SKILL_INSTALL_COMMAND in readme


def test_readme_documents_the_primary_cli_command_before_advanced_flags() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    run_section = readme.split("## Run TypeWitness", 1)[1].split("## Manual installation", 1)[0]
    cli_section = readme.split("## Command-line interface", 1)[1]

    assert "```bash\ntypewitness\n" in run_section
    assert "--baseline typewitness-baseline.json --write-baseline" in cli_section
