from types import SimpleNamespace
from unittest.mock import MagicMock
from io import StringIO

import pytest

from auto_proxy_vpn.providers.google import google_utils


class TestWaitForExtendedOperation:
    def test_returns_result_without_warnings(self):
        operation = SimpleNamespace(
            result=lambda timeout=0: "ok",
            error_code=None,
            warnings=[],
        )
        assert google_utils.wait_for_extended_operation(operation, timeout=10) == "ok"

    def test_raises_runtime_error_when_error_code_and_no_exception(self):
        operation = SimpleNamespace(
            result=lambda timeout=0: None,
            error_code=1,
            error_message="failed",
            exception=lambda: None,
            warnings=[],
        )
        with pytest.raises(RuntimeError, match="failed"):
            google_utils.wait_for_extended_operation(operation)

    def test_prints_warnings(self, monkeypatch):
        warning = SimpleNamespace(code="WARN", message="be careful")
        operation = SimpleNamespace(
            result=lambda timeout=0: "ok",
            error_code=None,
            warnings=[warning],
        )
        stream = StringIO()
        monkeypatch.setattr(google_utils, "stderr", stream)
        assert google_utils.wait_for_extended_operation(operation) == "ok"
        err = stream.getvalue()
        assert "Warnings during operation" in err
        assert "WARN: be careful" in err


class TestGetAvailableRegionsBySize:
    def test_builds_region_mapping(self):
        compute_v1 = SimpleNamespace(
            AggregatedListMachineTypesRequest=lambda **kwargs: kwargs,
        )

        zone_with_types = SimpleNamespace(machine_types=[SimpleNamespace(name="e2-micro")])
        zone_empty = SimpleNamespace(machine_types=[])

        machine_types_client = SimpleNamespace(
            aggregated_list=lambda request: [
                ("zones/us-central1-a", zone_with_types),
                ("zones/us-central1-b", zone_with_types),
                ("zones/europe-west1-b", zone_with_types),
                ("zones/asia-east1-a", zone_empty),
            ]
        )

        regions, by_size = google_utils.get_avaliable_regions_by_size(
            compute_v1,
            machine_types_client,
            "proj",
            {"small": "e2-micro", "medium": "e2-small", "large": "e2-standard-2"},
        )

        assert ("us-central1", ["us-central1-a", "us-central1-b"]) in regions
        assert ("europe-west1", ["europe-west1-b"]) in regions
        assert len(by_size["small"]) >= 2
        assert by_size["small"] == by_size["medium"] == by_size["large"]


class TestStartProxy:
    def _build_manager(self):
        compute_v1 = SimpleNamespace(
            Firewall=lambda **kwargs: kwargs,
            InsertInstanceRequest=lambda **kwargs: kwargs,
            GetInstanceRequest=lambda **kwargs: kwargs,
        )

        manager = SimpleNamespace(
            _compute_v1=compute_v1,
            _firewall_client=SimpleNamespace(insert=lambda **kwargs: None),
            _instances_client=SimpleNamespace(),
            project="test-project",
            proxy_image="ubuntu-image",
            ssh_keys=["ssh-rsa AAAA"],
            logger=MagicMock(),
        )

        class ServiceUnavailable(Exception):
            pass

        manager._google_exceptions = SimpleNamespace(ServiceUnavailable=ServiceUnavailable)
        return manager, ServiceUnavailable

    def test_returns_ip_when_operation_succeeds(self, monkeypatch):
        manager, _ = self._build_manager()

        operation = SimpleNamespace(result=lambda timeout=0: None, error_code=None, warnings=[])
        manager._instances_client.insert = lambda request: operation
        manager._instances_client.get = lambda request: SimpleNamespace(
            network_interfaces=[SimpleNamespace(access_configs=[SimpleNamespace(nat_i_p="35.1.2.3")])]
        )

        monkeypatch.setattr(google_utils, "get_squid_file", lambda *args, **kwargs: "#!/bin/bash")

        ip, error = google_utils.start_proxy(
            proxy_manager=manager, # type: ignore
            proxy_name="proxy1",
            port=3128,
            region="us-central1",
            zone="us-central1-a",
            zones=["us-central1-b"],
            machine_type="e2-micro",
            allowed_ips=["0.0.0.0/0"],
            is_async=False,
        )

        assert ip == "35.1.2.3"
        assert error is False

    def test_returns_error_when_zone_unavailable_and_no_fallback(self, monkeypatch):
        manager, service_unavailable = self._build_manager()

        operation = SimpleNamespace(result=lambda timeout=0: None, error_code=None, warnings=[])
        manager._instances_client.insert = lambda request: operation
        manager._instances_client.get = lambda request: SimpleNamespace(
            network_interfaces=[SimpleNamespace(access_configs=[SimpleNamespace(nat_i_p="35.1.2.3")])]
        )

        def raise_unavailable(*args, **kwargs):
            raise service_unavailable("zone unavailable")

        monkeypatch.setattr(google_utils, "wait_for_extended_operation", raise_unavailable)
        monkeypatch.setattr(google_utils, "get_squid_file", lambda *args, **kwargs: "#!/bin/bash")

        ip, error = google_utils.start_proxy(
            proxy_manager=manager, # type: ignore
            proxy_name="proxy1",
            port=3128,
            region="us-central1",
            zone="us-central1-a",
            zones=[],
            machine_type="e2-micro",
            allowed_ips=["0.0.0.0/0"],
            is_async=False,
        )

        assert ip == ""
        assert error is True
