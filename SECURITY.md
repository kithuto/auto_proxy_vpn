# Security Policy

## Reporting a Vulnerability

If you find a security issue, **please don't open a public issue**. Send me an email at **[your-email@example.com]** with `[SECURITY] auto_proxy_vpn` in the subject.

Include steps to reproduce and any details you think are relevant. I'll get back to you within 48 hours and work on a fix as fast as I can. Once it's resolved I'll credit you in the release notes (unless you'd rather stay anonymous).

## What This Project Handles

This package creates cloud VMs, installs Squid proxies on them via cloud-init, and manages SSH connections — so there are a few security-sensitive areas worth knowing about:

### Cloud API Credentials

Config objects (`AzureConfig`, `DigitalOceanConfig`, `GoogleConfig`) accept API tokens and service account credentials. These can be passed directly or read from environment variables.

- **Never hardcode credentials in your code.** Use `.env` files (added to `.gitignore`) or your provider's CLI auth.
- Use the minimum required permissions for each provider.
- Rotate tokens and service account keys regularly.

### SSH Keys

SSH keys are passed through config dataclasses and used via `subprocess` to connect to provisioned VMs. By default, `StrictHostKeyChecking` is disabled to simplify automated provisioning.

- Use **dedicated SSH key pairs** for proxy VMs — don't reuse your personal keys.
- Store private keys with restrictive permissions (`chmod 600`).

### Proxy Credentials in Cloud-Init

Squid proxy usernames and passwords are embedded in the cloud-init script that runs on VM creation. This means they're visible in the VM's cloud-init metadata.

- Be aware that anyone with access to the VM (or its cloud console) can see these credentials.
- Use `on_exit='destroy'` to clean up VMs when you're done, reducing the exposure window.

## Out of Scope

- Vulnerabilities in third-party SDKs (azure-identity, google-cloud-compute, etc.) — report those upstream.
- Misconfiguration of your own cloud accounts or firewall rules.
- Security of the underlying VMs beyond what this package provisions.
