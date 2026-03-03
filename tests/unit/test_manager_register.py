"""Tests for the ProxyManagers registry (manager_register.py)."""

import pytest

from auto_proxy_vpn import CloudProvider
from auto_proxy_vpn.manager_register import ProxyManagers
from auto_proxy_vpn.utils.base_proxy import BaseProxyManager


class TestProxyManagersRegistry:
    """Tests for the central ProxyManagers registry."""

    def test_registered_providers_include_expected(self):
        """Providers listed in CloudProvider enum should be auto-registered on import."""
        # These are registered because they are in the enum and have implementations
        for provider in CloudProvider:
            assert provider in ProxyManagers._registry, (
                f"{provider} should be registered"
            )

    def test_get_manager_returns_correct_class(self):
        """get_manager should return a subclass of BaseProxyManager."""
        for provider in CloudProvider:
            mgr_cls = ProxyManagers.get_manager(provider)
            assert issubclass(mgr_cls, BaseProxyManager)

    def test_get_manager_raises_for_unknown_provider(self):
        """Requesting an unregistered provider must raise ValueError."""
        with pytest.raises(ValueError, match="No manager registered"):
            ProxyManagers.get_manager("nonexistent_provider") # type: ignore

    def test_double_registration_raises(self):
        """Registering the same provider twice must raise ValueError."""
        # Pick a provider that is already registered
        provider = CloudProvider.DIGITALOCEAN

        with pytest.raises(ValueError, match="already registered"):
            @ProxyManagers.register(provider)
            class DuplicateManager(BaseProxyManager):
                pass

    def test_registry_maps_google(self):
        mgr = ProxyManagers.get_manager(CloudProvider.GOOGLE)
        assert mgr.__name__ == "ProxyManagerGoogle"

    def test_registry_maps_azure(self):
        mgr = ProxyManagers.get_manager(CloudProvider.AZURE)
        assert mgr.__name__ == "ProxyManagerAzure"

    def test_registry_maps_digitalocean(self):
        mgr = ProxyManagers.get_manager(CloudProvider.DIGITALOCEAN)
        assert mgr.__name__ == "ProxyManagerDigitalOcean"
