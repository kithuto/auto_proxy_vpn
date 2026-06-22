from base64 import b64encode
from re import fullmatch
from shlex import quote

from auto_proxy_vpn.utils.proxy_auth import (
    format_proxy_auth_metadata_comment,
    hash_proxy_password,
)

LINUX_USER_RE = r"[a-z_][a-z0-9_-]{0,31}"


def get_ips_str(ips_list: list[str]):
    return "\n".join([f"acl custom_ips src {ip}" for ip in ips_list])


def get_ssh_keys_str(ssh_keys: list[str], user: str = ""):
    create_user = user == "root" or not user
    if create_user:
        user = "proxy-user"

    if not fullmatch(LINUX_USER_RE, user):
        raise ValueError("Invalid linux user name")

    keys_b64 = b64encode("\n".join(ssh_keys).encode("utf-8")).decode("ascii")
    quoted_user = quote(user)
    home_dir = quote(f"/home/{user}")
    create_user_str = (
        f"\nid -u {quoted_user} >/dev/null 2>&1 || "
        f"useradd -m -s /bin/bash -G sudo {quoted_user}"
        if create_user
        else ""
    )
    return f"""{create_user_str}
mkdir -p {home_dir}/.ssh
chmod 700 {home_dir}/.ssh
printf '%s' '{keys_b64}' | base64 -d > {home_dir}/.ssh/authorized_keys
chmod 600 {home_dir}/.ssh/authorized_keys
chown -R {quoted_user}:{quoted_user} {home_dir}/.ssh
"""


def get_squid_file(
    port: int,
    user: str = "",
    password: str = "",
    allowed_ips: list[str] | None = None,
    ssh_keys: list[str] | None = None,
    os_user: str = "",
) -> str:
    allowed_ips = allowed_ips or []
    ssh_keys = ssh_keys or []
    auth_helper = ""
    password_hash = hash_proxy_password(password) if user else ""
    if user:
        access_rule = (
            f"{get_ips_str(allowed_ips)}\nhttp_access allow authenticated custom_ips"
            if allowed_ips
            else "http_access allow authenticated"
        )
        auth_str = f"""{format_proxy_auth_metadata_comment(user, password_hash)}
auth_param basic program /usr/local/bin/auto_proxy_vpn_basic_auth.py
auth_param basic realm proxy
auth_param basic credentialsttl 2 hours
acl authenticated proxy_auth REQUIRED
{access_rule}
http_access deny all"""
    else:
        auth_str = (
            "http_access allow all"
            if not allowed_ips
            else get_ips_str(allowed_ips)
            + "\nhttp_access allow custom_ips\nhttp_access deny all"
        )

    ssh_config = ""
    if ssh_keys:
        ssh_config = get_ssh_keys_str(ssh_keys, os_user)

    if user:
        auth_helper = f"""cat > /usr/local/bin/auto_proxy_vpn_basic_auth.py <<'PY'
#!/usr/bin/env python3
import base64
import hashlib
import hmac
import sys

AUTH_USER = {user!r}
PASSWORD_HASH = {password_hash!r}


def _b64_decode(value):
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def verify_password(password, password_hash):
    try:
        version, algorithm, iterations, salt, digest = password_hash.split("$", 4)
        if version != "apv1" or algorithm != "pbkdf2_sha256":
            return False
        iteration_count = int(iterations)
        if iteration_count <= 0 or iteration_count > 600000:
            return False
        salt_bytes = _b64_decode(salt)
        expected_digest = _b64_decode(digest)
        if len(salt_bytes) != 32 or len(expected_digest) != 32:
            return False
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt_bytes,
            iteration_count,
            dklen=len(expected_digest),
        )
    except Exception:
        return False
    return hmac.compare_digest(actual_digest, expected_digest)


for line in sys.stdin:
    try:
        supplied_user, supplied_password = line.rstrip("\\n").split(" ", 1)
    except ValueError:
        print("ERR")
    else:
        print(
            "OK"
            if supplied_user == AUTH_USER
            and verify_password(supplied_password, PASSWORD_HASH)
            else "ERR"
        )
    sys.stdout.flush()
PY
chmod 700 /usr/local/bin/auto_proxy_vpn_basic_auth.py
"""

    return f"""#!/bin/bash

apt update
apt install squid python3 -y
{ssh_config}{auth_helper}touch /etc/squid/squid.conf

cat > /etc/squid/squid.conf <<'SQUID_CONF'
acl CONNECT method CONNECT

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
refresh_pattern .       0   20% 4320
SQUID_CONF

systemctl enable squid.service
systemctl restart squid.service"""
