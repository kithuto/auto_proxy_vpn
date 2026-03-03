from typing import Literal
from logging import Logger, basicConfig, INFO, getLogger
from os import environ
from os.path import isfile
from random import randint, shuffle, choice
from re import finditer, search
from itertools import chain
from time import sleep
from ipaddress import ip_network, ip_address

from auto_proxy_vpn import CloudProvider, ProxyManagers, ManagerRuntimeConfig, GoogleConfig
from auto_proxy_vpn.utils.base_proxy import BaseProxy, BaseProxyManager
from .google_exceptions import GoogleAuthException
from .google_utils import start_proxy, wait_for_extended_operation, get_avaliable_regions_by_size
from auto_proxy_vpn.utils.util import get_public_ip

class GoogleProxy(BaseProxy):
    def __init__(self,
                 manager: 'ProxyManagerGoogle',
                 name: str,
                 ip: str,
                 port: int,
                 project: str,
                 region: str,
                 zone: str,
                 proxy_instance: str = '',
                 allowed_ips: list[str] = [],
                 is_async: bool = False,
                 user: str = '',
                 password: str = '',
                 logger: Logger | None = None,
                 reload: bool = False,
                 on_exit: Literal['keep', 'destroy'] = 'destroy'):
        """Represent a Google Cloud VM-based proxy instance.

        This object stores proxy metadata and lifecycle state, and can be
        initialized either for a newly created instance or by reloading an
        existing one.

        Parameters
        ----------
        manager : ProxyManagerGoogle
            Manager instance that owns the Google Compute clients used by
            this proxy.
        name : str
            Google Compute Engine instance name.
        ip : str
            Public IP address of the proxy instance. Can be empty while the
            instance is still starting.
        port : int
            Proxy listening port.
        project : str
            Google Cloud project ID where the instance exists.
        region : str
            Region of the proxy instance.
        zone : str
            Zone of the proxy instance.
        proxy_instance : str, optional
            Machine type used for the instance (for example ``'e2-micro'``).
            Defaults to ``''``.
        allowed_ips : list[str], optional
            Allowed IPs/ranges. Defaults to an empty list.
        is_async : bool, optional
            If True, the proxy may be returned before full startup completion.
            If the proxy is asynchronous on exit, it won't wait for full
            shutdown. Defaults to ``False``.
        user : str, optional
            Basic-auth username configured for the proxy. Defaults to ``''``.
        password : str, optional
            Basic-auth password configured for the proxy. Defaults to ``''``.
        logger : Logger or None, optional
            Logger used for status and lifecycle messages. Defaults to
            ``None``.
        reload : bool, optional
            If True the proxy is already running and the object is being
            reloaded with its info. In this case, the constructor will skip
            initial activation checks for an already running instance.
            Defaults to ``False``.
        on_exit : {'keep', 'destroy'}, optional
            Defines behavior when the proxy is closed: keep the cloud resource
            or destroy it. Defaults to ``'destroy'``.

        Raises
        ------
        ValueError
            If ``on_exit`` is not ``'keep'`` or ``'destroy'``.
        """
        
        self.manager = manager
        self.name = name
        self.ip = ip
        self.port = port
        self.project = project
        self.region = region
        self.zone = zone
        self.proxy_instance = proxy_instance
        self.allowed_ips = allowed_ips
        self.user = user
        self.password = password
        self.active = False
        self.is_async = is_async
        self.logger = logger
        self.stopped = False
        if on_exit not in ['keep', 'destroy']:
            raise ValueError("Bad on_exit option!")
        self.destroy = True if on_exit == 'destroy' else False
        self.retried = False
        
        if not reload or not self.ip:
            if not self.is_async and self.logger:
                self.logger.info('Waitting for the proxy to be set up...')
            self.active = self.is_active()
            if self.logger:
                self.logger.info(f'New google proxy{' '+self.get_proxy_str() if self.get_proxy_str() else ''} created {"and ready to use" if self.active else "but not active yet"}.')
        elif reload:
            self.active = self.is_active()
            if self.logger:
                self.logger.info(f'Google proxy{' '+self.get_proxy_str() if self.get_proxy_str() else ''} reloaded and {"active" if self.active else "inactive"}.')
    
    def is_active(self, wait: bool = False) -> bool:
        if not self.ip:
            instance_request = self.manager._compute_v1.GetInstanceRequest(instance=self.name, project=self.project, zone=self.zone)
            if self.is_async and not wait:
                try:
                    self.ip = self.manager._instances_client.get(instance_request).network_interfaces[0].access_configs[0].nat_i_p
                    print(self.ip)
                except:
                    if not self.retried:
                        if self.logger:
                            self.logger.info("The google proxy is down, retrying to start it...")
                        self.retried = True
                        is_async_backup = self.is_async
                        # wait for the instance to be deleted before trying to start it again, otherwise we can get errors about the instance already existing
                        self.is_async = False
                        self._stop_proxy(reset=False)
                        # Make sure we get an ip
                        self.ip, error = start_proxy(self.manager, self.name, self.port, self.region, self.zone, [], self.proxy_instance, self.allowed_ips, self.user, self.password, is_async=False, firewall=False)
                        if error:
                            if self.logger:
                                self.logger.error("Failed to start the google proxy on retry.")
                            self._stop_proxy()
                            return self.active
                        self.is_async = is_async_backup
                    else:
                        if self.logger:
                            self.logger.warning("The google proxy is taking too long to start and it has already been retried once, removing it...")
                        self._stop_proxy()
                        return self.active
                try:
                    if not self.ip:
                        raise Exception()
                except:
                    return self.active
            else:
                times = 0
                while not self.ip and times < 10:
                    try:
                        self.ip = self.manager._instances_client.get(instance_request).network_interfaces[0].access_configs[0].nat_i_p
                    except:
                        if not self.retried:
                            if self.logger:
                                self.logger.info("The google proxy is taking too long to start, retrying to start it...")
                            self.retried = True
                            is_async_backup = self.is_async
                            # wait for the instance to be deleted before trying to start it again, otherwise we can get errors about the instance already existing
                            self.is_async = False
                            self._stop_proxy(reset=False)
                            # Make sure we get an ip
                            self.ip, error = start_proxy(self.manager, self.name, self.port, self.region, self.zone, [], self.proxy_instance, self.allowed_ips, self.user, self.password, is_async=False, firewall=False)
                            if error:
                                if self.logger:
                                    self.logger.error("Failed to start the google proxy on retry.")
                                self._stop_proxy()
                                return self.active
                            self.is_async = is_async_backup
                            times = 0
                        else:
                            if self.logger:
                                self.logger.warning("The google proxy is taking too long to start and it has already been retried once, removing it...")
                            self._stop_proxy()
                            return self.active
                    try:
                        if not self.ip:
                            raise Exception()
                    except:
                        times += 1
                        sleep(5)
            if not self.ip:
                return self.active
        return super().is_active(wait)
    
    def _stop_proxy(self, wait: bool = True, reset: bool = True):
        if self.stopped:
            return
        
        if self.destroy:
            request = self.manager._compute_v1.DeleteFirewallRequest(firewall=f'{self.name}-firewall', project=self.project)
            response = self.manager._firewall_client.delete(request=request)
            if not self.is_async and wait:
                _ = wait_for_extended_operation(response)
            
            try:
                request = self.manager._compute_v1.DeleteInstanceRequest(instance=self.name, project=self.project, zone=self.zone)
                response = self.manager._instances_client.delete(request=request)
                if not self.is_async and wait:
                    _ = wait_for_extended_operation(response)
            except:
                pass
            
            if self.logger:
                self.logger.info(f"Google proxy{' '+self.get_proxy_str() if self.get_proxy_str() else ''} removed.")
        else:
            if self.logger:
                self.logger.info(f"Google proxy{' '+self.get_proxy_str() if self.get_proxy_str() else ''} kept as per on_exit='keep' setting.")
        
        if not reset:
            return
        
        self.stopped = True
        self.id = None
        self.ip = ''
        self.port = 0
        self.region = ''
        self.user = ''
        self.password = ''
        self.logger = None
    
    def __str__(self):
        return f"Google p{super().__str__()[1:]}"

@ProxyManagers.register(CloudProvider.GOOGLE)
class ProxyManagerGoogle(BaseProxyManager[GoogleProxy]):
    def __init__(self,
                 ssh_key: list[dict[str, str] | str] | dict[str, str] | str,
                 project: str,
                 credentials: str = '',
                 log: bool = True,
                 log_file: str | None = None,
                 log_format: str = '%(asctime)-10s %(levelname)-5s %(message)s',
                 logger: Logger | None = None):
        '''Create a manager that provisions Google Cloud proxy instances on demand.

        The manager validates credentials, configures SSH keys and logging,
        initializes Google Compute Engine clients, and loads available
        regions/zones plus the latest Ubuntu image used for proxy instances.

        Parameters
        ----------
        project : str
            Google Cloud project ID where proxy instances are created.
        ssh_key : list[dict[str, str] | str] | dict[str, str] | str
            SSH key configuration for created instances, provided either as a
            single public key string, a dictionary with keys
            ``{'name': ..., 'public_key': ...}``, a list mixing both formats,
            or a file path containing one public key per line.
        credentials : str, optional
            Path to a Google service-account JSON credentials file. Used only
            when ``GOOGLE_APPLICATION_CREDENTIALS`` is not already set in the
            environment. Defaults to ``''``.
        log : bool, optional
            Enable logging for manager actions. Defaults to ``True``.
        log_file : str or None, optional
            File path for logging output. If ``None``, logs are emitted to
            the terminal. Defaults to ``None``.
        log_format : str, optional
            Format string used by ``logging`` when an internal logger is
            created. Defaults to
            ``'%(asctime)-10s %(levelname)-5s %(message)s'``.
        logger : Logger or None, optional
            Custom logger instance. When provided, ``log_file`` and
            ``log_format`` are ignored. Defaults to ``None``.

        Raises
        ------
        GoogleAuthException
            If credentials are required but neither
            ``GOOGLE_APPLICATION_CREDENTIALS`` nor ``credentials`` is provided.
        TypeError
            If ``ssh_key`` has an invalid structure.
        ImportError
            If ``google-cloud-compute`` is not installed.

        Examples
        --------
        Use environment-based credentials with a context manager::

            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'my_google_credentials.json'
            manager = ProxyManagerGoogle(
                'my-google-project',
                ssh_key='ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC2...'
            )
            with manager.get_proxy() as proxy:
                result = requests.get('https://google.com', proxies=proxy.get_proxy())

        Pass credentials explicitly and close manually::

            manager = ProxyManagerGoogle(
                'my-google-project',
                credentials='my_google_credentials.json'
            )
            proxy = manager.get_proxy()
            try:
                # Use the proxy
                pass
            finally:
                proxy.close()
        '''
        
        credentials_file = environ.get("GOOGLE_APPLICATION_CREDENTIALS", '')
        if not credentials_file and not credentials:
            raise GoogleAuthException("Can't find google auth credentials! Set the GOOGLE_APPLICATION_CREDENTIALS environment variable or pass the credentials path to the manager.")
        if credentials:
            credentials_file = credentials
        
        self.project = project
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
        
        try:
            from google.cloud import compute_v1
            from google.api_core import exceptions as google_exceptions
            from google.oauth2 import service_account
        except:
            raise ImportError("Install google-cloud-compute to use the google cloud proxies. "
                              "python3 -m pip install google-cloud-compute")
        
        credential = service_account.Credentials.from_service_account_file(credentials_file)
        
        self._compute_v1 = compute_v1
        self._machine_types_client = self._compute_v1.MachineTypesClient(credentials=credential)
        self._images_client = self._compute_v1.ImagesClient(credentials=credential)
        self._firewall_client = self._compute_v1.FirewallsClient(credentials=credential)
        self._instances_client = self._compute_v1.InstancesClient(credentials=credential)
        
        self._google_exceptions = google_exceptions
        
        self._instance_proxy_sizes: dict[Literal["small", "medium", "large"], str] = {"small": "e2-micro", "medium": "e2-highcpu-2", "large": "e2-highcpu-4"}
        #self._instance_vpn_sizes: dict[Literal["small", "medium", "large"], str] = {"small": "e2-small", "medium": "e2-standard-2", "large": "e2-standard-4"}
        
        # get all available regions and zones
        self._regions, self._sizes_regions = get_avaliable_regions_by_size(self._compute_v1, self._machine_types_client, self.project, self._instance_proxy_sizes)
        
        # get latest ubuntu-minimal-2404-noble-amd64 image
        request = self._compute_v1.ListImagesRequest(project='ubuntu-os-cloud', filter='name eq "ubuntu-minimal-2404-noble-amd64.*"')
        images_results = self._images_client.list(request=request)
        self.proxy_image = sorted([x.name for x in images_results.items], reverse=True)[0]
    
    @classmethod
    def from_config(cls, config: GoogleConfig | None = None, runtime_config: ManagerRuntimeConfig | None = None) -> 'ProxyManagerGoogle':
        """Create a ProxyManagerGoogle instance from a GoogleConfig object and a ManagerRuntimeConfig."""
        if config is None or runtime_config is None:
            raise ValueError("GoogleConfig must be provided to create a ProxyManagerGoogle instance.")
        return cls(config.ssh_key, config.project, config.credentials, runtime_config.log, runtime_config.log_file, runtime_config.log_format, runtime_config.logger)
    
    def get_proxy(self,
                  port: int = 0,
                  size: Literal['small', 'medium', 'large'] = 'medium',
                  region: str = '',
                  auth: dict[Literal['user', 'password'], str] = {},
                  allowed_ips: str | list[str] = [],
                  is_async: bool = False,
                  retry: bool = True,
                  proxy_name: str = '',
                  on_exit: Literal['keep', 'destroy'] = 'destroy') -> GoogleProxy:
        """Create and start a Google Cloud proxy instance.

        Parameters
        ----------
        port : int, optional
            TCP port for the proxy. If 0, a random port between 10000 and
            65000 will be selected. Defaults to ``0``.
        size : {'small', 'medium', 'large'}, optional
            Instance size. Defaults to ``'medium'``.
        region : str, optional
            Preferred Google Cloud region name. If provided, selection is
            restricted to this region. If empty, a region and zone are chosen
            at random from available regions.
        auth : dict, optional
            Authentication credentials with keys ``'user'`` and
            ``'password'``. If omitted, no authentication is configured.
            Defaults to an empty dict.
        allowed_ips : str or list[str], optional
            A single IP string or a list of IPs/ranges allowed to connect to
            the proxy. The caller's public IP is added automatically if not
            present. Defaults to an empty list.
        is_async : bool, optional
            If True, start the instance asynchronously (do not wait for it to
            be ready). Defaults to ``False``.
        retry : bool, optional
            Whether to allow retrying across other regions when selecting a
            zone. If a specific ``region`` is provided, retries are disabled.
            Defaults to ``True``.
        proxy_name : str, optional
            Explicit name for the proxy instance. If omitted a unique name of
            the form ``'proxyN'`` is generated.
        on_exit : {'keep', 'destroy'}, optional
            Behavior when the returned :class:`GoogleProxy` is closed.
            Defaults to ``'destroy'``.

        Returns
        -------
        GoogleProxy
            :class:`GoogleProxy` instance that represents the started proxy
            instance (contains name, ip, port, project, region, zone, size
            and lifecycle info).

        Raises
        ------
        NameError
            If ``proxy_name`` is provided and already exists.
        ValueError
            If the provided ``region`` does not exist or is not available.
        TypeError
            If ``auth`` is not a dict, or ``allowed_ips`` contains entries
            with an invalid format.
        KeyError
            If ``auth`` is provided but missing the required keys ``'user'``
            or ``'password'``.
        Exception
            If instance creation fails or the instance does not start
            correctly.
        """
        
        retry = retry if not region else False
        
        if not port:
            port = randint(10000, 65000)
        
        instances_list = self.get_running_proxy_names()
        if proxy_name:
            if proxy_name in instances_list:
                raise NameError(f"Proxy {proxy_name} already exists!")
        else:
            proxy_num = len(instances_list)+1
            while f"proxy{proxy_num}" in instances_list:
                proxy_num += 1
            proxy_name = f"proxy{proxy_num}"
        
        proxy_size = self._instance_proxy_sizes[size]
        servers = self._sizes_regions[size]
        random_region = False
        if region:
            if not any(region == x[0] for x in servers):
                raise ValueError(f"Region {region} doesn't exist or is not available for this size in google cloud!")
            region, zones = [x for x in servers if region == x[0]][0]
        else:
            random_region = True
            shuffle(servers)
            region, zones = choice(servers)
            
        zone = choice(zones)
        
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
            
            if not all(search(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(\\\d\d?)?', i) for i in ips):
                raise TypeError("IPs or ranges of ips with bad format!")
        
        if ip not in ips:
            ips.append(ip)
        
        if self.logger:
            self.logger.info(f"Starting a new google proxy in the zone {zone}{f" for the user {auth['user']}" if auth else " with no authentification"}...")
        
        proxy_ip, error = start_proxy(self, proxy_name, port, region, zone, [x for x in zones if x != zone], proxy_size, ips, auth['user'] if auth else '', auth['password'] if auth else '', is_async)
        if error and retry and random_region:
            if self.logger:
                self.logger.warning(f"Failed to start the google proxy in the region {region}. Retrying in another region...")
            
            # retry with another random region, excluding the previous one
            region, zones = choice([x for x in servers if x[0] != region])
            zone = choice(zones)
            proxy_ip, error = start_proxy(self, proxy_name, port, region, zone, [x for x in zones if x != zone], proxy_size, ips, auth['user'] if auth else '', auth['password'] if auth else '', is_async, firewall=False)
        
        if error:
            if self.logger:
                self.logger.error("Failed to start the google proxy after retrying.")
            
            # remove the instances created during the failed attempts to avoid leaving unused resources in the cloud
            request = self._compute_v1.DeleteFirewallRequest(firewall=f'{proxy_name}-firewall', project=self.project)
            _ = self._firewall_client.delete(request=request)
            
            raise Exception("Failed to start the google proxy instance.")
        
        return GoogleProxy(self, proxy_name, proxy_ip, port, self.project, region, zone, proxy_size, is_async=is_async, user=auth['user'] if auth else '', password=auth['password'] if auth else '', logger=self.logger, on_exit=on_exit)
    
    def get_proxy_by_name(self, name: str, is_async: bool = False, on_exit: Literal['destroy', 'keep'] = 'destroy') -> GoogleProxy:
        """Load an existing Google Cloud proxy instance by its name.

        This method looks up a running instance, extracts its public IP,
        proxy port and optional authentication credentials from the startup
        script metadata, and returns a reloaded :class:`GoogleProxy` wrapper.

        Parameters
        ----------
        name : str
            Name of the proxy instance in Google Cloud.
        is_async : bool, optional
            If True, do not wait for full startup before returning. Defaults
            to ``False``.
        on_exit : {'destroy', 'keep'}, optional
            Behavior when the returned :class:`GoogleProxy` is closed.
            Defaults to ``'destroy'``.

        Returns
        -------
        GoogleProxy
            :class:`GoogleProxy` object bound to the existing instance.

        Raises
        ------
        NameError
            If no proxy instance with the given ``name`` exists.
        ValueError
            If the proxy port cannot be parsed from the instance startup
            script.
        ValueError
            If the startup script cannot be found in the instance metadata.
        """
        
        instance_request = self._compute_v1.AggregatedListInstancesRequest(project=self.project, filter=f"name eq {name}")
        result = [response.instances[0] for _, response in self._instances_client.aggregated_list(instance_request) if response.instances]
        if not result:
            raise NameError(f"Proxy {name} doesn't exist in google cloud!")
        
        proxy_info = result[0]
        
        ip = proxy_info.network_interfaces[0].access_configs[0].nat_i_p
        
        try:
            startup_script = [x for x in proxy_info.metadata.items if x.key == 'startup-script'][0].value
        except IndexError:
            raise ValueError("Can't find the startup script in the instance metadata!")
        
        try:
            port = int(search(r'http_port (\d+)', startup_script).group(1)) # type: ignore
        except:
            raise ValueError("Can't find the proxy port in the startup script of the instance!")
        
        region = proxy_info.zone.split('/')[-1].rsplit('-', 1)[0]
        zone = proxy_info.zone.split('/')[-1]
        
        avaliable_zones = [x for r, zs in self._regions for x in zs if r == region and x != zone]
        
        proxy_instance = proxy_info.machine_type.split('/')[-1]
        
        # Search IPs in the squid config file to get the allowed ips for the proxy
        allowed_ips = [str(match.group(1)) for match in finditer(r'acl custom_ips src (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', startup_script)]
        
        auth_search = search(r'#auth credentials: user: (.+), password: (.+)\n', startup_script)
        auth = {}
        if auth_search:
            auth['user'] = auth_search.group(1)
            auth['password'] = auth_search.group(2)
        
        if self.logger:
            self.logger.info(f"Google proxy {name} reloaded with IP {ip} and port {port}{f" for the user {auth['user']}" if auth else " with no authentification found"}.")
        
        return GoogleProxy(self, name, ip, port, self.project, region, zone, proxy_instance=proxy_instance, is_async=is_async, allowed_ips=allowed_ips, user=auth['user'] if auth else '', password=auth['password'] if auth else '', logger=self.logger, reload=True, on_exit=on_exit)
    
    def get_running_proxy_names(self) -> list[str]:
        instances = list(self._instances_client.aggregated_list(request={'project': self.project, "filter": 'tags.items: "proxy"'}))
        instances_list = list(chain(*[x[1].instances for x in instances if 'instances' in x[1]]))
        return [x.name for x in instances_list]