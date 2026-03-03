from typing import Literal
from requests import get, delete
from random import choice, randint, shuffle
from time import sleep
import logging
from re import search
from os import environ
from os.path import isfile

from auto_proxy_vpn import CloudProvider, ProxyManagers, ManagerRuntimeConfig, DigitalOceanConfig
from auto_proxy_vpn.utils.base_proxy import BaseProxy, BaseProxyManager
from .digitalocean_utils import get_or_create_project, get_or_create_ssh_keys, get_servers_and_size, start_proxy, get_next_droplet_name
from .digitalocean_exceptions import DropletNotProxyException
from auto_proxy_vpn.utils.exceptions import CountryNotAvailableException
from auto_proxy_vpn.utils.util import get_public_ip
from auto_proxy_vpn.utils.ssh_client import SSHClient

class DigitalOceanProxy(BaseProxy):
    def __init__(self,
                 id: int,
                 name: str,
                 ip: str,
                 port: int,
                 region: str,
                 token: str,
                 active: bool = False,
                 is_async: bool = False,
                 user: str = '',
                 password: str = '',
                 logger: logging.Logger | None = None,
                 reload: bool = False,
                 on_exit: Literal['keep', 'destroy'] = 'destroy'):
        """Represent a DigitalOcean droplet-based proxy instance.

        This object stores proxy metadata and lifecycle state, and can be
        initialized either for a newly created droplet or by reloading an
        existing one.

        Parameters
        ----------
        id : int
            DigitalOcean droplet ID.
        name : str
            Droplet name.
        ip : str
            Public IP address of the droplet. Can be empty while the droplet
            is still provisioning.
        port : int
            Proxy listening port.
        region : str
            Region slug where the droplet is deployed.
        token : str
            DigitalOcean API token used for management requests.
        active : bool, optional
            Whether the droplet is already active on DigitalOcean at
            initialization time. Defaults to ``False``.
        is_async : bool, optional
            If True, do not wait for full startup before returning. Defaults
            to ``False``.
        user : str, optional
            Basic-auth username configured for the proxy. Defaults to ``''``.
        password : str, optional
            Basic-auth password configured for the proxy. Defaults to ``''``.
        logger : logging.Logger or None, optional
            Logger used for status and lifecycle messages. Defaults to
            ``None``.
        reload : bool, optional
            If True, treat this instance as already initialized and skip
            startup activation checks. Defaults to ``False``.
        on_exit : {'keep', 'destroy'}, optional
            Behavior when the proxy is closed: keep the droplet or destroy it.
            Defaults to ``'destroy'``.

        Raises
        ------
        ValueError
            If ``on_exit`` is not ``'keep'`` or ``'destroy'``.
        """
        
        self.id = id
        self.name = name
        self.ip = ip
        self.port = port
        self.region = region
        self.user = user
        self.password = password
        self._headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token
        }
        self._digitalocean_active = active
        self.active = False
        self.is_async = is_async
        self.log = True if logger else False
        self.logger = logger
        self.stopped = False
        if on_exit not in ['keep', 'destroy']:
            raise ValueError("Bad on_exit option!")
        self.destroy = True if on_exit == 'destroy' else False
        
        if not reload:
            if not self.is_async and self.logger:
                self.logger.info('Waitting for the proxy to be set up...')
            self.active = self.is_active()
            if self.logger:
                self.logger.info(f'New DigitalOcean proxy{' '+self.get_proxy_str() if self.get_proxy_str() else ''} created {"and ready to use" if self.active else "but not active yet"}.')
        elif reload:
            self.active = self.is_active()
            if self.logger:
                self.logger.info(f'DigitalOcean proxy{' '+self.get_proxy_str() if self.get_proxy_str() else ''} reloaded and {"active" if self.active else "inactive"}.')
    
    def is_active(self, wait: bool = False) -> bool:
        if not self._digitalocean_active:
            if self.is_async and not wait:
                try:
                    droplet = get('https://api.digitalocean.com/v2/droplets/'+str(self.id), headers=self._headers).json()['droplet']
                    self._digitalocean_active = droplet['status'] == 'active'
                    if self._digitalocean_active:
                        self.ip = [x for x in droplet['networks']['v4'] if x['type'] == 'public'][0]['ip_address']
                except:
                    return self._digitalocean_active
            else:
                times = 0
                while (not self.ip or not self._digitalocean_active) and times < 10:
                    try:
                        droplet = get('https://api.digitalocean.com/v2/droplets/'+str(self.id), headers=self._headers).json()['droplet']
                        self._digitalocean_active = droplet['status'] == 'active'
                        if self._digitalocean_active:
                            self.ip = [x for x in droplet['networks']['v4'] if x['type'] == 'public'][0]['ip_address']
                    except:
                        times += 1
                        sleep(5)
            if not self._digitalocean_active:
                return self._digitalocean_active
        return super().is_active(wait)
        
    def _stop_proxy(self, wait: bool = True):
        if self.stopped or not self.destroy:
            return
        
        response = delete('https://api.digitalocean.com/v2/droplets/'+str(self.id), headers=self._headers)
        if self.logger:
            self.logger.info(f"DigitalOcean proxy{' '+self.get_proxy_str() if self.get_proxy_str() else ''}{' already' if response.status_code > 300 else ''} removed.")
        
        self.stopped = True
        
        if response.status_code < 300:
            self.id = None
            self.ip = ''
            self.port = 0
            self.region = None
            self.user = ''
            self.password = ''
            self._headers = None

    def __str__(self):
        return f"DigitalOcean p{super().__str__()[1:]}"

@ProxyManagers.register(CloudProvider.DIGITALOCEAN)
class ProxyManagerDigitalOcean(BaseProxyManager[DigitalOceanProxy]):
    def __init__(self,
                 ssh_key: list[dict[str, str] | str] | dict[str, str] | str,
                 project_name: str = 'AutoProxyVPN',
                 project_description: str = 'On demand proxies',
                 token: str = '',
                 log: bool = True,
                 log_file: str | None = None,
                 log_format: str = '%(asctime)-10s %(levelname)-5s %(message)s',
                 logger: logging.Logger | None = None):
        """Create a manager that provisions DigitalOcean proxy droplets on demand.

        The manager validates API access, loads available regions and sizes,
        ensures a target project exists, and registers/creates SSH keys for
        newly created droplets.

        Parameters
        ----------
        ssh_key : list[dict[str, str] | str] | dict[str, str] | str
            SSH key configuration used for new droplets. Accepted forms are a
            single public key string, a dict with
            ``{'name': ..., 'public_key': ...}``, a list mixing both forms,
            or a file path containing one public key per line.
        project_name : str, optional
            Name of the DigitalOcean project used to group managed proxies.
            Defaults to ``'AutoProxyVPN'``.
        project_description : str, optional
            Description for the DigitalOcean project if it needs to be
            created. Defaults to ``'On demand proxies'``.
        token : str, optional
            DigitalOcean API token. If empty, the value is read from the
            ``DIGITALOCEAN_API_TOKEN`` environment variable. Defaults to
            ``''``.
        log : bool, optional
            Enable logging for manager actions. Defaults to ``True``.
        log_file : str or None, optional
            File path for logging output. If ``None``, logs are emitted to
            the terminal. Defaults to ``None``.
        log_format : str, optional
            Format string used by ``logging`` when an internal logger is
            created. Defaults to
            ``'%(asctime)-10s %(levelname)-5s %(message)s'``.
        logger : logging.Logger or None, optional
            Custom logger instance. When provided, ``log_file`` and
            ``log_format`` are ignored. Defaults to ``None``.

        Raises
        ------
        ValueError
            If no API token is provided through ``token`` or
            ``DIGITALOCEAN_API_TOKEN``.
        ConnectionRefusedError
            If the provided DigitalOcean token is invalid.
        ConnectionError
            If DigitalOcean API validation cannot be completed.

        Examples
        --------
        Use environment token with a context manager::

            proxy_manager = ProxyManagerDigitalOcean(
                ssh_key='dummy existing key'
            )
            with proxy_manager.get_proxy() as proxy:
                result = requests.get('https://google.com', proxies=proxy.get_proxy())

        Pass token explicitly and close manually::

            proxy_manager = ProxyManagerDigitalOcean(
                ssh_key={'name': 'dummy_key', 'public_key': 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC2...'},
                token='dop_v1_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
            )
            proxy = proxy_manager.get_proxy()
            try:
                # Use the proxy
                pass
            finally:
                proxy.close()
        """
        
        self.proxy_image = 'ubuntu-24-04-x64'
        self.log = True if log or log_file or logger else False
        self.log_format = log_format
        self.logger = logger
        if self.log and not logger:
            logging.basicConfig(filename=log_file,
                    format=self.log_format,
                    filemode='a',
                    datefmt='%d-%b-%Y %H:%M:%S',
                    level=logging.INFO)
            self.logger = logging.getLogger('proxy_logger')
        self._token = token if token else environ.get("DIGITALOCEAN_API_TOKEN", "")
        if not self._token:
            raise ValueError("DigitalOcean token not provided! Please provide it as an argument or set the DIGITALOCEAN_API_TOKEN environment variable.")
        self._headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + self._token
        }
        
        try:
            do_regions_resp = get('https://api.digitalocean.com/v2/regions', headers=self._headers)
        except:
            raise ConnectionError('Error connecting to DigitalOcean.')
        if do_regions_resp.status_code == 401:
            raise ConnectionRefusedError('Bad DigitalOcean token.')
        elif do_regions_resp.status_code >= 400:
            raise ConnectionError('Error connecting to DigitalOcean.')
        
        self._active_servers: list[dict] = [x for x in do_regions_resp.json()['regions'] if x['available']]
        self._servers: list[str] = [x['slug'] for x in self._active_servers]
        self._sizes_regions = {'small': [x['slug'] for x in self._active_servers if 's-1vcpu-512mb-10gb' in x['sizes']], 'medium': self._servers, 'large': self._servers}
        
        # setting the project id
        self.project: str = get_or_create_project(project_name, project_description, self._headers)
        
        # set the ssh keys
        if isinstance(ssh_key, str) and isfile(ssh_key):
            with open(ssh_key, "r") as f:
                ssh_key = [x.strip('\n') for x in f.readlines() if x.strip('\n')]
        self.ssh_keys: list[int] = get_or_create_ssh_keys(ssh_key, self._headers)
    
    @classmethod
    def from_config(cls, config: DigitalOceanConfig | None = None, runtime_config: ManagerRuntimeConfig | None = None) -> 'ProxyManagerDigitalOcean':
        """Create a ProxyManagerDigitalOcean instance from a DigitalOceanConfig object and a ManagerRuntimeConfig."""
        if config is None or runtime_config is None:
            raise ValueError("DigitalOceanConfig must be provided to create a ProxyManagerDigitalOcean instance.")
        return cls(config.ssh_key, config.project_name, config.project_description, config.token, runtime_config.log, runtime_config.log_file, runtime_config.log_format, runtime_config.logger)
    
    def get_proxy(self,
                  port: int = 0,
                  size: Literal['small', 'medium', 'large'] = 'medium',
                  region: str = '',
                  auth: dict[Literal['user', 'password'], str] = {},
                  allowed_ips: str | list[str] = [],
                  is_async: bool = False,
                  retry: bool = True,
                  proxy_name: str = '',
                  on_exit: Literal['keep', 'destroy'] = 'destroy') -> DigitalOceanProxy:
        '''Starts a new proxy in DigitalOcean with the given settings and returns a proxy object to manage it.
        
        Parameters
        ----------
        port : int, optional
            Port number for the proxy. Default: random port between 10000
            and 65000.
        size : {'small', 'medium', 'large'}, optional
            Size of the server to deploy. Small size has fewer regions.
            Defaults to ``'medium'``.
        region : str, optional
            Region to start the proxy on. Starts on a random region if empty.
            To get available regions by size call ``get_regions_by_size()``.
        auth : dict, optional
            Basic auth for the proxy.
            Example: ``{'user': 'test', 'password': 'test01'}``
        allowed_ips : str or list[str], optional
            Allowed IP addresses or CIDR ranges. If empty, the current public
            IP address is used by default. A single IP may be provided as a
            string. Example: ``'8.8.8.8'``, ``['127.0.0.0/8', '1.1.1.1']``
        is_async : bool, optional
            If True, returns without waiting for the proxy to be active.
        retry : bool, optional
            If True, retries in another region if the first isn't available.
            Always False when ``region`` is given.
        proxy_name : str, optional
            Name of the created proxy. By default ``proxy1``, ``proxy2``, etc.
        on_exit : {'keep', 'destroy'}, optional
            When the proxy is closed, ``'destroy'`` permanently removes it;
            otherwise it stays running and can be retrieved later with
            ``get_proxy_by_name``.
            
        Returns
        -------
        DigitalOceanProxy
            :class:`DigitalOceanProxy` instance containing the new created
            proxy.
        '''
        
        retry = retry if not region else False
        proxy_name = get_next_droplet_name(self._headers, proxy_name)
        
        if not port:
            port = randint(10000, 65000)
        
        proxy_size, servers = get_servers_and_size(size, self._active_servers, self._servers)
        
        shuffle(servers)
        if region and region not in servers:
            raise CountryNotAvailableException("This country isn't avaliable in DigitalOcean for this size")
        elif not region:
            region = choice(servers)
        
        if auth:
            if not isinstance(auth, dict):
                raise TypeError('Bad auth format, auth must be a dict')
            
            if 'user' not in auth.keys() or 'password' not in auth.keys():
                raise KeyError('Auth dict must have two keys name and password')
        
        if allowed_ips:
            if isinstance(allowed_ips, str):
                allowed_ips = [allowed_ips]
            
            if not all(search(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(\\\d\d?)?', ip) for ip in allowed_ips):
                raise TypeError("IPs or ranges of ips with bad format!")
        else:
            try:
                allowed_ips = [get_public_ip()]
            except:
                allowed_ips = []

        if self.logger:
            self.logger.info(f"Starting a new DigitalOcean proxy in the region {region}{f" for the user {auth['user']}" if auth else " with no authentification"}...")
        
        proxy_id, proxy_ip, error = start_proxy(proxy_name, self.proxy_image, region, proxy_size, port, self.ssh_keys, self._headers, servers, self.logger, allowed_ips, auth['user'] if auth else '', auth['password'] if auth else '', is_async, retry) # type: ignore
        
        active = not error
        if not proxy_id:
            raise ConnectionError('Error creating the proxy in DigitalOcean.')
        
        return DigitalOceanProxy(proxy_id, proxy_name, proxy_ip, port, region, self._token, active, is_async, auth['user'] if auth else '', auth['password'] if auth else '', self.logger, on_exit=on_exit)
    
    def get_proxy_by_name(self, name: str, is_async: bool = False, on_exit: Literal['destroy', 'keep'] = 'destroy') -> DigitalOceanProxy:
        """Gets a proxy instance by droplet name.

        Parameters
        ----------
        name : str
            Droplet name.
        is_async : bool, optional
            If True, the returned proxy uses asynchronous behavior for
            lifecycle operations. Defaults to ``False``.
        on_exit : {'keep', 'destroy'}, optional
            Keep or destroy the proxy when the program ends. Defaults to
            ``'destroy'``.
        
        Returns
        -------
        DigitalOceanProxy
            :class:`DigitalOceanProxy` instance of the proxy.
        
        Raises
        ------
        ConnectionError
            Can't connect to DigitalOcean.
        NameError
            Name of the droplet doesn't exist.
        ConnectionError
            Can't connect to the proxy through SSH.
        DropletNotProxyException
            The droplet isn't a proxy (Squid config not found).
        ValueError
            Port or auth credentials not found in the Squid config.
        """
        
        try:
            droplets = get(f'https://api.digitalocean.com/v2/droplets?name={name}&type=droplets', headers=self._headers).json()['droplets']
        except:
            raise ConnectionError("Error searching for the droplet!")
        
        if not droplets:
            raise NameError(f"Proxy {name} doesn't exists!")
        
        droplet = droplets[0]
        public_ip = [x for x in droplet['networks']['v4'] if x['type'] == 'public'][0]['ip_address']
        
        ssh_client = SSHClient(public_ip, 'root')
        _, proxy_file, _ = ssh_client.run_command('cat /etc/squid/squid.conf')
        if not proxy_file:
            raise ConnectionError("Can't connect to the proxy!")
        
        port_search = search(r'http_port (\d+)', proxy_file)
        if not port_search:
            raise DropletNotProxyException("This droplet isn't a proxxy!")
        port = int(port_search.group(1))
        
        auth_search = search(r'#auth credentials: user: (.+), password: (.+)\n', proxy_file)
        auth = {}
        if auth_search:
            auth['user'] = auth_search.group(1)
            auth['password'] = auth_search.group(2)
            
        if self.logger:
            self.logger.info(f"DigitalOcean proxy {name} reloaded with IP {public_ip} and port {port}{f" for the user {auth['user']}" if auth else " with no authentification found"}")
        
        return DigitalOceanProxy(droplet['id'], name, public_ip, port, droplet['region']['slug'], self._token, active=False, is_async=is_async, user=auth['user'] if auth else '', password=auth['password'] if auth else '', logger=self.logger, reload=True, on_exit=on_exit)
    
    def get_running_proxy_names(self) -> list[str]:
        try:
            droplets = get('https://api.digitalocean.com/v2/droplets?tag_name=proxy', headers=self._headers).json()['droplets']
        except:
            raise ConnectionError('Error connecting to DigitalOcean.')
        
        return [x['name'] for x in droplets]
        