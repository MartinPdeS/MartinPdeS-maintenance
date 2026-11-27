# martinpdes-maintenance

One release method for the MartinPdeS Python ecosystem: explicit project versions,
updated by a shared command. Python 3.10+; flat package layout.

## Install

```sh
python -m pip install "martinpdes-maintenance==0.2.3"
# Development checkout:
python -m pip install -e ".[dev,testing]"
```

This is a release-development dependency, never a consumer runtime dependency.

## Shared development tools

The optional `testing` extra supplies pytest and coverage; the `quality` extra
also supplies mypy, numpydoc, Ruff, and the Python build frontend. Projects can
select these extras in their own development dependencies as follows:

```toml
[project.optional-dependencies]
testing = ["martinpdes-maintenance[testing]==0.2.3"]
dev = ["martinpdes-maintenance[quality]==0.2.3"]
```

These extras install tools;
projects keep their own tool configuration and any additional test dependencies.
The base maintenance package stays lightweight for release operations.

## Configuration

Declare a static `[project].version` and add a configuration table:

```toml
[tool.mps-maintenance]
version-file = "DeepPeak/_version.py"
version-method = "literal"
conda-recipe = "conda.recipe/meta.yaml"
```

`version-file` updates a `__version__ = version = "X.Y.Z"` assignment. Optional
`zenodo = ".zenodo.json"` updates version and publication date;
`citation = "CITATION.cff"` updates its existing version field, preserving dates.
All configured files must exist inside the repository. Unknown keys are errors.
Conda recipe versions must be literal. Dynamic project versions are unsupported.
A project with only distribution metadata can use an empty `[tool.mps-maintenance]`.

For Keep a Changelog release preparation, configure:

```toml
changelog = "CHANGELOG.md"
repository = "MartinPdeS/PyFiberModes"
```

The changelog must have one `## [Unreleased]` heading and one `[Unreleased]:`
comparison link. Releasing moves its entries under a dated version heading and
updates the comparison and release links. Checks require a section for the
current project version.

## Commands

Run at the repository root, or put `--root /path/to/repository` before the command:

```sh
mps-maintenance doctor
mps-maintenance check
mps-maintenance check --version v1.2.3
mps-maintenance next patch
mps-maintenance tag v1.2.4 --dry-run
```

`next` increments the highest stable semantic tag, including unreachable tags.
If there are no stable tags, it increments the explicit project version. Fetch
remote tags first; unrelated and prerelease tags are ignored. This selects a
release number; build versions always come from explicit project metadata.

`tag` requires a clean, full checkout and an unused `vMAJOR.MINOR.PATCH` tag.
It plans all replacements before writing, prints a diff, validates updated
metadata, stages only configured files, commits, and creates an annotated tag.
`--dry-run` changes no repository files, commits, index entries, or tags.
`--date YYYY-MM-DD` controls Zenodo and changelog dates; the default is the local
calendar date. Prerelease creation is unsupported. Nothing is pushed.

On write/validation failure original files are restored. A commit or tag failure
leaves recoverable state: inspect `git status` and `git log -1` before retrying.
A failed tag operation can leave a successful release commit. Never blindly reset
unrelated work.

## Shared README generator

In a consumer repository, put the distribution name and short description in
`[project].name` and `[project].description` in `pyproject.toml`. Keep the
scientific content in a UTF-8 `readme.yml` alongside it. README generation works
independently of the release settings and project version.

```yaml
introduction: |
  Explain the scientific problem this package solves.

  Describe what the reader will reproduce in the example below.
demo: https://example.org/demo
figure:
  path: docs/images/scattering-efficiency.png
  caption: Scattering efficiency as a function of particle diameter.
quickstart: examples/scattering_efficiency.py
sections:
  - title: Citation
    content: |
      Explain how to cite this work.
```

For source-only projects, set `pypi: false` to omit PyPI badges and the PyPI install command.
Set `conda: false` for a recipe that has not been published to the channel.
A custom Installation section can supply project-specific build instructions.

The header uses the distribution name for the Python versions, PyPI release and
monthly download badges. All generated badges appear in a two-column Badge/Status
table beneath the logo, with related test, PyPI, and Conda badges grouped by row. Logo discovery tries `<project name>/assets/logo/logo_light.svg`,
then `logo.svg` and `logo.png` in `docs/images` and `docs/source/_static`, in
that order. Set `logo: path/to/brand.svg` to override discovery. The optional
`figure` remains available for a scientific illustration.

For GitHub repositories, the logo and figures use raw image URLs on the default
branch so they also display on PyPI. Commit the referenced images to that branch. Both the documentation badge and the Documentation section use
`[project.urls].Documentation`. The section follows the quick start. An explicit
Documentation section in `readme.yml` takes precedence and keeps its position.
The Contact section lists `[project].maintainers`, falling back to `authors`.
Names with an email address link directly to an email draft. An optional
`[project.urls].Contact` adds a contact page. With no contact metadata the
section is omitted. A custom Contact section keeps its content and position.

The Contributing section links to the first `CONTRIBUTING.md` or
`CONTRIBUTING.rst` found in the repository root, `.github/`, or `docs/`, in
that order. GitHub projects get a link to the guide on their default branch.
A custom Contributing section takes precedence. Without a guide or custom
section, the heading is omitted.

The Citation section uses the first recognized Zenodo record URL or DOI from
`[project.urls].Zenodo`, the top-level `doi` in `CITATION.cff`, or the `doi` in
`.zenodo.json`. It links the DOI badge and citation to the record. Unrelated
publication DOIs do not produce Zenodo badges.

The License section displays the license expression in `[project].license`
and links the declared license file or a conventional root `LICENSE`,
`LICENSE.md`, `LICENSE.txt`, or `COPYING`. Use optional `license_note` prose
in `readme.yml` for project-specific terms. Explicit Citation and License
sections take precedence.

For a GitHub repository, the test badge links to the first existing workflow named
`tests.yml`, `tests.yaml`, `test.yml`, `test.yaml`, `unit-tests.yml`, or `unit-tests.yaml` in `.github/workflows/`.
A separate coverage badge is enabled by `deploy_coverage.yml`. MartinPdeS repositories with
`conda.recipe/meta.yaml` or a root `meta.yaml` receive channel badges and an install command for the literal
`package.name` in the recipe. Recipes with unresolved names omit the Conda block.

The Installation section uses `[project].requires-python` when declared and
`[project].name` for the pip command. A recognized GitHub repository URL adds
clone and editable-install commands. Keep deployment details in project-owned sections. Generation uses local metadata and files, including in check mode.

Only `introduction` is required. Prose fields accept reStructuredText, including
multiple paragraphs in YAML literal blocks (`|`). Use an HTTP(S) URL for
`demo` to add a launch badge in the first row of the table. A figure requires a `path` and can include a `caption`. Figure and
quick-start paths are relative to the repository root and must resolve to files
inside it. The generator embeds the Python example as source without running it.
To show an example and its result together, use the mapping form of `quickstart`.
Only `source` is required. The optional figure appears directly below the code.
Commit the image alongside the script; the generator reads both paths locally
and never runs the example. The short `quickstart: examples/example.py` form
still works.

```yaml
quickstart:
  title: Fit a fluorescence calibration
  description: Fit measured bead peaks to their reference intensities.
  source: examples/fluorescence_calibration.py
  figure:
    path: docs/images/fluorescence-calibration.png
    caption: Measured peaks and the fitted calibration curve.
```

Each extra section has a single-line `title` and prose `content`, in list order.

```sh
mps-maintenance readme
git diff -- README.rst
mps-maintenance readme --check
```

Review and commit `README.rst` with its inputs. In CI, `--check` compares the
working copy byte-for-byte and exits nonzero for missing or stale output. Both
modes accept a repository root, e.g. `mps-maintenance --root ../project readme --check`.
Consumer projects can add this shortcut to their shared Makefile:

```make
.PHONY: readme
readme:
	mps-maintenance readme
```

To change headings or section order for all projects, edit the packaged
reStructuredText template in `martinpdes_maintenance/readme.rst.j2`.

## Repository doctor

```sh
mps-maintenance doctor
mps-maintenance --root /path/to/project doctor --json
mps-maintenance doctor --strict
```

Doctor is read-only and works with uncommitted changes. It checks explicit
project versions, every configured release-version declaration, changelog release
headings, SCM dependencies/providers, obsolete release wrappers, literal script
and Sphinx source paths in Makefiles and root README/CONTRIBUTING files, and
maintenance-tool installation before visible GitHub Actions commands.

Each finding includes a stable diagnostic code, file path, and suggested fix.
Errors return exit status 1; warnings return 0 unless `--strict` is used. `--json`
returns counts and structured findings for automation. A healthy report returns 0.

CI analysis recognizes explicit pip installs and local extras declaring the tool.
It cannot interpret reusable workflow internals, composite actions, arbitrary
shell control flow, dynamic paths, or the dependency graph of every CI tool.
Unconfirmed installation produces a warning, not a claim that CI is broken.
Doctor does not execute project commands, import consumer packages, contact
services, install dependencies, or rewrite files.

## Development

```sh
python -m pytest
python -m ruff check martinpdes_maintenance tests
python -m ruff format --check martinpdes_maintenance tests
python -m build
python -m twine check dist/*
```

Tests use temporary local Git repositories and never publish. Consumer Makefile
shortcuts call the installed module directly; no local release scripts are
needed. Native build, scientific test, and registry publishing logic remains
outside it.
