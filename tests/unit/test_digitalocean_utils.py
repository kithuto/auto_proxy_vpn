"""Unit tests for DigitalOcean utility functions (mocked HTTP)."""

import pytest
import responses
from types import SimpleNamespace
from unittest.mock import MagicMock

DO_API = "https://api.digitalocean.com/v2"
HEADERS = {"Content-Type": "application/json", "Authorization": "Bearer tok"}


class TestGetOrCreateProject:
    @responses.activate
    def test_existing_default_project(self):
        responses.add(
            responses.GET,
            f"{DO_API}/projects",
            json={"projects": [{"id": "proj-id", "name": "MyProj", "is_default": True}]},
            status=200,
        )
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_or_create_project
        pid = get_or_create_project("MyProj", "desc", HEADERS)
        assert pid == "proj-id"

    @responses.activate
    def test_creates_new_project_when_missing(self):
        responses.add(
            responses.GET,
            f"{DO_API}/projects",
            json={"projects": []},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{DO_API}/projects",
            json={"project": {"id": "new-proj", "name": "NewProj"}},
            status=201,
        )
        responses.add(
            responses.PATCH,
            f"{DO_API}/projects/new-proj",
            json={"project": {"id": "new-proj"}},
            status=200,
        )
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_or_create_project
        pid = get_or_create_project("NewProj", "desc", HEADERS)
        assert pid == "new-proj"


class TestGetOrCreateSSHKeys:
    @responses.activate
    def test_existing_key_by_name(self):
        responses.add(
            responses.GET,
            f"{DO_API}/account/keys",
            json={"ssh_keys": [{"id": 42, "name": "mykey", "public_key": "ssh-rsa AAA"}]},
            status=200,
        )
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_or_create_ssh_keys
        keys = get_or_create_ssh_keys("mykey", HEADERS)
        assert keys == [42]

    @responses.activate
    def test_key_not_found_raises(self):
        responses.add(
            responses.GET,
            f"{DO_API}/account/keys",
            json={"ssh_keys": []},
            status=200,
        )
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_or_create_ssh_keys
        with pytest.raises(NameError, match="doesn't exists"):
            get_or_create_ssh_keys("missing-key", HEADERS)

    def test_empty_keys_raises(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_or_create_ssh_keys
        with pytest.raises(ValueError, match="ssh key"):
            get_or_create_ssh_keys([], HEADERS)

    @responses.activate
    def test_creates_key_from_dict(self):
        responses.add(
            responses.GET,
            f"{DO_API}/account/keys",
            json={"ssh_keys": []},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{DO_API}/account/keys",
            json={"ssh_key": {"id": 99}},
            status=201,
        )
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_or_create_ssh_keys
        keys = get_or_create_ssh_keys([{"name": "newkey", "public_key": "ssh-rsa BBB"}], HEADERS)
        assert keys == [99]


class TestGetServersAndSize:
    def test_small_returns_correct_slug(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_servers_and_size
        active = [{"slug": "nyc1", "sizes": ["s-1vcpu-512mb-10gb", "s-1vcpu-1gb"]}]
        size_slug, servers = get_servers_and_size("small", active, ["nyc1"])
        assert size_slug == "s-1vcpu-512mb-10gb"

    def test_medium_returns_correct_slug(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_servers_and_size
        size_slug, _ = get_servers_and_size("medium", [], ["nyc1"])
        assert size_slug == "s-1vcpu-1gb"

    def test_large_returns_correct_slug(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_servers_and_size
        size_slug, _ = get_servers_and_size("large", [], ["nyc1"])
        assert size_slug == "s-1vcpu-2gb"

    def test_invalid_size_raises(self):
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_servers_and_size
        with pytest.raises(NameError, match="Not valid"):
            get_servers_and_size("huge", [], [])


class TestGetNextProxyName:
    @responses.activate
    def test_first_proxy_name(self):
        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            json={"droplets": []},
            status=200,
        )
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_next_droplet_name
        name = get_next_droplet_name(HEADERS)
        assert name == "proxy1"

    @responses.activate
    def test_increments_name(self):
        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            json={"droplets": [{"name": "proxy1"}, {"name": "proxy2"}]},
            status=200,
        )
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_next_droplet_name
        name = get_next_droplet_name(HEADERS)
        assert name == "proxy3"

    @responses.activate
    def test_custom_name_returned(self):
        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            json={"droplets": []},
            status=200,
        )
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_next_droplet_name
        name = get_next_droplet_name(HEADERS, "custom-proxy")
        assert name == "custom-proxy"

    @responses.activate
    def test_duplicate_name_raises(self):
        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            json={"droplets": [{"name": "taken"}]},
            status=200,
        )
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_next_droplet_name
        with pytest.raises(NameError, match="already exists"):
            get_next_droplet_name(HEADERS, "taken")


class TestGetNextVpnName:
    @responses.activate
    def test_first_vpn_name(self):
        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            json={"droplets": []},
            status=200,
        )
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_next_droplet_name
        assert get_next_droplet_name(HEADERS, is_vpn=True) == "vpn1"

    @responses.activate
    def test_increments_vpn_name(self):
        responses.add(
            responses.GET,
            f"{DO_API}/droplets",
            json={"droplets": [{"name": "vpn1"}, {"name": "vpn2"}]},
            status=200,
        )
        from auto_proxy_vpn.providers.digitalocean.digitalocean_utils import get_next_droplet_name
        assert get_next_droplet_name(HEADERS, is_vpn=True) == "vpn3"


class TestStartProxy:
    def test_non_202_non_422_returns_error(self, monkeypatch):
        from auto_proxy_vpn.providers.digitalocean import digitalocean_utils as utils

        monkeypatch.setattr(utils, "post", lambda *args, **kwargs: SimpleNamespace(status_code=500))

        droplet_id, ip, error = utils.start_proxy(
            name="proxy1",
            image="img",
            region="nyc1",
            size="s-1vcpu-512mb-10gb",
            port=3128,
            ssh_keys=[1],
            headers=HEADERS,
            regions=["nyc1"],
            logger=None,
            is_async=True,
        )

        assert (droplet_id, ip, error) == (0, "", True)

    def test_422_without_retry_raises_country_not_available(self, monkeypatch):
        from auto_proxy_vpn.providers.digitalocean import digitalocean_utils as utils
        from auto_proxy_vpn.utils.exceptions import CountryNotAvailableException

        monkeypatch.setattr(utils, "post", lambda *args, **kwargs: SimpleNamespace(status_code=422))

        with pytest.raises(CountryNotAvailableException):
            utils.start_proxy(
                name="proxy1",
                image="img",
                region="nyc1",
                size="s-1vcpu-512mb-10gb",
                port=3128,
                ssh_keys=[1],
                headers=HEADERS,
                regions=["nyc1", "sfo1"],
                logger=MagicMock(),
                retry=False,
                is_async=True,
            )

    def test_successful_start_returns_ip(self, monkeypatch):
        from auto_proxy_vpn.providers.digitalocean import digitalocean_utils as utils

        monkeypatch.setattr(
            utils,
            "post",
            lambda *args, **kwargs: SimpleNamespace(
                status_code=202,
                json=lambda: {
                    "droplet": {
                        "id": 123,
                        "status": "new",
                        "networks": {"v4": []},
                    }
                },
            ),
        )
        monkeypatch.setattr(utils, "sleep", lambda *_: None)
        monkeypatch.setattr(
            utils,
            "get",
            lambda *args, **kwargs: SimpleNamespace(
                json=lambda: {
                    "droplet": {
                        "id": 123,
                        "status": "active",
                        "networks": {"v4": [{"type": "public", "ip_address": "1.2.3.4"}]},
                    }
                }
            ),
        )

        droplet_id, ip, error = utils.start_proxy(
            name="proxy1",
            image="img",
            region="nyc1",
            size="s-1vcpu-512mb-10gb",
            port=3128,
            ssh_keys=[1],
            headers=HEADERS,
            regions=["nyc1", "nyc2"],
            logger=None,
            is_async=False,
        )

        assert droplet_id == 123
        assert ip == "1.2.3.4"
        assert error is False
