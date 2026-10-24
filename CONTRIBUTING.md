# Contributing

Keep release logic independent of scientific-package imports. Add regression tests
using temporary Git repositories for behavioral changes. Preserve explicitly
configured metadata and unrelated user work. Do not execute release commands in
consumer repositories while testing.

Install `.[dev,testing]` and run the checks in README.md. CI covers Python 3.10–3.14.

## Releasing this tool

Install this checkout in the release environment. The Makefile invokes its own
CLI against the explicit project metadata; there is no dependency on a published
copy of itself.
Update `[project].version`, run checks, build and inspect the wheel and sdist,
commit the reviewed change, and create a matching annotated tag. Pushing a `v*` tag triggers the same MPSActions build and PyPI publication
workflows used by MartinPdeS-docs. Configure the repository PYPI_API_TOKEN secret
before publishing. Ordinary branch pushes and pull requests build and test only.
Before the first publication, confirm distribution-name availability and metadata.
