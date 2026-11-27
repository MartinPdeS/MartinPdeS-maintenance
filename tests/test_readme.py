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
    title, content = body.split(b".. list-table::", 1)
    assert title + content.split(b"|mps-downloads|\n\n", 1)[1] == expected
    assert b"|mps-demo|" not in rendered
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
    rendered = (project / "README.rst").read_text()
    assert ":alt: Launch ScatterPy\n   :target: https://example.org/demo" in rendered
    assert (
        rendered.split("\n.. |mps-python| image::", 1)[0]
        == """ScatterPy
=========

.. list-table::
   :width: 100%
   :widths: 35 65
   :header-rows: 1

   * - Badge
     - Status
   * - Web app
     - |mps-demo|
   * - Python versions
     - |mps-python|
   * - PyPI
     - |mps-pypi| |mps-downloads|

Model light.

A *model*.

Two paragraphs.

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
        ("introduction: Test\nquickstart: {title: Fit}", "quickstart.source"),
        (
            "introduction: Test\nquickstart: {source: readme.yml, figure: {}}",
            "quickstart.figure.path",
        ),
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
@pytest.mark.parametrize(
    "setting",
    [
        "quickstart: ",
        "figure:\n  path: ",
        "logo: ",
        "quickstart:\n  source: readme.yml\n  figure:\n    path: ",
    ],
)
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
    (project / "conda.recipe/meta.yaml").write_text(
        "package:\n  name: scatter-conda\n  version: {{ version }}\n"
    )
    with (project / "pyproject.toml").open("a") as stream:
        stream.write(
            'requires-python=">=3.11,<3.15"\n[project.urls]\nRepository="https://github.com/MartinPdeS/other.git"\n'
            'Documentation="https://docs.example.org/"\n'
        )
    args = ["--root", str(project), "readme"]
    assert main(args) == 0
    output = (project / "README.rst").read_text()
    assert (
        ".. image:: https://raw.githubusercontent.com/MartinPdeS/other/HEAD/docs/images/logo.png"
        in output
    )
    assert (
        "Documentation\n-------------\n\nUse the `ScatterPy documentation <https://docs.example.org/>`__ to work through"
        in output
    )
    assert ":target: https://docs.example.org/" in output
    assert "   * - Coverage\n     - |mps-coverage|" in output
    assert "|mps-ci|" not in output
    workflow = project / ".github/workflows/tests.yaml"
    workflow.touch()
    assert main(args) == 0
    output = (project / "README.rst").read_text()
    assert "   * - Tests\n     - |mps-ci| |mps-coverage|" in output
    assert ":target: https://github.com/MartinPdeS/other/actions/workflows/tests.yaml" in output
    (workflow.parent / "deploy_coverage.yml").unlink()
    assert main(args) == 0
    output = (project / "README.rst").read_text()
    assert "   * - Tests\n     - |mps-ci|\n" in output and "|mps-coverage|" not in output
    assert "|mps-conda| |mps-conda-downloads| |mps-conda-release|" in output
    assert "https://anaconda.org/martinpdes/scatter-conda/badges/version.svg" in output
    assert "Requires Python ``>=3.11,<3.15``" in output
    assert "$ conda install -c martinpdes scatter-conda" in output
    assert "$ git clone https://github.com/MartinPdeS/other.git\n   $ cd other\n" in output
    assert "$ python -m pip install -e ." in output
    (project / "brand.svg").touch()
    with (project / "readme.yml").open("a") as stream:
        stream.write("logo: brand.svg\n")
    assert main(args + ["--check"]) == 1
    assert main(args) == 0
    assert (
        "https://raw.githubusercontent.com/MartinPdeS/other/HEAD/brand.svg"
        in (project / "README.rst").read_text()
    )


def test_templated_conda_name_is_not_guessed(project):
    """Keep the source option while omitting Conda for a nonliteral package name."""
    recipe = project / "conda.recipe/meta.yaml"
    recipe.parent.mkdir()
    recipe.write_text("package:\n  name: {{ name }}\n")
    with (project / "pyproject.toml").open("a") as stream:
        stream.write('[project.urls]\nSource="https://github.com/MartinPdeS/checkout"\n')
    assert main(["--root", str(project), "readme"]) == 0
    output = (project / "README.rst").read_text()
    assert "conda install" not in output and "|mps-conda|" not in output
    assert "$ cd checkout" in output


def test_custom_documentation_takes_precedence(project):
    """Preserve a project's existing documentation content and section order."""
    with (project / "pyproject.toml").open("a") as stream:
        stream.write('[project.urls]\nDocumentation="https://docs.example.org/"\n')
    with (project / "readme.yml").open("a") as stream:
        stream.write(
            "sections:\n  - title: Citation\n    content: Cite us.\n"
            "  - title: DOCUMENTATION\n    content: Start with the tutorial.\n"
        )
    assert main(["--root", str(project), "readme"]) == 0
    output = (project / "README.rst").read_text()
    assert output.lower().count("\ndocumentation\n-------------\n") == 1
    assert output.index("Cite us.") < output.index("Start with the tutorial.")
    assert ":target: https://docs.example.org/" in output


def test_contact_metadata_and_override(project):
    """Prefer maintainers, retain ordering, and respect a custom Contact section."""
    metadata = project / "pyproject.toml"
    with metadata.open("a") as stream:
        stream.write('authors=[{name="Author",email="author@example.org"}]\n')
    args = ["--root", str(project), "readme"]
    assert main(args) == 0
    output = project / "README.rst"
    assert (
        "For questions, contact `Author <mailto:author@example.org?subject=ScatterPy>`__"
        in output.read_text()
    )
    with metadata.open("a") as stream:
        stream.write(
            'maintainers=[{name="The team"}, {email="support@example.org"}]\n'
            '[project.urls]\nContact="https://example.org/team"\n'
        )
    assert main(args + ["--check"]) == 1
    assert main(args) == 0
    rendered = output.read_text()
    assert (
        "For questions, contact The team or `support@example.org <mailto:support@example.org?subject=ScatterPy>`__"
        in rendered
    )
    assert "https://example.org/team" in rendered and "author@example.org" not in rendered
    with (project / "readme.yml").open("a") as stream:
        stream.write("sections:\n  - title: CONTACT\n    content: Use our issue tracker.\n")
    assert main(args) == 0
    rendered = output.read_text()
    assert rendered.lower().count("\ncontact\n-------\n") == 1
    assert "Use our issue tracker." in rendered and "mailto:" not in rendered


def test_contributing_guide_discovery_and_override(project):
    """Use an existing guide, prefer the root, and preserve custom instructions."""
    guide = project / "docs/CONTRIBUTING.rst"
    guide.parent.mkdir()
    guide.touch()
    args = ["--root", str(project), "readme"]
    output = project / "README.rst"
    assert main(args) == 0
    assert "<docs/CONTRIBUTING.rst>" in output.read_text()
    (project / "CONTRIBUTING.md").touch()
    with (project / "pyproject.toml").open("a") as stream:
        stream.write('[project.urls]\nRepository="https://github.com/example/repository.git"\n')
    assert main(args + ["--check"]) == 1
    assert main(args) == 0
    assert "<https://github.com/example/repository/blob/HEAD/CONTRIBUTING.md>" in output.read_text()
    with (project / "readme.yml").open("a") as stream:
        stream.write("sections:\n  - title: CONTRIBUTING\n    content: Send patches by email.\n")
    assert main(args) == 0
    rendered = output.read_text()
    assert rendered.lower().count("\ncontributing\n------------\n") == 1
    assert "Send patches by email." in rendered and "blob/HEAD/CONTRIBUTING.md" not in rendered


def test_citation_and_license_from_metadata(project):
    """Generate a real Zenodo badge and preserve license expressions and local notes."""
    (project / "CITATION.cff").write_text("doi: 10.5281/zenodo.12345\n")
    with (project / "pyproject.toml").open("a") as stream:
        stream.write('license="MIT OR Apache-2.0"\n')
    (project / "LICENSE").touch()
    with (project / "readme.yml").open("a") as stream:
        stream.write("license_note: Contact us about support.\n")
    args = ["--root", str(project), "readme"]
    output = project / "README.rst"
    assert main(args) == 0
    text = output.read_text()
    assert "   * - Zenodo DOI\n     - |mps-zenodo|" in text
    assert text.count("https://zenodo.org/badge/DOI/10.5281/zenodo.12345.svg") == 1
    assert "licensed under `MIT OR Apache-2.0 <LICENSE>`__." in text
    assert "Contact us about support." in text
    (project / "CITATION.cff").write_text("doi: 10.1364/EXAMPLE.12345\n")
    assert main(args + ["--check"]) == 1
    assert main(args) == 0
    assert "zenodo.org" not in output.read_text()
    (project / ".zenodo.json").write_text('{"doi":"10.5281/zenodo.6789"}')
    assert main(args) == 0
    assert "https://doi.org/10.5281/zenodo.6789" in output.read_text()
    with (project / "readme.yml").open("a") as stream:
        stream.write(
            "sections:\n  - title: Citation\n    content: Cite the paper.\n"
            "  - title: LICENSE\n    content: Special terms.\n"
        )
    assert main(args) == 0
    text = output.read_text()
    assert "Cite the paper." in text and "Special terms." in text
    assert "zenodo.org" not in text and "MIT OR Apache-2.0" not in text


def test_zenodo_record_url_and_legacy_license_file(project):
    """Read explicit record and license paths even when their filenames differ."""
    (project / "terms.txt").touch()
    with (project / "pyproject.toml").open("a") as stream:
        stream.write(
            'license={file="terms.txt"}\n[project.urls]\nZenodo="https://zenodo.org/records/42"\n'
        )
    assert main(["--root", str(project), "readme"]) == 0
    text = (project / "README.rst").read_text()
    assert "https://doi.org/10.5281/zenodo.42" in text
    assert "<terms.txt>" in text


def test_illustrated_quickstart(project):
    """Keep the worked example, literal code and caption together before extra sections."""
    (project / "readme.yml").write_text("""introduction: Intro.
quickstart:
  title: Calibration fit
  description: Fit *four* measurements.
  source: fit.py
  figure:
    path: fit.png
    caption: |
      Measured peaks.

      Line of best fit.
sections:
  - title: Data
    content: Sample data.
""")
    (project / "fit.py").write_text("if True:\n    raise RuntimeError('never execute')\n")
    (project / "fit.png").touch()
    args = ["--root", str(project), "readme"]
    assert main(args) == 0
    output = project / "README.rst"
    rendered = output.read_text()
    assert (
        """Calibration fit
---------------

Fit *four* measurements.

.. code-block:: python

   if True:
       raise RuntimeError('never execute')

.. figure:: fit.png

   Measured peaks.

   Line of best fit.

Data
----"""
        in rendered
    )
    assert main(args + ["--check"]) == 0
    (project / "fit.png").unlink()
    assert main(args) == 1
    assert output.read_text() == rendered


def test_github_figure_urls(project):
    """Use portable, encoded default-branch URLs for both validated figure paths."""
    (project / "result plot.png").touch()
    (project / "measure.py").write_text("print(1)\n")
    with (project / "pyproject.toml").open("a") as stream:
        stream.write('[project.urls]\nRepository="https://github.com/example/fibers"\n')
    with (project / "readme.yml").open("a") as stream:
        stream.write(
            "figure: {path: result plot.png}\nquickstart:\n  source: measure.py\n"
            "  figure: {path: result plot.png}\n"
        )
    assert main(["--root", str(project), "readme"]) == 0
    output = (project / "README.rst").read_text()
    assert (
        output.count(
            ".. figure:: https://raw.githubusercontent.com/example/fibers/HEAD/result%20plot.png"
        )
        == 2
    )
