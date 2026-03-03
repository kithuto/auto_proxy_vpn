from unittest.mock import Mock, patch

import pytest
from requests import RequestException

from auto_proxy_vpn.utils.util import get_public_ip


class TestGetPublicIp:
    def test_returns_ip_from_first_service(self):
        response = Mock()
        response.text = "8.8.8.8\n"
        response.raise_for_status.return_value = None

        with patch("auto_proxy_vpn.utils.util.get", return_value=response):
            ip = get_public_ip(timeout=1)

        assert ip == "8.8.8.8"

    def test_fallbacks_until_valid_ip(self):
        bad_response = Mock()
        bad_response.text = "not-an-ip"
        bad_response.raise_for_status.return_value = None

        good_response = Mock()
        good_response.text = "1.1.1.1"
        good_response.raise_for_status.return_value = None

        with patch(
            "auto_proxy_vpn.utils.util.get",
            side_effect=[RequestException("boom"), bad_response, good_response],
        ):
            ip = get_public_ip(timeout=1)

        assert ip == "1.1.1.1"

    def test_raises_when_all_services_fail(self):
        with patch(
            "auto_proxy_vpn.utils.util.get",
            side_effect=[RequestException("x"), RequestException("y"), RequestException("z")],
        ):
            with pytest.raises(RuntimeError, match="public IP"):
                get_public_ip(timeout=1)
