# DigitalOcean

Provision on-demand HTTP(S) proxy servers on **DigitalOcean Droplets** with a single Python call. Each proxy runs [Squid](http://www.squid-cache.org/) on an Ubuntu 24.04 droplet and is fully managed — creation, authentication, firewall rules, and cleanup are handled automatically.

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [DigitalOcean API Token](#digitalocean-api-token)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
  - [ProxyManagerDigitalOcean](#proxymanagerdigitalocean)
  - [DigitalOceanProxy](#digitaloceanproxy)
- [Advanced Usage](#advanced-usage)

---

## Installation

```bash
pip install auto_proxy_vpn
```

## DigitalOcean API Token

You need a **Personal Access Token** with read + write scopes.

### 1. Generate a Token

1. Go to [DigitalOcean API Tokens](https://cloud.digitalocean.com/account/api/tokens).
2. Click **Generate New Token**.
3. Give it a name, select **Full Access** (read + write), and click **Generate Token**.
4. Copy the token — it is shown only once.

### 2. Store it Securely

Create a `.env` file in your project root:

```dotenv
# .env
DIGITALOCEAN_API_TOKEN=dop_v1_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Load it at the start of your script:

```python
from dotenv import load_dotenv
load_dotenv()

manager = ProxyManagerDigitalOcean(ssh_key="my-existing-key-name")
```

Alternatively, pass the token directly in code (less secure — avoid committing secrets):

```python
manager = ProxyManagerDigitalOcean(
    token="dop_v1_xxxx...",
    ssh_key="my-existing-key-name",
)
```

> **⚠️ Security:** Never use `export` to set tokens in your shell history or commit secrets to version control. Always use a `.env` file and add it to your `.gitignore`. Install [`python-dotenv`](https://pypi.org/project/python-dotenv/) with `pip install python-dotenv`.

---

## Quick Start

### Import

```python
from auto_proxy_vpn.providers.digitalocean import ProxyManagerDigitalOcean, DigitalOceanProxy
```

### Minimal Example (environment token)

```python
manager = ProxyManagerDigitalOcean(
    ssh_key="my-existing-key-name"   # name of an SSH key already in your DO account
)

# Context manager — droplet is destroyed automatically on exit
with manager.get_proxy() as proxy:
    print(proxy.get_proxy_str())       # http://203.0.113.42:34521
    print(proxy.get_proxy())           # {'http': '...', 'https': '...'}

    import requests
    r = requests.get("https://httpbin.org/ip", proxies=proxy.get_proxy())
    print(r.json())
```

### Creating a New SSH Key on DigitalOcean

```python
manager = ProxyManagerDigitalOcean(
    ssh_key={"name": "my-proxy-key", "public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC2..."},
    token="dop_v1_xxxx...",
)
```

### Manual Lifecycle

```python
proxy = manager.get_proxy()

try:
    r = requests.get("https://httpbin.org/ip", proxies=proxy.get_proxy())
    print(r.json())
finally:
    proxy.close()           # destroys the droplet
```

---

## API Reference

### `ProxyManagerDigitalOcean`

Factory class that provisions and manages DigitalOcean proxy droplets.

```python
ProxyManagerDigitalOcean(
    ssh_key,                    # str | dict | list — key name, public key dict, or path to key file
    project_name="AutoProxyVPN",# str — DO project to group proxies under
    project_description="On demand proxies",
    token="",                   # str — API token (empty = env var DIGITALOCEAN_API_TOKEN)
    log=True,                   # bool — enable logging
    log_file=None,              # str | None — log file path (None = stdout)
    log_format="...",           # str — Python logging format string
    logger=None,                # Logger | None — custom logger instance
)
```

**SSH key formats:**

| Format | Example |
|---|---|
| Existing key name | `"my-key"` |
| New key dict | `{"name": "my-key", "public_key": "ssh-rsa AAAA..."}` |
| Mixed list | `["my-key", {"name": "other", "public_key": "ssh-rsa ..."}]` |
| File path | `"/path/to/authorized_keys"` (one public key per line) |

#### `manager.get_proxy()`

Create and start a new proxy droplet.

```python
proxy = manager.get_proxy(
    port=0,                 # int — proxy port (0 = random 10000–65000)
    size="medium",          # "small" | "medium" | "large"
    region="",              # str — region slug (empty = random)
    auth={},                # {"user": ..., "password": ...} — basic auth
    allowed_ips=[],         # str | list[str] — allowed source IPs (your IP is auto-added)
    is_async=False,         # bool — return immediately without waiting for full startup
    retry=True,             # bool — retry in a different region on failure
    proxy_name="",          # str — explicit name (empty = auto-generated proxy1, proxy2…)
    on_exit="destroy",      # "destroy" | "keep" — cleanup behavior on close
)
```

**Droplet sizes:**

| Size | DigitalOcean slug | Note |
|---|---|---|
| `small` | `s-1vcpu-512mb-10gb` | Fewer regions available |
| `medium` | `s-1vcpu-1gb` | All regions |
| `large` | `s-1vcpu-2gb` | All regions |

#### `manager.get_proxy_by_name()`

Reload a previously created (and still running) proxy by its droplet name.

```python
proxy = manager.get_proxy_by_name(
    name="proxy1",          # str — existing droplet name
    is_async=False,         # bool
    on_exit="destroy",      # "destroy" | "keep"
)
```

#### `manager.get_running_proxy_names()`

List names of all running proxy droplets (tagged `proxy`).

```python
names = manager.get_running_proxy_names()
# ["proxy1", "proxy2"]
```

---

### `DigitalOceanProxy`

Represents a single proxy droplet instance. You typically get this from `manager.get_proxy()` rather than constructing it directly.

#### Properties

| Property | Type | Description |
|---|---|---|
| `ip` | `str` | Public IPv4 address |
| `port` | `int` | Proxy TCP port |
| `region` | `str` | DigitalOcean region slug |
| `user` | `str` | Basic-auth username (empty if none) |
| `password` | `str` | Basic-auth password (empty if none) |
| `active` | `bool` | Whether the proxy is confirmed reachable |
| `name` | `str` | Droplet name |
| `id` | `int` | Droplet ID |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `get_proxy_str()` | `str` | Proxy URL, e.g. `http://user:pass@1.2.3.4:8080` |
| `get_proxy()` | `dict` | `{"http": url, "https": url}` for use with `requests` |
| `is_active(wait=False)` | `bool` | Check (or wait for) proxy readiness |
| `close(wait=True)` | `None` | Stop proxy; destroys droplet if `on_exit="destroy"` |

#### Context Manager

```python
with manager.get_proxy() as proxy:
    # proxy is guaranteed active here
    r = requests.get("https://example.com", proxies=proxy.get_proxy())
# droplet is automatically destroyed
```

---

## Advanced Usage

### Proxy with Basic Authentication

```python
proxy = manager.get_proxy(
    auth={"user": "myuser", "password": "s3cret"},
)
# Proxy URL: http://myuser:s3cret@<ip>:<port>
```

### Restrict Access by IP

```python
proxy = manager.get_proxy(
    allowed_ips=["203.0.113.10", "198.51.100.0/24"],
)
# Your current public IP is always added automatically
```

### Choose a Specific Region

```python
# See available regions for a given size
regions = manager.get_regions_by_size("small")
print(regions)   # ['nyc1', 'sfo3', 'ams3', ...]

proxy = manager.get_proxy(region="ams3")
```

### Keep Proxy Alive After Close

```python
proxy = manager.get_proxy(on_exit="keep")
proxy.close()  # droplet is NOT deleted

# Later, reconnect to it:
proxy = manager.get_proxy_by_name("proxy1", on_exit="destroy")
```

### Asynchronous Creation

```python
proxy = manager.get_proxy(is_async=True)

# Do other work while the droplet provisions...

# Block until ready when you need it:
if proxy.is_active(wait=True):
    r = requests.get("https://example.com", proxies=proxy.get_proxy())
```

### SSH Keys from File
Only accepts already existent digitalocean key names
```python
manager = ProxyManagerDigitalOcean(
    ssh_key="/path/to/do_keys",  # one public key name per line
)
```
