"""Unit tests for Google Cloud provider (fully mocked).

The Google SDK is not installed in CI, so every test fully mocks the
``google.cloud.compute_v1``, ``google.api_core.exceptions`` and
``google.oauth2.service_account`` module hierarchy via ``sys.modules``.

**Key implementation detail**: ``from google.cloud import compute_v1``
resolves via ``getattr(sys.modules['google.cloud'], 'compute_v1')``, so
the parent mock **must** expose the child as an attribute.  The helper
``_make_sys_modules_patch()`` takes care of wiring this up correctly.
"""

import pytest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from pathlib import Path
import builtins


# ---------------------------------------------------------------------------
# Helpers — mock the google-cloud-compute SDK
# ---------------------------------------------------------------------------

def _make_mock_google_sdk():
    """Build a complete mock of google.cloud.compute_v1 and friends.

    Returns
    -------
    tuple
        (compute_v1, google_exceptions, service_account, clients_dict)
    """
    compute_v1 = MagicMock()

    # ── Machine types client ──────────────────────────────────────────
    machine_types_client = MagicMock()

    # Use SimpleNamespace so ``.machine_types`` is a real list, not a
    # MagicMock that could confuse truthiness / iteration checks.
    zone_with_types = SimpleNamespace(
        machine_types=[SimpleNamespace(name="e2-micro")],
    )
    zone_empty = SimpleNamespace(machine_types=[])

    machine_types_client.aggregated_list.return_value = [
        ("zones/us-central1-a", zone_with_types),
        ("zones/us-central1-b", zone_with_types),
        ("zones/europe-west1-b", zone_with_types),
        ("zones/asia-east1-a", zone_empty),
    ]

    # ── Images client ─────────────────────────────────────────────────
    images_client = MagicMock()
    image_item = SimpleNamespace(
        name="ubuntu-minimal-2404-noble-amd64-v20250101",
    )
    images_result = SimpleNamespace(items=[image_item])
    images_client.list.return_value = images_result

    # ── Instances client ──────────────────────────────────────────────
    instances_client = MagicMock()
    instances_client.aggregated_list.return_value = []

    # ── Firewall client ───────────────────────────────────────────────
    firewall_client = MagicMock()

    # ── Wire compute_v1 constructors ──────────────────────────────────
    compute_v1.MachineTypesClient.return_value = machine_types_client
    compute_v1.ImagesClient.return_value = images_client
    compute_v1.InstancesClient.return_value = instances_client
    compute_v1.FirewallsClient.return_value = firewall_client

    # Request / resource classes — plain callables that return MagicMocks
    compute_v1.AggregatedListMachineTypesRequest = MagicMock
    compute_v1.ListImagesRequest = MagicMock
    compute_v1.AggregatedListInstancesRequest = MagicMock
    compute_v1.InsertInstanceRequest = MagicMock
    compute_v1.GetInstanceRequest = MagicMock
    compute_v1.DeleteFirewallRequest = MagicMock
    compute_v1.DeleteInstanceRequest = MagicMock
    compute_v1.Firewall = MagicMock

    # ── google.api_core.exceptions ────────────────────────────────────
    google_exceptions = MagicMock()
    google_exceptions.ServiceUnavailable = type(
        "ServiceUnavailable", (Exception,), {},
    )

    # ── google.oauth2.service_account ─────────────────────────────────
    service_account = MagicMock()
    service_account.Credentials.from_service_account_file.return_value = (
        MagicMock()
    )

    return compute_v1, google_exceptions, service_account, {
        "machine_types_client": machine_types_client,
        "images_client": images_client,
        "instances_client": instances_client,
        "firewall_client": firewall_client,
    }


def _make_sys_modules_patch(compute_v1, google_exceptions, service_account):
    """Build a ``sys.modules`` dict with a properly wired module hierarchy.

    ``from google.cloud import compute_v1`` resolves via
    ``getattr(sys.modules['google.cloud'], 'compute_v1')``, so each
    parent mock must expose the child mock as an attribute.
    """
    google_cloud_mock = MagicMock()
    google_cloud_mock.compute_v1 = compute_v1

    google_api_core_mock = MagicMock()
    google_api_core_mock.exceptions = google_exceptions

    google_oauth2_mock = MagicMock()
    google_oauth2_mock.service_account = service_account

    google_mock = MagicMock()
    google_mock.cloud = google_cloud_mock
    google_mock.api_core = google_api_core_mock
    google_mock.oauth2 = google_oauth2_mock

    return {
        "google": google_mock,
        "google.cloud": google_cloud_mock,
        "google.cloud.compute_v1": compute_v1,
        "google.api_core": google_api_core_mock,
        "google.api_core.exceptions": google_exceptions,
        "google.oauth2": google_oauth2_mock,
        "google.oauth2.service_account": service_account,
    }


def _build_google_manager():
    """Create a ``ProxyManagerGoogle`` with a fully mocked SDK.

    Returns ``(manager, clients_dict)`` so tests can further configure
    individual client return values before exercising the manager.
    """
    compute_v1, google_exceptions, service_account, clients = (
        _make_mock_google_sdk()
    )
    modules = _make_sys_modules_patch(
        compute_v1, google_exceptions, service_account,
    )

    with patch.dict("sys.modules", modules):
        from auto_proxy_vpn.providers.google.google_proxy import (
            ProxyManagerGoogle,
        )

        mgr = ProxyManagerGoogle(
            ssh_key="ssh-rsa AAAA...",
            project="test-project",
            credentials="/tmp/fake.json",
            log=False,
        )

    return mgr, clients


# ============================================================================
# ProxyManagerGoogle — constructor
# ============================================================================

class TestProxyManagerGoogleInit:

    def test_creates_manager_with_mocked_sdk(self):
        mgr, _ = _build_google_manager()
        assert mgr.project == "test-project"
        assert hasattr(mgr, "_sizes_regions")

    def test_proxy_image_selected(self):
        mgr, _ = _build_google_manager()
        assert "ubuntu-minimal-2404" in mgr.proxy_image

    def test_sizes_regions_has_expected_keys(self):
        mgr, _ = _build_google_manager()
        sr = mgr.get_sizes_and_regions()
        assert set(sr.keys()) == {"small", "medium", "large"}

    def test_regions_populated_from_machine_types(self):
        mgr, _ = _build_google_manager()
        regions = mgr.get_regions_by_size("small")
        region_names = [r[0] for r in regions]
        assert "us-central1" in region_names
        assert "europe-west1" in region_names

    def test_no_credentials_raises(self):
        compute_v1, google_exceptions, service_account, _ = (
            _make_mock_google_sdk()
        )
        modules = _make_sys_modules_patch(
            compute_v1, google_exceptions, service_account,
        )

        with (
            patch.dict("os.environ", {}, clear=True),
            patch.dict("sys.modules", modules),
        ):
            from auto_proxy_vpn.providers.google.google_proxy import (
                ProxyManagerGoogle,
            )
            from auto_proxy_vpn.providers.google.google_exceptions import (
                GoogleAuthException,
            )
            with pytest.raises(GoogleAuthException):
                ProxyManagerGoogle(ssh_key="key", project="proj")

    def test_from_config_with_none_raises(self):
        from auto_proxy_vpn.providers.google.google_proxy import (
            ProxyManagerGoogle,
        )
        with pytest.raises(ValueError):
            ProxyManagerGoogle.from_config(None, None)

    def test_from_config_success(self):
        from auto_proxy_vpn.providers.google.google_proxy import ProxyManagerGoogle
        from auto_proxy_vpn.configs import GoogleConfig, ManagerRuntimeConfig

        cfg = GoogleConfig(project="test-project", credentials="/tmp/fake.json", ssh_key="ssh-rsa AAAA...")
        runtime = ManagerRuntimeConfig(log=False)

        with patch.object(ProxyManagerGoogle, "__init__", return_value=None) as mock_init:
            manager = ProxyManagerGoogle.from_config(cfg, runtime)

        assert manager is not None
        mock_init.assert_called_once()

    def test_reads_ssh_keys_from_file_path(self, tmp_path):
        key_file = Path(tmp_path) / "keys.pub"
        key_file.write_text("ssh-rsa AAAA\nssh-rsa BBBB\n", encoding="utf-8")

        compute_v1, google_exceptions, service_account, _ = _make_mock_google_sdk()
        modules = _make_sys_modules_patch(compute_v1, google_exceptions, service_account)

        with patch.dict("sys.modules", modules):
            from auto_proxy_vpn.providers.google.google_proxy import ProxyManagerGoogle
            mgr = ProxyManagerGoogle(
                ssh_key=str(key_file),
                project="test-project",
                credentials="/tmp/fake.json",
                log=False,
            )

        assert mgr.ssh_keys == ["ssh-rsa AAAA", "ssh-rsa BBBB"]

    def test_bad_ssh_key_dict_raises_type_error(self):
        compute_v1, google_exceptions, service_account, _ = _make_mock_google_sdk()
        modules = _make_sys_modules_patch(compute_v1, google_exceptions, service_account)

        with patch.dict("sys.modules", modules):
            from auto_proxy_vpn.providers.google.google_proxy import ProxyManagerGoogle
            with pytest.raises(TypeError, match="Bad ssh_key"):
                ProxyManagerGoogle(
                    ssh_key=[{"name": "k-without-public-key"}],  # type: ignore[list-item]
                    project="test-project",
                    credentials="/tmp/fake.json",
                    log=False,
                )

    def test_no_valid_ssh_keys_found_raises(self):
        compute_v1, google_exceptions, service_account, _ = _make_mock_google_sdk()
        modules = _make_sys_modules_patch(compute_v1, google_exceptions, service_account)

        with patch.dict("sys.modules", modules):
            from auto_proxy_vpn.providers.google.google_proxy import ProxyManagerGoogle
            with pytest.raises(TypeError, match="No valid ssh keys found"):
                ProxyManagerGoogle(
                    ssh_key=["invalid-key", "still-invalid"],
                    project="test-project",
                    credentials="/tmp/fake.json",
                    log=False,
                )

    def test_import_error_when_google_sdk_missing(self):
        real_import = builtins.__import__

        def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in {"google.cloud", "google.api_core", "google.oauth2"}:
                raise ImportError("forced missing google sdk")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=_fake_import):
            from auto_proxy_vpn.providers.google.google_proxy import ProxyManagerGoogle
            with pytest.raises(ImportError, match="google-cloud-compute"):
                ProxyManagerGoogle(
                    ssh_key="ssh-rsa AAAA...",
                    project="test-project",
                    credentials="/tmp/fake.json",
                    log=False,
                )

    def test_logger_is_configured_when_enabled(self):
        compute_v1, google_exceptions, service_account, _ = _make_mock_google_sdk()
        modules = _make_sys_modules_patch(compute_v1, google_exceptions, service_account)

        with patch.dict("sys.modules", modules):
            with patch("auto_proxy_vpn.providers.google.google_proxy.basicConfig") as mock_basic:
                from auto_proxy_vpn.providers.google.google_proxy import ProxyManagerGoogle
                mgr = ProxyManagerGoogle(
                    ssh_key="ssh-rsa AAAA...",
                    project="test-project",
                    credentials="/tmp/fake.json",
                    log=True,
                )

        assert mgr.logger is not None
        mock_basic.assert_called_once()


# ============================================================================
# ProxyManagerGoogle — get_proxy
# ============================================================================

class TestProxyManagerGoogleGetProxy:

    def test_get_proxy_creates_instance(self):
        mgr, clients = _build_google_manager()

        # No running proxies
        clients["instances_client"].aggregated_list.return_value = []

        # Insert succeeds
        op = MagicMock()
        op.result.return_value = None
        op.error_code = None
        op.warnings = []
        clients["instances_client"].insert.return_value = op

        # get() returns an instance with a public IP
        inst = MagicMock()
        inst.network_interfaces = [MagicMock()]
        inst.network_interfaces[0].access_configs = [MagicMock()]
        inst.network_interfaces[0].access_configs[0].nat_i_p = "35.0.0.1"
        clients["instances_client"].get.return_value = inst

        clients["firewall_client"].insert.return_value = MagicMock()

        with patch(
            "auto_proxy_vpn.providers.google.google_proxy.get_public_ip",
            return_value="1.2.3.4",
        ):
            proxy = mgr.get_proxy(port=12345, size="small", is_async=True)

        assert proxy.port == 12345
        assert proxy.project == "test-project"

    def test_get_proxy_invalid_region_raises(self):
        mgr, clients = _build_google_manager()
        clients["instances_client"].aggregated_list.return_value = []

        with patch(
            "auto_proxy_vpn.providers.google.google_proxy.get_public_ip",
            return_value="1.2.3.4",
        ):
            with pytest.raises(ValueError, match="Region"):
                mgr.get_proxy(region="nonexistent-region")

    def test_get_proxy_duplicate_name_raises(self):
        mgr, clients = _build_google_manager()

        inst = MagicMock()
        inst.name = "proxy-existing"

        class _AggEntry:
            def __init__(self, instances):
                self.instances = instances

            def __contains__(self, key):
                return key == "instances" and bool(self.instances)

        clients["instances_client"].aggregated_list.return_value = [
            ("zones/us-central1-a", _AggEntry([inst])),
        ]

        with pytest.raises(NameError, match="already exists"):
            mgr.get_proxy(proxy_name="proxy-existing")

    def test_get_proxy_auth_type_raises(self):
        mgr, clients = _build_google_manager()
        clients["instances_client"].aggregated_list.return_value = []

        with patch(
            "auto_proxy_vpn.providers.google.google_proxy.get_public_ip",
            return_value="1.2.3.4",
        ):
            with pytest.raises(TypeError, match="auth"):
                mgr.get_proxy(auth="bad-auth")  # type: ignore[arg-type]

    def test_get_proxy_auth_missing_keys_raises(self):
        mgr, clients = _build_google_manager()
        clients["instances_client"].aggregated_list.return_value = []

        with patch(
            "auto_proxy_vpn.providers.google.google_proxy.get_public_ip",
            return_value="1.2.3.4",
        ):
            with pytest.raises(KeyError, match="two keys"):
                mgr.get_proxy(auth={"user": "only-user"})  # type: ignore[arg-type]

    def test_get_proxy_allowed_ips_bad_format_raises(self):
        mgr, clients = _build_google_manager()
        clients["instances_client"].aggregated_list.return_value = []

        with patch(
            "auto_proxy_vpn.providers.google.google_proxy.get_public_ip",
            return_value="1.2.3.4",
        ):
            with pytest.raises(TypeError, match="bad format"):
                mgr.get_proxy(allowed_ips=["bad-ip"])

    def test_get_proxy_failure_after_retry_raises(self):
        mgr, clients = _build_google_manager()
        clients["instances_client"].aggregated_list.return_value = []

        with patch(
            "auto_proxy_vpn.providers.google.google_proxy.get_public_ip",
            return_value="1.2.3.4",
        ):
            with patch(
                "auto_proxy_vpn.providers.google.google_proxy.start_proxy",
                side_effect=[("", True), ("", True)],
            ):
                with pytest.raises(Exception, match="Failed to start"):
                    mgr.get_proxy(size="small", is_async=True)

        clients["firewall_client"].delete.assert_called()

    def test_get_proxy_retry_succeeds_in_other_region(self):
        mgr, clients = _build_google_manager()
        clients["instances_client"].aggregated_list.return_value = []

        with patch(
            "auto_proxy_vpn.providers.google.google_proxy.get_public_ip",
            return_value="35.0.0.99",
        ):
            with patch(
                "auto_proxy_vpn.providers.google.google_proxy.start_proxy",
                side_effect=[("", True), ("35.0.0.99", False)],
            ):
                with patch(
                    "auto_proxy_vpn.providers.google.google_proxy.GoogleProxy.is_active",
                    return_value=True,
                ):
                    proxy = mgr.get_proxy(size="small", is_async=True)
        print(proxy.ip)
        assert proxy.ip == "35.0.0.99"

    def test_get_proxy_auto_name_skips_existing_names(self):
        mgr, clients = _build_google_manager()

        inst1 = MagicMock(); inst1.name = "proxy1"
        inst2 = MagicMock(); inst2.name = "proxy2"

        class _AggEntry:
            def __init__(self, instances):
                self.instances = instances
            def __contains__(self, key):
                return key == "instances" and bool(self.instances)

        clients["instances_client"].aggregated_list.return_value = [
            ("zones/us-central1-a", _AggEntry([inst1, inst2]))
        ]

        with patch("auto_proxy_vpn.providers.google.google_proxy.get_public_ip", return_value="1.2.3.4"):
            with patch("auto_proxy_vpn.providers.google.google_proxy.start_proxy", return_value=("35.0.0.7", False)) as mock_start:
                with patch(
                    "auto_proxy_vpn.providers.google.google_proxy.GoogleProxy.is_active",
                    return_value=True,
                ):
                    proxy = mgr.get_proxy(size="small", is_async=True)

        assert proxy.name == "proxy3"
        assert mock_start.call_args.args[1] == "proxy3"

    def test_get_proxy_with_valid_region_branch(self):
        mgr, clients = _build_google_manager()
        clients["instances_client"].aggregated_list.return_value = []

        with patch("auto_proxy_vpn.providers.google.google_proxy.get_public_ip", return_value="1.2.3.4"):
            with patch("auto_proxy_vpn.providers.google.google_proxy.start_proxy", return_value=("35.0.0.8", False)) as mock_start:
                with patch("auto_proxy_vpn.providers.google.google_proxy.GoogleProxy.is_active", return_value=True):
                    proxy = mgr.get_proxy(size="small", is_async=True, region="us-central1")

        assert proxy.region == "us-central1"
        assert mock_start.call_args.args[3] == "us-central1"

    def test_get_proxy_allowed_ips_string_branch(self):
        mgr, clients = _build_google_manager()
        clients["instances_client"].aggregated_list.return_value = []

        with patch("auto_proxy_vpn.providers.google.google_proxy.get_public_ip", return_value="35.0.0.9"):
            with patch("auto_proxy_vpn.providers.google.google_proxy.start_proxy", return_value=("35.0.0.9", False)) as mock_start:
                with patch("auto_proxy_vpn.providers.google.google_proxy.GoogleProxy.is_active", return_value=True):
                    mgr.get_proxy(size="small", allowed_ips="5.5.5.5", is_async=True)

        passed_allowed_ips = mock_start.call_args.args[7]
        assert "5.5.5.5" in passed_allowed_ips
        assert "35.0.0.9" in passed_allowed_ips

    def test_get_proxy_logs_warning_and_error(self):
        mgr, clients = _build_google_manager()
        clients["instances_client"].aggregated_list.return_value = []
        mgr.logger = MagicMock()

        with patch("auto_proxy_vpn.providers.google.google_proxy.get_public_ip", return_value="1.2.3.4"):
            with patch(
                "auto_proxy_vpn.providers.google.google_proxy.start_proxy",
                side_effect=[("", True), ("", True)],
            ):
                with pytest.raises(Exception):
                    mgr.get_proxy(size="small", is_async=True)

        assert mgr.logger.warning.called
        assert mgr.logger.error.called

    def test_get_proxy_auto_name_while_increment_branch(self):
        mgr, clients = _build_google_manager()

        inst1 = MagicMock(); inst1.name = "proxy1"
        inst3 = MagicMock(); inst3.name = "proxy3"
        instances = [inst1, inst3]

        class _AggEntry:
            def __init__(self, instances):
                self.instances = instances

            def __contains__(self, key):
                return key == "instances" and bool(self.instances)

        clients["instances_client"].aggregated_list.return_value = [
            ("zones/us-central1-a", _AggEntry(instances))
        ]

        with patch("auto_proxy_vpn.providers.google.google_proxy.get_public_ip", return_value="1.2.3.4"):
            with patch("auto_proxy_vpn.providers.google.google_proxy.start_proxy", return_value=("35.0.0.10", False)) as mock_start:
                with patch("auto_proxy_vpn.providers.google.google_proxy.GoogleProxy.is_active", return_value=True):
                    proxy = mgr.get_proxy(size="small", is_async=True)

        assert proxy.name == "proxy4"
        assert mock_start.call_args.args[1] == "proxy4"


# ============================================================================
# GoogleProxy
# ============================================================================

class TestGoogleProxy:

    def test_str_contains_google(self):
        mgr, _ = _build_google_manager()

        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        with patch.object(GoogleProxy, "is_active", return_value=True):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy1",
                ip="35.0.0.1",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=True,
                on_exit="destroy",
            )
        assert "Google" in str(proxy)

    def test_bad_on_exit_raises(self):
        mgr, _ = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy
        with pytest.raises(ValueError, match="on_exit"):
            with patch.object(GoogleProxy, "is_active", return_value=True):
                GoogleProxy(
                    manager=mgr, name="p", ip="1.1.1.1", port=80,
                    project="proj", region="r", zone="z",
                    is_async=True, on_exit="invalid",  # type: ignore
                )

    def test_init_logs_when_sync_with_logger(self):
        mgr, _ = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        logger = MagicMock()
        with patch.object(GoogleProxy, "is_active", return_value=True):
            GoogleProxy(
                manager=mgr,
                name="proxy-log",
                ip="35.0.0.1",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=False,
                logger=logger,
                on_exit="destroy",
            )

        assert logger.info.called

    def test_reload_logs_branch(self):
        mgr, _ = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        logger = MagicMock()
        with patch.object(GoogleProxy, "is_active", return_value=True):
            GoogleProxy(
                manager=mgr,
                name="proxy-reload",
                ip="35.0.0.1",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=True,
                logger=logger,
                reload=True,
                on_exit="destroy",
            )

        assert logger.info.called

    def test_is_active_async_fetches_ip_and_activates(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        inst = SimpleNamespace(
            network_interfaces=[SimpleNamespace(access_configs=[SimpleNamespace(nat_i_p="35.0.0.50")])]
        )
        clients["instances_client"].get.return_value = inst
        
        with patch.object(GoogleProxy, "is_active", return_value=True):
            with patch("auto_proxy_vpn.utils.base_proxy.get_public_ip", return_value="35.0.0.50"):
                with patch("auto_proxy_vpn.providers.google.google_proxy.start_proxy", return_value=("35.0.0.9", False)):
                    proxy = GoogleProxy(
                        manager=mgr,
                        name="proxy-async",
                        ip="",
                        port=8080,
                        project="test-project",
                        region="us-central1",
                        zone="us-central1-a",
                        is_async=True,
                        reload=True,
                        on_exit="destroy",
                    )

        with patch("auto_proxy_vpn.utils.base_proxy.get_public_ip", return_value="35.0.0.50"):
            assert proxy.is_active(wait=False) is True
        assert proxy.ip == "35.0.0.50"

    def test_is_active_async_retry_fails_and_stops(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        clients["instances_client"].get.side_effect = Exception("down")
        
        with patch("auto_proxy_vpn.providers.google.google_proxy.start_proxy", return_value=("", True)):
            with patch("auto_proxy_vpn.providers.google.google_proxy.GoogleProxy._stop_proxy") as mock_stop:
                _ = GoogleProxy(
                    manager=mgr,
                    name="proxy-retry-fail",
                    ip="",
                    port=8080,
                    project="test-project",
                    region="us-central1",
                    zone="us-central1-a",
                    is_async=True,
                    reload=False,
                    on_exit="keep",
                )

        assert mock_stop.called

    def test_stop_proxy_destroy_and_keep_paths(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        op = SimpleNamespace(result=lambda timeout=0: None, error_code=None, warnings=[])
        clients["firewall_client"].delete.return_value = op
        clients["instances_client"].delete.return_value = op

        with patch("auto_proxy_vpn.providers.google.google_proxy.wait_for_extended_operation", return_value=None):
            with patch.object(GoogleProxy, "is_active", return_value=True):
                proxy = GoogleProxy(
                    manager=mgr,
                    name="proxy-stop",
                    ip="35.0.0.1",
                    port=8080,
                    project="test-project",
                    region="us-central1",
                    zone="us-central1-a",
                    is_async=True,
                    reload=True,
                    on_exit="destroy",
                )
            proxy._stop_proxy(wait=True)

        assert proxy.stopped is True
        assert proxy.ip == ""

        with patch.object(GoogleProxy, "is_active", return_value=True):
            proxy_keep = GoogleProxy(
                manager=mgr,
                name="proxy-keep",
                ip="35.0.0.2",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=True,
                reload=True,
                on_exit="keep",
            )
        proxy_keep._stop_proxy(wait=False)
        assert proxy_keep.stopped is True

    def test_is_active_async_retry_success_restores_async_and_logs(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        logger = MagicMock()
        clients["instances_client"].get.side_effect = Exception("down")

        with patch.object(GoogleProxy, "is_active", return_value=False):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy-async-retry-ok",
                ip="",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=True,
                logger=logger,
                reload=True,
                on_exit="destroy",
            )

        proxy.retried = False
        with patch("auto_proxy_vpn.providers.google.google_proxy.start_proxy", return_value=("35.0.0.77", False)):
            with patch("auto_proxy_vpn.providers.google.google_proxy.GoogleProxy._stop_proxy") as mock_stop:
                with patch("auto_proxy_vpn.utils.base_proxy.get_public_ip", return_value="35.0.0.77"):
                    assert proxy.is_active(wait=False) is True

        mock_stop.assert_called_once_with(reset=False)
        assert proxy.is_async is True
        assert logger.info.called

    def test_is_active_async_retry_error_logs_and_returns_inactive(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        logger = MagicMock()
        clients["instances_client"].get.side_effect = Exception("down")

        with patch.object(GoogleProxy, "is_active", return_value=False):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy-async-retry-error",
                ip="",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=True,
                logger=logger,
                reload=True,
                on_exit="destroy",
            )

        with patch("auto_proxy_vpn.providers.google.google_proxy.start_proxy", return_value=("", True)):
            with patch("auto_proxy_vpn.providers.google.google_proxy.GoogleProxy._stop_proxy") as mock_stop:
                assert proxy.is_active(wait=False) is False

        assert mock_stop.call_count >= 2
        assert logger.error.called

    def test_is_active_async_when_already_retried_warns_and_stops(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        logger = MagicMock()
        clients["instances_client"].get.side_effect = Exception("down")

        with patch.object(GoogleProxy, "is_active", return_value=False):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy-async-retried",
                ip="",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=True,
                logger=logger,
                reload=True,
                on_exit="destroy",
            )

        proxy.retried = True
        with patch("auto_proxy_vpn.providers.google.google_proxy.GoogleProxy._stop_proxy") as mock_stop:
            assert proxy.is_active(wait=False) is False

        mock_stop.assert_called_once()
        assert logger.warning.called

    def test_is_active_async_empty_ip_returns_inactive(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        empty_inst = SimpleNamespace(
            network_interfaces=[SimpleNamespace(access_configs=[SimpleNamespace(nat_i_p="")])]
        )
        clients["instances_client"].get.return_value = empty_inst

        with patch.object(GoogleProxy, "is_active", return_value=False):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy-async-empty-ip",
                ip="",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=True,
                reload=True,
                on_exit="destroy",
            )

        assert proxy.is_active(wait=False) is False

    def test_is_active_sync_empty_ip_loops_and_returns_inactive(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        empty_inst = SimpleNamespace(
            network_interfaces=[SimpleNamespace(access_configs=[SimpleNamespace(nat_i_p="")])]
        )
        clients["instances_client"].get.return_value = empty_inst

        with patch.object(GoogleProxy, "is_active", return_value=False):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy-sync-empty-ip",
                ip="",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=False,
                reload=True,
                on_exit="destroy",
            )

        with patch("auto_proxy_vpn.providers.google.google_proxy.sleep", return_value=None):
            assert proxy.is_active(wait=False) is False

    def test_is_active_sync_retry_then_success(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        logger = MagicMock()
        clients["instances_client"].get.side_effect = Exception("down")

        with patch.object(GoogleProxy, "is_active", return_value=False):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy-sync-retry-ok",
                ip="",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=False,
                logger=logger,
                reload=True,
                on_exit="destroy",
            )

        with patch("auto_proxy_vpn.providers.google.google_proxy.start_proxy", return_value=("35.0.0.88", False)):
            with patch("auto_proxy_vpn.providers.google.google_proxy.GoogleProxy._stop_proxy") as mock_stop:
                with patch("auto_proxy_vpn.utils.base_proxy.get_public_ip", return_value="35.0.0.88"):
                    assert proxy.is_active(wait=False) is True

        mock_stop.assert_called_once_with(reset=False)
        assert logger.info.called

    def test_is_active_sync_retry_error_logs_and_stops(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        logger = MagicMock()
        clients["instances_client"].get.side_effect = Exception("down")

        with patch.object(GoogleProxy, "is_active", return_value=False):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy-sync-retry-error",
                ip="",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=False,
                logger=logger,
                reload=True,
                on_exit="destroy",
            )

        with patch("auto_proxy_vpn.providers.google.google_proxy.start_proxy", return_value=("", True)):
            with patch("auto_proxy_vpn.providers.google.google_proxy.GoogleProxy._stop_proxy") as mock_stop:
                assert proxy.is_active(wait=False) is False

        assert mock_stop.call_count >= 2
        assert logger.error.called

    def test_is_active_sync_already_retried_warns_and_returns(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        logger = MagicMock()
        clients["instances_client"].get.side_effect = Exception("down")

        with patch.object(GoogleProxy, "is_active", return_value=False):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy-sync-retried",
                ip="",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=False,
                logger=logger,
                reload=True,
                on_exit="destroy",
            )

        proxy.retried = True
        with patch("auto_proxy_vpn.providers.google.google_proxy.GoogleProxy._stop_proxy") as mock_stop:
            assert proxy.is_active(wait=False) is False

        mock_stop.assert_called_once()
        assert logger.warning.called

    def test_stop_proxy_sync_wait_calls_wait_operation_and_logs(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        logger = MagicMock()
        op = SimpleNamespace(result=lambda timeout=0: None, error_code=None, warnings=[])
        clients["firewall_client"].delete.return_value = op
        clients["instances_client"].delete.return_value = op

        with patch.object(GoogleProxy, "is_active", return_value=True):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy-stop-sync",
                ip="35.0.0.20",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=False,
                logger=logger,
                reload=True,
                on_exit="destroy",
            )

        with patch("auto_proxy_vpn.providers.google.google_proxy.wait_for_extended_operation", return_value=None) as wait_mock:
            proxy._stop_proxy(wait=True)

        assert wait_mock.call_count == 2
        assert logger.info.called

    def test_stop_proxy_instance_delete_exception_is_ignored(self):
        mgr, clients = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        logger = MagicMock()
        clients["firewall_client"].delete.return_value = SimpleNamespace()
        clients["instances_client"].delete.side_effect = Exception("delete failed")

        with patch.object(GoogleProxy, "is_active", return_value=True):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy-stop-ignore",
                ip="35.0.0.21",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=True,
                logger=logger,
                reload=True,
                on_exit="destroy",
            )

        proxy._stop_proxy(wait=False)
        assert proxy.stopped is True

    def test_stop_proxy_keep_logs_and_reset_false_returns(self):
        mgr, _ = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        logger = MagicMock()
        with patch.object(GoogleProxy, "is_active", return_value=True):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy-keep-log",
                ip="35.0.0.30",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=True,
                logger=logger,
                reload=True,
                on_exit="keep",
            )

        proxy._stop_proxy(wait=False, reset=False)
        assert proxy.stopped is False
        assert logger.info.called

    def test_stop_proxy_when_already_stopped_returns_immediately(self):
        mgr, _ = _build_google_manager()
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy

        with patch.object(GoogleProxy, "is_active", return_value=True):
            proxy = GoogleProxy(
                manager=mgr,
                name="proxy-stopped",
                ip="35.0.0.40",
                port=8080,
                project="test-project",
                region="us-central1",
                zone="us-central1-a",
                is_async=True,
                reload=True,
                on_exit="destroy",
            )

        proxy.stopped = True
        proxy._stop_proxy(wait=False)
        assert proxy.stopped is True


# ============================================================================
# get_running_proxy_names
# ============================================================================

class TestGoogleRunningNames:

    def test_returns_list(self):
        mgr, clients = _build_google_manager()

        instance1 = MagicMock()
        instance1.name = "proxy1"
        instance2 = MagicMock()
        instance2.name = "proxy2"

        # The production code checks ``'instances' in x[1]``.  We use a
        # small helper class so ``__contains__`` works correctly.
        class _AggEntry:
            def __init__(self, instances):
                self.instances = instances
            def __contains__(self, key):
                return key == "instances" and bool(self.instances)

        agg_entry = _AggEntry([instance1, instance2])

        clients["instances_client"].aggregated_list.return_value = [
            ("zones/us-central1-a", agg_entry),
        ]

        names = mgr.get_running_proxy_names()
        assert "proxy1" in names
        assert "proxy2" in names


class TestProxyManagerGoogleGetProxyByName:
    def test_get_proxy_by_name_not_found_raises(self):
        mgr, clients = _build_google_manager()
        clients["instances_client"].aggregated_list.return_value = []

        with pytest.raises(NameError, match="doesn't exist"):
            mgr.get_proxy_by_name("missing")

    def test_get_proxy_by_name_success_with_auth_and_allowed_ips(self):
        from auto_proxy_vpn.providers.google.google_proxy import GoogleProxy
        mgr, clients = _build_google_manager()

        startup_script = (
            "http_port 3128\n"
            "acl custom_ips src 10.0.0.1\n"
            "acl custom_ips src 10.0.0.2\n"
            "#auth credentials: user: alice, password: secret\n"
        )

        metadata_item = SimpleNamespace(key="startup-script", value=startup_script)
        proxy_info = SimpleNamespace(
            network_interfaces=[SimpleNamespace(access_configs=[SimpleNamespace(nat_i_p="35.10.10.10")])],
            metadata=SimpleNamespace(items=[metadata_item]),
            zone="projects/test/zones/us-central1-a",
            machine_type="projects/test/zones/us-central1-a/machineTypes/e2-micro",
        )

        class _AggResp:
            def __init__(self, instances):
                self.instances = instances

        clients["instances_client"].aggregated_list.return_value = [
            ("zones/us-central1-a", _AggResp([proxy_info])),
        ]

        with patch(
            "auto_proxy_vpn.utils.base_proxy.get_public_ip",
            return_value="35.10.10.10",
        ):
            with patch.object(GoogleProxy, "is_active", return_value=True):
                proxy = mgr.get_proxy_by_name("proxy1", on_exit="keep", is_async=True)

        assert proxy.name == "proxy1"
        assert proxy.ip == "35.10.10.10"
        assert proxy.port == 3128
        assert proxy.user == "alice"
        assert proxy.password == "secret"
        assert proxy.allowed_ips == ["10.0.0.1", "10.0.0.2"]
        assert proxy.destroy is False

    def test_get_proxy_by_name_logs_when_logger_present(self):
        mgr, clients = _build_google_manager()
        mgr.logger = MagicMock()

        startup_script = "http_port 3128\n"
        metadata_item = SimpleNamespace(key="startup-script", value=startup_script)
        proxy_info = SimpleNamespace(
            network_interfaces=[SimpleNamespace(access_configs=[SimpleNamespace(nat_i_p="35.10.10.11")])],
            metadata=SimpleNamespace(items=[metadata_item]),
            zone="projects/test/zones/us-central1-a",
            machine_type="projects/test/zones/us-central1-a/machineTypes/e2-micro",
        )

        class _AggResp:
            def __init__(self, instances):
                self.instances = instances

        clients["instances_client"].aggregated_list.return_value = [
            ("zones/us-central1-a", _AggResp([proxy_info])),
        ]

        with patch("auto_proxy_vpn.utils.base_proxy.get_public_ip", return_value="35.10.10.11"):
            with patch('auto_proxy_vpn.providers.google.google_proxy.GoogleProxy.is_active', return_value=True):
                mgr.get_proxy_by_name("proxy1", is_async=True)

        assert mgr.logger.info.called

    def test_get_proxy_by_name_missing_startup_script_raises(self):
        mgr, clients = _build_google_manager()

        proxy_info = SimpleNamespace(
            network_interfaces=[SimpleNamespace(access_configs=[SimpleNamespace(nat_i_p="35.10.10.10")])],
            metadata=SimpleNamespace(items=[]),
            zone="projects/test/zones/us-central1-a",
            machine_type="projects/test/zones/us-central1-a/machineTypes/e2-micro",
        )

        class _AggResp:
            def __init__(self, instances):
                self.instances = instances

        clients["instances_client"].aggregated_list.return_value = [
            ("zones/us-central1-a", _AggResp([proxy_info])),
        ]

        with pytest.raises(ValueError, match="startup script"):
            mgr.get_proxy_by_name("proxy1")

    def test_get_proxy_by_name_bad_port_raises(self):
        mgr, clients = _build_google_manager()

        metadata_item = SimpleNamespace(key="startup-script", value="http_port nope\n")
        proxy_info = SimpleNamespace(
            network_interfaces=[SimpleNamespace(access_configs=[SimpleNamespace(nat_i_p="35.10.10.10")])],
            metadata=SimpleNamespace(items=[metadata_item]),
            zone="projects/test/zones/us-central1-a",
            machine_type="projects/test/zones/us-central1-a/machineTypes/e2-micro",
        )

        class _AggResp:
            def __init__(self, instances):
                self.instances = instances

        clients["instances_client"].aggregated_list.return_value = [
            ("zones/us-central1-a", _AggResp([proxy_info])),
        ]

        with pytest.raises(ValueError, match="proxy port"):
            mgr.get_proxy_by_name("proxy1")
