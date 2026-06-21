from logging import INFO, Logger, basicConfig, getLogger
from os import environ
from os.path import isfile
from typing import Literal
from random import randint, shuffle, choice
from re import search, finditer
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from auto_proxy_vpn import CloudProvider, ProxyManagers, AwsConfig, ManagerRuntimeConfig
from auto_proxy_vpn.utils.base_proxy import BaseProxy, BaseProxyManager
from auto_proxy_vpn.utils.proxy_auth import (
    normalize_proxy_auth,
    resolve_reloaded_proxy_auth,
)
from auto_proxy_vpn.utils.ssh_client import SSHClient
from auto_proxy_vpn.utils.util import is_ssh_key, get_public_ip, normalize_allowed_ips
from .aws_utils import get_region_instances, start_proxy


class AwsProxy(BaseProxy):
    """Represent an AWS EC2-based proxy instance.

    This object stores proxy metadata and runtime state and can be initialized
    either for a newly created proxy EC2 instance or by reloading an existing
    one.

    Parameters
    ----------
    manager : ProxyManagerAws
        Manager instance that owns AWS SDK clients and credentials used by this
        proxy.
    instance_id : str
        AWS EC2 instance ID for the proxy VM.
    group_id : str
        AWS security group ID associated with the proxy instance.
    name : str
        Proxy name stored in EC2 tags.
    ip : str
        Public IPv4 address of the proxy.
    port : int
        Proxy listening TCP port.
    region : str
        AWS region where the proxy resources are deployed.
    proxy_instance : str, optional
        EC2 instance type used for this proxy (for example ``'t3.micro'``).
        Defaults to ``''``.
    allowed_ips : list[str], optional
        Source IPs/ranges allowed to connect to the proxy. Used for
        startup/reload metadata. Defaults to an empty list.
    is_async : bool, optional
        If True, do not block waiting for full startup/teardown completion.
        Defaults to ``False``.
    user : str, optional
        Basic-auth username configured in Squid. Defaults to ``''``.
    password : str, optional
        Basic-auth password configured in Squid. Defaults to ``''``.
    logger : Logger or None, optional
        Logger used for lifecycle and status messages. Defaults to ``None``.
    reload : bool, optional
        If True, this object is being created from an existing proxy and emits
        reload-oriented log messages. Defaults to ``False``.
    on_exit : {'keep', 'destroy'}, optional
        Behavior when the proxy is closed. ``'destroy'`` terminates cloud
        resources and ``'keep'`` leaves them running. Defaults to ``'destroy'``.

    Raises
    ------
    ValueError
        If ``on_exit`` is not ``'keep'`` or ``'destroy'``.
    """

    def __init__(
        self,
        manager: "ProxyManagerAws",
        instance_id: str,
        group_id: str,
        name: str,
        ip: str,
        port: int,
        region: str,
        proxy_instance: str = "",
        allowed_ips: list[str] | None = None,
        is_async: bool = False,
        user: str = "",
        password: str = "",
        logger: Logger | None = None,
        reload: bool = False,
        on_exit: Literal["keep", "destroy"] = "destroy",
    ):
        self.manager = manager
        self.instance_id = instance_id
        self.group_id = group_id
        self.name = name
        self.ip = ip
        self.port = port
        self.region = region
        self.proxy_instance = proxy_instance
        self.allowed_ips = allowed_ips or []
        self.is_async = is_async
        self.user = user
        self.password = password
        self._vm_started = False
        self.active = False
        self.logger = logger
        self.stopped = False
        if on_exit not in ["keep", "destroy"]:
            raise ValueError("on_exit parameter must be either 'keep' or 'destroy'")
        self.destroy = True if on_exit == "destroy" else False

        self._resource = manager._boto3.resource(
            "ec2",
            region_name=region,
            aws_access_key_id=manager._aws_access_key_id,
            aws_secret_access_key=manager._aws_secret_access_key,
        )
        self._client = manager._boto3.client(
            "ec2",
            region_name=region,
            aws_access_key_id=manager._aws_access_key_id,
            aws_secret_access_key=manager._aws_secret_access_key,
        )

        if not self.is_async and self.logger and not reload:
            self.logger.info("Waitting for the AWS proxy to be set up...")
        self.active = self.is_active()
        if self.logger:
            if not reload:
                proxy_suffix = (
                    f" {self.get_proxy_str(redact_auth=True)}"
                    if self.get_proxy_str()
                    else ""
                )
                status = "and ready to use" if self.active else "but not active yet"
                self.logger.info(f"New AWS proxy{proxy_suffix} created {status}.")
            else:
                proxy_suffix = (
                    f" {self.get_proxy_str(redact_auth=True)}"
                    if self.get_proxy_str()
                    else ""
                )
                status = "active" if self.active else "inactive"
                self.logger.info(f"AWS proxy{proxy_suffix} reloaded and {status}.")

    def is_active(self, wait: bool = False) -> bool:
        if not self._vm_started:
            instance = self._resource.Instance(self.instance_id)  # type: ignore
            if self.is_async and not wait:
                if instance.state["Name"] == "running":
                    self._vm_started = True
                    self.ip = instance.public_ip_address
            else:
                instance.wait_until_running()
                self._vm_started = True
                instance.reload()
                self.ip = instance.public_ip_address

        if not self._vm_started:
            return self.active

        return super().is_active(wait)

    def _stop_proxy(self, wait: bool = True):
        if self.stopped:
            return

        if self.destroy:
            default_security_group_id = self._client.describe_security_groups(
                Filters=[
                    {"Name": "group-name", "Values": ["default"]},
                ]
            )["SecurityGroups"][0]["GroupId"]

            instance = self._resource.Instance(self.instance_id)  # type: ignore
            _ = instance.modify_attribute(Groups=[default_security_group_id])

            self._client.delete_security_group(GroupId=self.group_id)
            _ = instance.terminate()
            if not self.is_async and wait:
                instance.wait_until_terminated()

            if self.logger:
                self.logger.info(
                    f"AWS proxy {self.get_proxy_str(redact_auth=True)} destroyed."
                )
        else:
            if self.logger:
                self.logger.info(
                    f"AWS proxy{' ' + self.get_proxy_str(redact_auth=True) if self.get_proxy_str() else ''} kept as per on_exit='keep' setting."
                )

        self.stopped = True
        self.id = None
        self.ip = ""
        self.port = 0
        self.region = ""
        self.user = ""
        self.password = ""
        self.logger = None

    def __str__(self):
        return f"AWS p{super().__str__()[1:]}"


@ProxyManagers.register(CloudProvider.AWS)
class ProxyManagerAws(BaseProxyManager[AwsProxy]):
    """Manager that provisions AWS EC2 proxy instances.

    This class validates AWS credentials and SSH key input, configures logging,
    imports AWS SDK clients, and loads available regions and size mappings used
    by the manager.

    Parameters
    ----------
    ssh_key : list[dict[str, str] | str] | dict[str, str] | str | Path
        SSH key configuration for created instances. Accepted forms are a single
        public key string, a dict with ``{'name': ..., 'public_key': ...}``, a
        list mixing both forms, or a file path containing one public key per
        line.
    credentials : dict[str, str] or None, optional
        AWS credential configuration. Supported keys are ``AWS_ACCESS_KEY_ID``
        and ``AWS_SECRET_ACCESS_KEY``. When omitted, environment variables are
        used. Defaults to ``None``.
    log : bool, optional
        Enable logging for manager actions. Defaults to ``True``.
    log_file : str or None, optional
        File path for logging output. If None, logging output goes to the
        terminal. Defaults to ``None``.
    log_format : str, optional
        Format string used when creating an internal logger. Defaults to
        ``'%(asctime)-10s %(levelname)-5s %(message)s'``.
    logger : Logger or None, optional
        Custom logger instance. When provided, ``log_file`` and ``log_format``
        are ignored. Defaults to ``None``.

    Raises
    ------
    ValueError
        If AWS credentials are missing both in ``credentials`` and in
        environment variables.
    TypeError
        If ``ssh_key`` has an invalid structure or no valid SSH keys are found.
    ImportError
        If required AWS SDK packages are not installed.
    """

    def __init__(
        self,
        ssh_key: list[dict[str, str] | str] | dict[str, str] | str | Path,
        credentials: dict[str, str] | None = None,
        log: bool = True,
        log_file: str | None = None,
        log_format: str = "%(asctime)-10s %(levelname)-5s %(message)s",
        logger: Logger | None = None,
    ):
        credentials = credentials or {}
        if (
            not credentials
            and not environ.get("AWS_ACCESS_KEY_ID")
            and not environ.get("AWS_SECRET_ACCESS_KEY")
        ):
            raise ValueError(
                "AWS credentials not provided. Please provide them as a dictionary or set the AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables."
            )

        self._aws_access_key_id = credentials.get("AWS_ACCESS_KEY_ID") or environ.get(
            "AWS_ACCESS_KEY_ID", ""
        )
        self._aws_secret_access_key = credentials.get(
            "AWS_SECRET_ACCESS_KEY"
        ) or environ.get("AWS_SECRET_ACCESS_KEY", "")

        if isinstance(ssh_key, Path):
            ssh_key = str(ssh_key)

        if isinstance(ssh_key, str) and isfile(ssh_key):
            with open(ssh_key, "r") as f:
                ssh_key = [x.strip("\n") for x in f.readlines() if x.strip("\n")]
        try:
            ssh_key = (
                [ssh_key]
                if isinstance(ssh_key, str) or isinstance(ssh_key, dict)
                else ssh_key
            )
            self.ssh_keys: list[str] = [
                x if not isinstance(x, dict) else x["public_key"]
                for x in ssh_key
                if isinstance(x, dict) or (isinstance(x, str) and is_ssh_key(x))
            ]
        except Exception:
            raise TypeError(
                "Bad ssh_key. SSH in a dict must follow format: {'name': 'ssh key name', 'public_key': 'ssh-rsa AAAAABBBBBCCCC...'}"
            )
        if not self.ssh_keys:
            raise TypeError(
                "No valid ssh keys found in the provided ssh_key parameter!"
            )
        self.log = True if log or log_file or logger else False
        self.log_format = log_format
        self.logger = logger
        if self.log and not logger:
            basicConfig(
                filename=log_file,
                format=self.log_format,
                filemode="a",
                datefmt="%d-%b-%Y %H:%M:%S",
                level=INFO,
            )
            self.logger = getLogger("proxy_logger")

        # check aws imports
        try:
            import boto3
            from botocore.exceptions import ClientError
        except Exception:
            raise ImportError(
                "Install the required boto3 package to use the AWSProxyManager:"
                "             python3 -m pip install auto_proxy_vpn[aws]"
            )

        self._boto3 = boto3
        self._aws_ClientError = ClientError

        # get all available regions
        client = self._boto3.client(
            "ec2",
            aws_access_key_id=self._aws_access_key_id,
            aws_secret_access_key=self._aws_secret_access_key,
            region_name="us-east-1",
        )
        self._regions = [
            r["RegionName"]
            for r in client.describe_regions(AllRegions=False)["Regions"]
        ]
        self._sizes_regions = {
            "small": [x for x in self._regions],
            "medium": [x for x in self._regions],
            "large": [x for x in self._regions],
        }

        self._instance_proxy_sizes: dict[Literal["small", "medium", "large"], str] = {
            "small": "t3.nano",
            "medium": "t3.micro",
            "large": "t3.small",
        }

        self._os_image_filters = [
            {
                "Name": "name",
                "Values": [
                    "ubuntu-minimal/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-minimal-*"
                ],
            },
            {"Name": "root-device-type", "Values": ["ebs"]},
            {"Name": "virtualization-type", "Values": ["hvm"]},
            {"Name": "owner-id", "Values": ["099720109477"]},
        ]

    @classmethod
    def from_config(
        cls,
        config: AwsConfig | None = None,
        runtime_config: ManagerRuntimeConfig | None = None,
    ) -> "ProxyManagerAws":
        """Create a ProxyManagerAws instance from an AwsConfig object and a ManagerRuntimeConfig."""
        if config is None:
            raise ValueError(
                "AwsConfig must be provided to create a ProxyManagerAws instance."
            )
        if runtime_config is None:
            runtime_config = ManagerRuntimeConfig()
        return cls(
            config.ssh_key,
            config.credentials,
            runtime_config.log,
            runtime_config.log_file,
            runtime_config.log_format,
            runtime_config.logger,
        )

    def get_proxy(
        self,
        port: int = 0,
        size: Literal["small", "medium", "large"] = "medium",
        region: str = "",
        auth: dict[Literal["user", "password"], str] | None = None,
        allowed_ips: str | list[str] | None = None,
        is_async: bool = False,
        retry: bool = True,
        proxy_name: str = "",
        on_exit: Literal["keep", "destroy"] = "destroy",
    ) -> AwsProxy:
        """Create and start an AWS-based proxy instance.

        The method randomly selects (or validates) a region, prepares authentication and
        allowed source IPs, starts the proxy EC2 resources, and returns an
        :class:`AwsProxy` wrapper.

        Parameters
        ----------
        port : int, optional
            TCP port for the proxy. If ``0``, a random port between ``10000``
            and ``65000`` is selected. Defaults to ``0``.
        size : {'small', 'medium', 'large'}, optional
            Proxy instance size profile. Defaults to ``'medium'``.
        region : str, optional
            Preferred AWS region. If empty, a random region is selected from
            available regions for the selected size. Defaults to ``''``.
        auth : dict, optional
            Basic-auth credentials as ``{'user': ..., 'password': ...}``. If
            empty, no basic authentication is configured. Defaults to an
            empty dict.
        allowed_ips : str or list[str], optional
            Source IP/range(s) allowed to access the proxy. Can be a single
            string or a list. The caller public IP is automatically added if
            missing. Defaults to an empty list.
        is_async : bool, optional
            If True, do not wait for full VM startup before returning.
            Defaults to ``False``.
        retry : bool, optional
            Enable retry when startup fails and region was chosen randomly.
            Ignored when a specific ``region`` is provided. Defaults to
            ``True``.
        proxy_name : str, optional
            Explicit proxy name. If empty, a unique name of the form
            ``proxyN`` is generated. Defaults to ``''``.
        on_exit : {'keep', 'destroy'}, optional
            Behavior when the returned proxy is closed. ``'destroy'`` removes
            cloud resources; ``'keep'`` leaves them running. Defaults to
            ``'destroy'``.

        Returns
        -------
        AwsProxy
            Proxy wrapper object for the created AWS proxy.

        Raises
        ------
        NameError
            If ``proxy_name`` is provided and already exists.
        ValueError
            If ``region`` is provided but not available.
        TypeError
            If ``auth`` is not a dict, or if ``allowed_ips`` has an invalid
            IP/range format.
        KeyError
            If ``auth`` is provided without both ``'user'`` and
            ``'password'`` keys.
        Exception
            If proxy startup fails and no valid retry path remains.
        """

        retry = retry if not region else False

        if not port:
            port = randint(10000, 65000)

        servers = self._regions
        random_region = False
        if region:
            if region not in servers:
                raise ValueError(
                    f"Region {region} not available in AWS. Check available regions with get_regions_by_size()."
                )
        else:
            random_region = True
            shuffle(servers)
            region = choice(servers)

        all_proxies = self.get_running_proxy_names()
        if proxy_name:
            if proxy_name in all_proxies:
                raise NameError(
                    f"Proxy with name {proxy_name} already exists in AWS. Please choose a different name or set proxy_name to an empty string to auto-generate a name."
                )
        else:
            proxy_num = len(all_proxies) + 1
            while f"proxy{proxy_num}" in all_proxies:
                proxy_num += 1
            proxy_name = f"proxy{proxy_num}"

        proxy_size = self._instance_proxy_sizes[size]

        auth = normalize_proxy_auth(auth)

        ip = get_public_ip()

        ips = normalize_allowed_ips(allowed_ips)

        if ip not in ips:
            ips.append(ip)

        if self.logger:
            user_suffix = "with authentication" if auth else "with no authentication"
            self.logger.info(
                f"Starting a new AWS proxy in the region {region} {user_suffix}..."
            )

        proxy_ip, instance_id, group_id, error = start_proxy(
            self,
            proxy_name,
            port,
            region,
            proxy_size,
            ips,
            auth.get("user", ""),
            auth.get("password", ""),
            is_async,
        )
        if error and retry and random_region:
            if self.logger:
                self.logger.warning(
                    f"Failed to start the AWS proxy {proxy_name} in the region {region}. Retrying with a different region..."
                )

            # retry with another random region, excluding the previous one
            region = choice([x for x in servers if x != region])
            proxy_ip, instance_id, group_id, error = start_proxy(
                self,
                proxy_name,
                port,
                region,
                proxy_size,
                ips,
                auth.get("user", ""),
                auth.get("password", ""),
                is_async,
            )

        if error:
            # if it fails again, we try to delete the resource group just in case it was created and then raise an exception
            if self.logger:
                self.logger.error(
                    f"Failed to start the AWS proxy {proxy_name} after retrying."
                )

            raise Exception("Failed to start the AWS proxy instance.")

        return AwsProxy(
            self,
            instance_id,
            group_id,
            proxy_name,
            proxy_ip,
            port,
            region,
            proxy_instance=proxy_size,
            allowed_ips=ips,
            is_async=is_async,
            user=auth.get("user", ""),
            password=auth.get("password", ""),
            logger=self.logger,
            reload=False,
            on_exit=on_exit,
        )

    def get_proxy_by_name(
        self,
        name: str,
        auth: dict[Literal["user", "password"], str] | None = None,
        is_async: bool = False,
        on_exit: Literal["destroy", "keep"] = "destroy",
    ) -> AwsProxy:
        """Reload an existing AWS proxy instance by its name.

        The method validates that the proxy exists, retrieves EC2 metadata,
        reads the remote Squid configuration to recover proxy settings (port,
        allowed IPs and optional basic-auth credentials), and returns a
        reloaded :class:`AwsProxy` object.

        Parameters
        ----------
        name : str
            Name tag of the AWS proxy to load.
        is_async : bool, optional
            If True, the returned proxy object uses asynchronous behavior for
            lifecycle operations. Defaults to ``False``.
        on_exit : {'destroy', 'keep'}, optional
            Behavior when the returned proxy is closed. ``'destroy'`` removes
            resources and ``'keep'`` leaves them running. Defaults to
            ``'destroy'``.

        Returns
        -------
        AwsProxy
            Reloaded proxy instance bound to the existing AWS resources.

        Raises
        ------
        NameError
            If no running proxy with ``name`` exists.
        ConnectionError
            If the Squid configuration cannot be read through SSH.
        ValueError
            If the proxy port cannot be extracted from the instance config.
        """

        running_proxies = self.get_running_proxy_names(return_region=True)
        if name not in [x[0] for x in running_proxies]:
            raise NameError(f"No proxy with the name {name} has been found in AWS.")

        region = [x[1] for x in running_proxies if x[0] == name][0]
        client = self._boto3.client(
            "ec2",
            region_name=region,
            aws_access_key_id=self._aws_access_key_id,
            aws_secret_access_key=self._aws_secret_access_key,
        )
        response = client.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [name]},
                {"Name": "instance-state-name", "Values": ["pending", "running"]},
            ]
        )
        instance_data = response["Reservations"][0]["Instances"][0]
        instance_id = instance_data["InstanceId"]
        group_id = instance_data["NetworkInterfaces"][0]["Groups"][0]["GroupId"]
        proxy_ip = instance_data["PublicIpAddress"]

        ssh_client = SSHClient(proxy_ip, "proxy-user")
        _, startup_script, _ = ssh_client.run_command("cat /etc/squid/squid.conf")
        if not startup_script:
            raise ConnectionError("Can't connect to the AWS proxy!")

        try:
            port = int(search(r"http_port (\d+)", startup_script).group(1))  # type: ignore
        except Exception:
            raise ValueError(
                "Can't find the proxy port in the startup script of the AWS instance!"
            )

        vm_size = instance_data["InstanceType"]

        allowed_ips = normalize_allowed_ips(
            [
                str(match.group(1))
                for match in finditer(
                    r"acl custom_ips src (\S+)",
                    startup_script,
                )
            ]
        )

        auth = resolve_reloaded_proxy_auth(startup_script, auth)

        if self.logger:
            user_suffix = (
                "with authentication" if auth else "with no authentication found"
            )
            self.logger.info(
                f"AWS proxy {name} reloaded with IP {proxy_ip} and port {port} {user_suffix}..."
            )

        return AwsProxy(
            self,
            instance_id,
            group_id,
            name,
            proxy_ip,
            port,
            region,
            proxy_instance=vm_size,
            allowed_ips=allowed_ips,
            is_async=is_async,
            user=auth.get("user", ""),
            password=auth.get("password", ""),
            logger=self.logger,
            reload=True,
            on_exit=on_exit,
        )

    def get_running_proxy_names(
        self, return_region: bool = False
    ) -> list[str] | list[tuple[str, str]]:
        """List currently running AWS proxies discovered across regions.

        The method queries every available AWS region concurrently and returns
        either only proxy names or name/region pairs.

        Parameters
        ----------
        return_region : bool, optional
            If True, return tuples containing ``(name, region)``. If False,
            return only proxy names. Defaults to ``False``.

        Returns
        -------
        list[str]
            List of proxy names when ``return_region`` is False. When True,
            returns a flattened list of name/region pairs.
        """
        with ThreadPoolExecutor() as executor:
            all_instance_names = list(
                executor.map(
                    get_region_instances, [self] * len(self._regions), self._regions
                )
            )

        if not return_region:
            return [x[0] for sublist in all_instance_names for x in sublist]

        return [x for sublist in all_instance_names for x in sublist]
