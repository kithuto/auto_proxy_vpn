"""Unit tests for AWS utility helpers (aws_utils.py)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from auto_proxy_vpn.providers.aws.aws_exceptions import AwsUnauthorizedOperationError
from auto_proxy_vpn.providers.aws.aws_utils import get_region_instances, start_proxy


class MockClientError(Exception):
    def __init__(self, code: str, message: str = "mock error"):
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


class _ManagerStub:
    def __init__(self):
        self._aws_access_key_id = "ak"
        self._aws_secret_access_key = "sk"
        self._os_image_filters = [{"Name": "name", "Values": ["ubuntu"]}]
        self._aws_ClientError = MockClientError
        self.ssh_keys = ["ssh-rsa AAAA..."]
        self._boto3 = MagicMock()


def _setup_clients_for_start() -> tuple[_ManagerStub, MagicMock, MagicMock, MagicMock]:
    manager = _ManagerStub()

    client = MagicMock()
    ec2_resource = MagicMock()
    instance = MagicMock()
    instance.id = "i-123"
    instance.public_ip_address = "54.0.0.10"
    ec2_resource.create_instances.return_value = [instance]

    manager._boto3.client.return_value = client
    manager._boto3.resource.return_value = ec2_resource

    return manager, client, ec2_resource, instance


class TestGetRegionInstances:
    def test_returns_name_region_pairs(self):
        manager = _ManagerStub()
        client = MagicMock()
        client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {"Tags": [{"Key": "Name", "Value": "proxy1"}]},
                        {"Tags": [{"Key": "Name", "Value": "proxy2"}]},
                    ]
                }
            ]
        }
        manager._boto3.client.return_value = client

        result = get_region_instances(manager, "us-east-1") # type: ignore

        assert result == [("proxy1", "us-east-1"), ("proxy2", "us-east-1")]

    def test_ignores_instances_without_name_tag(self):
        manager = _ManagerStub()
        client = MagicMock()
        client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {"Tags": [{"Key": "Other", "Value": "x"}]},
                    ]
                }
            ]
        }
        manager._boto3.client.return_value = client

        assert get_region_instances(manager, "eu-west-1") == [] # type: ignore


class TestStartProxy:
    def test_returns_error_true_when_no_ami_found(self):
        manager, client, _, _ = _setup_clients_for_start()
        client.describe_images.return_value = {"Images": []}

        ip, instance_id, sg_id, error = start_proxy(
            manager,  # type: ignore
            "proxy1",
            3128,
            "us-east-1",
            "t3.micro",
            ["1.2.3.4"],
            is_async=True,
        )

        assert (ip, instance_id, sg_id, error) == ("", "", "", True)

    def test_success_async_does_not_wait(self):
        manager, client, _, instance = _setup_clients_for_start()
        client.describe_images.return_value = {
            "Images": [{"ImageId": "ami-1", "CreationDate": "2025-01-01"}]
        }
        client.create_security_group.return_value = {"GroupId": "sg-1"}

        ip, instance_id, sg_id, error = start_proxy(
            manager,  # type: ignore
            "proxy1",
            3128,
            "us-east-1",
            "t3.micro",
            ["1.2.3.4"],
            is_async=True,
        )

        assert error is False
        assert ip == "54.0.0.10"
        assert instance_id == "i-123"
        assert sg_id == "sg-1"
        instance.wait_until_running.assert_not_called()

    def test_success_sync_waits_for_instance(self):
        manager, client, _, instance = _setup_clients_for_start()
        client.describe_images.return_value = {
            "Images": [{"ImageId": "ami-1", "CreationDate": "2025-01-01"}]
        }
        client.create_security_group.return_value = {"GroupId": "sg-1"}

        _, _, _, error = start_proxy(
            manager, # type: ignore
            "proxy1",
            3128,
            "us-east-1",
            "t3.micro",
            ["1.2.3.4"],
            is_async=False,
        )

        assert error is False
        instance.wait_until_running.assert_called_once()
        instance.reload.assert_called_once()

    def test_unauthorized_operation_raises_custom_exception(self):
        manager, client, ec2_resource, _ = _setup_clients_for_start()
        client.describe_images.return_value = {
            "Images": [{"ImageId": "ami-1", "CreationDate": "2025-01-01"}]
        }
        client.create_security_group.return_value = {"GroupId": "sg-1"}
        ec2_resource.create_instances.side_effect = MockClientError("UnauthorizedOperation")

        with pytest.raises(AwsUnauthorizedOperationError):
            start_proxy(
                manager, # type: ignore
                "proxy1",
                3128,
                "us-east-1",
                "t3.micro",
                ["1.2.3.4"],
                is_async=True,
            )

        client.delete_security_group.assert_called_once_with(GroupId="sg-1")

    def test_insufficient_capacity_returns_error(self):
        manager, client, ec2_resource, _ = _setup_clients_for_start()
        client.describe_images.return_value = {
            "Images": [{"ImageId": "ami-1", "CreationDate": "2025-01-01"}]
        }
        client.create_security_group.return_value = {"GroupId": "sg-1"}
        ec2_resource.create_instances.side_effect = MockClientError("InsufficientInstanceCapacity")

        ip, instance_id, sg_id, error = start_proxy(
            manager, # type: ignore
            "proxy1",
            3128,
            "us-east-1",
            "t3.micro",
            ["1.2.3.4"],
            is_async=True,
        )

        assert (ip, instance_id, sg_id, error) == ("", "", "", True)
        client.delete_security_group.assert_called_once_with(GroupId="sg-1")

    def test_unknown_client_error_is_re_raised(self):
        manager, client, ec2_resource, _ = _setup_clients_for_start()
        client.describe_images.return_value = {
            "Images": [{"ImageId": "ami-1", "CreationDate": "2025-01-01"}]
        }
        client.create_security_group.return_value = {"GroupId": "sg-1"}
        ec2_resource.create_instances.side_effect = MockClientError("InternalError")

        with pytest.raises(MockClientError):
            start_proxy(
                manager, # type: ignore
                "proxy1",
                3128,
                "us-east-1",
                "t3.micro",
                ["1.2.3.4"],
                is_async=True,
            )

        client.delete_security_group.assert_called_once_with(GroupId="sg-1")

    def test_ingress_uses_cidr32_for_plain_ips_and_keeps_cidr(self):
        manager, client, _, _ = _setup_clients_for_start()
        client.describe_images.return_value = {
            "Images": [{"ImageId": "ami-1", "CreationDate": "2025-01-01"}]
        }
        client.create_security_group.return_value = {"GroupId": "sg-1"}

        start_proxy(
            manager, # type: ignore
            "proxy1",
            3128,
            "us-east-1",
            "t3.micro",
            ["1.2.3.4", "5.6.7.0/24"],
            is_async=True,
        )

        kwargs = client.authorize_security_group_ingress.call_args.kwargs
        ip_ranges = kwargs["IpPermissions"][0]["IpRanges"]
        cidrs = {entry["CidrIp"] for entry in ip_ranges}
        assert "1.2.3.4/32" in cidrs
        assert "5.6.7.0/24" in cidrs
