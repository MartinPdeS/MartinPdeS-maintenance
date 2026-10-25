"""Exercise read-only diagnostics using small repositories and inert workflows."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from martinpdes_maintenance.cli import main
from martinpdes_maintenance.doctor import inspect_repository


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Provide a configured repository without requiring a clean working tree."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="example"\nversion="1.2.3"\n'
        '[project.optional-dependencies]\nrelease=["martinpdes-maintenance==0.2.2"]\n'
        '[tool.mps-maintenance]\nversion-file="_version.py"\n'
    )
    (tmp_path / "_version.py").write_text('__version__ = version = "1.2.3"\n')
    (tmp_path / "Makefile").write_text(
        "release-check:\n\t$(PYTHON) -m martinpdes_maintenance.cli check\n"
    )
    return tmp_path


def workflow(repo: Path, jobs: dict) -> None:
    """Write a workflow as data; never execute its commands."""
    directory = repo / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ci.yml").write_text(yaml.safe_dump({"name": "Test", "jobs": jobs}))


def codes(repo: Path) -> set[str]:
    """Return failing diagnostic identifiers."""
    return {finding.code for finding in inspect_repository(repo) if finding.level != "ok"}


def test_healthy_dirty_repository_is_read_only(repo: Path, capsys) -> None:
    """Dirty files, Git metadata, and all repository contents stay unchanged."""
    (repo / "unrelated.txt").write_text("User edits\n")
    before = {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    assert main(["--root", str(repo), "doctor", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counts"] == {"ok": 4, "warning": 0, "error": 0}
    assert before == {
        str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob("*") if p.is_file()
    }


def test_multiple_failures_are_reported_with_fixes(repo: Path) -> None:
    """Independent checks continue after metadata drift is detected."""
    (repo / "_version.py").write_text('__version__ = version = "0.0.1"\n')
    (repo / "Makefile").write_text("release-check:\n\tpython tools/check_release.py\n")
    findings = inspect_repository(repo)
    errors = [item for item in findings if item.level == "error"]
    assert {item.code for item in errors} >= {
        "version-mismatch",
        "legacy-release-wrapper",
        "missing-command-file",
    }
    assert all(item.fix for item in errors)
    assert main(["--root", str(repo), "doctor"]) == 1


def test_scm_dependencies_and_dynamic_versions(repo: Path) -> None:
    """Both build/runtime conventions and explicit versions are checked."""
    p = repo / "pyproject.toml"
    p.write_text(
        p.read_text().replace('version="1.2.3"', 'dynamic=["version"]')
        + '\n[build-system]\nrequires=["setuptools_scm[toml]>=8"]\n'
    )
    assert codes(repo) >= {"project-version", "scm-versioning", "release-configuration"}


def test_scm_provider_without_dependency(repo: Path) -> None:
    """An old backend provider is detected even after removing its dependency."""
    p = repo / "pyproject.toml"
    p.write_text(
        p.read_text()
        + '\n[tool.scikit-build]\nmetadata.version.provider="scikit_build_core.metadata.setuptools_scm"\n'
    )
    assert "scm-versioning" in codes(repo)


@pytest.mark.parametrize(
    "text, code",
    [
        ("[project", "invalid-toml"),
        ('project="bad"', "invalid-project-metadata"),
        ('[project]\nname="example"\nversion="1.2.3"', "release-configuration"),
    ],
)
def test_bad_project_metadata_is_actionable(repo: Path, text: str, code: str) -> None:
    """Invalid project data produces diagnostics rather than tracebacks."""
    (repo / "pyproject.toml").write_text(text)
    assert code in codes(repo)


def test_missing_configured_file(repo: Path) -> None:
    """Missing release files do not prevent checking other conventions."""
    (repo / "_version.py").unlink()
    assert "release-configuration" in codes(repo)


def test_documentation_warning_and_strict_exit(repo: Path, capsys) -> None:
    """Uncertain documentation commands warn by default and fail in strict mode."""
    (repo / "README.md").write_text(
        "Run python scripts/missing.py\npython -m sphinx -b html absent /tmp/docs\n"
    )
    assert codes(repo) >= {"missing-command-file", "missing-docs-source"}
    assert main(["--root", str(repo), "doctor"]) == 0
    capsys.readouterr()
    assert main(["--root", str(repo), "doctor", "--strict", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["warning"] == 2
    assert report["counts"]["error"] == 0


@pytest.mark.parametrize(
    "install",
    [
        'python -m pip install "martinpdes-maintenance==0.2.2"',
        'python -m pip install -e ".[release]"',
    ],
)
def test_ci_recognizes_direct_and_extra_installation(repo: Path, install: str) -> None:
    """Both standalone and declared release-extra installs satisfy CI setup."""
    workflow(
        repo,
        {
            "check": {
                "steps": [{"run": install}, {"run": "python -m martinpdes_maintenance.cli doctor"}]
            }
        },
    )
    assert "ci-tool-install" not in codes(repo)


def test_ci_reports_missing_install_without_running_commands(repo: Path) -> None:
    """Workflow commands are never run, even if they contain shell mutations."""
    workflow(repo, {"check": {"steps": [{"run": "touch SHOULD_NOT_EXIST; mps-maintenance check"}]}})
    assert "ci-tool-install" in codes(repo)
    assert not (repo / "SHOULD_NOT_EXIST").exists()


def test_reusable_workflow_installation_is_scoped(repo: Path) -> None:
    """A test install must not satisfy an independently executed release input."""
    workflow(
        repo,
        {
            "check": {
                "uses": "example/shared@v1",
                "with": {
                    "install-command": 'python -m pip install -e ".[release]"',
                    "test-command": "mps-maintenance check",
                    "release_validation_command": "mps-maintenance check",
                },
            }
        },
    )
    issues = [item for item in inspect_repository(repo) if item.code == "ci-tool-install"]
    assert len(issues) == 1
    assert "release_validation_command" in issues[0].message


def test_conditional_install_is_not_guaranteed(repo: Path) -> None:
    """A skipped install cannot establish tool availability for another step."""
    workflow(
        repo,
        {
            "check": {
                "steps": [
                    {"if": "false", "run": "python -m pip install martinpdes-maintenance"},
                    {"run": "mps-maintenance doctor"},
                ]
            }
        },
    )
    assert "ci-tool-install" in codes(repo)


@pytest.mark.parametrize(
    "text", ["jobs: [", "jobs: []", "!!python/object/apply:os.system ['touch UNSAFE']"]
)
def test_invalid_or_unsafe_yaml_is_not_executed(repo: Path, text: str) -> None:
    """Safe parsing rejects malformed YAML and Python-specific constructors."""
    workflow(repo, {})
    (repo / ".github/workflows/ci.yml").write_text(text)
    assert "invalid-workflow" in codes(repo)
    assert not (repo / "UNSAFE").exists()


def test_external_symlink_is_not_read(repo: Path, tmp_path: Path) -> None:
    """Documentation checks do not follow links outside the repository."""
    external = tmp_path.parent / (tmp_path.name + "-outside.md")
    external.write_text("python tools/check_release.py")
    (repo / "README.md").symlink_to(external)
    assert "external-path" in codes(repo)
    assert "legacy-release-wrapper" not in codes(repo)


def test_sphinx_flags_and_make_variables_are_not_paths(repo: Path) -> None:
    """Sphinx flags and unresolved Make variables must not look like directories."""
    (repo / "docs/source").mkdir(parents=True)
    (repo / "Makefile").write_text(
        "docs:\n\tpython -m sphinx -b html -W --keep-going docs/source /tmp/docs\n"
        "other:\n\tpython -m sphinx -b html -W $(DOCS_DIR)/source /tmp/docs\n"
    )
    assert "missing-docs-source" not in codes(repo)


def test_missing_changelog_release_is_reported(repo: Path) -> None:
    """A configured changelog must contain the currently declared release."""
    p = repo / "pyproject.toml"
    p.write_text(p.read_text() + 'changelog="CHANGELOG.md"\nrepository="owner/example"\n')
    (repo / "CHANGELOG.md").write_text("## [Unreleased]\n")
    assert "changelog-version" in codes(repo)
