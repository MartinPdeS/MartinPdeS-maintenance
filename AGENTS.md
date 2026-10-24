# Working in martinpdes-maintenance

Read README.md and CONTRIBUTING.md before changing behavior. Inspect git status
and preserve user changes. Support Python 3.10+. Test release operations only in
temporary Git repositories. Never push, publish, or create release tags in real
consumer repositories without an explicit release request. Run pytest, Ruff, and
build validation for release-tool changes. Keep package-specific differences in
configuration. Do not introduce runtime imports of consumer packages.
