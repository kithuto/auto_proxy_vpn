from auto_proxy_vpn.providers.digitalocean.digitalocean_exceptions import (
    DropletNotProxyException,
)


def test_droplet_not_proxy_exception_message():
    exc = DropletNotProxyException("not a proxy")
    assert str(exc) == "not a proxy"
