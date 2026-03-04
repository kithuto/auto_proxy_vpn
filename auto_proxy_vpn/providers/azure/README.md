# Azure

Provision on-demand HTTP(S) proxy servers on **Azure Virtual Machines** with a single Python call. Each proxy runs [Squid](http://www.squid-cache.org/) on an Ubuntu 24.04 LTS VM and is fully managed — creation, authentication, firewall rules, and cleanup are handled automatically.

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Azure Credentials Setup](#azure-credentials-setup)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
  - [ProxyManagerAzure](#proxymanagerazure)
  - [AzureProxy](#azureproxy)
- [Advanced Usage](#advanced-usage)

---

## Requirements

| Dependency | Purpose |
|---|---|
| `azure-identity` | Azure authentication (DefaultAzureCredential) |
| `azure-mgmt-subscription` | List available regions |
| `azure-mgmt-resource` | Manage resource groups |
| `azure-mgmt-network` | NSG, VNet, public IP, NIC management |
| `azure-mgmt-compute` | Virtual machine lifecycle |

## Installation

```bash
pip install auto_proxy_vpn[azure]
```

## Azure Credentials Setup

You need an Azure subscription. Authentication is handled by the Azure SDK's [`DefaultAzureCredential`](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential), which tries multiple credential sources automatically. Choose the option that best fits your workflow:

### Option A: Azure CLI Login (simplest)

If you already have the [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) installed, just log in and set your subscription ID:

```bash
az login
```

Then provide only the subscription ID. The recommended way is to create a `.env` file in your project root:

```dotenv
# .env
AZURE_SUBSCRIPTION_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Load it at the start of your script:

```python
from dotenv import load_dotenv
load_dotenv()  # reads .env into environment variables

manager = ProxyManagerAzure(ssh_key="ssh-rsa AAAAB3...")
```

Alternatively, pass the subscription ID directly in code:

```python
manager = ProxyManagerAzure(
    credentials="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",   # subscription ID
    ssh_key="ssh-rsa AAAAB3..."
)
```

> **Note:** This option is ideal for local development and interactive use. `DefaultAzureCredential` will pick up the session from `az login` automatically.

### Option B: Service Principal (recommended for automation)

Create a Service Principal with *Contributor* role:

```bash
az ad sp create-for-rbac \
  --name "auto-proxy-vpn" \
  --role contributor \
  --scopes /subscriptions/{your-subscription-id}
```

This outputs:

```json
{
  "appId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "password": "your-client-secret",
  "tenant": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

Map the output fields to the following variable names and store them in a `.env` file:

| CLI output | `.env` variable |
|---|---|
| `appId` | `AZURE_CLIENT_ID` |
| `password` | `AZURE_CLIENT_SECRET` |
| `tenant` | `AZURE_TENANT_ID` |
| *(your subscription id)* | `AZURE_SUBSCRIPTION_ID` |

```dotenv
# .env
AZURE_SUBSCRIPTION_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=your-client-secret
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Load the `.env` file at the start of your script:

```python
from dotenv import load_dotenv
load_dotenv()

manager = ProxyManagerAzure(ssh_key="ssh-rsa AAAAB3...")
```

Alternatively, pass credentials directly in code (less secure — avoid committing secrets):

```python
manager = ProxyManagerAzure(
    credentials={
        "AZURE_SUBSCRIPTION_ID": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "AZURE_CLIENT_ID": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "AZURE_CLIENT_SECRET": "your-client-secret",
        "AZURE_TENANT_ID": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    },
    ssh_key="ssh-rsa AAAAB3..."
)
```

> **⚠️ Security:** Never use `export` to set credentials in your shell history or commit secrets to version control. Always use a `.env` file and add it to your `.gitignore`. Install [`python-dotenv`](https://pypi.org/project/python-dotenv/) with `pip install python-dotenv`.
>
> This option is best suited for CI/CD pipelines, servers, and unattended scripts.

---

## Quick Start

### Import

```python
from auto_proxy_vpn.providers.azure import ProxyManagerAzure, AzureProxy
```

### Using Environment Variables (recommended)

```python
manager = ProxyManagerAzure(
    ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC2..."
)

# Context manager — proxy is destroyed automatically on exit
with manager.get_proxy() as proxy:
    print(proxy.get_proxy_str())       # http://203.0.113.42:34521
    print(proxy.get_proxy())           # {'http': '...', 'https': '...'}

    import requests
    r = requests.get("https://httpbin.org/ip", proxies=proxy.get_proxy())
    print(r.json())
```

### Passing Credentials Explicitly

```python
manager = ProxyManagerAzure(
    credentials={
        "AZURE_SUBSCRIPTION_ID": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "AZURE_CLIENT_ID": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "AZURE_CLIENT_SECRET": "your-client-secret",
        "AZURE_TENANT_ID": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    },
    ssh_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC2..."
)
```

### Manual Lifecycle

```python
proxy = manager.get_proxy()

try:
    r = requests.get("https://httpbin.org/ip", proxies=proxy.get_proxy())
    print(r.json())
finally:
    proxy.close()           # destroys Azure resources
```

---

## API Reference

### `ProxyManagerAzure`

Factory class that provisions and manages Azure proxy VMs.

```python
ProxyManagerAzure(
    ssh_key,                # str | dict | list — SSH public key(s) or path to key file
    credentials="",         # str | dict — subscription ID, credential dict, or "" for env vars
    log=True,               # bool — enable logging
    log_file=None,          # str | None — log file path (None = stdout)
    log_format="...",       # str — Python logging format string
    logger=None,            # Logger | None — custom logger instance
)
```

#### `manager.get_proxy()`

Create and start a new proxy VM.

```python
proxy = manager.get_proxy(
    port=0,                 # int — proxy port (0 = random 10000–65000)
    size="medium",          # "small" | "medium" | "large"
    region="",              # str — Azure region (empty = random)
    auth={},                # {"user": ..., "password": ...} — basic auth
    allowed_ips=[],         # str | list[str] — allowed source IPs (your IP is auto-added)
    is_async=False,         # bool — return immediately without waiting for full startup
    retry=True,             # bool — retry in a different region on failure
    proxy_name="",          # str — explicit name (empty = auto-generated)
    on_exit="destroy",      # "destroy" | "keep" — cleanup behavior on close
)
```

**VM sizes:**

| Size | Azure SKU |
|---|---|
| `small` | `Standard_B1s` |
| `medium` | `Standard_B1ms` |
| `large` | `Standard_B2s` |

#### `manager.get_proxy_by_name()`

Reload a previously created (and still running) proxy by name.

```python
proxy = manager.get_proxy_by_name(
    name="proxy1",          # str — existing proxy resource group name
    is_async=False,         # bool
    on_exit="destroy",      # "destroy" | "keep"
)
```

#### `manager.get_running_proxy_names()`

List names of all running proxy resource groups.

```python
names = manager.get_running_proxy_names()
# ["proxy1", "proxy2"]
```

---

### `AzureProxy`

Represents a single proxy VM instance. You typically get this from `manager.get_proxy()` rather than constructing it directly.

#### Properties

| Property | Type | Description |
|---|---|---|
| `ip` | `str` | Public IPv4 address |
| `port` | `int` | Proxy TCP port |
| `region` | `str` | Azure region |
| `user` | `str` | Basic-auth username (empty if none) |
| `password` | `str` | Basic-auth password (empty if none) |
| `active` | `bool` | Whether the proxy is confirmed reachable |
| `name` | `str` | Resource group / VM name |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `get_proxy_str()` | `str` | Proxy URL, e.g. `http://user:pass@1.2.3.4:8080` |
| `get_proxy()` | `dict` | `{"http": url, "https": url}` for use with `requests` |
| `is_active(wait=False)` | `bool` | Check (or wait for) proxy readiness |
| `close(wait=True)` | `None` | Stop proxy; destroys resources if `on_exit="destroy"` |

#### Context Manager

```python
with manager.get_proxy() as proxy:
    # proxy is guaranteed active here
    r = requests.get("https://example.com", proxies=proxy.get_proxy())
# proxy resources are automatically cleaned up
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

### Keep Proxy Alive After Close

```python
proxy = manager.get_proxy(on_exit="keep")
proxy.close()  # resources are NOT deleted

# Later, reconnect to it:
proxy = manager.get_proxy_by_name("proxy1", on_exit="destroy")
```

### Asynchronous Creation

```python
proxy = manager.get_proxy(is_async=True)

# Do other work while the VM provisions...

# Block until ready when you need it:
if proxy.is_active(wait=True):
    r = requests.get("https://example.com", proxies=proxy.get_proxy())
```

### SSH Key from File

```python
manager = ProxyManagerAzure(
    ssh_key="/path/to/authorized_keys",  # one public key per line
)
```
