from requests import get, RequestException
from ipaddress import ip_address
from typing import Optional

IP_SERVICES = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
]

def get_public_ip(timeout=2, proxy: Optional[dict[str, str]] = None):
    """
    Get the public IP address of the machine by querying multiple external services.
    """
    for url in IP_SERVICES:
        try:
            response = get(url, timeout=timeout, proxies=proxy)
            response.raise_for_status()
            ip = response.text.strip()

            # Validar IP (IPv4 o IPv6)
            ip_address(ip)
            return ip

        except (RequestException, ValueError):
            continue

    raise RuntimeError("Can't find the public IP address!")