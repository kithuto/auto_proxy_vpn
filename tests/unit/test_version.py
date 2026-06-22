import re
from pathlib import Path

import auto_proxy_vpn
import pytest
from auto_proxy_vpn.utils import _version as version_mod


def test_package_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', content)

    assert match is not None
    assert auto_proxy_vpn.__version__ == match.group(1)


def test_version_ignores_pyproject_for_another_project(tmp_path, monkeypatch):
    package_file = (
        tmp_path / "site-packages" / "auto_proxy_vpn" / "utils" / "_version.py"
    )
    package_file.parent.mkdir(parents=True)
    package_file.write_text("", encoding="utf-8")
    wrong_pyproject = tmp_path / "site-packages" / "pyproject.toml"
    wrong_pyproject.write_text(
        '[project]\nname = "another_project"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(version_mod, "__file__", str(package_file))
    monkeypatch.setattr(version_mod.metadata, "version", lambda distribution: "0.2.3")

    assert version_mod.get_version() == "0.2.3"


def test_version_module_does_not_require_tomllib():
    assert "tomllib" not in version_mod.__dict__


def test_read_pyproject_project_returns_none_when_file_cannot_be_read():
    class UnreadablePath:
        def read_text(self, encoding):
            raise OSError

    assert version_mod._read_pyproject_project(UnreadablePath()) is None


def test_read_pyproject_project_requires_project_name_and_version(tmp_path):
    no_project = tmp_path / "no_project.toml"
    no_project.write_text('[tool.example]\nname = "auto_proxy_vpn"\n', encoding="utf-8")
    missing_version = tmp_path / "missing_version.toml"
    missing_version.write_text('[project]\nname = "auto_proxy_vpn"\n', encoding="utf-8")

    assert version_mod._read_pyproject_project(no_project) is None
    assert version_mod._read_pyproject_project(missing_version) is None


def test_read_pyproject_version_rejects_wrong_project(tmp_path):
    wrong_pyproject = tmp_path / "pyproject.toml"
    wrong_pyproject.write_text(
        '[project]\nname = "another_project"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError, match="is not a pyproject.toml for auto_proxy_vpn"
    ):
        version_mod._read_pyproject_version(wrong_pyproject)
