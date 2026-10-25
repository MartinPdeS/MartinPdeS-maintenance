"""Read-only checks for the shared repository maintenance conventions."""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

SCM = re.compile(r"setuptools[-_.]scm", re.IGNORECASE)
CLI = re.compile(
    r"\bmps-maintenance\b|\bpython[\d.]*\s+-m\s+martinpdes_maintenance\.cli\b|\$\(PYTHON\)\s+-m\s+martinpdes_maintenance\.cli\b"
)
WRAPPER = re.compile(r"tools/(?:check_release|next_release_version|release_tag)\.py")
SCRIPT = re.compile(r"(?:\$\(PYTHON\)|\bpython[\d.]*)\s+[\"']?((?:tools|scripts)/[\w./-]+\.py)")


@dataclass(frozen=True)
class Finding:
    """A diagnostic and an actionable correction, without changing the repository."""

    level: str
    code: str
    path: str
    message: str
    fix: str = ""


def _uses_tool(dependencies: list[str]) -> bool:
    return any(
        re.match(r"martinpdes[-_]maintenance(?:\b|\[)", item, re.IGNORECASE)
        for item in dependencies
    )


def _installs_tool(command: str, project: dict) -> bool:
    """Recognize explicit pip installs and local extras declaring the tool."""
    for line in command.splitlines():
        if not re.search(r"\bpip\s+install\b", line):
            continue
        if _uses_tool([token.strip("\"'") for token in line.split()]):
            return True
        if re.search(r"(?:^|\s)[\"']?\.(?:\[|[\"']?(?:\s|$))", line):
            metadata = project.get("project", {})
            if re.sub(r"[-_.]+", "-", metadata.get("name", "")).lower() == "martinpdes-maintenance":
                return True
            dependencies = list(metadata.get("dependencies", []))
            for extras in re.findall(r"\.\[([^\]]+)\]", line):
                for extra in extras.split(","):
                    dependencies.extend(
                        metadata.get("optional-dependencies", {}).get(extra.strip(), [])
                    )
            if _uses_tool(dependencies):
                return True
    return False


def inspect_repository(root: Path) -> list[Finding]:
    """Inspect metadata and literal maintenance commands without executing them.

    Parameters
    ----------
    root : pathlib.Path
        Repository root. Commands, consumer modules, and network requests are
        never executed. Only conventional root documentation and workflow files
        are inspected; this is a static check, not a complete CI interpreter.

    Returns
    -------
    list of Finding
        Errors, warnings, and successful checks in deterministic order.
    """
    from .cli import TAG, load, tomllib, versions

    root = root.resolve()
    findings: list[Finding] = []

    def add(level: str, code: str, path: str, message: str, fix: str = "") -> None:
        findings.append(Finding(level, code, path, message, fix))

    def read(path: Path) -> str | None:
        relative = str(path.relative_to(root))
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            add(
                "warning",
                "external-path",
                relative,
                "Skipped a symlink or external path.",
                "Use a regular file within the repository.",
            )
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            add(
                "error",
                "unreadable-file",
                relative,
                str(error),
                "Make this file readable UTF-8 text.",
            )
            return None

    text = read(root / "pyproject.toml")
    project = None
    if text is not None:
        try:
            project = tomllib.loads(text)
        except ValueError as error:
            add("error", "invalid-toml", "pyproject.toml", str(error), "Correct the TOML syntax.")
    if project is not None:
        metadata = project.get("project", {})
        tool = project.get("tool", {})
        build = project.get("build-system", {})
        extras = metadata.get("optional-dependencies", {}) if isinstance(metadata, dict) else None
        groups_valid = isinstance(extras, dict) and all(
            isinstance(deps, list) and all(isinstance(dep, str) for dep in deps)
            for deps in extras.values()
        )
        if not (
            isinstance(metadata, dict)
            and isinstance(tool, dict)
            and isinstance(build, dict)
            and groups_valid
            and isinstance(metadata.get("dependencies", []), list)
            and isinstance(build.get("requires", []), list)
            and all(
                isinstance(dep, str)
                for dep in metadata.get("dependencies", []) + build.get("requires", [])
            )
        ):
            add(
                "error",
                "invalid-project-metadata",
                "pyproject.toml",
                "Project, build, tool, or dependency settings have invalid types.",
                "Use TOML tables and string dependency arrays matching the project metadata schema.",
            )
            project = None
    if project is not None:
        metadata = project.get("project", {})
        expected = metadata.get("version")
        if (
            not isinstance(expected, str)
            or TAG.fullmatch("v" + expected) is None
            or "version" in metadata.get("dynamic", [])
        ):
            add(
                "error",
                "project-version",
                "pyproject.toml",
                "An explicit MAJOR.MINOR.PATCH version is required.",
                "Set [project].version and remove version from project.dynamic.",
            )
        else:
            add("ok", "project-version", "pyproject.toml", f"Explicit version {expected}.")
        groups = {
            "build-system.requires": project.get("build-system", {}).get("requires", []),
            "project.dependencies": metadata.get("dependencies", []),
        }
        groups.update(
            {
                f"project.optional-dependencies.{name}": deps
                for name, deps in metadata.get("optional-dependencies", {}).items()
            }
        )
        scm = [name for name, deps in groups.items() if any(SCM.search(dep) for dep in deps)]
        tool = project.get("tool", {})
        if (
            "setuptools_scm" in tool
            or "setuptools-scm" in tool
            or "setuptools_scm" in str(tool.get("scikit-build", {}))
        ):
            scm.append("tool configuration")
        if scm:
            add(
                "error",
                "scm-versioning",
                "pyproject.toml",
                "SCM versioning remains in " + ", ".join(scm) + ".",
                "Remove SCM dependencies/providers and use literal maintenance configuration.",
            )
        else:
            add("ok", "scm-versioning", "pyproject.toml", "No SCM dependencies or providers.")
        try:
            _, config = load(root)
            declared = versions(root, config)
            mismatches = [(path, value) for path, value in declared.items() if value != expected]
            for path, value in mismatches:
                add(
                    "error",
                    "version-mismatch",
                    path,
                    f"Declares {value}; project version is {expected}.",
                    "Align this file with the intended project version before releasing.",
                )
            if not mismatches:
                add(
                    "ok",
                    "release-metadata",
                    "pyproject.toml",
                    f"All {len(declared)} configured version declarations agree.",
                )
            if "changelog" in config:
                changelog = (root / config["changelog"]).read_text()
                if not re.search(
                    r"^## \[" + re.escape(str(expected)) + r"\]", changelog, re.MULTILINE
                ):
                    add(
                        "error",
                        "changelog-version",
                        config["changelog"],
                        f"Missing release section for {expected}.",
                        "Restore the release heading for the current project version.",
                    )
        except (ValueError, KeyError, TypeError, OSError) as error:
            add(
                "error",
                "release-configuration",
                "pyproject.toml",
                str(error),
                "Correct [tool.mps-maintenance] and its configured metadata files.",
            )

    def commands(text: str, path: str, level: str) -> None:
        if WRAPPER.search(text):
            add(
                level,
                "legacy-release-wrapper",
                path,
                "References a repository-local release wrapper.",
                "Call python -m martinpdes_maintenance.cli directly.",
            )
        for target in sorted(set(SCRIPT.findall(text))):
            if not (root / target).is_file():
                add(
                    level,
                    "missing-command-file",
                    path,
                    f"Command references missing file {target}.",
                    "Correct the command path or remove the obsolete command.",
                )
        for source in re.findall(
            r"\bsphinx\s+-(?:b|M)\s+\S+\s+(?:(?:-W|--keep-going|-E|-a|-n|-q)\s+)*([A-Za-z0-9_./][\w./-]*)",
            text,
        ):
            if not (root / source).is_dir():
                add(
                    level,
                    "missing-docs-source",
                    path,
                    f"Sphinx source directory {source} does not exist.",
                    "Correct the documentation source path.",
                )

    makefiles = [path for path in root.iterdir() if path.name.lower() == "makefile"]
    for path in sorted(makefiles):
        text = read(path)
        if text is None:
            continue
        commands(text, path.name, "error")
        if re.search(r"^(?:release|tag|release-check):", text, re.MULTILINE) and not CLI.search(
            text
        ):
            add(
                "warning",
                "release-command",
                path.name,
                "Release targets do not visibly invoke the installed maintenance CLI.",
                "Use $(PYTHON) -m martinpdes_maintenance.cli in release targets.",
            )
        elif CLI.search(text):
            add("ok", "release-command", path.name, "Calls the installed maintenance CLI.")
    for path in sorted(root.iterdir()):
        if path.is_file() and (path.name.startswith("README.") or path.name == "CONTRIBUTING.md"):
            text = read(path)
            if text is not None:
                commands(text, path.name, "warning")

    workflow_directory = root / ".github" / "workflows"
    for path in sorted(workflow_directory.glob("*")):
        if path.suffix not in {".yaml", ".yml"}:
            continue
        text = read(path)
        if text is None:
            continue
        relative = str(path.relative_to(root))
        try:
            workflow = yaml.safe_load(text)
            if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
                raise TypeError("Expected a workflow mapping with jobs")
        except (yaml.YAMLError, TypeError) as error:
            add(
                "error",
                "invalid-workflow",
                relative,
                str(error),
                "Correct the workflow YAML structure.",
            )
            continue
        for name, job in workflow["jobs"].items():
            if not isinstance(job, dict):
                add(
                    "error",
                    "invalid-workflow",
                    relative,
                    f"Job {name} must be a mapping.",
                    "Correct this job's YAML structure.",
                )
                continue
            inputs = job.get("with", {})
            if isinstance(inputs, dict):
                installation = str(inputs.get("install-command", inputs.get("install_command", "")))
                for key, value in inputs.items():
                    if "command" not in str(key) or not isinstance(value, str):
                        continue
                    commands(value, relative, "error")
                    # Each release-validation input executes independently of test setup.
                    prefix = "" if key == "release_validation_command" else installation
                    before = re.split(CLI, value, maxsplit=1)[0]
                    if CLI.search(value) and not _installs_tool(
                        prefix + "\n" + before, project or {}
                    ):
                        add(
                            "warning",
                            "ci-tool-install",
                            relative,
                            f"Job {name}, {key}: no recognized maintenance-tool install before use.",
                            "Install martinpdes-maintenance or a local extra declaring it; inspect reusable workflows if setup is inherited.",
                        )
            available = False
            for step in job.get("steps", []):
                if not isinstance(step, dict) or not isinstance(step.get("run"), str):
                    continue
                command = step["run"]
                commands(command, relative, "error")
                before = re.split(CLI, command, maxsplit=1)[0]
                if (
                    CLI.search(command)
                    and not available
                    and not _installs_tool(before, project or {})
                ):
                    add(
                        "warning",
                        "ci-tool-install",
                        relative,
                        f"Job {name}: no recognized maintenance-tool install before use.",
                        "Install the tool before this step. Conditional and composite-action setup needs manual verification.",
                    )
                # Conditional installs cannot guarantee availability to later steps.
                if not step.get("if") and _installs_tool(command, project or {}):
                    available = True
    return findings


def run_doctor(root: Path, *, json_output: bool = False, strict: bool = False) -> int:
    """Print diagnostics and return failure for errors or strict-mode warnings."""
    findings = inspect_repository(root)
    counts = {
        level: sum(item.level == level for item in findings) for level in ("ok", "warning", "error")
    }
    if json_output:
        print(
            json.dumps(
                {
                    "root": str(root),
                    "counts": counts,
                    "findings": [asdict(item) for item in findings],
                },
                indent=2,
            )
        )
    else:
        for item in findings:
            print(f"{item.level.upper():7} [{item.code}] {item.path}: {item.message}")
            if item.fix:
                print(f"        Fix: {item.fix}")
        print(
            f"Doctor: {counts['error']} errors, {counts['warning']} warnings, {counts['ok']} checks passed."
        )
    return int(bool(counts["error"] or (strict and counts["warning"])))
