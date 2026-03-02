from typing import Literal
from logging import INFO, ERROR, Logger, basicConfig, getLogger
from os import environ
from os.path import isfile
from random import choice, randint, shuffle
from re import finditer, search
from time import sleep

from auto_proxy_vpn import CloudProvider, ProxyManagers, ManagerRuntimeConfig, AzureConfig
from auto_proxy_vpn.utils.base_proxy import BaseProxy, BaseProxyManager
from auto_proxy_vpn.utils.util import get_public_ip
from auto_proxy_vpn.utils.ssh_client import SSHClient
from .azure_utils import start_proxy

class AzureProxy(BaseProxy):
    def __init__(self,
                 manager: 'ProxyManagerAzure',
                 name: str,
                 ip: str,
                 port: int,
                 region: str,
                 proxy_instance: str = '',
                 allowed_ips: list[str] = [],
                 is_async: bool = False,
                 user: str = '',
                 password: str = '',
                 logger: Logger | None = None,
                 reload: bool = False,
                 on_exit: Literal['keep', 'destroy'] = 'destroy'):
        """Represent an Azure VM-based proxy instance.

        This object stores proxy metadata and lifecycle state and can be
        initialized either for a newly created proxy VM or by reloading an
        existing one.

        Parameters
        ----------
        manager : ProxyManagerAzure
            Manager instance that owns Azure SDK clients and resources used
            by this proxy.
        name : str
            Proxy resource group / VM base name.
        ip : str
            Public IPv4 address of the proxy. May be empty while the VM is
            still provisioning.
        port : int
            Proxy listening TCP port.
        region : str
            Azure region where the proxy resources are deployed.
        proxy_instance : str, optional
            Azure VM size used for this proxy (for example
            ``'Standard_B1s'``). Defaults to ``''``.
        allowed_ips : list[str], optional
            Source IPs/ranges allowed to connect to the proxy. Used for
            startup/retry metadata. Defaults to an empty list.
        is_async : bool, optional
            If True, do not block waiting for full startup completion.
            Defaults to ``False``.
        user : str, optional
            Basic-auth username configured in Squid. Defaults to ``''``.
        password : str, optional
            Basic-auth password configured in Squid. Defaults to ``''``.
        logger : Logger or None, optional
            Logger used for lifecycle and status messages. Defaults to
            ``None``.
        reload : bool, optional
            If True and ``ip`` is already set, skip initial activation checks
            for a previously created proxy. Defaults to ``False``.
        on_exit : {'keep', 'destroy'}, optional
            Behavior when the proxy is closed. ``'destroy'`` removes Azure
            resources and ``'keep'`` leaves them running. Defaults to
            ``'destroy'``.

        Raises
        ------
        ValueError
            If ``on_exit`` is not ``'keep'`` or ``'destroy'``.
        """
        
        self.manager = manager
        self.name = name
        self.ip = ip
        self.port = port
        self.region = region
        self.proxy_instance = proxy_instance
        self.allowed_ips = allowed_ips
        self.is_async = is_async
        self.user = user
        self.password = password
        self._vm_started = False
        self.active = False
        self.logger = logger
        self.stopped = False
        if on_exit not in ['keep', 'destroy']:
            raise ValueError("Bad on_exit option!")
        self.destroy = True if on_exit == 'destroy' else False
        self.retried = False
        
        if not reload or not self.ip:
            if not self.is_async and self.logger:
                self.logger.info('Waitting for the azure proxy to be set up...')
            self.active = self.is_active()
            if self.logger:
                self.logger.info(f'New azure proxy{' '+self.get_proxy_str() if self.get_proxy_str() else ''} created {"and ready to use" if self.active else "but not active yet"}.')
        elif reload:
            self.active = self.is_active()
            if self.logger:
                self.logger.info(f'Azure proxy{' '+self.get_proxy_str() if self.get_proxy_str() else ''} reloaded and {"active" if self.active else "inactive"}.')
    
    def is_active(self, wait = False) -> bool:
        if not self._vm_started:
            if self.is_async and not wait:
                self._vm_started = self.manager._compute_client.virtual_machines.get(self.name, self.name).provisioning_state == 'Succeeded'
            else:
                times = 0
                self._vm_started = self.manager._compute_client.virtual_machines.get(self.name, self.name).provisioning_state == 'Succeeded'
                while not self._vm_started and times < 10:
                    times += 1
                    sleep(5)
                    self._vm_started = self.manager._compute_client.virtual_machines.get(self.name, self.name).provisioning_state == 'Succeeded'
        
        if not self._vm_started:
            return self.active
        
        return super().is_active(wait)
    
    def _stop_proxy(self, wait: bool = True):
        if self.stopped:
            return
        
        if self.destroy:
            if not self.is_async and wait:
                resources_proxy_names = [self.name, f'{self.name}-firewall', f'{self.name}-vnet']
                resources_proxy = sorted([x for x in self.manager._resource_client.resources.list(filter=f"resourceGroup eq '{self.name}'") if x.name and x.name in resources_proxy_names], key=lambda x: x.name if x.name else '')
                for resource in resources_proxy:
                    if resource.name and '-' not in resource.name:
                        self.manager._compute_client.virtual_machines.begin_delete(self.name, resource.name).wait()
                    elif resource.name and resource.name.endswith('-firewall'):
                        self.manager._network_client.network_security_groups.begin_delete(self.name, resource.name)
                    elif resource.name and resource.name.endswith('-vnet'):
                        self.manager._network_client.virtual_networks.begin_delete(self.name, resource.name)
            
            resource_group_deletion = self.manager._resource_client.resource_groups.begin_delete(self.name)
            if not self.is_async and wait:
                resource_group_deletion.wait()
            
            if self.logger:
                self.logger.info(f"Azure proxy{' '+self.get_proxy_str() if self.get_proxy_str() else ''} removed.")
        else:
            if self.logger:
                self.logger.info(f"Azure proxy{' '+self.get_proxy_str() if self.get_proxy_str() else ''} kept as per on_exit='keep' setting.")
        
        self.stopped = True
        self.id = None
        self.ip = ''
        self.port = 0
        self.region = ''
        self.user = ''
        self.password = ''
        self.logger = None
        
    def __str__(self):
        return f"Azure p{super().__str__()[1:]}"

@ProxyManagers.register(CloudProvider.AZURE)
class ProxyManagerAzure(BaseProxyManager[AzureProxy]):
    def __init__(self,
                 ssh_key: list[dict[str, str] | str] | dict[str, str] | str,
                 credentials: str | dict[str, str] = '',
                 log: bool = True,
                 log_file: str | None = None,
                 log_format: str = '%(asctime)-10s %(levelname)-5s %(message)s',
                 logger: Logger | None = None):
        """Create a manager that provisions Azure proxy virtual machines.

        This initializer validates Azure credentials and SSH key input,
        configures logging, imports Azure SDK clients, and loads available
        VM regions and size mappings used by the manager.
        
        To obtain Azure credentials, you need to create a new subscription and 
        register an application in Azure Active Directory with the appropriate 
        permissions. Then, you can provide the subscription ID, client ID, client 
        secret, and tenant ID either as environment variables or directly as a 
        dictionary to the manager.\n
        With azure cli you can easily obtain the required credentials by running:\n
        
        $ az ad sp create-for-rbac --name "my-proxy-manager" --role contributor --scopes /subscriptions/{subscription-id}
        
        And save in a .env file or set the environment variables directly:\n
        appId → AZURE_CLIENT_ID\n
        password → AZURE_CLIENT_SECRET\n
        tenant → AZURE_TENANT_ID

        Parameters
        ----------
        ssh_key : list[dict[str, str] | str] | dict[str, str] | str
            SSH key configuration for created VMs. Accepted forms are a
            single public key string, a dict with
            ``{'name': ..., 'public_key': ...}``, a list mixing both forms,
            or a file path containing one public key per line.
        credentials : str or dict[str, str], optional
            Azure credential configuration. Supported values are:
            subscription ID as a string, dict containing
            ``AZURE_SUBSCRIPTION_ID``, optionally with ``AZURE_CLIENT_ID``,
            ``AZURE_CLIENT_SECRET`` and ``AZURE_TENANT_ID``, or empty value
            to rely on environment variables. Defaults to ``''``.
        log : bool, optional
            Enable logging for manager actions. Defaults to ``True``.
        log_file : str, optional
            File path for logging output. If empty, logging output goes to
            the terminal. Defaults to ``''``.
        log_format : str, optional
            Format string used when creating an internal logger. Defaults to
            ``'%(asctime)-10s %(levelname)-5s %(message)s'``.
        logger : Logger or None, optional
            Custom logger instance. When provided, ``log_file`` and
            ``log_format`` are ignored. Defaults to ``None``.

        Raises
        ------
        ValueError
            If subscription information is missing both in ``credentials``
            and in ``AZURE_SUBSCRIPTION_ID`` environment variable.
        TypeError
            If ``ssh_key`` has an invalid structure.
        ImportError
            If required Azure SDK packages are not installed.

        Examples
        --------
        Use environment-based credentials with a context manager::

            manager = ProxyManagerAzure(
                ssh_key='ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC2...'
            )
            with manager.get_proxy() as proxy:
                result = requests.get('https://google.com', proxies=proxy.get_proxy())

        Pass credentials explicitly and close manually::

            manager = ProxyManagerAzure(
                credentials={
                    'AZURE_SUBSCRIPTION_ID': 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
                    'AZURE_CLIENT_ID': 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
                    'AZURE_CLIENT_SECRET': 'your-client-secret',
                    'AZURE_TENANT_ID': 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
                },
                ssh_key='ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC2...'
            )
            proxy = manager.get_proxy()
            try:
                # Use the proxy
                pass
            finally:
                proxy.close()
        """
        
        if (not credentials or isinstance(credentials, dict) and "AZURE_SUBSCRIPTION_ID" not in credentials) and not environ.get("AZURE_SUBSCRIPTION_ID", ""):
            raise ValueError("Azure credentials not provided. Please provide them as a parameter or set the AZURE_SUBSCRIPTION_ID environment variable.")
        
        if isinstance(ssh_key, str) and isfile(ssh_key):
            with open(ssh_key, "r") as f:
                ssh_key = [x.strip('\n') for x in f.readlines() if x.strip('\n')]
        try:
            ssh_key = [ssh_key] if isinstance(ssh_key, str) or isinstance(ssh_key, dict) else ssh_key
            self.ssh_keys: list[str] = [x if not isinstance(x, dict) else x['public_key'] for x in ssh_key] 
        except:
            raise TypeError("Bad ssh_key. SSH in a dict must follow format: {'name': 'ssh key name', 'public_key': 'ssh-rsa AAAAABBBBBCCCC...'}")
        self.log = True if log or log_file or logger else False
        self.log_format = log_format
        self.logger = logger
        if self.log and not logger:
            basicConfig(filename=log_file,
                    format=self.log_format,
                    filemode='a',
                    datefmt='%d-%b-%Y %H:%M:%S',
                    level=INFO)
            self.logger = getLogger('proxy_logger')
            
        # check azure imports
        try:
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.subscription import SubscriptionClient
            from azure.mgmt.resource import ResourceManagementClient
            from azure.mgmt.network import NetworkManagementClient
            from azure.mgmt.compute import  ComputeManagementClient
            
            from azure.mgmt.network import models as network_models
            from azure.mgmt.compute import models as compute_models
            
            # supressing azure sdk logs
            azure_logs = getLogger("azure")
            azure_logs.setLevel(ERROR)
        except:
            raise ImportError("Install azure-identity and azure-mgmt packages to use the azure proxies.\n"
                              "             python3 -m pip install azure-identity azure-mgmt-subscription azure-mgmt-resource azure-mgmt-network azure-mgmt-compute")
        
        credential = DefaultAzureCredential()
        subscription_id = environ.get("AZURE_SUBSCRIPTION_ID", "")
        if credentials:
            if isinstance(credentials, str):
                subscription_id = credentials
            elif isinstance(credentials, dict) and "AZURE_SUBSCRIPTION_ID" in credentials:
                subscription_id = credentials["AZURE_SUBSCRIPTION_ID"]
        
        # saving all azure imports as instance variables to avoid import errors when the user is not using azure proxies
        self._resource_client = ResourceManagementClient(credential, subscription_id)
        self._network_client = NetworkManagementClient(credential, subscription_id)
        self._compute_client = ComputeManagementClient(credential, subscription_id)
        self._network_models = network_models
        self._compute_models = compute_models
        
        subscription_client = SubscriptionClient(credential)
        # Only getting the available locations to deploy a virtual machine
        locations_virtual_machine: list[str] = [x for x in self._resource_client.providers.get("Microsoft.Compute").resource_types if x.resource_type == 'virtualMachines'][0].locations # type: ignore
        self._regions = [str(x.name) for x in subscription_client.subscriptions.list_locations(subscription_id) if x.display_name in locations_virtual_machine]
        self._sizes_regions = {'small': [x for x in self._regions], 'medium': [x for x in self._regions], 'large': [x for x in self._regions]}
        
        self._instance_proxy_sizes: dict[Literal["small", "medium", "large"], str] = {"small": "Standard_B1s", "medium": "Standard_B1ms", "large": "Standard_B2s"}
        
        # os image info
        self._image_publisher = "Canonical"
        self._image_offer = "ubuntu-24_04-lts"
        self._image_sku = "minimal"
    
    @classmethod
    def from_config(cls, config: AzureConfig | None = None, runtime_config: ManagerRuntimeConfig | None = None) -> 'ProxyManagerAzure':
        """Create a ProxyManagerAzure instance from an AzureConfig object and a ManagerRuntimeConfig."""
        if config is None or runtime_config is None:
            raise ValueError("AzureConfig must be provided to create a ProxyManagerAzure instance.")
        return cls(config.ssh_key, config.credentials, runtime_config.log, runtime_config.log_file, runtime_config.log_format, runtime_config.logger)
    
    def get_proxy(self,
                  port: int = 0,
                  size: Literal['small', 'medium', 'large'] = 'medium',
                  region: str = '',
                  auth: dict[Literal['user', 'password'], str] = {},
                  allowed_ips: str | list[str] = [],
                  is_async: bool = False,
                  retry: bool = True,
                  proxy_name: str = '',
                  on_exit: Literal['keep', 'destroy'] = 'destroy') -> AzureProxy:
        """Create and start an Azure-based proxy instance.

        The method selects (or validates) a region, prepares authentication and
        allowed source IPs, starts the proxy VM/resources, and returns an
        :class:`AzureProxy` wrapper.

        Parameters
        ----------
        port : int, optional
            TCP port for the proxy. If ``0``, a random port between ``10000``
            and ``65000`` is selected. Defaults to ``0``.
        size : {'small', 'medium', 'large'}, optional
            Proxy VM size profile. Defaults to ``'medium'``.
        region : str, optional
            Preferred Azure region. If empty, a random region is selected
            from available regions for the selected size. Defaults to ``''``.
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
        AzureProxy
            Proxy wrapper object for the created Azure proxy.

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
        
        all_resources = [x for x in self._resource_client.resource_groups.list() if x.name]
        instances_list = [x.name for x in all_resources if x.tags and x.tags.get('type', '') == 'proxy']
        all_resources = [x.name for x in all_resources]
        if proxy_name:
            if proxy_name in all_resources:
                raise NameError(f"Resource {proxy_name} already exists in azure!")
        else:
            proxy_num = len(instances_list)+1
            while f"proxy{proxy_num}" in all_resources:
                proxy_num += 1
            proxy_name = f"proxy{proxy_num}"
        
        proxy_size = self._instance_proxy_sizes[size]
        servers = self._regions
        random_region = False
        if region:
            if region not in servers:
                raise ValueError(f"Region {region} don't exist in azure or doesn't have the required resources to create a proxy! Check the available regions with get_regions_by_size()")
        else:
            random_region = True
            shuffle(servers)
            region = choice(servers)
        
        if auth:
            if not isinstance(auth, dict):
                raise TypeError('Bad auth format, auth must be a dict')
            
            if 'user' not in auth.keys() or 'password' not in auth.keys():
                raise KeyError('Auth dict must have two keys name and password')
        
        ip = get_public_ip()
        
        ips = []
        if allowed_ips:
            if isinstance(allowed_ips, str):
                ips = [allowed_ips]
            else:
                ips = allowed_ips
            
            if not all(search(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(\\\d\d?)?', ip) for ip in allowed_ips):
                raise TypeError("IPs or ranges of ips with bad format!")
        
        if ip not in ips:
            ips.append(ip)
        
        if self.logger:
            self.logger.info(f"Starting a new azure proxy in the region {region}{f" for the user {auth['user']}" if auth else " with no authentification"}...")
        
        proxy_ip, error = start_proxy(self, proxy_name, port, region, proxy_size, ips, auth['user'] if auth else '', auth['password'] if auth else '', is_async)
        if error and retry and random_region:
            if self.logger:
                self.logger.warning(f"Failed to start the azure proxy {proxy_name} in the region {region}. Retrying with a different region...")
            
            # retry with another random region, excluding the previous one
            region = choice([x for x in servers if x != region])
            proxy_ip, error = start_proxy(self, proxy_name, port, region, proxy_size, ips, auth['user'] if auth else '', auth['password'] if auth else '', is_async)
        
        if error:
            # if it fails again, we try to delete the resource group just in case it was created and then raise an exception
            if self.logger:
                self.logger.error(f"Failed to start the azure proxy {proxy_name} after retrying.")
            try:
                self._resource_client.resource_groups.begin_delete(proxy_name)
            finally:
                raise Exception(f"Failed to start the azure proxy {proxy_name}, no public IP obtained.")
        
        return AzureProxy(self, proxy_name, proxy_ip, port, region, proxy_size, ips, is_async=is_async, user=auth['user'] if auth else '', password=auth['password'] if auth else '', logger=self.logger, reload=False, on_exit=on_exit)
    
    def get_proxy_by_name(self, name: str, is_async: bool = False, on_exit: Literal['destroy', 'keep'] = 'destroy') -> AzureProxy:
        """Reload an existing Azure proxy instance by its name.

        The method validates that the proxy exists, retrieves VM metadata and
        public IP information, reads the remote Squid configuration to recover
        proxy settings (port, allowed IPs and optional basic-auth credentials),
        and returns a reloaded :class:`AzureProxy` object.

        Parameters
        ----------
        name : str
            Name of the Azure proxy to load.
        is_async : bool, optional
            If True, the returned proxy object uses asynchronous behavior for
            lifecycle operations. Defaults to ``False``.
        on_exit : {'destroy', 'keep'}, optional
            Behavior when the returned proxy is closed. ``'destroy'`` removes
            resources and ``'keep'`` leaves them running. Defaults to
            ``'destroy'``.

        Returns
        -------
        AzureProxy
            Reloaded proxy instance bound to the existing Azure resources.

        Raises
        ------
        NameError
            If no running proxy with ``name`` exists.
        Exception
            If the public IP cannot be obtained.
        ConnectionError
            If the Squid configuration cannot be read through SSH.
        ValueError
            If the proxy port or VM size cannot be extracted from the
            instance data.
        """
        
        if not name in self.get_running_proxy_names():
            raise NameError(f"No proxy with the name {name} was found!")
        
        instance = self._compute_client.virtual_machines.get(name, name)
        
        region = instance.location
        ip = self._network_client.public_ip_addresses.get(name, f"{name}-public-ip").ip_address
        if not ip:
            raise Exception(f"Failed to get the public IP for the azure proxy {name}.")
        
        ssh_client = SSHClient(ip, 'proxy-user')
        _, startup_script, _ = ssh_client.run_command('cat /etc/squid/squid.conf')
        if not startup_script:
            raise ConnectionError("Can't connect to the proxy!")
        
        try:
            port = int(search(r'http_port (\d+)', startup_script).group(1)) # type: ignore
        except:
            raise ValueError("Can't find the proxy port in the startup script of the instance!")
        
        if not instance.hardware_profile or not instance.hardware_profile.vm_size:
            raise ValueError("Can't find the proxy instance type in the azure instance information!")
        vm_size = instance.hardware_profile.vm_size
        
        # Search IPs in the squid config file to get the allowed ips for the proxy
        allowed_ips = [str(match.group(1)) for match in finditer(r'acl custom_ips src (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', startup_script)]
        
        auth_search = search(r'#auth credentials: user: (.+), password: (.+)\n', startup_script)
        auth = {}
        if auth_search:
            auth['user'] = auth_search.group(1)
            auth['password'] = auth_search.group(2)
        
        if self.logger:
            self.logger.info(f"Azure proxy {name} reloaded with IP {ip} and port {port}{f" for the user {auth['user']}" if auth else " with no authentification found"}...")
        
        return AzureProxy(self, name, ip, port, region, proxy_instance=vm_size, allowed_ips=allowed_ips, is_async=is_async, user=auth.get('user', ''), password=auth.get('password', ''), logger=self.logger, reload=True, on_exit=on_exit)
    
    def get_running_proxy_names(self) -> list[str]:
        return [x.name for x in self._resource_client.resource_groups.list() if x.name and x.tags and x.tags.get('type', '') == 'proxy']