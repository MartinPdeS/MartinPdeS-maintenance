"""Command-line release operations; publishing remains the caller's responsibility."""

import argparse
import difflib
import json
import re
import subprocess
import sys
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
    config = project.get("tool", {}).get("mps-maintenance")
    allowed = {
        "version-file",
        "version-method",
        "conda-recipe",
        "zenodo",
        "citation",
        "changelog",
        "repository",
    }
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError("Configure [tool.mps-maintenance]; unknown settings are not allowed")
    if config.get("version-method", "literal") != "literal":
        raise ValueError("Only explicit literal versioning is supported")
    for key in allowed - {"version-method", "repository"}:
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
    metadata = project["project"]
    if "version" in metadata.get("dynamic", []) or "version" not in metadata:
        raise ValueError("Declare an explicit [project].version; dynamic versioning is unsupported")
    if "changelog" in config and not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", config.get("repository", "")
    ):
        raise ValueError("changelog requires repository = 'owner/name'")
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
    if "changelog" in config:
        path = config["changelog"]
        updates[path] = update_changelog(
            (root / path).read_text(), version, release_date, config["repository"]
        )
    return updates


def update_changelog(text, version, release_date, repository):
    """Roll an Unreleased section into a dated release, preserving its entries."""
    if re.search(r"^## \[" + re.escape(version) + r"\]", text, re.MULTILINE):
        raise ValueError(f"Changelog already contains release {version}")
    text = replace(
        text,
        r"^## \[Unreleased\]$",
        lambda m: f"{m[0]}\n\n## [{version}] - {release_date}",
    )
    base = f"https://github.com/{repository}"
    return replace(
        text,
        r"^\[Unreleased\]:.*$",
        lambda m: (
            f"[Unreleased]: {base}/compare/v{version}...HEAD\n"
            f"[{version}]: {base}/releases/tag/v{version}"
        ),
    )


def main(argv=None):
    """Execute a release command and return a shell exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("next").add_argument("kind", choices=["major", "minor", "patch"])
    doctor = commands.add_parser(
        "doctor", help="Inspect repository maintenance conventions without changes"
    )
    doctor.add_argument("--json", action="store_true", dest="json_output")
    doctor.add_argument("--strict", action="store_true", help="Treat warnings as failures")
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
        if args.command == "doctor":
            from .doctor import run_doctor

            return run_doctor(root, json_output=args.json_output, strict=args.strict)
        if args.command == "next":
            tags = [
                tuple(map(int, m.groups()))
                for t in git(root, "tag", "--list").splitlines()
                if (m := TAG.fullmatch(t))
            ]
            if not tags:
                project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
                match = TAG.fullmatch("v" + project["version"])
                if match is None:
                    raise ValueError("Project version must use MAJOR.MINOR.PATCH")
                tags = [tuple(map(int, match.groups()))]
            numbers = list(max(tags))
            index = ["major", "minor", "patch"].index(args.kind)
            numbers[index] += 1
            numbers[index + 1 :] = [0] * (2 - index)
            print("v" + ".".join(map(str, numbers)))
            return 0
        _, config = load(root)
        if args.command == "check":
            declared = versions(root, config)
            expected = (
                args.version or declared.get("pyproject.toml") or declared[config["version-file"]]
            ).removeprefix("v")
            for path, value in declared.items():
                print(f"{'OK' if value == expected else 'MISMATCH'} {path}: {value}")
            failed = False
            for path, value in declared.items():
                if value != expected:
                    print(f"{path} declares {value}; expected {expected}", file=sys.stderr)
                    failed = True
            if "changelog" in config:
                text = (root / config["changelog"]).read_text()
                if not re.search(r"^## \[" + re.escape(expected) + r"\]", text, re.MULTILINE):
                    print(f"Changelog has no release section for {expected}", file=sys.stderr)
                    failed = True
            return int(failed)
        match = TAG.fullmatch(args.tag)
        if not match:
            raise ValueError("Tag must use vMAJOR.MINOR.PATCH")
        date.fromisoformat(args.date)
        if git(root, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError("working tree is not clean")
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
