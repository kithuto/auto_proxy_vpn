from __future__ import annotations
from typing import Union, Literal
from random import shuffle, choice
from requests import get, delete
from time import sleep
import logging

from auto_proxy_vpn.utils.ssh_client import SSHClient
from .digitalocean_utils import get_or_create_project, get_or_create_ssh_keys, get_next_vpn_name, get_servers_and_size, start_vpn

class DigitalOceanVpn:
    def __init__(self, id: int,
                 ip: str,
                 port: int,
                 region: str,
                 users: list[str],
                 ftp_password: str,
                 allowed_ips: str,
                 headers: dict[str, str],
                 is_async: bool,
                 output: bool,
                 error: bool,
                 on_exit: Literal['keep', 'destroy'] = 'destroy') -> None:
        
        self.id = id
        self.ip = ip
        self.port = port
        self.users = users
        self._ftp_password = ftp_password
        self._users_dict = {x: 'peer'+str(pos+1) for pos, x in enumerate(users)}
        self.region = region
        self.allowed_ips = allowed_ips
        self.is_async = is_async
        self._headers = headers
        self.output = output
        if not on_exit in ['keep', 'destroy']:
            raise ValueError("Bad on_exit option!")
        self.destroy = True if on_exit == 'destroy' else False
        self.stopped = False
        
        self._ssh_session = SSHClient(ip, user='root')
        
        self._digitalocean_active = not error
        self.active = False
        if self.output:
            print('Waitting for the VPN to be set up...')
        self.active = self.is_active()
        if output:
            if self.active:
                print('New VPN created and ready to use.')
            else:
                print('New VPN created but not active yet.')
        
    def is_active(self) -> bool:
        if not self._digitalocean_active:
            if not self.is_async:
                times = 0
                while (not self.ip or not self._digitalocean_active) and times < 9:
                    try:
                        droplet = get('https://api.digitalocean.com/v2/droplets/'+str(self.id), headers=self._headers).json()['droplet']
                        self._digitalocean_active = droplet['status'] == 'active'
                        if self._digitalocean_active:
                            self.ip = [x for x in droplet['networks']['v4'] if x['type'] == 'public'][0]['ip_address']
                    except:
                        times += 1
                        sleep(10)
            else:
                try:
                    droplet = get('https://api.digitalocean.com/v2/droplets/'+str(self.id), headers=self._headers).json()['droplet']
                    self._digitalocean_active = droplet['status'] == 'active'
                    if self._digitalocean_active:
                        self.ip = [x for x in droplet['networks']['v4'] if x['type'] == 'public'][0]['ip_address']
                except:
                    pass
            if not self._digitalocean_active:
                return self._digitalocean_active
        if not self.active:
            if not self.is_async:
                times = 0
                while not self.active and times < 40:
                    if not self._ssh_session.connect():
                        times += 1
                        sleep(5)
                    else:
                        _, _, stderr = self._ssh_session.run_command('cd wireward/config/peer1; ls -l')
                        
                        if not stderr:
                            self.active = True
                        else:
                            times += 1
                            sleep(5)
                        
            else:
                if self._ssh_session.connect():
                    _, _, stderr = self._ssh_session.run_command('cd wireward/config/peer1; ls -l')
                    
                    if not stderr:
                        self.active = True
                
        return self.active
    
    def get_user_conf(self, user: str) -> None:
        if not self.is_active():
            print('VPN not active yet...')
            return
        if user not in self._users_dict.keys(): # type: ignore
            raise KeyError("This vpn user doesn't exists")
        
        user_str = self._users_dict[user] # type: ignore
        
        self._ssh_session.download_file(f'wireward/config/{user_str}/{user_str}.conf', f'{user}.conf')
        
        print('Downloaded config file in '+user+'.conf')
    
    def get_user_qrcode(self, user: str) -> bool:
        if not self.is_active():
            if self.output:
                print('VPN not active yet...')
            return False
        
        if user not in self._users_dict.keys(): # type: ignore
            raise KeyError("This vpn user doesn't exist")
        
        user_str = self._users_dict[user] # type: ignore
        
        self._ssh_session.download_file(f'wireward/config/{user_str}/{user_str}.png', f'{user}.png')
        
        if self.output:
            print('Downloaded qrcode in '+user+'.png')
        
        return True
    
    def _stop_vpn(self):
        if not self.stopped:
            response = delete('https://api.digitalocean.com/v2/droplets/'+str(self.id), headers=self._headers)
            if response.status_code < 300:
                self.id = None
                self.ip = None
                self.port = None
                self.users = None
                self._ftp_password = None
                self._users_dict = None
                self.region = None
                self._headers = None
            
            if self.output:
                if response.status_code > 300:
                    print("VPN already removed.")
                else:
                    print("VPN removed.")
                    
            self.stopped = True
    
    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self.destroy:
            self._stop_vpn()
        self.output = False
        self.log = False
    
    def __del__(self):
        if self.destroy:
            self._stop_vpn()
    
class VPNManagerDigitalOcean:
    """Creates a new DigitalOcean manager for automatic droplet creation with WireGuard.

    Go to https://www.wireguard.com/install/ to download the desktop client.

    Parameters
    ----------
    token : str
        DigitalOcean API token.
    sftp_password : str
        A secure password to use in the SFTP service (to download VPN keys
        for each user).
    ssh_keys : list or dict or str, optional
        Can be a list of ints with DigitalOcean ssh_key ids, a list of
        ssh_key names, or a list of dicts with the name and the ssh_key.
        Will create a new SSH key if it doesn't exist. No SSH access to
        the server if empty. Default: ``[]``.

        Example::

            {'name': 'ssh name', 'public_key': 'ssh-rsa AAAAB3...'}
            [{'name': 'ssh name', 'public_key': 'ssh-rsa AAAAB3...'}, 12313473, 'ssh test key']

    project_name : str, optional
        The project where the VPNs will be created. Default: ``'AutoVPNs'``.
    project_description : str, optional
        The project description. Default: ``'On demand WireGuard VPNs'``.
    output : bool, optional
        Prints the logs in the command line. Default: ``True``.
    log_file : str, optional
        File name. Outputs the logs to a file. Default: ``''``.
    """
    def __init__(self,
                 token: str,
                 sftp_password: str,
                 ssh_keys: Union[list[Union[dict[str, str], str]], dict[str, str], str] = [],
                 project_name: str = 'AutoVPNs',
                 project_description: str = 'On demand WireWard VPNs',
                 output: bool = True,
                 log_file: str = '') -> None:
        
        self.vpn_image = 'docker-20-04'
        self._sftp_password = sftp_password
        self.output = output
        self.log = True if log_file else False
        self.logger = None
        if self.log:
            self.logger = logging.getLogger('vpn_logger')
        self._headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token
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
        self._sizes_regions: dict[Literal["small", "medium", "large"], list[str]] = {'small': [x['slug'] for x in self._active_servers if 's-1vcpu-512mb-10gb' in x['sizes']], 'medium': self._servers, 'large': self._servers}
        
        # setting the project id
        self.project = get_or_create_project(project_name, project_description, self._headers)
        
        # set the ssh keys
        self.ssh_keys = get_or_create_ssh_keys(ssh_keys, self._headers)
        
        self._vpns = []
        
    def create_vpn(self,
                region: str,
                users: list[str],
                port: int = 52820,
                size: Literal['small', 'medium', 'large'] = 'medium',
                allowed_ips: str = '0.0.0.0/0',
                retry: bool = True,
                is_async: bool = False,
                on_exit: Literal['keep', 'destroy'] = 'destroy') -> Union[DigitalOceanVpn, list[DigitalOceanVpn]]:
        """Start a WireGuard VPN in DigitalOcean.

        Parameters
        ----------
        region : str
            Region to start the VPN on. If empty, a random region is chosen.
            Possible regions: ``['nyc1', 'nyc2', 'nyc3', 'sfo1', 'sfo2',
            'sfo3', 'ams2', 'ams3', 'sgp1', 'lon1', 'fra1', 'tor1',
            'blr1', 'syd1']``.
        users : list[str]
            List of the users to access the VPN.
        port : int, optional
            Port number for the VPN. Default: ``52820``.
        size : {'small', 'medium', 'large'}, optional
            Size of the server to deploy. Small size has fewer regions
            available. Default: ``'medium'``.
        allowed_ips : str, optional
            IPs allowed to access the VPN server. Default: ``'0.0.0.0/0'``.
        retry : bool, optional
            If ``True``, tries another region if the chosen one is
            unavailable.
        is_async : bool, optional
            If ``True``, returns immediately without waiting for the VPN
            to become active.
        on_exit : {'keep', 'destroy'}, optional
            Action to take when the VPN is no longer needed.
            Default: ``'destroy'``.

        Returns
        -------
        DigitalOceanVpn or list[DigitalOceanVpn]
            The newly created VPN(s).
        """
        vpn_name = get_next_vpn_name(self._headers)
        
        if port < 1000:
            raise ValueError('Port number must be greater than 1000')
        
        if not on_exit in ['keep', 'destroy']:
            raise ValueError("Bad on_exit option!")
        
        vpn_size, servers = get_servers_and_size(size, self._active_servers, self._servers, vpn=True)
        
        if not region:
            if self.output:
                print('Choosing a random region...')
            shuffle(servers)
            region = choice(servers)
        
        if not users:
            raise ValueError("VPN users can't be empty")
        
        if self.output:
            print("Starting a new VPN in the region "+region+"...")
            
        vpn_id, vpn_ip, error = start_vpn(vpn_name, self.vpn_image, region, vpn_size, port, self.ssh_keys, len(users), self._sftp_password, allowed_ips, self._headers, servers, self.output, is_async, retry) # type: ignore
        
        if error:
            raise ConnectionError('Error creating the vpn in DigitalOcean.')
        
        if not vpn_id:
            raise ConnectionError('Error creating the vpn in DigitalOcean.')
    
        vpn = DigitalOceanVpn(vpn_id, vpn_ip, port, region, users, self._sftp_password, allowed_ips, self._headers, self.output, error, is_async, on_exit)
        
        self._vpns.append(vpn)
        
        return vpn