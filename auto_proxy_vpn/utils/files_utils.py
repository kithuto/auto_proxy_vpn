def get_ips_str(ips_list: list[str]):
    return "\n".join([f"acl custom_ips src {ip}" for ip in ips_list])

def get_ssh_keys_str(ssh_keys: list[str], user: str):
    keys = "\n".join(ssh_keys)
    create_user = True if user == 'root' else False
    if create_user:
        user = 'ubuntu'
    return f"""{f"\nuseradd -m -s /bin/bash -G sudo {user}" if create_user else ""}
mkdir -p /home/{user}/.ssh
chmod 700 /home/{user}/.ssh
echo "{keys}" > /home/{user}/.ssh/authorized_keys

chmod 600 /home/{user}/.ssh/authorized_keys
chown -R {user}:{user} /home/{user}/.ssh
"""

def get_squid_file(port: int, user: str = '', password: str = "", allowed_ips: list[str] = [], ssh_keys: list[str] = [], os_user: str = '') -> str:
    allowed_ips_str = get_ips_str(allowed_ips)+'\nhttp_access allow custom_ips' if allowed_ips else ''
    auth_str = f"""#auth credentials: user: {user}, password: {password}
auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwords
auth_param basic realm proxy
acl authenticated proxy_auth REQUIRED
http_access allow authenticated
{allowed_ips_str}
http_access deny all""" if user else ("http_access allow all" if not allowed_ips else get_ips_str(allowed_ips)+"\nhttp_access allow custom_ips\nhttp_access deny all")

    ssh_config = ""
    if ssh_keys and os_user:
        ssh_config = get_ssh_keys_str(ssh_keys, os_user)
    
    return f"""#!/bin/bash

apt update
apt install squid -y
{ssh_config}{f"htpasswd -b -c /etc/squid/passwords {user} {password}" if user else ""}
touch /etc/squid/squid.conf

echo "acl CONNECT method CONNECT

visible_hostname proxy-node
httpd_suppress_version_string on

via off
forwarded_for off

header_access From deny all
header_access Server deny all
header_access WWW-Authenticate deny all
header_access Link deny all
header_access Cache-Control deny all
header_access Proxy-Connection deny all
header_access X-Cache deny all
header_access X-Cache-Lookup deny all
header_access Via deny all
header_access Forwarded-For deny all
header_access X-Forwarded-For deny all
header_access Pragma deny all
header_access Keep-Alive deny all

{auth_str}

http_port {str(port)}

coredump_dir /var/spool/squid

refresh_pattern ^ftp:       1440    20% 10080
refresh_pattern ^gopher:    1440    0%  1440
refresh_pattern -i (/cgi-bin/|\\?) 0 0%  0
refresh_pattern (Release|Packages(.gz)*)$      0       20%     2880
refresh_pattern .       0   20% 4320" > /etc/squid/squid.conf

systemctl enable squid.service
systemctl restart squid.service"""