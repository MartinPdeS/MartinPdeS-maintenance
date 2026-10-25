# martinpdes-maintenance

One release method for the MartinPdeS Python ecosystem: explicit project versions,
updated by a shared command. Python 3.10+; flat package layout.

## Install

```sh
python -m pip install "martinpdes-maintenance==0.2.2"
# Development checkout:
python -m pip install -e ".[dev,testing]"
```

This is a release-development dependency, never a consumer runtime dependency.

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
