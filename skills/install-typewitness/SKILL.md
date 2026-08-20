---
name: install-typewitness
description: Install and configure TypeWitness in a local Python repository. Use when a user asks to add TypeWitness, enforce cast and type-ignore evidence, wire up the typewitness CLI, or integrate the pre-commit hook.
---

# Install TypeWitness

Add TypeWitness as a development dependency and integrate it with the repository's existing lint or check workflow. Preserve unrelated work, keep TypeWitness defaults unless the repository clearly needs configuration, and validate through the project's normal commands.

## Procedure

1. Inspect the repository before changing it:
   - Read agent instructions (`AGENTS.md`, `CLAUDE.md`, and similar).
   - Check `git status` and preserve unrelated changes.
   - Identify the Python package manager from lockfiles and config (`uv.lock`, `poetry.lock`, `Pipfile.lock`, `requirements*.txt`, `[tool.uv]`, and so on).
   - Find the existing lint or check entry point (`just check`, `make lint`, `[tool.hatch.envs.*]`, `tox`, CI scripts, or a documented dev command).
   - Check for pre-commit (`.pre-commit-config.yaml`) or prek (`.prek.toml`, `prek.toml`).
   - Note whether TypeWitness is already installed or configured; do not overwrite existing settings without reviewing the diff.

2. Add TypeWitness as a development dependency from the canonical GitHub repository until PyPI publication:

   ```text
   https://github.com/micic-mihajlo/typewitness
   ```

   Use the repository's package manager and its normal dev-dependency workflow. Prefer a VCS or git URL dependency over copying source. After PyPI publication, prefer `pip install typewitness` or the equivalent package-manager install command instead.

3. Integrate the `typewitness` CLI into the repository's existing workflow:
   - Prefer the project's primary lint or check command when one exists. Append or compose `typewitness` there rather than inventing a parallel check.
   - When pre-commit or prek is already in use, add the public hook from this repository:

     ```yaml
     - repo: https://github.com/micic-mihajlo/typewitness
       rev: <tag-or-commit>
       hooks:
         - id: typewitness
     ```

     The shipped hook passes filenames; do not add `--staged`, `--worktree`, or `--diff-ref` to hook args.
   - When no shared check command exists, document or wire a minimal `typewitness` invocation from the project root that contains `pyproject.toml`.
   - Keep `[tool.typewitness]` unset unless the repository needs excludes, rule selection, or baseline files. Defaults are TW001, TW002, TW003, TW005, TW006, TW007, TW008, TW009, and TW010.

4. Validate through the repository's normal command, not a one-off ad hoc invocation when a standard check exists. Report findings; do not auto-fix violations, add suppressions, weaken rules, or rewrite unrelated code to make TypeWitness pass.

5. Review the final diff and report:
   - dependency change and install method,
   - lint/check or hook configuration changed,
   - validation command run and its result,
   - any remaining findings the user should address deliberately.
