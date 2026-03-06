# Testing

This project uses [pytest](https://docs.pytest.org/) for all automated testing. Tests are split into **unit tests** (fast, fully mocked, no cloud credentials) and **integration tests** (hit real cloud APIs, require credentials and environment variables).

## Quick Start

```bash
# Install the package with test dependencies
pip install -e ".[test]"

# Run all unit tests (the default — no credentials needed)
pytest

# Run with a coverage report
pytest --cov=auto_proxy_vpn --cov-report=html
open htmlcov/index.html        # macOS

# Report to terminal
pytest --cov=auto_proxy_vpn --cov-report=term-missing
```

## Test Dependencies

All testing dependencies are declared in `pyproject.toml` under `[project.optional-dependencies] test`:

| Package        | Purpose                                                |
|----------------|--------------------------------------------------------|
| `pytest`       | Test runner and assertion framework                    |
| `pytest-cov`   | Coverage measurement and reporting                    |
| `pytest-mock`  | `mocker` fixture for convenient patching              |
| `responses`    | Mock `requests` HTTP calls (used by DigitalOcean)     |

## Test Structure

```
tests/
├── conftest.py                       # Shared fixtures, stubs, helpers
├── README.md                         # Quick-start guide for contributors
├── unit/                             # Mocked tests — fast, deterministic
│   ├── test_configs.py               # Config dataclasses & validation
│   ├── test_manager_register.py      # ProxyManagers registry
│   ├── test_base_proxy.py            # BaseProxy, ProxyBatch, BaseProxyManager
│   ├── test_proxy_pool.py            # ProxyPool & RandomManagerPicker
│   ├── test_utils.py                 # Public IP detection, SSH, exceptions
│   ├── test_digitalocean_proxy.py    # DigitalOcean provider (mocked HTTP)
│   ├── test_digitalocean_utils.py    # DigitalOcean utility functions
│   ├── test_google_proxy.py          # Google Cloud provider (mocked SDK)
│   └── test_azure_proxy.py          # Azure provider (mocked SDK)
└── integration/                      # Real cloud tests — slow, needs creds
    ├── test_digitalocean_real.py
    ├── test_google_real.py
    └── test_azure_real.py
```

### Shared Fixtures

`tests/conftest.py` provides reusable fixtures and stubs available to every test:

| Fixture / Helper            | Description                                              |
|-----------------------------|----------------------------------------------------------|
| `StubProxy`                 | Concrete `BaseProxy` subclass for testing base behavior  |
| `StubProxyManager`          | Concrete `BaseProxyManager` subclass for testing         |
| `stub_proxy`                | Pre-built `StubProxy` instance (no auth)                 |
| `stub_proxy_with_auth`      | Pre-built `StubProxy` with user/password                 |
| `stub_manager`              | Pre-built `StubProxyManager`                             |
| `digitalocean_config`       | `DigitalOceanConfig` fixture with fake credentials       |
| `google_config`             | `GoogleConfig` fixture with fake credentials             |
| `azure_config`              | `AzureConfig` fixture with fake credentials              |
| `make_do_regions_response()`| Builds a mock DigitalOcean `/v2/regions` response        |
| `make_do_droplet()`         | Builds a mock DigitalOcean droplet payload               |

---

## Markers

Pytest markers control which tests run. They are defined in `pyproject.toml`:

| Marker          | Description                                  |
|-----------------|----------------------------------------------|
| `unit`          | Unit tests with mocked dependencies          |
| `integration`   | Tests that hit real cloud APIs               |
| `digitalocean`  | Requires a DigitalOcean API token            |
| `google`        | Requires Google Cloud credentials            |
| `azure`         | Requires Azure credentials                   |
| `slow`          | Tests that take a long time to run           |

### Filtering by marker

```bash
# Only unit tests (this is the default)
pytest

# Only integration tests
pytest -m integration

# DigitalOcean integration tests only
pytest -m "integration and digitalocean"

# Exclude slow tests
pytest -m "not slow"
```

---

## Unit Tests

Unit tests are the backbone of the test suite. They run in milliseconds, require no cloud credentials, and cover:

- **Core** — config dataclasses, the `ProxyManagers` registry, `ProxyPool`, `RandomManagerPicker`.
- **Base classes** — `BaseProxy`, `ProxyBatch`, `BaseProxyManager` (using `StubProxy` / `StubProxyManager`).
- **Providers** — each provider is tested with its external SDK or HTTP API fully mocked.

### Mocking Strategy

Each provider has a different external dependency surface, so the mocking approach varies:

#### DigitalOcean

DigitalOcean calls the REST API with the `requests` library. We use the [`responses`](https://github.com/getsentry/responses) library to intercept and mock HTTP calls:

```python
import responses

@responses.activate
def test_something(self, digitalocean_config):
    responses.add(responses.GET, f"{DO_API}/regions", json={...}, status=200)
    # ... rest of the test
```

#### Google Cloud

Google Cloud uses the `google-cloud-compute` SDK which is **not installed in CI**. We mock the entire module hierarchy via `sys.modules`:

```python
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

# 1. Build mock objects
compute_v1 = MagicMock()
images_client = MagicMock()
images_client.list.return_value = SimpleNamespace(
    items=[SimpleNamespace(name="ubuntu-minimal-2404-noble-amd64-v20250101")]
)

# 2. Wire parent → child relationships
#    (from google.cloud import compute_v1  resolves via
#     getattr(sys.modules['google.cloud'], 'compute_v1'))
google_cloud_mock = MagicMock()
google_cloud_mock.compute_v1 = compute_v1

# 3. Patch sys.modules
with patch.dict("sys.modules", {
    "google": google_mock,
    "google.cloud": google_cloud_mock,
    "google.cloud.compute_v1": compute_v1,
    # ... etc.
}):
    from auto_proxy_vpn.providers.google.google_proxy import ProxyManagerGoogle
```

```{important}
When mocking `sys.modules`, the parent module mock **must** expose
the child mock as an attribute.  Otherwise `from parent import child`
silently gets an auto-generated `MagicMock` instead of your configured
one.
```

#### Azure

Azure uses multiple `azure-mgmt-*` SDKs. The approach is the same as Google — mock the module hierarchy via `sys.modules` and wire parent → child attributes.

### Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| `DigitalOceanProxy.__init__` calls `is_active()` which triggers real HTTP | Pass `reload=True` when constructing test proxies to skip the activation loop |
| `MagicMock().items` returns a MagicMock, not a list | Use `types.SimpleNamespace(items=[...])` for data containers |
| `from google.cloud import compute_v1` gets a random MagicMock | Wire `google_cloud_mock.compute_v1 = compute_v1` before patching `sys.modules` |
| `'instances' in entry` fails on MagicMock | Implement `__contains__` on the mock or use a helper class |

---

## Integration Tests

Integration tests create **real cloud resources** and are skipped unless the required environment variables are set.

```{warning}
Integration tests create real cloud resources that **cost money**. They
include cleanup logic in `finally` blocks, but always verify resources
are destroyed after a run.
```

### Required Environment Variables

#### DigitalOcean

```bash
export DIGITALOCEAN_API_TOKEN="dop_v1_..."
export DO_SSH_KEY_NAME="my-ssh-key"
pytest -m "integration and digitalocean"
```

#### Google Cloud

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials.json"
export GOOGLE_PROJECT="my-project-id"
export GOOGLE_SSH_KEY="ssh-rsa AAAA..."
pytest -m "integration and google"
```

#### Azure

```bash
export AZURE_SUBSCRIPTION_ID="..."
export AZURE_TENANT_ID="..."
export AZURE_CLIENT_ID="..."
export AZURE_CLIENT_SECRET="..."
export AZURE_SSH_KEY="ssh-rsa AAAA..."
pytest -m "integration and azure"
```

---

## Writing Tests

### Conventions

- Group related tests in classes: `class TestProxyManagerInit:`
- Name tests descriptively: `test_<what>_<condition>_<expected>`
- Use `conftest.py` fixtures for shared setup
- Mock external calls — never let a unit test touch the network
- Integration tests **must** clean up cloud resources in `finally` blocks

### Adding Tests for a New Provider

1. Create `tests/unit/test_<provider>_proxy.py` for mocked tests.
2. Create `tests/integration/test_<provider>_real.py` for real-cloud tests.
3. Add a marker in `pyproject.toml` under `[tool.pytest.ini_options]`.
4. Add the integration CI job in `.github/workflows/tests.yml`.
5. Add required secrets to the table below.

### Test Naming

```python
class TestProxyManagerFooGetProxy:
    def test_get_proxy_creates_instance(self):          # happy path
        ...
    def test_get_proxy_invalid_region_raises(self):     # error case
        ...
    def test_get_proxy_duplicate_name_raises(self):     # edge case
        ...
```

---

### GitHub Secrets

To enable integration tests in CI, configure these repository secrets under **Settings → Secrets and variables → Actions**:

| Secret                             | Provider      |
|------------------------------------|---------------|
| `DIGITALOCEAN_API_TOKEN`           | DigitalOcean  |
| `DO_SSH_KEY_NAME`                  | DigitalOcean  |
| `GOOGLE_APPLICATION_CREDENTIALS`   | Google Cloud  |
| `GOOGLE_PROJECT`                   | Google Cloud  |
| `GOOGLE_SSH_KEY`                   | Google Cloud  |
| `AZURE_SUBSCRIPTION_ID`            | Azure         |
| `AZURE_TENANT_ID`                  | Azure         |
| `AZURE_CLIENT_ID`                  | Azure         |
| `AZURE_CLIENT_SECRET`              | Azure         |
| `AZURE_SSH_KEY`                    | Azure         |

---

## Coverage

Coverage is measured with `pytest-cov` and reported in CI as an XML artifact.

```bash
# Terminal report
pytest --cov=auto_proxy_vpn --cov-report=term-missing

# HTML report (opens in browser)
pytest --cov=auto_proxy_vpn --cov-report=html
open htmlcov/index.html
```

The coverage configuration in `pyproject.toml` ensures only the `auto_proxy_vpn/` source tree is measured — the `tests/` directory itself is excluded.
