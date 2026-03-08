"""Unit tests for AWS provider (fully mocked boto3/botocore)."""

from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from auto_proxy_vpn.configs import ManagerRuntimeConfig


VALID_SSH_KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQAwsUnitTestKeyMaterial"


class MockClientError(Exception):
    """Small stand-in for botocore ClientError with .response payload."""

    def __init__(self, code: str, message: str = "mock error"):
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


def _make_mock_boto3_sdk():
    """Build a mock boto3 module surface used by ProxyManagerAws/AwsProxy."""
    # Shared EC2 client for constructor/default usage
    base_client = MagicMock()
    base_client.describe_regions.return_value = {
        "Regions": [
            {"RegionName": "us-east-1"},
            {"RegionName": "eu-west-1"},
        ]
    }
    base_client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupId": "sg-default"}]
    }

    # Shared resource
    base_resource = MagicMock()
    instance = MagicMock()
    instance.state = {"Name": "pending"}
    instance.id = "i-1"
    instance.public_ip_address = "54.0.0.1"
    base_resource.Instance.return_value = instance

    boto3_mock = MagicMock()
    boto3_mock.client.return_value = base_client
    boto3_mock.resource.return_value = base_resource

    return {
        "boto3": boto3_mock,
        "client": base_client,
        "resource": base_resource,
        "instance": instance,
    }


def _build_aws_manager(credentials: dict[str, str] | None = None, log: bool = False):
    sdk = _make_mock_boto3_sdk()

    with patch.dict(
        "sys.modules",
        {
            "boto3": sdk["boto3"],
            "botocore": MagicMock(),
            "botocore.exceptions": MagicMock(ClientError=MockClientError),
        },
    ):
        from auto_proxy_vpn.providers.aws.aws_proxy import ProxyManagerAws

        manager = ProxyManagerAws(
            ssh_key=VALID_SSH_KEY,
            credentials={
                "AWS_ACCESS_KEY_ID": "ak-test",
                "AWS_SECRET_ACCESS_KEY": "sk-test",
            }
            if credentials is None
            else credentials,
            log=log,
        )

    return manager, sdk


class TestProxyManagerAwsInit:
    def test_creates_manager_with_mocked_sdk(self):
        mgr, _ = _build_aws_manager()
        assert "us-east-1" in mgr._regions
        assert set(mgr._sizes_regions.keys()) == {"small", "medium", "large"}

    def test_sizes_mapping_is_expected(self):
        mgr, _ = _build_aws_manager()
        assert mgr._instance_proxy_sizes["small"] == "t3.nano"
        assert mgr._instance_proxy_sizes["medium"] == "t3.micro"
        assert mgr._instance_proxy_sizes["large"] == "t3.small"

    def test_uses_environment_credentials_when_not_passed(self):
        with patch.dict(
            "os.environ",
            {
                "AWS_ACCESS_KEY_ID": "env-ak",
                "AWS_SECRET_ACCESS_KEY": "env-sk",
            },
            clear=True,
        ):
            mgr, _ = _build_aws_manager(credentials={})

        assert mgr._aws_access_key_id == "env-ak"
        assert mgr._aws_secret_access_key == "env-sk"

    def test_no_credentials_raises_value_error(self):
        from auto_proxy_vpn.providers.aws.aws_proxy import ProxyManagerAws

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="credentials not provided"):
                ProxyManagerAws(ssh_key=VALID_SSH_KEY, credentials={})

    def test_reads_ssh_keys_from_file_path(self, tmp_path):
        key_file = Path(tmp_path) / "keys.pub"
        key_file.write_text(f"{VALID_SSH_KEY}\n{VALID_SSH_KEY}2\n", encoding="utf-8")

        sdk = _make_mock_boto3_sdk()
        with patch.dict(
            "sys.modules",
            {
                "boto3": sdk["boto3"],
                "botocore": MagicMock(),
                "botocore.exceptions": MagicMock(ClientError=MockClientError),
            },
        ):
            from auto_proxy_vpn.providers.aws.aws_proxy import ProxyManagerAws

            mgr = ProxyManagerAws(
                ssh_key=str(key_file),
                credentials={
                    "AWS_ACCESS_KEY_ID": "ak",
                    "AWS_SECRET_ACCESS_KEY": "sk",
                },
                log=False,
            )

        assert len(mgr.ssh_keys) == 2
        assert VALID_SSH_KEY in mgr.ssh_keys[0]

    def test_bad_ssh_key_dict_raises_type_error(self):
        sdk = _make_mock_boto3_sdk()
        with patch.dict(
            "sys.modules",
            {
                "boto3": sdk["boto3"],
                "botocore": MagicMock(),
                "botocore.exceptions": MagicMock(ClientError=MockClientError),
            },
        ):
            from auto_proxy_vpn.providers.aws.aws_proxy import ProxyManagerAws

            with pytest.raises(TypeError, match="Bad ssh_key"):
                ProxyManagerAws(
                    ssh_key=[{"name": "missing-public-key"}],  # type: ignore[list-item]
                    credentials={
                        "AWS_ACCESS_KEY_ID": "ak",
                        "AWS_SECRET_ACCESS_KEY": "sk",
                    },
                    log=False,
                )

    def test_no_valid_ssh_keys_raises_type_error(self):
        sdk = _make_mock_boto3_sdk()
        with patch.dict(
            "sys.modules",
            {
                "boto3": sdk["boto3"],
                "botocore": MagicMock(),
                "botocore.exceptions": MagicMock(ClientError=MockClientError),
            },
        ):
            from auto_proxy_vpn.providers.aws.aws_proxy import ProxyManagerAws

            with pytest.raises(TypeError, match="No valid ssh keys found"):
                ProxyManagerAws(
                    ssh_key=["invalid-key"],
                    credentials={
                        "AWS_ACCESS_KEY_ID": "ak",
                        "AWS_SECRET_ACCESS_KEY": "sk",
                    },
                    log=False,
                )

    def test_import_error_when_boto3_missing(self):
        from auto_proxy_vpn.providers.aws.aws_proxy import ProxyManagerAws

        real_import = builtins.__import__

        def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in {"boto3", "botocore.exceptions"}:
                raise ImportError("forced missing boto3")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=_fake_import):
            with pytest.raises(ImportError, match="boto3"):
                ProxyManagerAws(
                    ssh_key=VALID_SSH_KEY,
                    credentials={
                        "AWS_ACCESS_KEY_ID": "ak",
                        "AWS_SECRET_ACCESS_KEY": "sk",
                    },
                    log=False,
                )

    def test_logger_is_configured_when_enabled(self):
        sdk = _make_mock_boto3_sdk()
        with patch.dict(
            "sys.modules",
            {
                "boto3": sdk["boto3"],
                "botocore": MagicMock(),
                "botocore.exceptions": MagicMock(ClientError=MockClientError),
            },
        ):
            with patch("auto_proxy_vpn.providers.aws.aws_proxy.basicConfig") as mock_basic:
                from auto_proxy_vpn.providers.aws.aws_proxy import ProxyManagerAws

                mgr = ProxyManagerAws(
                    ssh_key=VALID_SSH_KEY,
                    credentials={
                        "AWS_ACCESS_KEY_ID": "ak",
                        "AWS_SECRET_ACCESS_KEY": "sk",
                    },
                    log=True,
                )

        assert mgr.logger is not None
        mock_basic.assert_called_once()

    def test_from_config_with_none_raises(self):
        from auto_proxy_vpn.providers.aws.aws_proxy import ProxyManagerAws

        with pytest.raises(ValueError):
            ProxyManagerAws.from_config(None, None)

    def test_from_config_success(self, aws_config):
        from auto_proxy_vpn.providers.aws.aws_proxy import ProxyManagerAws

        runtime = ManagerRuntimeConfig(log=False)
        with patch.object(ProxyManagerAws, "__init__", return_value=None) as mock_init:
            manager = ProxyManagerAws.from_config(aws_config, runtime)

        assert manager is not None
        mock_init.assert_called_once()

    def test_from_config_uses_default_runtime_when_none(self, aws_config):
        from auto_proxy_vpn.providers.aws.aws_proxy import ProxyManagerAws

        with patch.object(ProxyManagerAws, "__init__", return_value=None) as mock_init:
            manager = ProxyManagerAws.from_config(aws_config, None)

        assert manager is not None
        mock_init.assert_called_once()


class TestProxyManagerAwsGetProxy:
    def test_get_proxy_success(self):
        mgr, _ = _build_aws_manager()

        with patch.object(mgr, "get_running_proxy_names", return_value=[]):
            with patch(
                "auto_proxy_vpn.providers.aws.aws_proxy.get_public_ip",
                return_value="1.2.3.4",
            ):
                with patch(
                    "auto_proxy_vpn.providers.aws.aws_proxy.start_proxy",
                    return_value=("54.0.0.1", "i-1", "sg-1", False),
                ):
                    proxy = mgr.get_proxy(size="small", is_async=True)

        assert proxy.name.startswith("proxy")
        assert proxy.region in {"us-east-1", "eu-west-1"}

    def test_get_proxy_invalid_region_raises(self):
        mgr, _ = _build_aws_manager()

        with patch.object(mgr, "get_running_proxy_names", return_value=[]):
            with pytest.raises(ValueError, match="Region"):
                mgr.get_proxy(region="no-such-region")

    def test_get_proxy_duplicate_name_raises(self):
        mgr, _ = _build_aws_manager()

        with patch.object(mgr, "get_running_proxy_names", return_value=["proxy1"]):
            with pytest.raises(NameError, match="already exists"):
                mgr.get_proxy(proxy_name="proxy1")

    def test_get_proxy_bad_auth_type_raises(self):
        mgr, _ = _build_aws_manager()

        with patch.object(mgr, "get_running_proxy_names", return_value=[]):
            with pytest.raises(TypeError, match="auth"):
                mgr.get_proxy(auth="bad-auth")  # type: ignore[arg-type]

    def test_get_proxy_auth_missing_keys_raises(self):
        mgr, _ = _build_aws_manager()

        with patch.object(mgr, "get_running_proxy_names", return_value=[]):
            with pytest.raises(KeyError, match="two keys"):
                mgr.get_proxy(auth={"user": "only-user"})  # type: ignore[arg-type]

    def test_get_proxy_bad_allowed_ips_raises(self):
        mgr, _ = _build_aws_manager()

        with patch.object(mgr, "get_running_proxy_names", return_value=[]):
            with patch(
                "auto_proxy_vpn.providers.aws.aws_proxy.get_public_ip",
                return_value="1.2.3.4",
            ):
                with pytest.raises(TypeError, match="bad format"):
                    mgr.get_proxy(allowed_ips=["bad-ip"])

    def test_get_proxy_retries_and_then_fails(self):
        mgr, _ = _build_aws_manager()

        with patch.object(mgr, "get_running_proxy_names", return_value=[]):
            with patch(
                "auto_proxy_vpn.providers.aws.aws_proxy.get_public_ip",
                return_value="1.2.3.4",
            ):
                with patch(
                    "auto_proxy_vpn.providers.aws.aws_proxy.start_proxy",
                    side_effect=[
                        ("", "", "", True),
                        ("", "", "", True),
                    ],
                ):
                    with pytest.raises(Exception, match="Failed to start"):
                        mgr.get_proxy(region="", retry=True)

    def test_get_proxy_name_autoincrements_when_existing_names_taken(self):
        mgr, _ = _build_aws_manager()

        with patch.object(mgr, "get_running_proxy_names", return_value=["proxy1", "proxy2", "proxy3"]):
            with patch("auto_proxy_vpn.providers.aws.aws_proxy.get_public_ip", return_value="1.2.3.4"):
                with patch(
                    "auto_proxy_vpn.providers.aws.aws_proxy.start_proxy",
                    return_value=("54.0.0.2", "i-2", "sg-2", False),
                ):
                    proxy = mgr.get_proxy(size="small", is_async=True)

        assert proxy.name == "proxy4"

    def test_get_proxy_accepts_allowed_ips_string(self):
        mgr, _ = _build_aws_manager()

        with patch.object(mgr, "get_running_proxy_names", return_value=[]):
            with patch("auto_proxy_vpn.providers.aws.aws_proxy.get_public_ip", return_value="1.2.3.4"):
                with patch(
                    "auto_proxy_vpn.providers.aws.aws_proxy.start_proxy",
                    return_value=("54.0.0.3", "i-3", "sg-3", False),
                ) as start_mock:
                    proxy = mgr.get_proxy(allowed_ips="8.8.8.8", size="small", is_async=True)

        assert proxy.ip == "54.0.0.3"
        assert start_mock.call_args.args[5] == ["8.8.8.8", "1.2.3.4"]

    def test_get_proxy_logs_info_warning_and_error(self):
        mgr, _ = _build_aws_manager()
        mgr.logger = MagicMock()

        with patch.object(mgr, "get_running_proxy_names", return_value=[]):
            with patch("auto_proxy_vpn.providers.aws.aws_proxy.get_public_ip", return_value="1.2.3.4"):
                with patch(
                    "auto_proxy_vpn.providers.aws.aws_proxy.start_proxy",
                    side_effect=[("", "", "", True), ("", "", "", True)],
                ):
                    with pytest.raises(Exception, match="Failed to start"):
                        mgr.get_proxy(size="small", is_async=True)

        assert mgr.logger.info.called
        assert mgr.logger.warning.called
        assert mgr.logger.error.called


class TestProxyManagerAwsReloadAndList:
    def test_get_proxy_by_name_not_found_raises(self):
        mgr, _ = _build_aws_manager()

        with patch.object(mgr, "get_running_proxy_names", return_value=[]):
            with pytest.raises(NameError, match="has been found"):
                mgr.get_proxy_by_name("proxy404")

    def test_get_proxy_by_name_cant_connect_raises(self):
        mgr, sdk = _build_aws_manager()

        client = MagicMock()
        client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-1",
                            "NetworkInterfaces": [{"Groups": [{"GroupId": "sg-1"}]}],
                            "PublicIpAddress": "54.0.0.1",
                            "InstanceType": "t3.micro",
                        }
                    ]
                }
            ]
        }
        sdk["boto3"].client.return_value = client

        with patch.object(mgr, "get_running_proxy_names", return_value=[("proxy1", "us-east-1")]):
            with patch("auto_proxy_vpn.providers.aws.aws_proxy.SSHClient") as ssh_cls:
                ssh_cls.return_value.run_command.return_value = ("", "", "")
                with pytest.raises(ConnectionError, match="AWS proxy"):
                    mgr.get_proxy_by_name("proxy1")

    def test_get_proxy_by_name_bad_port_raises(self):
        mgr, sdk = _build_aws_manager()

        client = MagicMock()
        client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-1",
                            "NetworkInterfaces": [{"Groups": [{"GroupId": "sg-1"}]}],
                            "PublicIpAddress": "54.0.0.1",
                            "InstanceType": "t3.micro",
                        }
                    ]
                }
            ]
        }
        sdk["boto3"].client.return_value = client

        with patch.object(mgr, "get_running_proxy_names", return_value=[("proxy1", "us-east-1")]):
            with patch("auto_proxy_vpn.providers.aws.aws_proxy.SSHClient") as ssh_cls:
                ssh_cls.return_value.run_command.return_value = ("", "acl custom_ips src 1.2.3.4", "")
                with pytest.raises(ValueError, match="proxy port"):
                    mgr.get_proxy_by_name("proxy1")

    def test_get_proxy_by_name_success(self):
        mgr, sdk = _build_aws_manager()

        client = MagicMock()
        client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-1",
                            "NetworkInterfaces": [{"Groups": [{"GroupId": "sg-1"}]}],
                            "PublicIpAddress": "54.0.0.1",
                            "InstanceType": "t3.micro",
                        }
                    ]
                }
            ]
        }
        sdk["boto3"].client.return_value = client

        squid_cfg = """http_port 3128
acl custom_ips src 1.2.3.4
#auth credentials: user: u1, password: p1
"""

        with patch.object(mgr, "get_running_proxy_names", return_value=[("proxy1", "us-east-1")]):
            with patch("auto_proxy_vpn.providers.aws.aws_proxy.SSHClient") as ssh_cls:
                ssh_cls.return_value.run_command.return_value = ("", squid_cfg, "")
                with patch("auto_proxy_vpn.providers.aws.aws_proxy.AwsProxy.is_active", return_value=True):
                    proxy = mgr.get_proxy_by_name("proxy1", is_async=True)

        assert proxy.port == 3128
        assert proxy.user == "u1"
        assert proxy.password == "p1"

    def test_get_proxy_by_name_logs_reload_info(self):
        mgr, sdk = _build_aws_manager()
        mgr.logger = MagicMock()

        client = MagicMock()
        client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-1",
                            "NetworkInterfaces": [{"Groups": [{"GroupId": "sg-1"}]}],
                            "PublicIpAddress": "54.0.0.1",
                            "InstanceType": "t3.micro",
                        }
                    ]
                }
            ]
        }
        sdk["boto3"].client.return_value = client

        squid_cfg = "http_port 3128\nacl custom_ips src 1.2.3.4\n"

        with patch.object(mgr, "get_running_proxy_names", return_value=[("proxy1", "us-east-1")]):
            with patch("auto_proxy_vpn.providers.aws.aws_proxy.SSHClient") as ssh_cls:
                ssh_cls.return_value.run_command.return_value = ("", squid_cfg, "")
                with patch("auto_proxy_vpn.providers.aws.aws_proxy.AwsProxy.is_active", return_value=True):
                    _ = mgr.get_proxy_by_name("proxy1", is_async=True)

        assert mgr.logger.info.called

    def test_get_running_proxy_names_with_and_without_regions(self):
        mgr, _ = _build_aws_manager()

        fake_all = [[("proxy1", "us-east-1")], [("proxy2", "eu-west-1")]]

        class _FakeExecutor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def map(self, func, managers, regions):
                return fake_all

        with patch("auto_proxy_vpn.providers.aws.aws_proxy.ThreadPoolExecutor", _FakeExecutor):
            names = mgr.get_running_proxy_names()
            names_regions = mgr.get_running_proxy_names(return_region=True)

        assert names == ["proxy1", "proxy2"]
        assert names_regions == [("proxy1", "us-east-1"), ("proxy2", "eu-west-1")]


class TestAwsProxy:
    def _make_proxy(self, on_exit: str = "destroy", is_async: bool = True):
        mgr, sdk = _build_aws_manager()
        # Keep VM as pending for async path to avoid network probe in BaseProxy.is_active.
        sdk["instance"].state = {"Name": "pending"}
        proxy = None
        with patch("auto_proxy_vpn.providers.aws.aws_proxy.AwsProxy.is_active", return_value=True):
            proxy = __import__(
                "auto_proxy_vpn.providers.aws.aws_proxy", fromlist=["AwsProxy"]
            ).AwsProxy(
                manager=mgr,
                instance_id="i-1",
                group_id="sg-1",
                name="proxy1",
                ip="54.0.0.1",
                port=3128,
                region="us-east-1",
                is_async=is_async,
                on_exit=on_exit,  # type: ignore[arg-type]
            )
        return proxy, sdk

    def test_bad_on_exit_raises(self):
        mgr, _ = _build_aws_manager()
        from auto_proxy_vpn.providers.aws.aws_proxy import AwsProxy

        with pytest.raises(ValueError, match="on_exit"):
            AwsProxy(
                manager=mgr,
                instance_id="i-1",
                group_id="sg-1",
                name="proxy1",
                ip="54.0.0.1",
                port=3128,
                region="us-east-1",
                is_async=True,
                on_exit="invalid",  # type: ignore[arg-type]
            )

    def test_stop_proxy_destroy(self):
        proxy, _ = self._make_proxy(on_exit="destroy", is_async=True)
        proxy._stop_proxy()

        assert proxy.stopped is True
        assert proxy.ip == ""
        assert proxy.port == 0

    def test_stop_proxy_keep(self):
        proxy, _ = self._make_proxy(on_exit="keep", is_async=True)
        proxy._stop_proxy()

        # keep mode still marks object as stopped/cleared for local lifecycle
        assert proxy.stopped is True

    def test_stop_proxy_already_stopped_noop(self):
        proxy, _ = self._make_proxy(on_exit="destroy", is_async=True)
        proxy.stopped = True
        old_ip = proxy.ip
        proxy._stop_proxy()
        assert proxy.ip == old_ip

    def test_is_active_async_without_wait_keeps_inactive_when_not_running(self):
        mgr, sdk = _build_aws_manager()
        from auto_proxy_vpn.providers.aws.aws_proxy import AwsProxy

        sdk["instance"].state = {"Name": "pending"}
        proxy = AwsProxy(
            manager=mgr,
            instance_id="i-1",
            group_id="sg-1",
            name="proxy1",
            ip="54.0.0.1",
            port=3128,
            region="us-east-1",
            is_async=True,
            reload=True,
        )
        proxy.active = False

        assert proxy.is_active(wait=False) is False

    def test_is_active_wait_calls_base(self):
        mgr, sdk = _build_aws_manager()
        from auto_proxy_vpn.providers.aws.aws_proxy import AwsProxy

        sdk["instance"].state = {"Name": "running"}
        with patch("auto_proxy_vpn.providers.aws.aws_proxy.BaseProxy.is_active", return_value=True) as base_active:
            proxy = AwsProxy(
                manager=mgr,
                instance_id="i-1",
                group_id="sg-1",
                name="proxy1",
                ip="54.0.0.1",
                port=3128,
                region="us-east-1",
                is_async=True,
                reload=True,
            )
            assert proxy.is_active(wait=True) is True

        assert base_active.called

    def test_str_includes_aws(self):
        proxy, _ = self._make_proxy(on_exit="destroy", is_async=True)
        assert "AWS" in str(proxy)

    def test_init_logs_create_and_reload_paths(self):
        mgr, _ = _build_aws_manager()
        logger = MagicMock()

        from auto_proxy_vpn.providers.aws.aws_proxy import AwsProxy

        with patch("auto_proxy_vpn.providers.aws.aws_proxy.BaseProxy.is_active", return_value=True):
            _ = AwsProxy(
                manager=mgr,
                instance_id="i-1",
                group_id="sg-1",
                name="proxy-new",
                ip="54.0.0.9",
                port=3128,
                region="us-east-1",
                is_async=False,
                logger=logger,
                reload=False,
            )

        with patch("auto_proxy_vpn.providers.aws.aws_proxy.BaseProxy.is_active", return_value=False):
            _ = AwsProxy(
                manager=mgr,
                instance_id="i-2",
                group_id="sg-2",
                name="proxy-reload",
                ip="54.0.0.10",
                port=3128,
                region="us-east-1",
                is_async=True,
                logger=logger,
                reload=True,
            )

        assert logger.info.called

    def test_is_active_sync_waits_until_running(self):
        mgr, sdk = _build_aws_manager()
        from auto_proxy_vpn.providers.aws.aws_proxy import AwsProxy

        sdk["instance"].state = {"Name": "pending"}
        with patch("auto_proxy_vpn.providers.aws.aws_proxy.BaseProxy.is_active", return_value=True):
            proxy = AwsProxy(
                manager=mgr,
                instance_id="i-3",
                group_id="sg-3",
                name="proxy-sync",
                ip="54.0.0.11",
                port=3128,
                region="us-east-1",
                is_async=False,
                reload=True,
            )

        assert proxy._vm_started is True
        sdk["instance"].wait_until_running.assert_called()

    def test_stop_proxy_destroy_wait_and_logs(self):
        mgr, _ = _build_aws_manager()
        from auto_proxy_vpn.providers.aws.aws_proxy import AwsProxy

        logger = MagicMock()
        with patch("auto_proxy_vpn.providers.aws.aws_proxy.BaseProxy.is_active", return_value=True):
            proxy = AwsProxy(
                manager=mgr,
                instance_id="i-4",
                group_id="sg-4",
                name="proxy-stop",
                ip="54.0.0.12",
                port=3128,
                region="us-east-1",
                is_async=False,
                logger=logger,
                reload=True,
                on_exit="destroy",
            )

        instance = proxy._resource.Instance.return_value # type: ignore
        proxy._stop_proxy(wait=True)

        instance.wait_until_terminated.assert_called_once()
        assert logger.info.called

    def test_stop_proxy_keep_logs_message(self):
        mgr, _ = _build_aws_manager()
        from auto_proxy_vpn.providers.aws.aws_proxy import AwsProxy

        logger = MagicMock()
        with patch("auto_proxy_vpn.providers.aws.aws_proxy.BaseProxy.is_active", return_value=True):
            proxy = AwsProxy(
                manager=mgr,
                instance_id="i-5",
                group_id="sg-5",
                name="proxy-keep",
                ip="54.0.0.13",
                port=3128,
                region="us-east-1",
                is_async=True,
                logger=logger,
                reload=True,
                on_exit="keep",
            )

        proxy._stop_proxy()
        assert logger.info.called
