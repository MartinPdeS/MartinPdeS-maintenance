"""Check the shared development-tool dependency groups."""

from pathlib import Path

from martinpdes_maintenance.cli import tomllib


def test_shared_tool_extras() -> None:
    """Keep the testing and quality tools available to consumer projects."""
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    extras = project["optional-dependencies"]

    assert set(extras["testing"]) <= set(extras["quality"])
    assert {"pytest>=8,<10", "pytest-cov>=5"} <= set(extras["testing"])
    assert {"mypy>=1.15", "numpydoc>=1.8", "ruff==0.17.2", "build>=1,<2"} <= set(extras["quality"])
    assert not any("pytest" in dependency for dependency in project["dependencies"])
