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

from auto_proxy_vpn import CloudProvider
from auto_proxy_vpn.configs import GoogleConfig, ManagerRuntimeConfig


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
