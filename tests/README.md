# Testing Guide

## Quick Start

```bash
# Install test dependencies
pip install -e ".[test]"

# Run all unit tests (default, no cloud credentials needed)
pytest

# Run with coverage report
pytest --cov=auto_proxy_vpn --cov-report=html
```

## Test Structure

```
tests/
├── conftest.py                       # Shared fixtures, stubs, helpers
├── unit/                             # Mocked tests (fast, no cloud access)
│   ├── test_configs.py               # Config dataclasses & validation
│   ├── test_manager_register.py      # ProxyManagers registry
│   ├── test_base_proxy.py            # BaseProxy, ProxyBatch, BaseProxyManager
│   ├── test_proxy_pool.py            # ProxyPool & RandomManagerPicker
│   ├── test_digitalocean_proxy.py    # DigitalOcean provider (mocked HTTP)
│   ├── test_digitalocean_utils.py    # DigitalOcean utility functions
│   ├── test_google_proxy.py          # Google Cloud provider (mocked SDK)
│   └── test_azure_proxy.py          # Azure provider (mocked SDK)
└── integration/                      # Real cloud tests (slow, needs credentials)
    ├── test_digitalocean_real.py
    ├── test_google_real.py
    └── test_azure_real.py
```

## Markers

| Marker          | Description                                  |
|-----------------|----------------------------------------------|
| `unit`          | Unit tests with mocked dependencies          |
| `integration`   | Tests that hit real cloud APIs               |
| `digitalocean`  | Requires DigitalOcean token                  |
| `google`        | Requires Google Cloud credentials            |
| `azure`         | Requires Azure credentials                   |
| `slow`          | Tests that take a long time                  |

### Running specific markers

```bash
# Only unit tests (default)
pytest

# Only integration tests
pytest -m integration

# Only DigitalOcean integration tests
pytest -m "integration and digitalocean"

# Exclude slow tests
pytest -m "not slow"
```

## Integration Tests

Integration tests are **skipped by default**. To run them, you need to:

1. Set the required environment variables for the provider
2. Pass `-m integration` to pytest

### DigitalOcean

```bash
export DIGITALOCEAN_API_TOKEN="your-token"
export DO_SSH_KEY_NAME="your-ssh-key-name"
pytest -m "integration and digitalocean"
```

### Google Cloud

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials.json"
export GOOGLE_PROJECT="your-project-id"
export GOOGLE_SSH_KEY="ssh-rsa AAAA..."
pytest -m "integration and google"
```

### Azure

```bash
export AZURE_SUBSCRIPTION_ID="your-subscription-id"
export AZURE_TENANT_ID="your-tenant-id"
export AZURE_CLIENT_ID="your-client-id"
export AZURE_CLIENT_SECRET="your-client-secret"
export AZURE_SSH_KEY="ssh-rsa AAAA..."
pytest -m "integration and azure"
```

## Writing New Tests

### Adding a test for a new provider

1. Create `tests/unit/test_<provider>_proxy.py` for mocked tests
2. Create `tests/integration/test_<provider>_real.py` for real tests
3. Add a marker in `pyproject.toml` under `[tool.pytest.ini_options]`
4. Add the integration job in `.github/workflows/tests.yml`

### Conventions

- Use `conftest.py` fixtures for shared setup (`StubProxy`, `StubProxyManager`, etc.)
- Group related tests in classes (`class TestFoo:`)
- Name tests descriptively: `test_<what>_<condition>_<expected>`
- Mock external HTTP calls with `responses` library
- Mock SDK objects with `unittest.mock.MagicMock`
- Integration tests must always clean up resources in `finally` blocks

## CI/CD

The GitHub Actions workflow (`.github/workflows/tests.yml`) runs:

- **Unit tests** on every push/PR to `main` across Python 3.10–3.13
- **Integration tests** only on pushes to `main` (require repository secrets)

### Required GitHub Secrets (for integration tests)

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
