"""Unit tests for Azure provider (fully mocked)."""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from auto_proxy_vpn import CloudProvider
from auto_proxy_vpn.configs import AzureConfig, ManagerRuntimeConfig


# ---------------------------------------------------------------------------
# Helpers — mock the Azure SDK
# ---------------------------------------------------------------------------

def _make_mock_azure_sdk():
    """Build mocks for all Azure SDK dependencies."""
    credential_mock = MagicMock()
    default_azure_credential = MagicMock(return_value=credential_mock)

    # Subscription client
    location1 = MagicMock()
    location1.name = "eastus"
    location1.display_name = "East US"
    location2 = MagicMock()
    location2.name = "westeurope"
    location2.display_name = "West Europe"

    subscription_client = MagicMock()
    subscription_client.subscriptions.list_locations.return_value = [location1, location2]

    # Resource client
    resource_client = MagicMock()
    vm_resource_type = MagicMock()
    vm_resource_type.resource_type = "virtualMachines"
    vm_resource_type.locations = ["East US", "West Europe"]
    provider = MagicMock()
    provider.resource_types = [vm_resource_type]
    resource_client.providers.get.return_value = provider
    resource_client.resource_groups.list.return_value = []

    # Network client
    network_client = MagicMock()

    # Compute client
    compute_client = MagicMock()

    # Models
    network_models = MagicMock()
    compute_models = MagicMock()

    return {
        "DefaultAzureCredential": default_azure_credential,
        "SubscriptionClient": MagicMock(return_value=subscription_client),
        "ResourceManagementClient": MagicMock(return_value=resource_client),
        "NetworkManagementClient": MagicMock(return_value=network_client),
        "ComputeManagementClient": MagicMock(return_value=compute_client),
        "network_models": network_models,
        "compute_models": compute_models,
        "resource_client": resource_client,
        "network_client": network_client,
        "compute_client": compute_client,
        "subscription_client": subscription_client,
    }


def _build_azure_manager():
    """Create a ProxyManagerAzure with fully mocked SDK."""
    sdk = _make_mock_azure_sdk()

    with patch.dict("sys.modules", {
        "azure": MagicMock(),
        "azure.identity": MagicMock(DefaultAzureCredential=sdk["DefaultAzureCredential"]),
        "azure.mgmt": MagicMock(),
        "azure.mgmt.subscription": MagicMock(SubscriptionClient=sdk["SubscriptionClient"]),
        "azure.mgmt.resource": MagicMock(ResourceManagementClient=sdk["ResourceManagementClient"]),
        "azure.mgmt.network": MagicMock(
            NetworkManagementClient=sdk["NetworkManagementClient"],
            models=sdk["network_models"],
        ),
        "azure.mgmt.compute": MagicMock(
            ComputeManagementClient=sdk["ComputeManagementClient"],
            models=sdk["compute_models"],
        ),
    }):
        with patch.dict("os.environ", {"AZURE_SUBSCRIPTION_ID": "fake-sub-id"}):
            from auto_proxy_vpn.providers.azure.azure_proxy import ProxyManagerAzure

            mgr = ProxyManagerAzure(
                ssh_key="ssh-rsa AAAA...",
                credentials="fake-sub-id",
                log=False,
            )

    return mgr, sdk


# ============================================================================
# ProxyManagerAzure — constructor
# ============================================================================

class TestProxyManagerAzureInit:

    def test_creates_manager_with_mocked_sdk(self):
        mgr, _ = _build_azure_manager()
        assert hasattr(mgr, "_regions")
        assert hasattr(mgr, "_sizes_regions")

    def test_regions_populated(self):
        mgr, _ = _build_azure_manager()
        assert "eastus" in mgr._regions
        assert "westeurope" in mgr._regions

    def test_sizes_regions_keys(self):
        mgr, _ = _build_azure_manager()
        sr = mgr.get_sizes_and_regions()
        assert set(sr.keys()) == {"small", "medium", "large"}

    def test_no_credentials_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            sdk = _make_mock_azure_sdk()
            with patch.dict("sys.modules", {
                "azure": MagicMock(),
                "azure.identity": MagicMock(DefaultAzureCredential=sdk["DefaultAzureCredential"]),
                "azure.mgmt": MagicMock(),
                "azure.mgmt.subscription": MagicMock(SubscriptionClient=sdk["SubscriptionClient"]),
                "azure.mgmt.resource": MagicMock(ResourceManagementClient=sdk["ResourceManagementClient"]),
                "azure.mgmt.network": MagicMock(
                    NetworkManagementClient=sdk["NetworkManagementClient"],
                    models=sdk["network_models"],
                ),
                "azure.mgmt.compute": MagicMock(
                    ComputeManagementClient=sdk["ComputeManagementClient"],
                    models=sdk["compute_models"],
                ),
            }):
                from auto_proxy_vpn.providers.azure.azure_proxy import ProxyManagerAzure
                with pytest.raises(ValueError, match="credentials not provided"):
                    ProxyManagerAzure(ssh_key="key")

    def test_from_config_with_none_raises(self):
        from auto_proxy_vpn.providers.azure.azure_proxy import ProxyManagerAzure
        with pytest.raises(ValueError):
            ProxyManagerAzure.from_config(None, None)


# ============================================================================
# ProxyManagerAzure — get_proxy
# ============================================================================

class TestProxyManagerAzureGetProxy:

    def test_get_proxy_creates_vm(self):
        mgr, sdk = _build_azure_manager()

        # Mock resource group listing (no existing proxies)
        sdk["resource_client"].resource_groups.list.return_value = []
        sdk["resource_client"].resource_groups.create_or_update.return_value = MagicMock()

        # Mock network operations
        nsg_future = MagicMock()
        nsg_result = MagicMock()
        nsg_result.id = "nsg-id"
        nsg_future.result.return_value = nsg_result
        sdk["network_client"].network_security_groups.begin_create_or_update.return_value = nsg_future

        vnet_future = MagicMock()
        subnet_mock = MagicMock()
        subnet_mock.id = "subnet-id"
        vnet_result = MagicMock()
        vnet_result.subnets = [subnet_mock]
        vnet_future.result.return_value = vnet_result
        sdk["network_client"].virtual_networks.begin_create_or_update.return_value = vnet_future

        public_ip_future = MagicMock()
        public_ip_result = MagicMock()
        public_ip_result.ip_address = "40.0.0.1"
        public_ip_result.id = "pip-id"
        public_ip_future.result.return_value = public_ip_result
        sdk["network_client"].public_ip_addresses.begin_create_or_update.return_value = public_ip_future

        nic_future = MagicMock()
        nic_result = MagicMock()
        nic_result.id = "nic-id"
        nic_future.result.return_value = nic_result
        sdk["network_client"].network_interfaces.begin_create_or_update.return_value = nic_future

        # Mock compute operations
        vm_future = MagicMock()
        vm_future.result.return_value = MagicMock()
        sdk["compute_client"].virtual_machines.begin_create_or_update.return_value = vm_future

        # Mock resource group deletion (for NetworkWatcherRG)
        sdk["resource_client"].resource_groups.begin_delete.side_effect = Exception("not found")

        # Mock image version
        image_version = MagicMock()
        image_version.name = "1.0.0"
        sdk["compute_client"].virtual_machine_images.list.return_value = [image_version]

        with patch("auto_proxy_vpn.providers.azure.azure_proxy.get_public_ip", return_value="1.2.3.4"):
            proxy = mgr.get_proxy(port=12345, size="small", region="eastus", is_async=True)

        assert proxy.port == 12345
        assert proxy.region == "eastus"

    def test_get_proxy_invalid_region_raises(self):
        mgr, sdk = _build_azure_manager()
        sdk["resource_client"].resource_groups.list.return_value = []

        with patch("auto_proxy_vpn.providers.azure.azure_proxy.get_public_ip", return_value="1.2.3.4"):
            with pytest.raises(ValueError, match="Region"):
                mgr.get_proxy(region="nonexistent-region")

    def test_get_proxy_duplicate_name_raises(self):
        mgr, sdk = _build_azure_manager()
        rg = MagicMock()
        rg.name = "proxy1"
        rg.tags = {"type": "proxy"}
        sdk["resource_client"].resource_groups.list.return_value = [rg]

        with patch("auto_proxy_vpn.providers.azure.azure_proxy.get_public_ip", return_value="1.2.3.4"):
            with pytest.raises(NameError, match="already exists"):
                mgr.get_proxy(proxy_name="proxy1")


# ============================================================================
# AzureProxy
# ============================================================================

class TestAzureProxy:

    def test_str_contains_azure(self):
        mgr, _ = _build_azure_manager()
        from auto_proxy_vpn.providers.azure.azure_proxy import AzureProxy

        with patch.object(AzureProxy, "is_active", return_value=True):
            proxy = AzureProxy(
                manager=mgr,
                name="proxy1",
                ip="40.0.0.1",
                port=8080,
                region="eastus",
                is_async=True,
                on_exit="destroy",
            )
        assert "Azure" in str(proxy)

    def test_bad_on_exit_raises(self):
        mgr, _ = _build_azure_manager()
        from auto_proxy_vpn.providers.azure.azure_proxy import AzureProxy
        with pytest.raises(ValueError, match="on_exit"):
            with patch.object(AzureProxy, "is_active", return_value=True):
                AzureProxy(
                    manager=mgr, name="p", ip="1.1.1.1", port=80,
                    region="r", is_async=True, on_exit="invalid", # type: ignore
                )


# ============================================================================
# get_running_proxy_names
# ============================================================================

class TestAzureRunningNames:
    def test_returns_proxy_names(self):
        mgr, sdk = _build_azure_manager()

        rg1 = MagicMock()
        rg1.name = "proxy1"
        rg1.tags = {"type": "proxy"}
        rg2 = MagicMock()
        rg2.name = "proxy2"
        rg2.tags = {"type": "proxy"}
        rg3 = MagicMock()
        rg3.name = "other-rg"
        rg3.tags = {"type": "other"}

        sdk["resource_client"].resource_groups.list.return_value = [rg1, rg2, rg3]

        names = mgr.get_running_proxy_names()
        assert names == ["proxy1", "proxy2"]
