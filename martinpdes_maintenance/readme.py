"""Generate a consumer README from repository-owned scientific content."""

import json  # noqa: I001 -- repository convention keeps imports contiguous
import re
import tokenize
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote, urlsplit
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


def _conda_package(*, root: Path, repository: str | None) -> str | None:
    """Read a literal package name without evaluating Jinja in a consumer recipe."""
    recipe = next(
        (path for path in ("conda.recipe/meta.yaml", "meta.yaml") if (root / path).is_file()), None
    )
    if not repository or not repository.lower().startswith("martinpdes/") or recipe is None:
        return None
    source = _file(root=root, value=recipe, field="Conda recipe").read_text(encoding="utf-8")
    # Other recipe sections can contain unquoted Jinja that is not plain YAML.
    block = re.search(r"^package:[^\n]*\n(?:[ \t][^\n]*\n?|\n|\#[^\n]*\n?)*", source, re.MULTILINE)
    if block is None:
        return None
    try:
        # Preserve literal names when a sibling field uses an unquoted Jinja expression.
        package = yaml.safe_load(re.sub(r"{{.*?}}", "UNRESOLVED", block[0]))["package"]
    except yaml.YAMLError:
        return None
    name = package.get("name") if isinstance(package, dict) else None
    return name if isinstance(name, str) and re.fullmatch(r"[a-z0-9_][a-z0-9_.-]*", name) else None


def _contacts(*, project: dict) -> list[dict]:
    """Read maintainer contacts in order, falling back to the project authors."""
    for field in ("maintainers", "authors"):
        entries = project.get(field, [])
        if not isinstance(entries, list):
            raise ReadmeError(f"[project].{field} must be a list")
        contacts = []
        for index, entry in enumerate(entries):
            location = f"[project].{field}[{index}]"
            if not isinstance(entry, dict) or not ("name" in entry or "email" in entry):
                raise ReadmeError(f"{location} requires a name or email")
            name = (
                _text(value=entry["name"], field=f"{location}.name", single_line=True)
                if "name" in entry
                else ""
            )
            email = (
                _text(value=entry["email"], field=f"{location}.email", single_line=True)
                if "email" in entry
                else ""
            )
            # Names and addresses are plain metadata inserted into RST inline markup.
            label = re.sub(r"([\\`*_<>|])", r"\\\1", name or email)
            contacts.append({"label": label, "address": quote(email, safe="@+")})
        if contacts:
            return contacts
    return []


def _zenodo_doi(*, root: Path, urls: dict) -> str | None:
    """Find a Zenodo record in project metadata without resolving URLs online."""

    def recognized(*, value):
        """Normalize a Zenodo DOI or record URL."""
        match = re.fullmatch(
            r"(?:(?:https://doi\.org/)?10\.5281/zenodo\.|https://zenodo\.org/records?/)([0-9]+)/?",
            str(value).strip(),
            re.IGNORECASE,
        )
        return f"10.5281/zenodo.{match[1]}" if match else None

    if doi := recognized(value=urls.get("zenodo")):
        return doi
    for filename in ("CITATION.cff", ".zenodo.json"):
        if not (root / filename).is_file():
            continue
        path = _file(root=root, value=filename, field=filename)
        try:
            source = path.read_text(encoding="utf-8")
            metadata = json.loads(source) if filename.endswith(".json") else yaml.safe_load(source)
        except (ValueError, yaml.YAMLError) as error:
            raise ReadmeError(f"{filename}: {error}") from error
        if not isinstance(metadata, dict):
            raise ReadmeError(f"{filename} must contain a mapping")
        if doi := recognized(value=metadata.get("doi")):
            return doi
    return None


def _figure(*, root: Path, value, field: str) -> dict:
    """Validate a repository image path and optional reStructuredText caption."""
    settings = _mapping(value=value, field=field, allowed={"path", "caption"})
    _file(root=root, value=settings.get("path"), field=f"{field}.path")
    caption = (
        _text(value=settings["caption"], field=f"{field}.caption")
        if "caption" in settings
        else None
    )
    return {"path": Path(settings["path"]).as_posix(), "caption": caption}


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
        allowed={
            "introduction",
            "logo",
            "demo",
            "figure",
            "quickstart",
            "sections",
            "license_note",
            "pypi",
            "conda",
        },
    )
    pypi = config.get("pypi", True)
    if not isinstance(pypi, bool):
        raise ReadmeError("pypi must be a boolean")
    conda = config.get("conda", True)
    if not isinstance(conda, bool):
        raise ReadmeError("conda must be a boolean")
    introduction = _text(value=config.get("introduction"), field="introduction")

    if "logo" in config:
        logo = _text(value=config["logo"], field="logo", single_line=True)
    else:
        candidates = [f"{name}/assets/logo/logo_light.svg"] + [
            f"{folder}/logo.{extension}"
            for folder in ("docs/images", "docs/source/_static")
            for extension in ("svg", "png")
        ]
        logo = next((path for path in candidates if (root / path).is_file()), None)
    if logo:
        _file(root=root, value=logo, field="logo")
        logo = Path(logo).as_posix()

    urls = project.get("urls", {})
    if not isinstance(urls, dict):
        raise ReadmeError("[project].urls must be a table")
    urls = {key.lower(): value for key, value in urls.items()}
    repository = None
    for key in ("repository", "source", "homepage"):
        match = re.fullmatch(
            r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?",
            str(urls.get(key, "")),
            re.IGNORECASE,
        )
        if match:
            repository = match[1]
            break
    documentation = urls.get("documentation")
    if documentation is not None and (
        not isinstance(documentation, str) or not re.fullmatch(r"https?://[^\s<>`]+", documentation)
    ):
        raise ReadmeError("[project.urls].Documentation must be an HTTP(S) URL")
    contact_url = urls.get("contact")
    if contact_url is not None and (
        not isinstance(contact_url, str) or not re.fullmatch(r"https?://[^\s<>`]+", contact_url)
    ):
        raise ReadmeError("[project.urls].Contact must be an HTTP(S) URL")
    workflows = root / ".github" / "workflows"
    test_workflow = next(
        (
            filename
            for filename in (
                "tests.yml",
                "tests.yaml",
                "test.yml",
                "test.yaml",
                "unit-tests.yml",
                "unit-tests.yaml",
            )
            if repository and (workflows / filename).is_file()
        ),
        None,
    )
    coverage = bool(repository and (workflows / "deploy_coverage.yml").is_file())
    python_requirement = project.get("requires-python")
    if python_requirement is not None:
        python_requirement = _text(
            value=python_requirement, field="[project].requires-python", single_line=True
        )

    demo = None
    if "demo" in config:
        demo = _text(value=config["demo"], field="demo", single_line=True)
        url = urlsplit(demo)
        if url.scheme not in {"http", "https"} or not url.hostname or re.search(r"[\s<>`]", demo):
            raise ReadmeError("demo must be an HTTP(S) URL")

    figure = (
        _figure(root=root, value=config["figure"], field="figure") if "figure" in config else None
    )

    quickstart = None
    if "quickstart" in config:
        value = config["quickstart"]
        settings = (
            _mapping(
                value=value,
                field="quickstart",
                allowed={"source", "title", "description", "figure"},
            )
            if isinstance(value, dict)
            else {"source": value}
        )
        field = "quickstart.source" if isinstance(value, dict) else "quickstart"
        example = _file(root=root, value=settings.get("source"), field=field)
        try:
            with tokenize.open(example) as stream:
                source = stream.read().removesuffix("\n")
        except (SyntaxError, UnicodeError) as error:
            raise ReadmeError(f"{field}: cannot decode {example}: {error}") from error
        quickstart = {
            "source": source,
            "title": _text(
                value=settings.get("title", "Quick start"),
                field="quickstart.title",
                single_line=True,
            ),
            "description": _text(value=settings["description"], field="quickstart.description")
            if "description" in settings
            else None,
            "figure": _figure(root=root, value=settings["figure"], field="quickstart.figure")
            if "figure" in settings
            else None,
        }

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

    section_titles = {section["title"].strip().casefold() for section in extra_sections}
    license_note = (
        _text(value=config["license_note"], field="license_note")
        if "license_note" in config
        else None
    )
    license_label = None
    license_file = None
    if "license" not in section_titles:
        declared = project.get("license")
        if isinstance(declared, str):
            license_label = _text(value=declared, field="[project].license", single_line=True)
        elif isinstance(declared, dict) and "file" in declared:
            _file(root=root, value=declared["file"], field="[project].license.file")
            license_file = Path(declared["file"]).as_posix()
        if not license_file:
            for filename in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
                if (root / filename).is_file():
                    _file(root=root, value=filename, field="license file")
                    license_file = filename
                    break

    contributing_guide = None
    if "contributing" not in section_titles:
        for directory in (Path("."), Path(".github"), Path("docs")):
            for filename in ("CONTRIBUTING.md", "CONTRIBUTING.rst"):
                relative = (directory / filename).as_posix()
                if (root / relative).is_file():
                    _file(root=root, value=relative, field="contributing guide")
                    contributing_guide = relative
                    break
            if contributing_guide:
                break

    template = files(__package__).joinpath("readme.rst.j2").read_text(encoding="utf-8")
    environment = Environment(
        trim_blocks=True, undefined=StrictUndefined, keep_trailing_newline=True
    )
    rendered = (
        environment.from_string(template)
        .render(
            name=name,
            logo=logo,
            repository=repository,
            documentation=documentation,
            section_titles=section_titles,
            contributing_guide=contributing_guide,
            zenodo_doi=_zenodo_doi(root=root, urls=urls)
            if "citation" not in section_titles
            else None,
            license_label=license_label,
            license_file=license_file,
            license_note=license_note,
            contacts=_contacts(project=project),
            contact_url=contact_url,
            docs_workflow=repository and (workflows / "deploy_documentation.yml").is_file(),
            test_workflow=test_workflow,
            pypi=pypi,
            coverage=coverage,
            conda=_conda_package(root=root, repository=repository) if conda else None,
            python_requirement=python_requirement,
            slug=re.sub(r"[-_.]+", "-", name).lower(),
            description=description,
            introduction=introduction,
            demo=demo,
            figure=figure,
            quickstart=quickstart,
            sections=extra_sections,
        )
        .rstrip("\n")
        .encode("utf-8")
        + b"\n"
    )
    output = root / "README.rst"
    if output.is_symlink():
        raise ReadmeError("README.rst must not be a symlink")
    if output.is_file() and output.read_bytes() == rendered:
        return
    if check:
        raise ReadmeError("README.rst is missing or stale; run mps-maintenance readme")
    output.write_bytes(rendered)
