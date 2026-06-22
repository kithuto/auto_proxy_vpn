from __future__ import annotations

from importlib import metadata
from pathlib import Path
import re


_DISTRIBUTION_NAME = "auto_proxy_vpn"


def _read_pyproject_project(pyproject: Path) -> dict[str, str] | None:
    try:
        content = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None

    project_match = re.search(r"(?ms)^\[project\]\s*(.*?)(?:^\[|\Z)", content)
    if not project_match:
        return None

    project_content = project_match.group(1)
    name_match = re.search(r'(?m)^name\s*=\s*["\']([^"\']+)["\']', project_content)
    version_match = re.search(
        r'(?m)^version\s*=\s*["\']([^"\']+)["\']', project_content
    )
    if not name_match or not version_match:
        return None

    return {
        "name": name_match.group(1),
        "version": version_match.group(1),
    }


def _pyproject_path() -> Path | None:
    for directory in Path(__file__).resolve().parents:
        candidate = directory / "pyproject.toml"
        project = _read_pyproject_project(candidate) if candidate.exists() else None
        if project and project.get("name") == _DISTRIBUTION_NAME:
            return candidate
    return None


def _read_pyproject_version(pyproject: Path) -> str:
    project = _read_pyproject_project(pyproject)
    if not project or project.get("name") != _DISTRIBUTION_NAME:
        raise RuntimeError(
            f"{pyproject} is not a pyproject.toml for {_DISTRIBUTION_NAME}"
        )
    return str(project["version"])


def get_version() -> str:
    pyproject = _pyproject_path()
    if pyproject is not None:
        return _read_pyproject_version(pyproject)

    return metadata.version(_DISTRIBUTION_NAME)
