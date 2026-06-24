# Security Policy

## Reporting a Vulnerability

If you find a security issue, **please don't open a public issue**. Send me an email at **[your-email@example.com]** with `[SECURITY] auto_proxy_vpn` in the subject.

Include steps to reproduce and any details you think are relevant. I'll get back to you within 48 hours and work on a fix as fast as I can. Once it's resolved I'll credit you in the release notes (unless you'd rather stay anonymous).

## What This Project Handles

This package creates cloud VMs, installs Squid proxies on them via cloud-init, and manages SSH connections — so there are a few security-sensitive areas worth knowing about:

### Cloud API Credentials

Config objects (`AwsConfig`, `AzureConfig`, `DigitalOceanConfig`, `GoogleConfig`) accept API tokens and service account credentials. These can be passed directly or read from environment variables.

- **Never hardcode credentials in your code.** Use `.env` files (added to `.gitignore`) or your provider's CLI auth.
- Use the minimum required permissions for each provider.
- Rotate tokens and service account keys regularly.

### SSH Keys

SSH keys are passed through config dataclasses and used via `subprocess` to connect to provisioned VMs. By default, `StrictHostKeyChecking` is disabled to simplify automated provisioning.

- Use **dedicated SSH key pairs** for proxy VMs — don't reuse your personal keys.
- Store private keys with restrictive permissions (`chmod 600`).

### Proxy Authentication Metadata

When basic auth is enabled, proxy passwords are not stored in plaintext in
`squid.conf`, cloud-init metadata, startup scripts, logs, or diagnostic output.
The generated Squid configuration stores only secure auth metadata with the
username and a PBKDF2-SHA256 password hash. The password itself is kept only in
memory while the proxy object is active so `get_proxy_str()` and `get_proxy()`
can return a usable authenticated proxy URL.

- Reconnecting to an authenticated proxy with `get_proxy_by_name(...)` requires
  passing `auth={"user": "...", "password": "..."}` again.
- If the supplied credentials do not match the stored hash, recovery fails.
- Proxies created with the old insecure plaintext metadata format are not
  supported; recreate them instead of relying on legacy recovery.
- Use unique proxy passwords and prefer `on_exit='destroy'` for disposable
  workloads to reduce the exposure window.

## Out of Scope

- Vulnerabilities in third-party SDKs (azure-identity, google-cloud-compute, etc.) — report those upstream.
- Misconfiguration of your own cloud accounts or firewall rules.
- Security of the underlying VMs beyond what this package provisions.
