# martinpdes-maintenance

Shared release preparation for the MartinPdeS scientific Python ecosystem.
The distribution is `martinpdes-maintenance`; its command is `mps-maintenance`.
Python 3.10 and newer are supported. The Python package lives directly in
`martinpdes_maintenance/`, following the flat layout used by MartinPdeS-docs.

## Install

From a source checkout:

```sh
python -m pip install -e ".[dev,scm]"
```

This repository has not yet been published on PyPI. After publication, consumers
can pin a reviewed version in their release development extra. The tool is not
a runtime dependency of scientific packages.

## Configure a consuming project

Add explicit settings to the consumer's `pyproject.toml`:

```toml
[tool.mps-maintenance]
version-file = "DeepPeak/_version.py"
version-method = "setuptools-scm"
conda-recipe = "conda.recipe/meta.yaml"
```

Use `version-method = "literal"` (the default) to update a simple
`__version__ = version = "X.Y.Z"` assignment directly. SCM mode requires this
tool's `scm` extra and generates the file using setuptools-scm. Optional settings:

```toml
zenodo = ".zenodo.json"
citation = "CITATION.cff"
```

All configured files must already exist inside the repository. Unknown settings
are errors. Project versions must be static in `[project].version`; Conda recipes
must contain one literal `version:` field. Jinja-templated recipe versions and
prerelease creation are not supported in this initial implementation. Citation
updates currently change the version only, preserving existing date behavior.

## Commands

Run from the consumer repository root, or supply `--root /path/to/repository`
before the subcommand:

```sh
mps-maintenance check
mps-maintenance check --version v1.2.3
mps-maintenance next patch
mps-maintenance tag v1.2.4 --dry-run
```

`next` selects the highest stable `vMAJOR.MINOR.PATCH` tag available locally,
including tags not reachable from HEAD. It ignores prerelease and unrelated tags;
fetch tags first when remote releases may be missing. It fails if no stable tag exists.

`tag` requires a clean, full Git checkout and an unused stable tag. It calculates
all replacements before writing, prints a diff, validates updated versions,
stages the release files, commits, then creates an annotated tag. `--dry-run`
prints the plan without writing repository files, staging, committing, or tagging.
Zenodo publication dates default to the local calendar date; `--date YYYY-MM-DD`
sets a reproducible date explicitly.

To actually create the release commit and tag, omit `--dry-run`. Nothing is
pushed. Existing Makefile push behavior should remain in the consumer repository.
A commit or tag failure leaves state for inspection: use `git status` and
`git log -1`, fix the cause, and recover explicitly. A tag failure can leave a
successful release commit. Do not blindly rerun or reset unrelated work.

## Migration

1. Install a reviewed tool revision in the release environment.
2. Configure every file the old scripts check or update.
3. Compare `check`, `next`, and dry-run output with the old scripts.
4. Replace old script bodies with thin CLI wrappers, preserving Makefile behavior.
5. Verify in a disposable clone before removing compatibility wrappers.

DeepPeak uses SCM generation; PyMieSim and PackLab additionally update Zenodo;
BornSim uses literal generation plus Zenodo and Citation metadata. No consumer
repositories are migrated automatically.

## Development

```sh
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m build
python -m twine check dist/*
```

Tests create local temporary Git repositories and never push or publish.
See CONTRIBUTING.md for release bootstrapping.
