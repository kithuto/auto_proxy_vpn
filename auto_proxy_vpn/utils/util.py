from logging import FileHandler, Formatter, INFO, Logger, StreamHandler, getLogger
from pathlib import Path
from requests import get, RequestException
from ipaddress import ip_address, ip_network
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


def is_ssh_key(key: str) -> bool:
    """
    Check if the provided string is a valid SSH public key.
    """
    return (
        key.startswith(("ssh-", "ecdsa-", "sk-ssh-", "sk-ecdsa-"))
        and len(key.split()) >= 2
    )


def normalize_allowed_ips(allowed_ips: str | list[str] | None) -> list[str]:
    if not allowed_ips:
        return []

    ips = [allowed_ips] if isinstance(allowed_ips, str) else list(allowed_ips)
    normalized_ips = []
    for ip in ips:
        try:
            normalized_ips.append(str(ip_network(ip, strict=False)))
        except ValueError as exc:
            raise TypeError("IPs or ranges of ips with bad format!") from exc
    return normalized_ips


def get_proxy_logger(
    log: bool = True,
    log_file: str | None = None,
    log_format: str = "%(asctime)-10s %(levelname)-5s %(message)s",
    logger: Logger | None = None,
) -> Logger | None:
    if logger:
        return logger
    if not (log or log_file):
        return None

    proxy_logger = getLogger("auto_proxy_vpn.proxy")
    proxy_logger.setLevel(INFO)
    proxy_logger.propagate = False
    formatter = Formatter(log_format, datefmt="%d-%b-%Y %H:%M:%S")

    resolved_log_file = str(Path(log_file).resolve()) if log_file else ""
    if log_file and not any(
        isinstance(handler, FileHandler)
        and getattr(handler, "baseFilename", None) == resolved_log_file
        for handler in proxy_logger.handlers
    ):
        handler = FileHandler(log_file)
        handler.setFormatter(formatter)
        proxy_logger.addHandler(handler)
    elif log and not proxy_logger.handlers:
        handler = StreamHandler()
        handler.setFormatter(formatter)
        proxy_logger.addHandler(handler)

    return proxy_logger
