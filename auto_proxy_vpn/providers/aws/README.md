# AWS

Provision on-demand HTTP(S) proxy servers on **AWS EC2** with a single Python call. Each proxy runs [Squid](http://www.squid-cache.org/) on an Ubuntu 24.04 minimal instance and is fully managed — creation, authentication, security group rules, and cleanup are handled automatically.

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [AWS Credentials Setup](#aws-credentials-setup)
    - [Enable All AWS Regions for EC2](#enable-all-aws-regions-for-ec2)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
  - [ProxyManagerAws](#proxymanageraws)
  - [AwsProxy](#awsproxy)
- [Advanced Usage](#advanced-usage)

---

## Requirements

| Dependency | Purpose |
|---|---|
| `boto3` | AWS EC2 instance and security group lifecycle |

## Installation

```bash
pip install auto_proxy_vpn[aws]
```

## AWS Credentials Setup

You need an AWS account with permission to create and terminate EC2 instances and security groups.

### 1. Create an IAM User (or use existing access keys)

1. Open [AWS IAM Console](https://console.aws.amazon.com/iam/).
2. Create an IAM user with programmatic access.
3. Attach permissions that include at least EC2 + security group management.
4. Generate an **Access Key ID** and **Secret Access Key**.

### 2. Store Credentials Securely

Create a `.env` file in your project root:

```dotenv
# .env
AWS_ACCESS_KEY_ID=AKIAxxxxxxxxxxxxxxxx
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Load it at the start of your script:

```python
from dotenv import load_dotenv
load_dotenv()

manager = ProxyManagerAws(ssh_key="ssh-rsa AAAAB3...")
```

Alternatively, pass credentials directly in code (less secure — avoid committing secrets):

```python
manager = ProxyManagerAws(
    credentials={
        "AWS_ACCESS_KEY_ID": "AKIAxxxxxxxxxxxxxxxx",
        "AWS_SECRET_ACCESS_KEY": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    },
    ssh_key="ssh-rsa AAAAB3..."
)
```

> **⚠️ Security:** Never use `export` to set credentials in your shell history or commit secrets to version control. Always use a `.env` file and add it to your `.gitignore`. Install [`python-dotenv`](https://pypi.org/project/python-dotenv/) with `pip install python-dotenv`.

### Enable All AWS Regions for EC2

`ProxyManagerAws` can choose regions automatically when `region=""` (default). To maximize availability, enable all opt-in AWS regions in your account.

### Option A: AWS Console

1. Open [AWS Account Console](https://console.aws.amazon.com/account/home).
2. Go to **AWS Regions**.
3. For each region with status **Not enabled** (opt-in), click **Enable**.
4. Wait until the region status changes to **Enabled**.

### Option B: AWS CLI

List region status:

```bash
aws account list-regions --all-regions \
    --query "Regions[].{Region:RegionName,Status:RegionOptStatus}" \
    --output table
```

Enable one opt-in region:

```bash
aws account enable-region --region-name ap-east-1
```

After enabling, confirm your credentials can use EC2 in that region:

```bash
aws ec2 describe-regions --region us-east-1 --all-regions \
    --query "Regions[].RegionName" --output text
```

> **Notes:**
> - Region enablement can take several minutes.
> - Some AWS organizations restrict region usage with SCPs or IAM policies.
> - You may still hit capacity or quota limits in specific regions; in that case use `retry=True` (default) or set a specific `region` manually.

---

## Quick Start

### Import

```python
from auto_proxy_vpn.providers.aws import ProxyManagerAws, AwsProxy
```

### Minimal Example (environment credentials)

```python
manager = ProxyManagerAws(
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
    proxy.close()           # terminates EC2 instance and removes security group
```

---

## API Reference

### `ProxyManagerAws`

Factory class that provisions and manages AWS EC2 proxy instances.

**Instance sizes:**

| Size | EC2 instance type |
|---|---|
| `small` | `t3.nano` |
| `medium` | `t3.micro` |
| `large` | `t3.small` |

```python
ProxyManagerAws(
    ssh_key,                # str | dict | list — SSH public key(s) or path to key file
    credentials=None,       # dict | None — AWS keys (None = env vars)
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
    size="medium",         # "small" | "medium" | "large"
    region="",             # str — AWS region (empty = random)
    auth={},                # {"user": ..., "password": ...} — basic auth
    allowed_ips=[],         # str | list[str] — allowed source IPs (your IP is auto-added)
    is_async=False,         # bool — return immediately without waiting for full startup
    retry=True,             # bool — retry in a different region on failure
    proxy_name="",         # str — explicit name (empty = auto-generated proxy1, proxy2…)
    on_exit="destroy",     # "destroy" | "keep" — cleanup behavior on close
)
```

#### `manager.get_proxies()`

Create multiple proxies in one call and return a `ProxyBatch`.

```python
batch = manager.get_proxies(
    number=3,
    sizes=["small", "medium", "large"],
    is_async=True,
)

for proxy in batch:
    print(proxy.get_proxy_str())

batch.close()
```

#### `manager.get_proxy_by_name()`

Reload a previously created (and still running) proxy by its instance name.

```python
proxy = manager.get_proxy_by_name(
    name="proxy1",         # str — existing instance name (Name tag)
    is_async=False,         # bool
    on_exit="destroy",     # "destroy" | "keep"
)
```

#### `manager.get_running_proxy_names()`

List names of all running proxy instances (tagged `Type=proxy`).

```python
names = manager.get_running_proxy_names()
# ["proxy1", "proxy2"]
```

---

### `AwsProxy`

Represents a single proxy EC2 instance. You typically get this from `manager.get_proxy()` rather than constructing it directly.

#### Properties

| Property | Type | Description |
|---|---|---|
| `ip` | `str` | Public IPv4 address |
| `port` | `int` | Proxy TCP port |
| `region` | `str` | AWS region |
| `user` | `str` | Basic-auth username (empty if none) |
| `password` | `str` | Basic-auth password (empty if none) |
| `active` | `bool` | Whether the proxy is confirmed reachable |
| `name` | `str` | EC2 Name tag |
| `instance_id` | `str` | EC2 instance ID |
| `group_id` | `str` | Security group ID |
| `proxy_instance` | `str` | EC2 instance type |

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
# instance and security group are automatically destroyed
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
print(regions)   # ['us-east-1', 'eu-west-1', ...]

proxy = manager.get_proxy(size='small', region="eu-west-1")
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

# Do other work while EC2 is provisioning...

# Block until ready when you need it:
if proxy.is_active(wait=True):
    r = requests.get("https://example.com", proxies=proxy.get_proxy())
```

### SSH Key from File

```python
manager = ProxyManagerAws(
    ssh_key="/path/to/authorized_keys",  # one public key per line
)
```

### Using `AwsConfig` (for `ProxyPool` integration)

```python
from auto_proxy_vpn import AwsConfig, ManagerRuntimeConfig

config = AwsConfig(
    ssh_key="ssh-rsa AAAAB3...",
    credentials={
        "AWS_ACCESS_KEY_ID": "AKIAxxxxxxxxxxxxxxxx",
        "AWS_SECRET_ACCESS_KEY": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    },
)
runtime = ManagerRuntimeConfig(log=True)

manager = ProxyManagerAws.from_config(config, runtime)
```
