from logging import Logger
from typing import Optional, Tuple
from requests import get, post, patch
from time import sleep
from random import choice
from re import search

from auto_proxy_vpn.utils.files_utils import get_squid_file
from auto_proxy_vpn.utils.exceptions import CountryNotAvailableException

def get_or_create_project(name: str, description: str, headers: dict[str, str]) -> str:
    '''
    Creates the project if doesn't exist and sets the project as default. Returns the project id.
    '''
    try:
        projects = get('https://api.digitalocean.com/v2/projects', headers=headers, timeout=15)
    except:
        raise ConnectionError('Error connecting to DigitalOcean.')
    if projects.status_code >= 400:
        raise ConnectionError('Error connecting to DigitalOcean.')
    projects = projects.json()['projects']
    project_id = [x for x in projects if x['name'] == name]
    if not project_id or not project_id[0]['is_default']:
        if not project_id:
            data_proxy = {
                "name": name,
                "description": description,
                "purpose": "Service or API",
                "environment": "Production",
                "is_default": False
            }
            project_id = [post('https://api.digitalocean.com/v2/projects', headers=headers, json=data_proxy).json()['project']]
        
        data = {
            "is_default": True
        }
        project_id = patch('https://api.digitalocean.com/v2/projects/'+project_id[0]['id'], headers=headers, json=data).json()['project']['id']
    else:
        project_id = project_id[0]['id']
        
    return project_id

def get_or_create_ssh_keys(ssh_keys: list[dict[str, str] | str] | dict[str, str] | str, headers: dict[str, str]) -> list[int]:
    '''
    Gets or creates ssh keys in DigitalOcean. If no ssh key then a dummy one will be created.
    '''
    if not ssh_keys:
        raise ValueError('At least one ssh key is required to create a proxy in DigitalOcean. Please provide at least one ssh key or create a dummy one.')
    
    if isinstance(ssh_keys, dict) or isinstance(ssh_keys, str):
        ssh_keys = [ssh_keys]
    
    if not isinstance(ssh_keys, list):
        raise TypeError('Bad ssh_key')
    
    all_ssh_keys = get('https://api.digitalocean.com/v2/account/keys', headers=headers).json()['ssh_keys']
    
    keys = []
    for item in ssh_keys:
        if isinstance(item, dict):
            if (len(item.keys()) > 2 or 'name' not in item.keys() or 'public_key' not in item.keys()):
                raise KeyError('ssh dict must have only name and public_key')
            key = [x for x in all_ssh_keys if x['name'] == item['name']]
            if not key:
                key = post('https://api.digitalocean.com/v2/account/keys', headers=headers, json=item).json()
                key = key['ssh_key']['id']
            else:
                key = key[0]['id']
        elif isinstance(item, str):
            keys_found = [x for x in all_ssh_keys if x['name'] == item]
            if not keys_found:
                raise NameError('ssh key '+ str(item) + " doesn't exists in DigitalOcean")
            key = keys_found[0]['id']
        else:
            raise TypeError('Bad ssh_key')
        
        if key not in keys:
            keys.append(key)
    
    return keys

def get_servers_and_size(server_size: str, active_servers: list[dict], servers: list[str], vpn: bool = False) -> Tuple[str, list[str]]:
    '''
    Get the server size slug and the list of servers that support it
    '''
    
    if server_size not in ['small', 'medium', 'large']:
        raise NameError('Not valid server size')
    
    if server_size == 'small':
        if vpn:
            return 's-1vcpu-1gb', servers
        return 's-1vcpu-512mb-10gb', [x['slug'] for x in active_servers if 's-1vcpu-512mb-10gb' in x['sizes']]
    
    elif server_size == 'medium':
        if vpn:
            return 's-1vcpu-2gb', servers
        return 's-1vcpu-1gb', servers
    
    else:
        if vpn:
            return 's-2vcpu-4gb', servers
        return 's-1vcpu-2gb', servers

def get_next_proxy_name(headers: dict[str, str], name: str = '') -> str:
    '''
    Get next avaliable proxy name.
    '''
    try:
        droplets = get('https://api.digitalocean.com/v2/droplets?tag_name=proxy', headers=headers).json()['droplets']
    except:
        raise ConnectionError('Error connecting to DigitalOcean.')
    
    if name:
        if [x['name'] for x in droplets if x['name'] == name]:
            raise NameError(f"Proxy {name} already exists!")
        return name
    
    names = sorted([x['name'] for x in droplets if search(r'^proxy\d+$', x['name'])])
    if names:
        last_name = names[-1]
        return 'proxy'+str(int(last_name[5:])+1)
    return 'proxy1'

def get_next_vpn_name(headers: dict[str, str]) -> str:
    '''
    Get next avaliable VPN name.
    '''
    try:
        droplets = get('https://api.digitalocean.com/v2/droplets', headers=headers).json()['droplets']
    except:
        raise ConnectionError('Error connecting to DigitalOcean.')
    
    names = sorted([x['name'] for x in droplets if search(r'^vpn\d+$', x['name'])])
    if names:
        last_name = names[-1]
        return 'vpn'+str(int(last_name[3:])+1)
    return 'vpn1'

def start_proxy(name: str,
                image: str,
                region: str,
                size: str,
                port: int,
                ssh_keys: list[int],
                headers: dict[str, str],
                regions: list[str],
                logger: Optional[Logger],
                allowed_ips: list[str] = [],
                user: str = '',
                password: str = '',
                is_async: bool = False,
                retry: bool = True) -> Tuple[int, str, bool]:
    """Create a DigitalOcean droplet configured as an HTTP proxy.

    The function provisions a droplet with a Squid startup script, optionally
    retries in alternative regions when capacity errors occur (HTTP 422), and
    returns the droplet id, detected public IP, and an error flag.

    Parameters
    ----------
    name : str
        Droplet name.
    image : str
        DigitalOcean image slug used to create the droplet.
    region : str
        Preferred region slug.
    size : str
        Droplet size slug.
    port : int
        Proxy port used in Squid configuration.
    ssh_keys : list[int]
        List of DigitalOcean SSH key IDs attached to the droplet.
    headers : dict[str, str]
        Request headers including API authorization.
    regions : list[str]
        Candidate region list used for fallback retries. This list may be
        modified in place when a region is discarded.
    logger : Logger or None
        Optional logger used for status/warning messages.
    allowed_ips : list[str], optional
        Source IPs/ranges allowed by Squid. Defaults to an empty list.
    user : str, optional
        Basic-auth username configured in Squid. Defaults to ``''``.
    password : str, optional
        Basic-auth password configured in Squid. Defaults to ``''``.
    is_async : bool, optional
        If True, do not wait for droplet activation before returning.
        Defaults to ``False``.
    retry : bool, optional
        If True, retry in other available regions when region capacity is
        unavailable. Defaults to ``True``.

    Returns
    -------
    tuple[int, str, bool]
        A tuple ``(droplet_id, public_ip, error)`` where ``error`` indicates
        whether startup/IP resolution failed.

    Raises
    ------
    CountryNotAvailableException
        If no suitable region is available and ``retry`` is False (or no
        fallback remains).
    """
    
    image_commands = get_squid_file(port, user, password, allowed_ips)

    data = {
        "name": name,
        "region": region,
        "size": size,
        "image": image,
        "ssh_keys": ssh_keys,
        "tags": ["proxy"],
        "user_data": image_commands,
        "with_droplet_agent": False
    }
    
    new_droplet = post('https://api.digitalocean.com/v2/droplets', headers=headers, json=data)
    
    if new_droplet.status_code != 202:
        if new_droplet.status_code == 422:
            if logger:
                logger.warning(f"The region {region} isn't avaliable in DigitalOcean.")
            regions.remove(region)
            local_regions = [x for x in regions if x[:-1] == region[:-1]]
            if local_regions:
                region = choice(local_regions) # type: ignore
                if logger:
                    logger.info(f"Starting a new DigitalOcean proxy in the region {region}...")
                return start_proxy(name, image, region, size, port, ssh_keys, headers, regions, logger, allowed_ips, user, password, is_async, retry)
            if logger:
                logger.warning(f"No more servers in {region[:-1]} are avaliable in DigitalOcean.")
                
            if retry:
                region = choice(regions)
                if logger:
                    logger.info(f"Starting a new DigitalOcean proxy in the region {region}...")
                return start_proxy(name, image, region, size, port, ssh_keys, headers, regions, logger, allowed_ips, user, password, is_async, retry)
            else:
                raise CountryNotAvailableException(f"The region {region[:-1]} isn't avaliable in DigitalOcean!")
        return 0, '', True
    else:
        new_droplet = new_droplet.json()['droplet']
    
    times = 0
    error = True
    if not is_async:
        sleep(15)
        while new_droplet['status'] != 'active' and times < 10:
            try:
                new_droplet = get('https://api.digitalocean.com/v2/droplets/'+str(new_droplet['id']), headers=headers).json()['droplet']
                error = False
            except:
                times += 1
                sleep(5)
    
    try:
        ip = [x for x in new_droplet['networks']['v4'] if x['type'] == 'public']
        if ip:
            ip = ip[0]['ip_address']
        else:
            ip = ''
            error = True
    except:
        ip = ''
        error = True
    
    return new_droplet['id'], ip, error

def start_vpn(name: str,
              image: str,
              region: str,
              size: str,
              port: int,
              ssh_keys: list[int],
              num_users: int,
              ftp_password: str,
              allowed_ips: str,
              headers: dict[str, str],
              regions: list[str],
              output: bool,
              is_async: bool = False,
              retry: bool = True,
              times: int = 0) -> Tuple[int, str, bool]:
    
    image_commands = f"""#!/bin/bash

rm -R /etc/ssh/sshd_config.d/*

echo -e '{ftp_password}\n{ftp_password}' | passwd root

systemctl restart sshd.service

cd ~
mkdir wireward
cd wireward

echo "services:
  wireguard:
    image: lscr.io/linuxserver/wireguard:latest
    container_name: wireguard
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Europe/Madrid
      - SERVERURL=auto
      - PEERS={str(num_users)}
      - PEERDNS=auto
      - INTERNAL_SUBNET=10.13.13.0
      - ALLOWEDIPS={allowed_ips}
      - LOG_CONFS=false
    volumes:
      - ./config:/config
      - /lib/modules:/lib/modules
    ports:
      - {str(port)}:51820/udp
    sysctls:
      - net.ipv4.conf.all.src_valid_mark=1
    restart: always" > docker-compose.yml

docker compose up -d"""

    data = {
        "name": name,
        "region": region,
        "size": size,
        "image": image,
        "ssh_keys": ssh_keys,
        "tags": ["vpn"],
        "user_data": image_commands,
        "with_droplet_agent": False
    }
    
    new_droplet = post('https://api.digitalocean.com/v2/droplets', headers=headers, json=data)
    
    if new_droplet.status_code != 202:
        if new_droplet.status_code == 422:
            if output:
                print('The region '+region+" isn't avaliable.")
            if retry:
                if times == 5:
                    if output:
                        print('Something going wrong in digitalocean...')
                    return 0, '', True
                regions.remove(region)
                local_regions = [x for x in regions if x[:-1] == region[:-1]]
                if local_regions:
                    region = choice(local_regions) # type: ignore
                else:
                    if output:
                        print('No servers in '+region[:-1]+' are avaliable.')
                    region = choice(regions)
                if output:
                    print("Starting a new vpn in the region "+region+"...")
                return start_vpn(name, image, region, size, port, ssh_keys, num_users, ftp_password, allowed_ips, headers, regions, output, is_async, times=times+1)
        if output:
            print('Something going wrong in digitalocean...')
        return 0, '', True
    else:
        new_droplet = new_droplet.json()['droplet']
    
    times = 0
    error = False
    if not is_async:
        while new_droplet['status'] != 'active' and times < 3:
            sleep(5)
            try:
                new_droplet = get('https://api.digitalocean.com/v2/droplets/'+str(new_droplet['id']), headers=headers).json()['droplet']
            except:
                if output:
                    print('Error checking the status of the droplet... Trying again...')
                times += 1
                sleep(5)
        if new_droplet['status'] == 'active':
            error = True
        
    
    try:
        ip = [x for x in new_droplet['networks']['v4'] if x['type'] == 'public']
    except:
        ip = ''
        error = True
        
    if ip:
        ip = ip[0]['ip_address']
    else:
        ip = ''
        error = True
    
    return new_droplet['id'], ip, error