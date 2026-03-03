from types import SimpleNamespace
from unittest.mock import patch

import pytest

from auto_proxy_vpn.utils.ssh_client import SSHClient


class TestSSHClient:
    def test_init_non_strict_includes_flag(self):
        client = SSHClient("1.2.3.4", "root", strict=False)
        assert "StrictHostKeyChecking=no" in client.ssh_command

    def test_init_strict_excludes_flag(self):
        client = SSHClient("1.2.3.4", "root", strict=True)
        assert "StrictHostKeyChecking=no" not in client.ssh_command

    def test_connect_success_sets_active(self):
        with patch(
            "auto_proxy_vpn.utils.ssh_client.run",
            return_value=SimpleNamespace(stdout=b"OK\n", returncode=0, stderr=b""),
        ):
            client = SSHClient("1.2.3.4", "root")
            assert client.connect() is True
            assert client.active is True

    def test_connect_failure_returns_false(self):
        with patch(
            "auto_proxy_vpn.utils.ssh_client.run",
            return_value=SimpleNamespace(stdout=b"", returncode=1, stderr=b"err"),
        ):
            client = SSHClient("1.2.3.4", "root")
            assert client.connect() is False

    def test_run_command_raises_if_not_connected(self):
        client = SSHClient("1.2.3.4", "root")
        with patch.object(client, "connect", return_value=False):
            with pytest.raises(ConnectionError, match="Can't connect"):
                client.run_command("echo hi")

    def test_run_command_returns_result(self):
        with patch(
            "auto_proxy_vpn.utils.ssh_client.run",
            return_value=SimpleNamespace(stdout=b"hi\n", returncode=0, stderr=b""),
        ):
            client = SSHClient("1.2.3.4", "root")
            with patch.object(client, "connect", return_value=True):
                code, out, err = client.run_command("echo hi")

        assert code == 0
        assert out == "hi\n"
        assert err == ""

    def test_download_file_raises_if_missing(self):
        client = SSHClient("1.2.3.4", "root")
        with patch.object(
            client,
            "run_command",
            return_value=(1, "", "No such file or directory"),
        ):
            with pytest.raises(FileNotFoundError):
                client.download_file("/tmp/a.txt", "./a.txt")

    def test_download_file_raises_connection_error_on_stderr(self):
        client = SSHClient("1.2.3.4", "root")
        with patch.object(client, "run_command", return_value=(1, "", "permission denied")):
            with pytest.raises(ConnectionError, match="Can't connect"):
                client.download_file("/tmp/a.txt", "./a.txt")

    def test_download_file_runs_scp_when_exists(self):
        client = SSHClient("1.2.3.4", "root")
        with patch.object(client, "run_command", return_value=(0, "", "")):
            with patch("auto_proxy_vpn.utils.ssh_client.run") as mock_run:
                client.download_file("/tmp/a.txt", "./a.txt")

        mock_run.assert_called_once_with(
            "scp root@1.2.3.4:/tmp/a.txt ./a.txt",
            shell=True,
            capture_output=True,
        )
