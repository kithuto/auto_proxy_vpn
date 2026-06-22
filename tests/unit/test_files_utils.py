from auto_proxy_vpn.utils.files_utils import get_squid_file


def test_get_squid_file_stores_hash_not_plaintext_password(monkeypatch):
    monkeypatch.setattr(
        "auto_proxy_vpn.utils.files_utils.hash_proxy_password",
        lambda password: "apv1$pbkdf2_sha256$1$salt$digest",
    )

    script = get_squid_file(
        3128,
        user="alice",
        password="super-secret",
        allowed_ips=["1.2.3.4", "10.0.0.0/24"],
    )

    assert "super-secret" not in script
    assert "password_hash" in script
    assert "apv1$pbkdf2_sha256$1$salt$digest" in script
    assert "#auth credentials" not in script
    assert "/usr/local/bin/auto_proxy_vpn_basic_auth.py" in script
    assert "auth_param basic program" in script
    assert "http_access allow authenticated custom_ips" in script
    assert "http_access allow custom_ips" not in script
    assert "cat > /etc/squid/squid.conf <<'SQUID_CONF'" in script
    assert "acl custom_ips src 10.0.0.0/24" in script


def test_get_squid_file_writes_ssh_keys_without_echo():
    script = get_squid_file(
        3128,
        ssh_keys=["ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCtest"],
        os_user="root",
    )

    assert "base64 -d > /home/proxy-user/.ssh/authorized_keys" in script
    assert "echo " not in script
