"""Unit tests for DigitalOcean provider (mocked HTTP calls)."""

import pytest
from unittest.mock import patch, MagicMock

import responses
from responses import matchers

from auto_proxy_vpn.configs import ManagerRuntimeConfig
from auto_proxy_vpn.utils.exceptions import CountryNotAvailableException
from tests.conftest import make_do_regions_response, make_do_droplet


DO_API = "https://api.digitalocean.com/v2"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_common_do_mocks(slugs=None):
    """Register responses mocks shared by most constructor tests."""
    regions = make_do_regions_response(slugs)
    responses.add(responses.GET, f"{DO_API}/regions", json=regions, status=200)
    responses.add(
        responses.GET,
        f"{DO_API}/projects",
        json={"projects": [{"id": "proj-1", "name": "TestProject", "is_default": True}]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{DO_API}/account/keys",
        json={"ssh_keys": [{"id": 1, "name": "test-key", "public_key": "ssh-rsa AAAA..."}]},
        status=200,
    )


# ============================================================================
# ProxyManagerDigitalOcean — constructor
# ============================================================================

class TestProxyManagerDigitalOceanInit:
    """Constructor and config validation."""

    @responses.activate
    def test_from_config_creates_manager(self, digitalocean_config):
        _register_common_do_mocks()
        runtime = ManagerRuntimeConfig(log=False)

        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        assert mgr._token == "fake-do-token-1234"
        assert mgr.project == "proj-1"
        assert len(mgr.ssh_keys) >= 1

    @responses.activate
    def test_bad_token_raises_connection_refused(self):
        responses.add(responses.GET, f"{DO_API}/regions", json={"id": "unauthorized"}, status=401)

        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        with pytest.raises(ConnectionRefusedError, match="Bad DigitalOcean token"):
            ProxyManagerDigitalOcean(
                ssh_key=[{"name": "k", "public_key": "ssh-rsa AAA"}],
                token="bad-token",
            )

    def test_empty_token_and_no_env_raises(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="token not provided"):
                ProxyManagerDigitalOcean(ssh_key="key")

    @responses.activate
    def test_sizes_regions_populated(self, digitalocean_config):
        _register_common_do_mocks()
        runtime = ManagerRuntimeConfig(log=False)

        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        sr = mgr.get_sizes_and_regions()
        assert "small" in sr and "medium" in sr and "large" in sr

    @responses.activate
    def test_from_config_with_none_raises(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        with pytest.raises(ValueError):
            ProxyManagerDigitalOcean.from_config(None, None)


# ============================================================================
# ProxyManagerDigitalOcean — get_proxy
# ============================================================================

class TestProxyManagerDigitalOceanGetProxy:
    """Proxy creation with mocked HTTP."""

    @responses.activate
    def test_get_proxy_creates_droplet(self, digitalocean_config):
        _register_common_do_mocks()

        # Mock for get_next_proxy_name
        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            json={"droplets": []},
            status=200,
        )
        # Mock droplet creation
        droplet = make_do_droplet()
        responses.add(
            responses.POST,
            f"{DO_API}/droplets",
            json={"droplet": droplet},
            status=202,
        )
        # Mock for is_active check (get droplet by id)
        responses.add(
            responses.GET,
            f"{DO_API}/droplets/123",
            json={"droplet": droplet},
            status=200,
        )

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import (
            ProxyManagerDigitalOcean,
            DigitalOceanProxy,
        )
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.get_public_ip", return_value="10.0.0.1"):
            proxy = mgr.get_proxy(port=12345, size="medium", region="nyc1", is_async=True)

        assert isinstance(proxy, DigitalOceanProxy)
        assert proxy.port == 12345
        assert proxy.name == "proxy1"

    @responses.activate
    def test_get_proxy_invalid_region_raises(self, digitalocean_config):
        _register_common_do_mocks()

        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            json={"droplets": []},
            status=200,
        )

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.get_public_ip", return_value="10.0.0.1"):
            with pytest.raises(CountryNotAvailableException):
                mgr.get_proxy(region="invalid-region", retry=False)

    @responses.activate
    def test_get_proxy_bad_auth_type_raises(self, digitalocean_config):
        _register_common_do_mocks()
        responses.add(responses.GET, f"{DO_API}/droplets", json={"droplets": []}, status=200)

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        with pytest.raises(TypeError, match="auth"):
            mgr.get_proxy(auth="bad-auth")  # type: ignore[arg-type]

    @responses.activate
    def test_get_proxy_bad_auth_keys_raises(self, digitalocean_config):
        _register_common_do_mocks()
        responses.add(responses.GET, f"{DO_API}/droplets", json={"droplets": []}, status=200)

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        with pytest.raises(KeyError, match="two keys"):
            mgr.get_proxy(auth={"user": "only-user"})  # type: ignore[arg-type]

    @responses.activate
    def test_get_proxy_bad_allowed_ips_format_raises(self, digitalocean_config):
        _register_common_do_mocks()
        responses.add(responses.GET, f"{DO_API}/droplets", json={"droplets": []}, status=200)

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        with pytest.raises(TypeError, match="bad format"):
            mgr.get_proxy(allowed_ips=["not-an-ip"])

    @responses.activate
    def test_get_proxy_creation_failure_raises_connection_error(self, digitalocean_config):
        _register_common_do_mocks()
        responses.add(responses.GET, f"{DO_API}/droplets", json={"droplets": []}, status=200)

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        with patch(
            "auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.start_proxy",
            return_value=(0, "", True),
        ):
            with pytest.raises(ConnectionError, match="creating the proxy"):
                mgr.get_proxy(is_async=True)


# ============================================================================
# DigitalOceanProxy
# ============================================================================

class TestDigitalOceanProxy:
    """Tests for the proxy object itself."""

    @responses.activate
    def test_stop_proxy_calls_delete(self):
        responses.add(responses.DELETE, f"{DO_API}/droplets/999", status=204)

        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import DigitalOceanProxy
        with patch(
            "auto_proxy_vpn.utils.base_proxy.get_public_ip",
            return_value="35.10.10.10",
        ):
            proxy = DigitalOceanProxy(
                id=999, name="proxy1", ip="10.0.0.1", port=8080,
                region="nyc1", token="tok", active=True, on_exit="destroy",
                is_async=True,  # skip is_active() in __init__ — avoids real HTTP
            )
        proxy.active = True
        proxy._stop_proxy()

        assert proxy.stopped is True
        assert proxy.ip == ""

    def test_stop_proxy_keep_does_not_delete(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import DigitalOceanProxy
        with patch(
            "auto_proxy_vpn.utils.base_proxy.get_public_ip",
            return_value="35.10.10.10",
        ):
            proxy = DigitalOceanProxy(
                id=999, name="proxy1", ip="10.0.0.1", port=8080,
                region="nyc1", token="tok", active=True, on_exit="keep",
                is_async=True,  # skip is_active() in __init__
            )
        proxy.active = True
        proxy._stop_proxy()

        # Should not have made any HTTP call
        assert proxy.stopped is False  # keep mode doesn't mark stopped
        assert proxy.ip == "10.0.0.1"

    def test_str_includes_digitalocean(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import DigitalOceanProxy
        with patch(
            "auto_proxy_vpn.utils.base_proxy.get_public_ip",
            return_value="35.10.10.10",
        ):
            proxy = DigitalOceanProxy(
                id=1, name="test", ip="1.1.1.1", port=80,
                region="nyc1", token="tok", active=True, is_async=True, on_exit="destroy",  # skip is_active() in __init__
            )
        assert "DigitalOcean" in str(proxy)

    def test_bad_on_exit_raises(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import DigitalOceanProxy
        with pytest.raises(ValueError, match="on_exit"):
            DigitalOceanProxy(
                id=1, name="test", ip="1.1.1.1", port=80,
                region="nyc1", token="tok", active=True, is_async=True,
                on_exit="invalid", reload=True,  # type: ignore
            )

    def test_is_active_async_gets_ip(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import DigitalOceanProxy

        droplet = make_do_droplet(99, "proxy1", ip="9.9.9.9", status="active")
        with patch(
            "auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.get",
            return_value=MagicMock(json=lambda: {"droplet": droplet}),
        ):
            with patch(
                "auto_proxy_vpn.utils.base_proxy.get_public_ip",
                return_value="9.9.9.9",
            ):
                proxy = DigitalOceanProxy(
                    id=99,
                    name="proxy1",
                    ip="",
                    port=8080,
                    region="nyc1",
                    token="tok",
                    active=False,
                    is_async=True,
                    reload=True,
                )

        assert proxy._digitalocean_active is True
        assert proxy.ip == "9.9.9.9"

    def test_init_logs_create_and_reload_paths(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import DigitalOceanProxy

        logger = MagicMock()
        with patch.object(DigitalOceanProxy, "is_active", return_value=True):
            DigitalOceanProxy(
                id=1,
                name="proxy-log",
                ip="1.1.1.1",
                port=80,
                region="nyc1",
                token="tok",
                active=True,
                is_async=False,
                logger=logger,
                reload=False,
                on_exit="destroy",
            )

        with patch.object(DigitalOceanProxy, "is_active", return_value=True):
            DigitalOceanProxy(
                id=2,
                name="proxy-reload",
                ip="1.1.1.2",
                port=80,
                region="nyc1",
                token="tok",
                active=True,
                is_async=True,
                logger=logger,
                reload=True,
                on_exit="destroy",
            )

        assert logger.info.called

    def test_is_active_async_get_error_returns_inactive(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import DigitalOceanProxy

        with patch.object(DigitalOceanProxy, "is_active", return_value=False):
            proxy = DigitalOceanProxy(
                id=99,
                name="proxy-err",
                ip="",
                port=8080,
                region="nyc1",
                token="tok",
                active=False,
                is_async=True,
                reload=True,
                on_exit="destroy",
            )

        proxy._digitalocean_active = False
        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.get", side_effect=Exception("down")):
            assert proxy.is_active(wait=False) is False

    def test_is_active_sync_get_errors_return_inactive(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import DigitalOceanProxy

        with patch.object(DigitalOceanProxy, "is_active", return_value=False):
            proxy = DigitalOceanProxy(
                id=100,
                name="proxy-sync-err",
                ip="",
                port=8080,
                region="nyc1",
                token="tok",
                active=False,
                is_async=False,
                reload=True,
                on_exit="destroy",
            )

        proxy._digitalocean_active = False
        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.get", side_effect=Exception("down")):
            with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.sleep", return_value=None):
                assert proxy.is_active(wait=False) is False

    def test_is_active_sync_success_sets_public_ip(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import DigitalOceanProxy

        droplet = make_do_droplet(101, "proxy-sync", ip="9.9.9.8", status="active")
        with patch.object(DigitalOceanProxy, "is_active", return_value=False):
            proxy = DigitalOceanProxy(
                id=101,
                name="proxy-sync",
                ip="",
                port=8080,
                region="nyc1",
                token="tok",
                active=False,
                is_async=False,
                reload=True,
                on_exit="destroy",
            )

        proxy._digitalocean_active = False
        with patch(
            "auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.get",
            return_value=MagicMock(json=lambda: {"droplet": droplet}),
        ):
            with patch("auto_proxy_vpn.utils.base_proxy.get_public_ip", return_value="9.9.9.8"):
                assert proxy.is_active(wait=False) is True

        assert proxy.ip == "9.9.9.8"

    def test_stop_proxy_logs_already_when_delete_fails(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import DigitalOceanProxy

        logger = MagicMock()
        with patch.object(DigitalOceanProxy, "is_active", return_value=True):
            proxy = DigitalOceanProxy(
                id=101,
                name="proxy-del-fail",
                ip="1.1.1.1",
                port=8080,
                region="nyc1",
                token="tok",
                active=True,
                is_async=True,
                logger=logger,
                reload=True,
                on_exit="destroy",
            )

        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.delete", return_value=MagicMock(status_code=404)):
            proxy._stop_proxy()

        assert logger.info.called


# ============================================================================
# ProxyManagerDigitalOcean — get_running_proxy_names
# ============================================================================

class TestDigitalOceanRunningNames:
    @responses.activate
    def test_get_running_proxy_names(self, digitalocean_config):
        _register_common_do_mocks()
        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            json={"droplets": [
                make_do_droplet(1, "proxy1"),
                make_do_droplet(2, "proxy2"),
            ]},
            status=200,
        )

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        names = mgr.get_running_proxy_names()
        assert "proxy1" in names
        assert "proxy2" in names

    @responses.activate
    def test_get_running_proxy_names_connection_error(self, digitalocean_config):
        _register_common_do_mocks()
        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean

        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.get", side_effect=Exception("down")):
            with pytest.raises(ConnectionError, match="Error connecting to DigitalOcean"):
                mgr.get_running_proxy_names()


class TestProxyManagerDigitalOceanGetProxyByName:
    @responses.activate
    def test_not_found_raises(self, digitalocean_config):
        _register_common_do_mocks()
        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            match=[matchers.query_param_matcher({"name": "missing", "type": "droplets"})],
            json={"droplets": []},
            status=200,
        )

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        with pytest.raises(NameError, match="doesn't exists"):
            mgr.get_proxy_by_name("missing")

    @responses.activate
    def test_reload_success_parses_port_and_auth(self, digitalocean_config):
        _register_common_do_mocks()
        droplet = make_do_droplet(10, "proxy-a", ip="8.8.4.4", status="active")

        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            match=[matchers.query_param_matcher({"name": "proxy-a", "type": "droplets"})],
            json={"droplets": [droplet]},
            status=200,
        )

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        squid_conf = (
            "http_port 3128\n"
            "#auth credentials: user: alice, password: secret\n"
        )

        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.SSHClient") as mock_ssh:
            mock_ssh.return_value.run_command.return_value = (0, squid_conf, "")
            with patch(
                "auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.DigitalOceanProxy.is_active",
                return_value=True,
            ):
                proxy = mgr.get_proxy_by_name("proxy-a", is_async=True, on_exit="keep")

        assert proxy.name == "proxy-a"
        assert proxy.port == 3128
        assert proxy.user == "alice"
        assert proxy.password == "secret"
        assert proxy.destroy is False

    @responses.activate
    def test_reload_without_squid_conf_raises_connection_error(self, digitalocean_config):
        _register_common_do_mocks()
        droplet = make_do_droplet(10, "proxy-b", ip="8.8.4.5", status="active")

        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            match=[matchers.query_param_matcher({"name": "proxy-b", "type": "droplets"})],
            json={"droplets": [droplet]},
            status=200,
        )

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.SSHClient") as mock_ssh:
            mock_ssh.return_value.run_command.return_value = (0, "", "")
            with pytest.raises(ConnectionError, match="Can't connect"):
                mgr.get_proxy_by_name("proxy-b")

    @responses.activate
    def test_reload_non_proxy_droplet_raises(self, digitalocean_config):
        _register_common_do_mocks()
        droplet = make_do_droplet(11, "proxy-c", ip="8.8.4.6", status="active")

        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            match=[matchers.query_param_matcher({"name": "proxy-c", "type": "droplets"})],
            json={"droplets": [droplet]},
            status=200,
        )

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        from auto_proxy_vpn.providers.digitalocean.digitalocean_exceptions import DropletNotProxyException

        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.SSHClient") as mock_ssh:
            mock_ssh.return_value.run_command.return_value = (0, "acl custom_ips src 1.1.1.1\n", "")
            with pytest.raises(DropletNotProxyException):
                mgr.get_proxy_by_name("proxy-c")

    @responses.activate
    def test_get_proxy_by_name_search_error_raises_connection_error(self, digitalocean_config):
        _register_common_do_mocks()
        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean

        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)

        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.get", side_effect=Exception("down")):
            with pytest.raises(ConnectionError, match="Error searching for the droplet"):
                mgr.get_proxy_by_name("proxy-x")

    @responses.activate
    def test_get_proxy_by_name_logs_when_logger_exists(self, digitalocean_config):
        _register_common_do_mocks()
        droplet = make_do_droplet(12, "proxy-d", ip="8.8.4.7", status="active")

        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            match=[matchers.query_param_matcher({"name": "proxy-d", "type": "droplets"})],
            json={"droplets": [droplet]},
            status=200,
        )

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)
        mgr.logger = MagicMock()

        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.SSHClient") as mock_ssh:
            mock_ssh.return_value.run_command.return_value = (0, "http_port 3128\n", "")
            with patch(
                "auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.DigitalOceanProxy.is_active",
                return_value=True,
            ):
                mgr.get_proxy_by_name("proxy-d", is_async=True)

        assert mgr.logger.info.called


class TestProxyManagerDigitalOceanInitExtra:
    def test_regions_request_exception_raises_connection_error(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean

        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.get", side_effect=Exception("down")):
            with pytest.raises(ConnectionError, match="Error connecting to DigitalOcean"):
                ProxyManagerDigitalOcean(ssh_key="test-key", token="tok", log=False)

    def test_regions_http_error_raises_connection_error(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.get", return_value=mock_resp):
            with pytest.raises(ConnectionError, match="Error connecting to DigitalOcean"):
                ProxyManagerDigitalOcean(ssh_key="test-key", token="tok", log=False)

    @responses.activate
    def test_reads_ssh_keys_from_file_path(self, tmp_path):
        key_file = tmp_path / "keys.txt"
        key_file.write_text("test-key-1\ntest-key-2\n", encoding="utf-8")

        responses.add(
            responses.GET,
            f"{DO_API}/regions",
            json=make_do_regions_response(),
            status=200,
        )

        with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.get_or_create_project", return_value="proj-1"):
            with patch("auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.get_or_create_ssh_keys", return_value=[1, 2]) as mock_keys:
                from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
                mgr = ProxyManagerDigitalOcean(ssh_key=str(key_file), token="tok", log=False)

        assert mgr.ssh_keys == [1, 2]
        assert mock_keys.call_args.args[0] == ["test-key-1", "test-key-2"]


class TestProxyManagerDigitalOceanGetProxyExtra:
    @responses.activate
    def test_get_proxy_allowed_ips_string_and_logger_path(self, digitalocean_config):
        _register_common_do_mocks()
        responses.add(responses.GET, f"{DO_API}/droplets", json={"droplets": []}, status=200)

        runtime = ManagerRuntimeConfig(log=False)
        from auto_proxy_vpn.providers.digitalocean.digitalocean_proxy import ProxyManagerDigitalOcean
        mgr = ProxyManagerDigitalOcean.from_config(digitalocean_config, runtime)
        mgr.logger = MagicMock()

        with patch(
            "auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.start_proxy",
            return_value=(123, "10.0.0.9", False),
        ) as mock_start:
            with patch(
                "auto_proxy_vpn.providers.digitalocean.digitalocean_proxy.DigitalOceanProxy.is_active",
                return_value=True,
            ):
                proxy = mgr.get_proxy(allowed_ips="8.8.8.8", is_async=True)

        passed_allowed_ips = mock_start.call_args.args[9]
        assert passed_allowed_ips == ["8.8.8.8"]
        assert proxy.ip == "10.0.0.9"
        assert mgr.logger.info.called
