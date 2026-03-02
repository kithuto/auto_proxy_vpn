<p align="center">
  <h1 align="center">Auto proxy vpn</h1>
  <p align="center">
    On-demand proxies and VPNs across multiple cloud providers — from a single Python call.
  </p>
</p>

<p align="center">
  <a href="#installation">Installation</a> &nbsp;·&nbsp;
  <a href="#quick-start">Quick Start</a> &nbsp;·&nbsp;
  <a href="#supported-providers">Providers</a> &nbsp;·&nbsp;
  <a href="#proxy-pool">Proxy Pool</a> &nbsp;·&nbsp;
  <a href="#api-reference">API Reference</a> &nbsp;·&nbsp;
  <a href="#limitations">Limitations</a>
<!-- hide-nav-contributing -->
 &nbsp;·&nbsp;
  <a href="#contributing">Contributing</a>
<!-- /hide-nav-contributing -->
</p>

---

**auto_proxy_vpn** is a Python library that provisions disposable HTTP(S) proxy servers (and WireGuard VPNs) on major cloud platforms. Each proxy runs [Squid](http://www.squid-cache.org/) on a fresh VM/droplet, is accessible in one or two minutes, and is cleaned up automatically when you're done.

**Key features:**

- **Multi-cloud** — spin up proxies on Google Cloud, Azure, or DigitalOcean with the same API.
- **Zero infrastructure** — no pre-existing VMs, containers, or images required.
- **Context manager support** — resources are created on entry and destroyed on exit.
- **Proxy Pool** — distribute proxy creation across multiple providers with a single call.
- **Multi-account** — use multiple accounts per provider in the same pool to multiply capacity and avoid rate limits.
- **Batch creation** — provision multiple proxies at once with `create_batch()`.
- **Async-friendly** — return faster and poll readiness later.
- **Random region by default** — each proxy is deployed by default to a randomly selected region, maximizing IP diversity out of the box.
- **Basic auth & IP filtering** — optional Squid authentication and source-IP firewall rules.
- **Reconnect** — reload a previously created proxy by name without re-provisioning.

> **⚠️ Responsible Use:** This tool is intended for legitimate purposes such as testing, privacy, and accessing geo-restricted content you have rights to. If you use it for web scraping, please respect each website's `robots.txt`, rate limits, and terms of service. Hammering servers or bypassing protections you're not supposed to bypass isn't cool — and it gives tools like this a bad name.

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Supported Providers](#supported-providers)
- [Provider Setup Guides](#provider-setup-guides)
- [Usage](#usage)
  - [Single Provider](#single-provider)
  - [Proxy Pool (Multi-Provider)](#proxy-pool)
  - [Batch Creation](#batch-creation)
  - [Authentication & IP Filtering](#authentication--ip-filtering)
  - [Asynchronous Creation](#asynchronous-creation)
  - [Reconnecting to Existing Proxies](#reconnecting-to-existing-proxies)
- [API Reference](#api-reference)
  - [ProxyPool](#proxypool)
  - [BaseProxy](#baseproxy)
  - [ProxyBatch](#proxybatch)
  - [Configuration Objects](#configuration-objects)
- [Limitations](#limitations)
- [Project Structure](#project-structure)
- [Contributing](#contributing)

---

## Installation

```bash
pip install auto_proxy_vpn
```

Then install the SDK dependencies for the providers you plan to use:

| Provider | Extra packages |
|---|---|
| **DigitalOcean** | *(none — uses `requests`, already included)* |
| **Google Cloud** | `pip install google-cloud-compute` |
| **Azure** | `pip install azure-identity azure-mgmt-subscription azure-mgmt-resource azure-mgmt-network azure-mgmt-compute` |

## Quick Start

### 1. DigitalOcean — simplest setup

```python
from auto_proxy_vpn.providers.digitalocean import ProxyManagerDigitalOcean

manager = ProxyManagerDigitalOcean(
    ssh_key="my-existing-key-name",
    token="dop_v1_xxxx..."          # or set DIGITALOCEAN_API_TOKEN env var
)

with manager.get_proxy() as proxy:
    import requests
    r = requests.get("https://httpbin.org/ip", proxies=proxy.get_proxy())
    print(r.json())
# Droplet is destroyed automatically
```

### 2. Google Cloud

```python
from auto_proxy_vpn.providers.google import ProxyManagerGoogle

manager = ProxyManagerGoogle(
    project="my-gcp-project-id",
    ssh_key="ssh-rsa AAAAB3...",
    credentials="google_credentials.json"   # or set GOOGLE_APPLICATION_CREDENTIALS
)

with manager.get_proxy() as proxy:
    print(proxy.get_proxy_str())   # http://203.0.113.42:38721
```

### 3. Azure

```python
from auto_proxy_vpn.providers.azure import ProxyManagerAzure

manager = ProxyManagerAzure(
    ssh_key="ssh-rsa AAAAB3...",
    credentials={
        "AZURE_SUBSCRIPTION_ID": "xxxx-...",
        "AZURE_CLIENT_ID": "xxxx-...",
        "AZURE_CLIENT_SECRET": "xxxx-...",
        "AZURE_TENANT_ID": "xxxx-...",
    }
    # or set env vars and use: credentials="your-subscription-id"
    # or az login and use: credentials="your-subscription-id"
)

with manager.get_proxy() as proxy:
    print(proxy.get_proxy_str())
```

### 4. Multi-cloud with ProxyPool

```python
from auto_proxy_vpn import ProxyPool, GoogleConfig, AzureConfig, DigitalOceanConfig

pool = ProxyPool(
    GoogleConfig(project="my-project", ssh_key="ssh-rsa AAAA..."),
    AzureConfig(ssh_key="ssh-rsa AAAA..."),
    DigitalOceanConfig(ssh_key="my-key", token="dop_v1_xxxx..."),
)

# One proxy from a randomly selected provider
with pool.create_one() as proxy:
    print(proxy.get_proxy_str())

# Batch of 6 proxies distributed evenly across providers
with pool.create_batch(6) as batch:
    for proxy in batch:
        print(proxy)
```

---

## Supported Providers

| Provider | Proxy | VPN | Status |
|---|---|---|---|
| **Google Cloud** | Yes | No | Stable |
| **Azure** | Yes | — | Stable |
| **DigitalOcean** | Yes | Yes | Stable |
| AWS | — | — | Planned |
| Oracle Cloud | — | — | Planned |
| Alibaba Cloud | — | — | Planned |

---

## Provider Setup Guides

Each provider has its own README with step-by-step credential setup, full API reference, and advanced usage examples:

| Provider | Guide |
|---|---|
| Google Cloud | [Google docs](auto_proxy_vpn/providers/google/README.md) |
| Azure | [Azure docs](auto_proxy_vpn/providers/azure/README.md) |
| DigitalOcean | [DigitalOcean docs](auto_proxy_vpn/providers/digitalocean/README.md) |

> **Security:** All guides recommend storing credentials in a `.env` file (never via `export` in shell history or committed to version control). See each provider README for details.

---

## Usage

### Single Provider

Every provider exposes a **Manager** class that creates and manages proxy instances:

```python
from auto_proxy_vpn.providers.digitalocean import ProxyManagerDigitalOcean

manager = ProxyManagerDigitalOcean(ssh_key="my-key")

# Context manager (recommended) — auto-cleanup on exit
with manager.get_proxy() as proxy:
    response = requests.get("https://example.com", proxies=proxy.get_proxy())

# Manual lifecycle
proxy = manager.get_proxy()
try:
    response = requests.get("https://example.com", proxies=proxy.get_proxy())
finally:
    proxy.close()
```

### Proxy Pool

`ProxyPool` distributes proxy creation across multiple providers **and multiple accounts of the same provider**. Each config object with different credentials creates a separate manager — proxies are then distributed evenly across all of them using round-robin random selection:

```python
from auto_proxy_vpn import ProxyPool, GoogleConfig, AzureConfig, DigitalOceanConfig

pool = ProxyPool(
    GoogleConfig(project="my-project", ssh_key="ssh_keys"),
    DigitalOceanConfig(ssh_key="my-key"),
)

proxy = pool.create_one(size="small", on_exit="destroy")
# do something with the proxy
proxy.close()

# or with context manager
with pool.create_one(size="small", on_exit="destroy") as proxy:
    response = requests.get("https://example.com", proxies=proxy.get_proxy())
```

#### Multi-account per provider

Pass multiple configs for the same provider with different credentials to multiply your capacity and distribute load across accounts. If a config omits credentials, the corresponding environment variable is used as fallback (e.g. `GOOGLE_APPLICATION_CREDENTIALS`, `AZURE_SUBSCRIPTION_ID`, `DIGITALOCEAN_API_TOKEN`):

```python
pool = ProxyPool(
    # Account 1: explicit credentials
    GoogleConfig(project="project-1", ssh_key="ssh_keys", credentials="creds_1.json"),
    # Account 2: uses GOOGLE_APPLICATION_CREDENTIALS env var
    GoogleConfig(project="project-2", ssh_key="ssh_keys"),
    # Plus an Azure account
    AzureConfig(ssh_key="ssh-rsa AAAA..."),
)

# 9 proxies distributed across 3 managers (≈3 each)
with pool.create_batch(9) as batch:
    for proxy in batch:
        print(proxy)
```

### Batch Creation

Create multiple proxies at once — they are provisioned asynchronously by default:

```python
with pool.create_batch(6) as batch:
    for proxy in batch:
        print(proxy.get_proxy_str())
# All 6 proxies are destroyed on exit

# or
batch = pool.create_batch(6)
for proxy in batch:
    print(proxy.get_proxy_str())
batch.close()
```

Or directly from a single manager:

```python
batch = manager.get_proxies(
    number=3,
    sizes=["small", "medium", "large"],
    is_async=True,
)
# Use batch[0], batch[1], batch[2]
batch.close()
```

### Authentication & IP Filtering

```python
proxy = manager.get_proxy(
    auth={"user": "myuser", "password": "s3cret"},
    allowed_ips=["203.0.113.10", "198.51.100.0/24"],
)
# Proxy URL: http://myuser:s3cret@<ip>:<port>
# Only listed IPs (+ your current IP, auto-added) can connect
```

### Asynchronous Creation

Return immediately without blocking on VM provisioning:

```python
proxy = manager.get_proxy(is_async=True)

# ... do other work ...

# Block until the proxy is ready
if proxy.is_active(wait=True):
    r = requests.get("https://example.com", proxies=proxy.get_proxy())
```

### Reconnecting to Existing Proxies

If a proxy was created with `on_exit="keep"`, it remains running after `close()`. Reconnect later by name:

```python
# Create and keep alive
proxy = manager.get_proxy(on_exit="keep")
print(proxy.name)   # "proxy1"
proxy.close()       # resources are NOT deleted

# Later session — reconnect
proxy = manager.get_proxy_by_name("proxy1", on_exit="destroy")
```

List all running proxies:

```python
names = manager.get_running_proxy_names()
# ["proxy1", "proxy2"]
```

---

## API Reference

### `ProxyPool`

High-level orchestrator that distributes proxy creation across providers.

```python
from auto_proxy_vpn import ProxyPool

pool = ProxyPool(
    *provider_configs,      # GoogleConfig, AzureConfig, DigitalOceanConfig, ...
    log=True,
    log_file=None,
    log_format="%(asctime)-10s %(levelname)-5s %(message)s",
    logger=None,
)
```

| Method | Returns | Description |
|---|---|---|
| `create_one(...)` | `BaseProxy` | Create one proxy from a randomly selected provider |
| `create_batch(count, ...)` | `ProxyBatch` | Create `count` proxies distributed across providers |

Both methods accept the same proxy parameters: `port`, `size`, `region`, `auth`, `allowed_ips`, `is_async`, `retry`, `proxy_name`/`proxy_names`, and `on_exit`.

---

### `BaseProxy`

Common interface shared by all proxy instances (`GoogleProxy`, `AzureProxy`, `DigitalOceanProxy`).

| Property | Type | Description |
|---|---|---|
| `ip` | `str` | Public IPv4 address |
| `port` | `int` | Proxy TCP port |
| `name` | `str` | Instance/droplet name |
| `active` | `bool` | Whether the proxy is confirmed reachable |
| `user` | `str` | Basic-auth username (empty if none) |
| `password` | `str` | Basic-auth password (empty if none) |

| Method | Returns | Description |
|---|---|---|
| `get_proxy_str()` | `str` | Full proxy URL: `http://user:pass@ip:port` |
| `get_proxy()` | `dict \| None` | `{"http": url, "https": url}` for `requests` |
| `is_active(wait=False)` | `bool` | Check or wait for proxy readiness |
| `close(wait=True)` | `None` | Destroy or keep the proxy (depends on `on_exit`) |

**Context manager:**

```python
with manager.get_proxy() as proxy:
    # proxy is guaranteed active
    ...
# resources are cleaned up automatically
```

---

### `ProxyBatch`

Container for multiple proxies with iteration and lifecycle control.

```python
with pool.create_batch(5) as batch:
    print(len(batch))       # 5
    print(batch[0])         # first proxy
    for proxy in batch:
        print(proxy.get_proxy_str())
# All proxies are closed on exit
```

| Method | Returns | Description |
|---|---|---|
| `close()` | `None` | Close all proxies in the batch |
| `len(batch)` | `int` | Number of proxies |
| `batch[i]` | `BaseProxy` | Access by index |
| `for p in batch` | iteration | Iterate over proxies |

---

### Configuration Objects

Dataclass-based configs used with `ProxyPool` or `Manager.from_config()`.

#### `GoogleConfig`

```python
from auto_proxy_vpn import GoogleConfig

GoogleConfig(
    project="my-gcp-project-id",    # required
    ssh_key="ssh-rsa AAAA...",      # str | dict | list | file path
    credentials="creds.json",       # path to service account JSON (or env var)
)
```

#### `AzureConfig`

```python
from auto_proxy_vpn import AzureConfig

AzureConfig(
    ssh_key="ssh-rsa AAAA...",
    credentials="subscription-id",  # str | dict with AZURE_* keys (or env vars)
)
```

#### `DigitalOceanConfig`

```python
from auto_proxy_vpn import DigitalOceanConfig

DigitalOceanConfig(
    ssh_key="my-key-name",
    token="dop_v1_xxxx...",         # or env var DIGITALOCEAN_API_TOKEN
    project_name="AutoProxyVPN",
    project_description="On demand proxies",
)
```

#### `ManagerRuntimeConfig`

Shared logging configuration passed to all managers.

```python
from auto_proxy_vpn import ManagerRuntimeConfig

ManagerRuntimeConfig(
    log=True,
    log_file=None,
    log_format="%(asctime)-10s %(levelname)-5s %(message)s",
    logger=None,
)
```

---

### Common `get_proxy()` Parameters

All provider managers share the same `get_proxy()` signature:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `port` | `int` | `0` (random) | Proxy TCP port (random 10000–65000 if 0) |
| `size` | `"small" \| "medium" \| "large"` | `"medium"` | VM/droplet size tier |
| `region` | `str` | `""` (random) | Cloud region/zone |
| `auth` | `dict` | `{}` | `{"user": ..., "password": ...}` for basic auth |
| `allowed_ips` | `str \| list[str]` | `[]` | Allowed source IPs (your IP auto-added) |
| `is_async` | `bool` | `False` | Return before VM is fully ready |
| `retry` | `bool` | `True` | Retry in another region on failure |
| `proxy_name` | `str` | `""` | Custom name (auto-generated if empty) |
| `on_exit` | `"destroy" \| "keep"` | `"destroy"` | Cleanup behavior when proxy is closed |

---

## Limitations

Before choosing this tool, keep in mind:

- **Cloud IP blacklists.** Some websites maintain blacklists of IP ranges belonging to major cloud providers (AWS, Google Cloud, Azure, DigitalOcean, etc.). If a target site blocks cloud IPs, proxies created by this library will be blocked too — no matter how many regions or accounts you rotate through. This is a fundamental limitation of cloud-based proxies vs. residential ones.
- **Not a residential proxy.** The IPs you get are datacenter IPs. Services with aggressive anti-bot detection (e.g. some e-commerce sites, social media platforms, or ticket sellers) will likely flag or block them.
- **Provider rate limits.** Each cloud provider imposes quotas on VM/droplet creation. If you spin up many proxies in a short time, you may hit these limits. Using multiple accounts via `ProxyPool` helps, but doesn't eliminate them entirely.
- **Cost.** Every proxy is a real cloud VM. Forgetting to destroy instances will incur charges.

---

## Project Structure

```
auto_proxy_vpn/
├── __init__.py              # CloudProvider enum, public exports
├── configs.py               # GoogleConfig, AzureConfig, DigitalOceanConfig, ManagerRuntimeConfig
├── manager_register.py      # ProxyManagers registry + provider auto-discovery
├── proxy_pool.py            # ProxyPool, RandomManagerPicker
├── providers/
│   ├── azure/               # Azure VM proxy provider
│   ├── digitalocean/        # DigitalOcean droplet proxy + WireGuard VPN
│   ├── google/              # Google Compute Engine proxy + WireGuard VPN
│   ├── aws/                 # (planned)
│   ├── alibaba/             # (planned)
│   └── oracle/              # (planned)
└── utils/
    ├── base_proxy.py        # BaseProxy, BaseProxyManager, ProxyBatch
    ├── base_vpn.py          # Base VPN classes
    ├── exceptions.py        # Shared exceptions
    ├── files_utils.py       # Squid config generator
    ├── ssh_client.py        # SSH command execution and file download
    └── util.py              # Public IP detection
```

<!-- hide-contributing -->
---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) guide for detailed information on:

- Reporting bugs and suggesting features
- Development setup and workflow
- Coding guidelines and style conventions
- Adding a new cloud provider (step-by-step)
- Pull request process
