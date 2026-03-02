# Google Cloud

Provision on-demand HTTP(S) proxy servers on **Google Compute Engine** instances with a single Python call. Each proxy runs [Squid](http://www.squid-cache.org/) on an Ubuntu 24.04 LTS VM and is fully managed — creation, authentication, firewall rules, and cleanup are handled automatically.

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Google Cloud Credentials Setup](#google-cloud-credentials-setup)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
  - [ProxyManagerGoogle](#proxymanagergoogle)
  - [GoogleProxy](#googleproxy)
- [Advanced Usage](#advanced-usage)

---

## Requirements

| Dependency | Purpose |
|---|---|
| `google-cloud-compute` | Google Compute Engine instance lifecycle, firewall and image management |

## Installation

```bash
pip install auto_proxy_vpn

# Install Google Cloud SDK dependency
pip install google-cloud-compute
```

## Google Cloud Credentials Setup

You need a **Google Cloud project** and a **Service Account** with Compute Engine permissions.

### 1. Create a Service Account and Download Credentials

1. Go to the [Google Cloud Console → IAM & Admin → Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts).
2. Select your project (or create one).
3. Click **Create Service Account**.
4. Give it a name (e.g. `auto-proxy-vpn`) and grant the **Compute Admin** role (`roles/compute.admin`).
5. On the service account page, go to **Keys → Add Key → Create new key → JSON**.
6. Download the JSON file — this is your credentials file.

Or using `gcloud` CLI:

```bash
# Create the service account
gcloud iam service-accounts create auto-proxy-vpn \
  --display-name="auto-proxy-vpn"

# Grant Compute Admin role
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:auto-proxy-vpn@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/compute.admin"

# Generate the JSON key file
gcloud iam service-accounts keys create google_credentials.json \
  --iam-account=auto-proxy-vpn@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

### 2. Store the Credentials Securely

Create a `.env` file in your project root pointing to the JSON key:

```dotenv
# .env
GOOGLE_APPLICATION_CREDENTIALS=/path/to/google_credentials.json
```

Load it at the start of your script:

```python
from dotenv import load_dotenv
load_dotenv()

manager = ProxyManagerGoogle(
    project="my-gcp-project-id",
    ssh_key="ssh-rsa AAAAB3..."
)
```

Alternatively, pass the credentials path directly in code:

```python
manager = ProxyManagerGoogle(
    project="my-gcp-project-id",
    credentials="google_credentials.json",
    ssh_key="ssh-rsa AAAAB3..."
)
```

> **⚠️ Security:** Never commit the JSON key file or credentials to version control. Add both `.env` and `*.json` key files to your `.gitignore`. Install [`python-dotenv`](https://pypi.org/project/python-dotenv/) with `pip install python-dotenv`.

---

## Quick Start

### Import

```python
from auto_proxy_vpn.providers.google import ProxyManagerGoogle, GoogleProxy
```

### Minimal Example (environment credentials)

```python
manager = ProxyManagerGoogle(
    project="my-gcp-project-id",
    ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC2..."
)

# Context manager — instance is destroyed automatically on exit
with manager.get_proxy() as proxy:
    print(proxy.get_proxy_str())       # http://203.0.113.42:34521
    print(proxy.get_proxy())           # {'http': '...', 'https': '...'}

    import requests
    r = requests.get("https://httpbin.org/ip", proxies=proxy.get_proxy())
    print(r.json())
```

### Manual Lifecycle

```python
proxy = manager.get_proxy()

try:
    r = requests.get("https://httpbin.org/ip", proxies=proxy.get_proxy())
    print(r.json())
finally:
    proxy.close()           # destroys the GCE instance and firewall rule
```

---

## API Reference

### `ProxyManagerGoogle`

Factory class that provisions and manages Google Compute Engine proxy instances.

```python
ProxyManagerGoogle(
    ssh_key,                # str | dict | list — SSH public key(s) or path to key file
    project,                # str — Google Cloud project ID
    credentials="",         # str — path to service account JSON (empty = env var)
    log=True,               # bool — enable logging
    log_file=None,          # str | None — log file path (None = stdout)
    log_format="...",       # str — Python logging format string
    logger=None,            # Logger | None — custom logger instance
)
```

#### `manager.get_proxy()`

Create and start a new proxy instance.

```python
proxy = manager.get_proxy(
    port=0,                 # int — proxy port (0 = random 10000–65000)
    size="medium",          # "small" | "medium" | "large"
    region="",              # str — GCP region (empty = random)
    auth={},                # {"user": ..., "password": ...} — basic auth
    allowed_ips=[],         # str | list[str] — allowed source IPs (your IP is auto-added)
    is_async=False,         # bool — return immediately without waiting for full startup
    retry=True,             # bool — retry in a different region on failure
    proxy_name="",          # str — explicit name (empty = auto-generated proxy1, proxy2…)
    on_exit="destroy",      # "destroy" | "keep" — cleanup behavior on close
)
```

**Instance sizes:**

| Size | Machine type |
|---|---|
| `small` | `e2-micro` |
| `medium` | `e2-highcpu-2` |
| `large` | `e2-highcpu-4` |

#### `manager.get_proxy_by_name()`

Reload a previously created (and still running) proxy by its instance name.

```python
proxy = manager.get_proxy_by_name(
    name="proxy1",          # str — existing instance name
    is_async=False,         # bool
    on_exit="destroy",      # "destroy" | "keep"
)
```

#### `manager.get_running_proxy_names()`

List names of all running proxy instances (tagged `proxy`).

```python
names = manager.get_running_proxy_names()
# ["proxy1", "proxy2"]
```

---

### `GoogleProxy`

Represents a single proxy GCE instance. You typically get this from `manager.get_proxy()` rather than constructing it directly.

#### Properties

| Property | Type | Description |
|---|---|---|
| `ip` | `str` | Public IPv4 address |
| `port` | `int` | Proxy TCP port |
| `project` | `str` | Google Cloud project ID |
| `region` | `str` | GCP region |
| `zone` | `str` | GCP zone |
| `user` | `str` | Basic-auth username (empty if none) |
| `password` | `str` | Basic-auth password (empty if none) |
| `active` | `bool` | Whether the proxy is confirmed reachable |
| `name` | `str` | Instance name |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `get_proxy_str()` | `str` | Proxy URL, e.g. `http://user:pass@1.2.3.4:8080` |
| `get_proxy()` | `dict` | `{"http": url, "https": url}` for use with `requests` |
| `is_active(wait=False)` | `bool` | Check (or wait for) proxy readiness |
| `close(wait=True)` | `None` | Stop proxy; destroys instance + firewall if `on_exit="destroy"` |

#### Context Manager

```python
with manager.get_proxy() as proxy:
    # proxy is guaranteed active here
    r = requests.get("https://example.com", proxies=proxy.get_proxy())
# instance and firewall are automatically destroyed
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
print(regions)   # [('us-central1', ['us-central1-a', ...]), ...]

proxy = manager.get_proxy(region="europe-west1")
```

### Keep Proxy Alive After Close

```python
proxy = manager.get_proxy(on_exit="keep")
proxy.close()  # instance is NOT deleted

# Later, reconnect to it:
proxy = manager.get_proxy_by_name("proxy1", on_exit="destroy")
```

### Asynchronous Creation

```python
proxy = manager.get_proxy(is_async=True)

# Do other work while the instance provisions...

# Block until ready when you need it:
if proxy.is_active(wait=True):
    r = requests.get("https://example.com", proxies=proxy.get_proxy())
```

### SSH Key from File

```python
manager = ProxyManagerGoogle(
    project="my-gcp-project-id",
    ssh_key="/path/to/authorized_keys",  # one public key per line
)
```

### Using `GoogleConfig` (for `ProxyPool` integration)

```python
from auto_proxy_vpn import GoogleConfig, ManagerRuntimeConfig

config = GoogleConfig(
    project="my-gcp-project-id",
    ssh_key="ssh-rsa AAAAB3...",
    credentials="google_credentials.json",
)
runtime = ManagerRuntimeConfig(log=True)

manager = ProxyManagerGoogle.from_config(config, runtime)
```
