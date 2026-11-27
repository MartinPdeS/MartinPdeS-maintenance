"""Generate a consumer README from repository-owned scientific content."""

import re  # noqa: I001 -- repository convention keeps imports contiguous
import tokenize
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit
import yaml
from jinja2 import Environment, StrictUndefined

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


class ReadmeError(ValueError):
    """Report a consumer configuration or README consistency error."""


def _mapping(*, value, field, allowed):
    """Require a YAML mapping with recognized keys."""
    if not isinstance(value, dict):
        raise ReadmeError(f"{field} must be a mapping")
    for key in value:
        if key not in allowed:
            raise ReadmeError(f"{field}: unknown field {key!r}")
    return value


def _text(*, value, field, single_line=False):
    """Validate a required string while retaining reStructuredText indentation."""
    if not isinstance(value, str) or not value.strip():
        raise ReadmeError(f"{field} must be a nonempty string")
    value = value.strip("\n")
    if single_line and len(value.splitlines()) != 1:
        raise ReadmeError(f"{field} must fit on one line")
    return value


def _file(*, root, value, field):
    """Resolve a repository-relative input to an existing regular file."""
    relative = Path(_text(value=value, field=field, single_line=True))
    try:
        path = (root / relative).resolve(strict=True)
    except (RuntimeError, OSError) as error:
        raise ReadmeError(f"{field}: cannot resolve {relative}: {error}") from error
    if relative.is_absolute() or not path.is_relative_to(root) or not path.is_file():
        raise ReadmeError(f"{field}: {relative} must name a file inside the repository")
    return path


def update_readme(*, root: Path, check: bool) -> None:
    """Render the shared template after validating all inputs.

    Parameters
    ----------
    root : Path
        Resolved consumer repository root.
    check : bool
        Compare the rendered bytes to README.rst without writing.

    Raises
    ------
    ReadmeError
        An input is invalid or the check detects missing or stale output.
    """
    metadata = _file(root=root, value="pyproject.toml", field="pyproject.toml")
    try:
        with metadata.open("rb") as stream:
            project = tomllib.load(stream).get("project")
    except tomllib.TOMLDecodeError as error:
        raise ReadmeError(f"pyproject.toml: {error}") from error
    if not isinstance(project, dict):
        raise ReadmeError("pyproject.toml requires a [project] table")
    name = _text(value=project.get("name"), field="[project].name", single_line=True)
    if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?", name):
        raise ReadmeError("[project].name must be a Python distribution name")
    description = _text(value=project.get("description"), field="[project].description")

    config_path = _file(root=root, value="readme.yml", field="readme.yml")
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ReadmeError(f"readme.yml: {error}") from error
    _mapping(
        value=config,
        field="readme.yml",
        allowed={"introduction", "demo", "figure", "quickstart", "sections"},
    )
    introduction = _text(value=config.get("introduction"), field="introduction")

    demo = None
    if "demo" in config:
        demo = _text(value=config["demo"], field="demo", single_line=True)
        url = urlsplit(demo)
        if url.scheme not in {"http", "https"} or not url.hostname or re.search(r"[\s<>`]", demo):
            raise ReadmeError("demo must be an HTTP(S) URL")

    figure = None
    if "figure" in config:
        settings = _mapping(value=config["figure"], field="figure", allowed={"path", "caption"})
        _file(root=root, value=settings.get("path"), field="figure.path")
        caption = (
            _text(value=settings["caption"], field="figure.caption")
            if "caption" in settings
            else None
        )
        figure = {"path": Path(settings["path"]).as_posix(), "caption": caption}

    quickstart = None
    if "quickstart" in config:
        example = _file(root=root, value=config["quickstart"], field="quickstart")
        try:
            with tokenize.open(example) as stream:
                quickstart = stream.read().removesuffix("\n")
        except (SyntaxError, UnicodeError) as error:
            raise ReadmeError(f"quickstart: cannot decode {example}: {error}") from error

    sections = config.get("sections", [])
    if not isinstance(sections, list):
        raise ReadmeError("sections must be a list")
    extra_sections = []
    for index, section in enumerate(sections):
        field = f"sections[{index}]"
        _mapping(value=section, field=field, allowed={"title", "content"})
        title = _text(value=section.get("title"), field=f"{field}.title", single_line=True)
        content = _text(value=section.get("content"), field=f"{field}.content")
        extra_sections.append({"title": title, "content": content})

    template = files(__package__).joinpath("readme.rst.j2").read_text(encoding="utf-8")
    environment = Environment(
        trim_blocks=True, undefined=StrictUndefined, keep_trailing_newline=True
    )
    rendered = (
        environment.from_string(template)
        .render(
            name=name,
            description=description,
            introduction=introduction,
            demo=demo,
            figure=figure,
            quickstart=quickstart,
            sections=extra_sections,
        )
        .encode("utf-8")
    )
    output = root / "README.rst"
    if output.is_symlink():
        raise ReadmeError("README.rst must not be a symlink")
    if output.is_file() and output.read_bytes() == rendered:
        return
    if check:
        raise ReadmeError("README.rst is missing or stale; run mps-maintenance readme")
    output.write_bytes(rendered)
