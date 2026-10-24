"""Exercise release behavior in isolated Git repositories."""

import json
import subprocess

import pytest

from martinpdes_maintenance.cli import main


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "pyproject.toml").write_text("""[project]
name = "example"
version = "1.2.3"
[tool.mps-maintenance]
version-file = "_version.py"
conda-recipe = "meta.yaml"
zenodo = ".zenodo.json"
citation = "CITATION.cff"
""")
    (tmp_path / "_version.py").write_text('__version__ = version = "1.2.3"\n')
    (tmp_path / "meta.yaml").write_text("package:\n  name: example\n  version: 1.2.3 # keep\n")
    (tmp_path / "CITATION.cff").write_text('version: "1.2.3"\ntitle: Example\n')
    (tmp_path / ".zenodo.json").write_text(json.dumps({"version": "1.2.3", "title": "Keep"}))
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "Initial")
    git(tmp_path, "tag", "v1.2.3")
    return tmp_path


def call(repo, *args):
    return main(["--root", str(repo), *args])


def test_next_ignores_nonstable_tags(repo, capsys):
    git(repo, "tag", "v9.0.0rc1")
    git(repo, "tag", "v2.0.0")
    assert call(repo, "next", "minor") == 0
    assert capsys.readouterr().out.strip() == "v2.1.0"


def test_check_reports_mismatch(repo, capsys):
    assert call(repo, "check") == 0
    (repo / "_version.py").write_text('__version__ = version = "0.0.1"\n')
    assert call(repo, "check") == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_dry_run_is_read_only(repo):
    before = {p.name: p.read_bytes() for p in repo.iterdir() if p.is_file()}
    head = git(repo, "rev-parse", "HEAD")
    assert call(repo, "tag", "v1.2.4", "--dry-run") == 0
    assert before == {p.name: p.read_bytes() for p in repo.iterdir() if p.is_file()}
    assert git(repo, "rev-parse", "HEAD") == head
    assert not git(repo, "tag", "--list", "v1.2.4")


def test_release_updates_all_metadata_and_annotates_tag(repo):
    assert call(repo, "tag", "v1.2.4", "--date", "2026-10-24") == 0
    assert call(repo, "check", "--version", "v1.2.4") == 0
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "cat-file", "-t", "refs/tags/v1.2.4") == "tag"
    metadata = json.loads((repo / ".zenodo.json").read_text())
    assert metadata == {"version": "1.2.4", "title": "Keep", "publication_date": "2026-10-24"}
    assert "# keep" in (repo / "meta.yaml").read_text()


@pytest.mark.parametrize("reason", ["dirty", "existing", "invalid", "malformed", "escape"])
def test_rejected_operations_do_not_change_head(repo, reason):
    tag = "v1.2.4"
    if reason == "dirty":
        (repo / "unrelated").write_text("preserve")
    elif reason == "existing":
        tag = "v1.2.3"
    elif reason == "invalid":
        tag = "v01.2.4"
    elif reason == "malformed":
        (repo / "meta.yaml").write_text("not a recipe")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "Malformed fixture")
    else:
        p = repo / "pyproject.toml"
        p.write_text(p.read_text().replace('"_version.py"', '"../outside.py"'))
        git(repo, "add", ".")
        git(repo, "commit", "-m", "Invalid configuration")
    head = git(repo, "rev-parse", "HEAD")
    assert call(repo, "tag", tag) == 1
    assert git(repo, "rev-parse", "HEAD") == head


def test_literal_project_without_optional_metadata(repo):
    p = repo / "pyproject.toml"
    p.write_text(
        '[project]\nname="example"\nversion="1.2.3"\n'
        '[tool.mps-maintenance]\nversion-file="_version.py"\n'
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Minimal configuration")
    assert call(repo, "tag", "v1.2.4") == 0
    assert json.loads((repo / ".zenodo.json").read_text())["version"] == "1.2.3"


def test_failed_commit_leaves_metadata_for_recovery(repo):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    head = git(repo, "rev-parse", "HEAD")
    assert call(repo, "tag", "v1.2.4") == 1
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "tag", "--list", "v1.2.4") == ""
    assert call(repo, "check", "--version", "v1.2.4") == 0
    assert git(repo, "diff", "--cached", "--name-only")


def test_dynamic_version_is_rejected(repo):
    p = repo / "pyproject.toml"
    p.write_text(p.read_text().replace('version = "1.2.3"', 'dynamic = ["version"]'))
    assert call(repo, "check") == 1


def test_metadata_only_project_and_first_release(repo, capsys):
    p = repo / "pyproject.toml"
    p.write_text('[project]\nname="example"\nversion="1.2.3"\n[tool.mps-maintenance]\n')
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Metadata only")
    git(repo, "tag", "-d", "v1.2.3")
    assert call(repo, "next", "minor") == 0
    assert "v1.3.0" in capsys.readouterr().out
    assert call(repo, "tag", "v1.3.0") == 0
    assert call(repo, "check") == 0
    assert git(repo, "diff", "HEAD~1", "--name-only") == "pyproject.toml"


def test_changelog_release_and_check(repo):
    p = repo / "pyproject.toml"
    p.write_text(p.read_text() + 'changelog = "CHANGELOG.md"\nrepository = "example/package"\n')
    log = repo / "CHANGELOG.md"
    log.write_text(
        "# Changes\n\n## [Unreleased]\n\n- Feature.\n\n"
        "[Unreleased]: https://github.com/example/package/compare/v1.2.3...HEAD\n"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Changelog fixture")
    assert call(repo, "check") == 1
    original = log.read_bytes()
    assert call(repo, "tag", "v1.3.0", "--dry-run") == 0
    assert log.read_bytes() == original
    assert call(repo, "tag", "v1.3.0", "--date", "2026-10-25") == 0
    assert call(repo, "check") == 0
    assert "## [1.3.0] - 2026-10-25" in log.read_text()
    assert "- Feature." in log.read_text()
    assert "compare/v1.3.0...HEAD" in log.read_text()


def test_malformed_changelog_does_not_write_any_metadata(repo):
    p = repo / "pyproject.toml"
    p.write_text(p.read_text() + 'changelog = "CHANGELOG.md"\nrepository = "example/package"\n')
    (repo / "CHANGELOG.md").write_text("Missing section and link")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Malformed changelog fixture")
    assert call(repo, "tag", "v1.3.0") == 1
    assert git(repo, "status", "--porcelain") == ""
