"""Tests for BaseProxy, ProxyBatch, and BaseProxyManager base behaviour."""

import pytest
from unittest.mock import patch, MagicMock

from auto_proxy_vpn.utils.base_proxy import BaseProxy, BaseProxyManager, ProxyBatch
from auto_proxy_vpn.utils.exceptions import ProxyIpNotAvailableException
from tests.conftest import StubProxy, StubProxyManager


# ============================================================================
# BaseProxy
# ============================================================================

class TestBaseProxyStr:
    """Proxy string / URL generation."""

    def test_get_proxy_str_no_auth(self, stub_proxy):
        assert stub_proxy.get_proxy_str() == "http://1.2.3.4:12345"

    def test_get_proxy_str_with_auth(self, stub_proxy_with_auth):
        assert stub_proxy_with_auth.get_proxy_str() == "http://admin:s3cret@1.2.3.4:12345"

    def test_get_proxy_str_empty_when_no_ip(self, inactive_proxy):
        assert inactive_proxy.get_proxy_str() == ""

    def test_get_proxy_returns_dict(self, stub_proxy):
        result = stub_proxy.get_proxy()
        assert result == {"http": "http://1.2.3.4:12345", "https": "http://1.2.3.4:12345"}

    def test_get_proxy_returns_none_when_no_ip(self, inactive_proxy):
        assert inactive_proxy.get_proxy() is None

    def test_str_contains_name_and_url(self, stub_proxy):
        s = str(stub_proxy)
        assert "stub-proxy" in s
        assert "1.2.3.4" in s

    def test_repr_equals_str(self, stub_proxy):
        assert repr(stub_proxy) == str(stub_proxy)

    def test_str_shows_active(self, stub_proxy):
        assert "(active)" in str(stub_proxy)

    def test_str_shows_inactive(self, inactive_proxy):
        # inactive_proxy has no IP, so it won't show the url
        inactive_proxy.ip = "5.5.5.5"
        inactive_proxy.active = False
        assert "(inactive)" in str(inactive_proxy)


class TestBaseProxyIsActive:
    """Checking is_active with mocked IP resolution."""

    @patch("auto_proxy_vpn.utils.base_proxy.get_public_ip", return_value="1.2.3.4")
    def test_is_active_returns_true_for_matching_ip(self, mock_ip, stub_proxy):
        stub_proxy.active = False
        result = stub_proxy.is_active(wait=True)
        assert result is True

    def test_is_active_raises_when_no_ip(self, inactive_proxy):
        with pytest.raises(ProxyIpNotAvailableException):
            inactive_proxy.is_active()


class TestBaseProxyContextManager:
    """Context manager (with statement) behaviour."""

    @patch("auto_proxy_vpn.utils.base_proxy.get_public_ip", return_value="1.2.3.4")
    def test_enter_returns_proxy_when_active(self, mock_ip, stub_proxy):
        stub_proxy.active = False
        with stub_proxy as p:
            assert p is stub_proxy

    def test_exit_calls_stop(self, stub_proxy):
        stub_proxy.__exit__(None, None, None)
        assert stub_proxy.stopped is True

    def test_close_calls_stop(self, stub_proxy):
        stub_proxy.close()
        assert stub_proxy.stopped is True


# ============================================================================
# ProxyBatch
# ============================================================================

class TestProxyBatch:
    """Tests for the ProxyBatch container."""

    def test_len(self, proxy_batch):
        assert len(proxy_batch) == 5

    def test_iter(self, proxy_batch):
        items = list(proxy_batch)
        assert len(items) == 5
        assert all(isinstance(p, StubProxy) for p in items)

    def test_getitem_int(self, proxy_batch):
        p = proxy_batch[0]
        assert isinstance(p, StubProxy)

    def test_getitem_slice(self, proxy_batch):
        ps = proxy_batch[1:3]
        assert len(ps) == 2

    def test_next_iterates_and_stops(self, proxy_batch):
        results = []
        for _ in range(5):
            results.append(next(proxy_batch))
        with pytest.raises(StopIteration):
            next(proxy_batch)
        assert len(results) == 5

    def test_close_marks_batch_closed(self, proxy_batch):
        proxy_batch.close()
        with pytest.raises(RuntimeError, match="closed"):
            len(proxy_batch)

    def test_close_stops_all_proxies(self, proxy_batch):
        proxy_batch.close()
        assert all(p.stopped for p in proxy_batch.proxies)

    def test_double_close_is_safe(self, proxy_batch):
        proxy_batch.close()
        proxy_batch.close()  # should not raise

    def test_context_manager_closes(self, proxy_batch):
        with proxy_batch:
            pass
        assert proxy_batch._closed

    def test_operations_after_close_raise(self, proxy_batch):
        proxy_batch.close()
        with pytest.raises(RuntimeError):
            list(proxy_batch)
        with pytest.raises(RuntimeError):
            proxy_batch[0]
        with pytest.raises(RuntimeError):
            next(proxy_batch)


# ============================================================================
# BaseProxyManager — get_proxies validation
# ============================================================================

class TestBaseProxyManagerGetProxies:
    """Tests for parameter validation in BaseProxyManager.get_proxies."""

    def test_returns_proxy_batch(self, stub_manager):
        batch = stub_manager.get_proxies(3)
        assert isinstance(batch, ProxyBatch)
        assert len(batch) == 3

    def test_mismatched_ports_list_raises(self, stub_manager):
        with pytest.raises(ValueError, match="ports"):
            stub_manager.get_proxies(3, ports=[80, 81])

    def test_mismatched_sizes_list_raises(self, stub_manager):
        with pytest.raises(ValueError, match="sizes"):
            stub_manager.get_proxies(2, sizes=["small"])

    def test_mismatched_regions_list_raises(self, stub_manager):
        with pytest.raises(ValueError, match="regions"):
            stub_manager.get_proxies(2, regions=["region-a", "region-b", "region-c"])

    def test_mismatched_auths_list_raises(self, stub_manager):
        with pytest.raises(ValueError, match="auths"):
            stub_manager.get_proxies(2, auths=[{"user": "a", "password": "b"}])

    def test_mismatched_proxy_names_list_raises(self, stub_manager):
        with pytest.raises(ValueError, match="proxy_names"):
            stub_manager.get_proxies(2, proxy_names=["a"])

    def test_invalid_size_string_raises(self, stub_manager):
        with pytest.raises(ValueError, match="Invalid size"):
            stub_manager.get_proxies(1, sizes="huge")

    def test_invalid_size_in_list_raises(self, stub_manager):
        with pytest.raises(ValueError, match="Invalid size"):
            stub_manager.get_proxies(2, sizes=["small", "tiny"])

    def test_invalid_region_string_raises(self, stub_manager):
        with pytest.raises(ValueError, match="region"):
            stub_manager.get_proxies(1, regions="nonexistent")

    def test_invalid_auth_type_raises(self, stub_manager):
        with pytest.raises(TypeError, match="auth"):
            stub_manager.get_proxies(1, auths="not-a-dict")

    def test_auth_missing_keys_raises(self, stub_manager):
        with pytest.raises(KeyError, match="two keys"):
            stub_manager.get_proxies(1, auths={"user": "u"})

    def test_auth_list_missing_keys_raises(self, stub_manager):
        with pytest.raises(KeyError, match="two keys"):
            stub_manager.get_proxies(1, auths=[{"user": "u"}])

    def test_valid_params_pass(self, stub_manager):
        batch = stub_manager.get_proxies(
            2,
            ports=[8080, 8081],
            sizes=["small", "medium"],
            regions=["region-a", "region-b"],
            auths=[{"user": "u1", "password": "p1"}, {"user": "u2", "password": "p2"}],
            proxy_names=["n1", "n2"],
        )
        assert len(batch) == 2


class TestBaseProxyManagerSizesRegions:
    """Tests for get_sizes_and_regions / get_regions_by_size."""

    def test_get_sizes_and_regions(self, stub_manager):
        sr = stub_manager.get_sizes_and_regions()
        assert "small" in sr
        assert "medium" in sr
        assert "large" in sr

    def test_get_regions_by_size(self, stub_manager):
        regions = stub_manager.get_regions_by_size("small")
        assert "region-a" in regions

    def test_get_regions_by_invalid_size_raises(self, stub_manager):
        with pytest.raises(NameError):
            stub_manager.get_regions_by_size("tiny")
