"""Exercise README generation in temporary consumer repositories."""

import subprocess  # noqa: I001 -- repository convention keeps imports contiguous
import pytest
from martinpdes_maintenance.cli import main


@pytest.fixture
def project(tmp_path):
    """Create a consumer repository with only the required README inputs."""
    root = tmp_path / "consumer"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname="ScatterPy"\ndescription="Model light."\n'
    )
    (root / "readme.yml").write_text("introduction: Our *model*.\n")
    return root


def test_minimal_generation_and_check(project, monkeypatch):
    """Cover missing, current, and stale output through the default CLI root."""
    monkeypatch.chdir(project)
    output = project / "README.rst"
    assert main(["readme", "--check"]) == 1
    assert not output.exists()
    assert main(["readme"]) == 0
    expected = (
        b"ScatterPy\n=========\n\nModel light.\n\nOur *model*.\n\nInstallation\n------------\n\n"
        b".. code-block:: console\n\n   $ python -m pip install ScatterPy\n"
    )
    rendered = output.read_bytes()
    body, definitions = rendered.split(b"\n.. |mps-python| image::", 1)
    assert body.replace(b"|mps-python| |mps-pypi| |mps-downloads|\n\n", b"") == expected
    assert b"https://img.shields.io/pypi/pyversions/scatterpy.svg" in definitions
    assert b"https://img.shields.io/pypi/dm/scatterpy.svg" in definitions
    modified = output.stat().st_mtime_ns
    assert main(["readme", "--check"]) == 0
    assert output.stat().st_mtime_ns == modified
    assert main(["readme"]) == 0
    assert output.read_bytes() == rendered
    (project / "readme.yml").write_text("introduction: Updated.\n")
    assert main(["readme", "--check"]) == 1
    assert output.read_bytes() == rendered
    assert output.stat().st_mtime_ns == modified


def test_full_generation(project):
    """Preserve prose, order, literal template syntax, and Python indentation."""
    (project / "readme.yml").write_text("""introduction: |
  A *model*.

  Two paragraphs.
demo: https://example.org/demo
figure:
  path: figure.png
  caption: |
    First paragraph.

    Second paragraph.
quickstart: example.py
sections:
  - title: Citation
    content: |
      Cite {{ authors }}.
  - title: Data
    content: An archive.
""")
    (project / "figure.png").touch()
    (project / "example.py").write_text("if True:\n    raise RuntimeError('never execute')\n")
    assert main(["--root", str(project), "readme"]) == 0
    assert (
        (project / "README.rst").read_text().split("\n.. |mps-python| image::", 1)[0]
        == """ScatterPy
=========

|mps-python| |mps-pypi| |mps-downloads|

Model light.

A *model*.

Two paragraphs.

`Live demo <https://example.org/demo>`_

.. figure:: figure.png

   First paragraph.

   Second paragraph.

Installation
------------

.. code-block:: console

   $ python -m pip install ScatterPy

Quick start
-----------

.. code-block:: python

   if True:
       raise RuntimeError('never execute')

Citation
--------

Cite {{ authors }}.

Data
----

An archive.
"""
    )


@pytest.mark.parametrize(
    ("config", "field"),
    [
        ("[", "readme.yml"),
        ("[]", "readme.yml"),
        ("{}", "introduction"),
        ("introduction: 12", "introduction"),
        ("introduction: Test\nother: 1", "other"),
        ("introduction: Test\nfigure: {file: fig.png}", "file"),
        ("introduction: Test\nfigure: {}", "figure.path"),
        ("introduction: Test\nquickstart: missing.py", "missing.py"),
        ("introduction: Test\nsections: {}", "sections"),
        ("introduction: Test\nsections: [{title: Citation}]", "content"),
        ("introduction: Test\ndemo: []", "demo"),
    ],
)
def test_invalid_input_preserves_readme(project, capsys, config, field):
    """Identify the offending input and preserve existing output."""
    output = project / "README.rst"
    output.write_bytes(b"original")
    (project / "readme.yml").write_text(config)
    assert main(["--root", str(project), "readme"]) == 1
    assert field in capsys.readouterr().err
    assert output.read_bytes() == b"original"


@pytest.mark.parametrize("reference", ["../outside", "link"])
@pytest.mark.parametrize("setting", ["quickstart: ", "figure:\n  path: ", "logo: "])
def test_external_assets_rejected(project, reference, setting):
    """Reject traversal and symlinks resolving outside the repository."""
    outside = project.parent / "outside"
    outside.touch()
    (project / "link").symlink_to(outside)
    (project / "readme.yml").write_text(f"introduction: Test\n{setting}{reference}\n")
    output = project / "README.rst"
    output.write_bytes(b"preserve")
    assert main(["--root", str(project), "readme"]) == 1
    assert output.read_bytes() == b"preserve"


def test_conventional_branding(project):
    """Discover a logo and derive applicable links from local project metadata."""
    logo = project / "docs/images/logo.png"
    logo.parent.mkdir(parents=True)
    logo.touch()
    for path in (".github/workflows/deploy_coverage.yml", "conda.recipe/meta.yaml"):
        asset = project / path
        asset.parent.mkdir(parents=True)
        asset.touch()
    with (project / "pyproject.toml").open("a") as stream:
        stream.write(
            '[project.urls]\nRepository="https://github.com/MartinPdeS/other.git"\n'
            'Documentation="https://docs.example.org/"\n'
        )
    args = ["--root", str(project), "readme"]
    assert main(args) == 0
    output = (project / "README.rst").read_text()
    assert (
        ".. image:: https://raw.githubusercontent.com/MartinPdeS/other/HEAD/docs/images/logo.png"
        in output
    )
    assert ":target: https://docs.example.org/" in output
    assert "https://github.com/MartinPdeS/other/actions/workflows/deploy_coverage.yml" in output
    assert "https://anaconda.org/martinpdes/scatterpy/badges/version.svg" in output
    (project / "brand.svg").touch()
    with (project / "readme.yml").open("a") as stream:
        stream.write("logo: brand.svg\n")
    assert main(args + ["--check"]) == 1
    assert main(args) == 0
    assert (
        "https://raw.githubusercontent.com/MartinPdeS/other/HEAD/brand.svg"
        in (project / "README.rst").read_text()
    )
