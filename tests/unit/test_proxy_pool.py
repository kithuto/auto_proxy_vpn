"""Tests for ProxyPool and RandomManagerPicker."""

import pytest
from unittest.mock import patch, MagicMock

from auto_proxy_vpn.proxy_pool import ProxyPool, RandomManagerPicker
from auto_proxy_vpn.utils.base_proxy import BaseProxy, ProxyBatch
from auto_proxy_vpn.configs import DigitalOceanConfig
from tests.conftest import StubProxyManager


# ============================================================================
# RandomManagerPicker
# ============================================================================

class TestRandomManagerPicker:
    """Round-robin random manager selection."""

    def test_single_manager_always_returns_same(self):
        mgr = StubProxyManager("only")
        picker = RandomManagerPicker([mgr])
        for _ in range(10):
            assert picker.next() is mgr

    def test_all_managers_seen_per_cycle(self, stub_managers):
        picker = RandomManagerPicker(stub_managers)
        seen = {picker.next() for _ in range(len(stub_managers))}
        assert seen == set(stub_managers)

    def test_refills_after_exhaustion(self, stub_managers):
        picker = RandomManagerPicker(stub_managers)
        # Exhaust one full cycle
        for _ in range(len(stub_managers)):
            picker.next()
        # Should still return valid managers in next cycle
        for _ in range(len(stub_managers)):
            m = picker.next()
            assert m in stub_managers

    def test_iter_protocol(self, stub_managers):
        picker = RandomManagerPicker(stub_managers)
        assert iter(picker) is picker
        m = next(picker)
        assert m in stub_managers


# ============================================================================
# ProxyPool — init validation
# ============================================================================

class TestProxyPoolInit:
    """Tests for ProxyPool constructor validation."""

    def test_no_providers_raises(self):
        with pytest.raises(ValueError, match="At least one"):
            ProxyPool()

    def test_duplicate_configs_raises(self):
        c1 = DigitalOceanConfig(token="same-tok", ssh_key='key')
        c2 = DigitalOceanConfig(token="same-tok", ssh_key='key')
        with pytest.raises(ValueError, match="Duplicate"):
            # We need to mock the manager initialization to avoid real API calls
            with patch("auto_proxy_vpn.proxy_pool.ProxyManagers.get_manager") as mock_get:
                mock_cls = MagicMock()
                mock_get.return_value = mock_cls
                ProxyPool(c1, c2)

    def test_different_configs_same_provider_ok(self):
        """Two configs with different tokens for the same provider should be valid."""
        c1 = DigitalOceanConfig(token="tok-1", ssh_key='key')
        c2 = DigitalOceanConfig(token="tok-2", ssh_key='key')
        with patch("auto_proxy_vpn.proxy_pool.ProxyManagers.get_manager") as mock_get:
            mock_cls = MagicMock()
            mock_cls.from_config.return_value = StubProxyManager("do")
            mock_get.return_value = mock_cls
            pool = ProxyPool(c1, c2, log=False)
            assert len(pool.managers) == 2


class TestProxyPoolCreateOne:
    """Tests for ProxyPool.create_one with stubbed managers."""

    @pytest.fixture
    def pool_with_stubs(self, stub_managers):
        """Build a ProxyPool with injected stub managers (bypassing real init)."""
        c1 = DigitalOceanConfig(token="tok-a", ssh_key='key')
        with patch("auto_proxy_vpn.proxy_pool.ProxyManagers.get_manager") as mock_get:
            mock_cls = MagicMock()
            mock_cls.from_config.return_value = stub_managers[0]
            mock_get.return_value = mock_cls
            pool = ProxyPool(c1, log=False)
        # Replace managers with our stubs
        pool.managers = stub_managers
        pool.random_manager_picker = RandomManagerPicker(stub_managers)
        return pool

    def test_create_one_returns_base_proxy(self, pool_with_stubs):
        proxy = pool_with_stubs.create_one()
        assert isinstance(proxy, BaseProxy)

    def test_create_one_uses_different_managers(self, pool_with_stubs):
        seen_names = set()
        for _ in range(len(pool_with_stubs.managers)):
            p = pool_with_stubs.create_one()
            seen_names.add(p.name.split("-proxy-")[0])
        assert len(seen_names) == len(pool_with_stubs.managers)


class TestProxyPoolCreateBatch:
    """Tests for ProxyPool.create_batch with stubbed managers."""

    @pytest.fixture
    def pool_with_stubs(self, stub_managers):
        c1 = DigitalOceanConfig(token="tok-b", ssh_key='key')
        with patch("auto_proxy_vpn.proxy_pool.ProxyManagers.get_manager") as mock_get:
            mock_cls = MagicMock()
            mock_cls.from_config.return_value = stub_managers[0]
            mock_get.return_value = mock_cls
            pool = ProxyPool(c1, log=False)
        pool.managers = stub_managers
        pool.random_manager_picker = RandomManagerPicker(stub_managers)
        return pool

    def test_create_batch_returns_proxy_batch(self, pool_with_stubs):
        batch = pool_with_stubs.create_batch(6)
        assert isinstance(batch, ProxyBatch)

    def test_create_batch_distributes_evenly(self, pool_with_stubs):
        batch = pool_with_stubs.create_batch(6)
        # 6 / 3 managers = 2 each
        assert len(batch) == 6

    def test_create_batch_handles_remainder(self, pool_with_stubs):
        batch = pool_with_stubs.create_batch(7)
        # 7 / 3 = 2 base + 1 remainder → first manager gets 3
        assert len(batch) == 7

    def test_create_batch_single_proxy(self, pool_with_stubs):
        batch = pool_with_stubs.create_batch(1)
        assert len(batch) == 1

    def test_batch_can_be_closed(self, pool_with_stubs):
        batch = pool_with_stubs.create_batch(3)
        batch.close()
        assert batch._closed


class TestProxyPoolLogging:
    def test_initializes_shared_logger_when_log_enabled_and_no_logger(self):
        config = DigitalOceanConfig(token="tok-log", ssh_key="key")

        with patch("auto_proxy_vpn.proxy_pool.basicConfig") as mock_basic_config:
            with patch("auto_proxy_vpn.proxy_pool.getLogger") as mock_get_logger:
                with patch("auto_proxy_vpn.proxy_pool.ProxyManagers.get_manager") as mock_get_manager:
                    mock_logger = MagicMock()
                    mock_get_logger.return_value = mock_logger

                    manager_cls = MagicMock()
                    manager_cls.from_config.return_value = StubProxyManager("do")
                    mock_get_manager.return_value = manager_cls

                    pool = ProxyPool(config, log=True, logger=None)

        assert len(pool.managers) == 1
        mock_basic_config.assert_called_once()
        mock_get_logger.assert_called_once_with("proxy_logger")
