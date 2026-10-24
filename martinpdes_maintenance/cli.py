"""Command-line release operations; publishing remains the caller's responsibility."""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

TAG = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def git(root, *args):
    """Run Git in the explicit repository and return its output."""
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def load(root):
    """Load project metadata and validate explicitly configured release paths."""
    project = tomllib.loads((root / "pyproject.toml").read_text())
    config = project.get("tool", {}).get("mps-maintenance", {})
    allowed = {"version-file", "version-method", "conda-recipe", "zenodo", "citation"}
    if not config or set(config) - allowed:
        raise ValueError("Configure [tool.mps-maintenance]; unknown settings are not allowed")
    if config.get("version-method", "literal") not in {"literal", "setuptools-scm"}:
        raise ValueError("version-method must be literal or setuptools-scm")
    for key in allowed - {"version-method"}:
        if key not in config:
            continue
        value = config[key]
        if not isinstance(value, str) or not value:
            raise ValueError(f"{key} must be a nonempty relative path")
        path = root / value
        if Path(value).is_absolute() or not path.resolve().is_relative_to(root):
            raise ValueError(f"{key} must stay within the repository")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"{key} must name an existing regular file")
    if "version-method" in config and "version-file" not in config:
        raise ValueError("version-method requires version-file")
    return project, config


def replace(text, pattern, replacement):
    """Require exactly one matching metadata field."""
    if len(list(re.finditer(pattern, text, re.MULTILINE))) != 1:
        raise ValueError(f"Expected exactly one field matching {pattern}")
    return re.sub(pattern, replacement, text, flags=re.MULTILINE)


def fields(root, config):
    """Return configured version fields and their regular expressions."""
    result = {"pyproject.toml": r'(?m)(^version\s*=\s*)["\']([^"\']+)["\']'}
    for key, pattern in {
        "version-file": r'(^__version__\s*=\s*version\s*=\s*)["\']([^"\']+)["\']',
        "conda-recipe": r'(^[ \t]*version:[ \t]*)["\']?([^\s"\'#]+)["\']?',
        "citation": r'(^version:[ \t]*)["\']?([^\s"\'#]+)["\']?',
    }.items():
        if key in config:
            result[config[key]] = pattern
    return result


def versions(root, config):
    """Read every configured version, failing on missing or ambiguous fields."""
    result = {}
    for path, pattern in fields(root, config).items():
        if path == "pyproject.toml":
            result[path] = str(tomllib.loads((root / path).read_text())["project"]["version"])
            continue
        matches = list(re.finditer(pattern, (root / path).read_text(), re.MULTILINE))
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one version in {path}")
        result[path] = matches[0].group(2)
    if "zenodo" in config:
        result[config["zenodo"]] = json.loads((root / config["zenodo"]).read_text())["version"]
    return result


def plan(root, config, version, release_date):
    """Prepare all new file contents before writing any release metadata."""
    versions(root, config)
    updates = {}
    for path, pattern in fields(root, config).items():
        text = (root / path).read_text()
        if path == "pyproject.toml":
            # Restrict replacement to the project table, never a tool's version setting.
            table = re.search(r"(?ms)^\[project\][ \t]*\n.*?(?=^\[|\Z)", text)
            if table is None:
                raise ValueError("Missing [project] table")
            section = replace(table[0], pattern, lambda m: m[1] + json.dumps(version))
            updates[path] = text[: table.start()] + section + text[table.end() :]
        else:
            updates[path] = replace(text, pattern, lambda m: m[1] + json.dumps(version))
    if "zenodo" in config:
        path = config["zenodo"]
        data = json.loads((root / path).read_text())
        data.update(version=version, publication_date=release_date)
        updates[path] = json.dumps(data, indent=2) + "\n"
    if config.get("version-method") == "setuptools-scm":
        # Generate into a temporary destination, keeping planning read-only for the repository.
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "_version.py"
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from setuptools_scm import get_version; "
                        "import sys; get_version(root=sys.argv[1], write_to=sys.argv[2], "
                        "version_scheme='only-version', local_scheme='no-local-version')"
                    ),
                    str(Path(directory).resolve()),
                    str(destination.resolve()),
                ],
                check=True,
                capture_output=True,
                text=True,
                env={**os.environ, "SETUPTOOLS_SCM_PRETEND_VERSION": version},
            )
            updates[config["version-file"]] = destination.read_text()
    return updates


def main(argv=None):
    """Execute a release command and return a shell exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("next").add_argument("kind", choices=["major", "minor", "patch"])
    check = commands.add_parser("check")
    check.add_argument("--version")
    tag = commands.add_parser("tag")
    tag.add_argument("tag")
    tag.add_argument("--dry-run", action="store_true")
    tag.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root:
            raise ValueError("--root must be the Git repository root")
        if args.command == "next":
            tags = [
                tuple(map(int, m.groups()))
                for t in git(root, "tag", "--list").splitlines()
                if (m := TAG.fullmatch(t))
            ]
            if not tags:
                raise ValueError("No stable semantic-version tag found")
            numbers = list(max(tags))
            index = ["major", "minor", "patch"].index(args.kind)
            numbers[index] += 1
            numbers[index + 1 :] = [0] * (2 - index)
            print("v" + ".".join(map(str, numbers)))
            return 0
        _, config = load(root)
        if args.command == "check":
            declared = versions(root, config)
            expected = (args.version or declared["pyproject.toml"]).removeprefix("v")
            for path, value in declared.items():
                print(f"{'OK' if value == expected else 'MISMATCH'} {path}: {value}")
            return int(any(value != expected for value in declared.values()))
        match = TAG.fullmatch(args.tag)
        if not match:
            raise ValueError("Tag must use vMAJOR.MINOR.PATCH")
        date.fromisoformat(args.date)
        if git(root, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError("Working tree must be clean")
        if git(root, "tag", "--list", args.tag):
            raise ValueError("Tag already exists")
        if git(root, "rev-parse", "--is-shallow-repository") == "true":
            raise ValueError("Release creation requires a full clone")
        updates = plan(root, config, args.tag[1:], args.date)
        for path, text in updates.items():
            print(
                "".join(
                    difflib.unified_diff(
                        (root / path).read_text().splitlines(True),
                        text.splitlines(True),
                        fromfile=path,
                        tofile=path,
                    )
                ),
                end="",
            )
        if args.dry_run:
            return 0
        originals = {path: (root / path).read_bytes() for path in updates}
        try:
            for path, text in updates.items():
                (root / path).write_text(text)
            if any(v != args.tag[1:] for v in versions(root, config).values()):
                raise ValueError("Updated metadata failed validation")
        except Exception:
            for path, content in originals.items():
                (root / path).write_bytes(content)
            raise
        git(root, "add", "--", *updates)
        git(root, "commit", "-m", f"Release {args.tag}")
        git(root, "tag", "-a", args.tag, "-m", f"Release {args.tag}")
        print(f"Created {args.tag}; nothing was pushed.")
        return 0
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f"Release operation failed: {error}", file=sys.stderr)
        print(
            "Inspect git status and git log before retrying a failed tag operation.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
