# Contributing to auto_proxy_vpn

Hey! Thanks for considering a contribution to **auto_proxy_vpn**. I maintain this project on my own, so any help is genuinely appreciated — bug reports, docs fixes, typos, new providers, you name it.

This guide will help you get up and running quickly.

## Table of Contents

- [Be Nice](#be-nice)
- [Ways to Contribute](#ways-to-contribute)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Coding Guidelines](#coding-guidelines)
- [Adding a New Cloud Provider](#adding-a-new-cloud-provider)<!-- hide testing menu --> 
- [Testing](#testing)<!-- /hide testing menu -->
- [Updating Documentation](#updating-documentation)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [License](#license)

---

## Be Nice

Just the basics: be respectful, be constructive, and keep things friendly. That's it.

---

## Ways to Contribute

### Found a bug?

Open an issue with:

- A short description of what went wrong.
- Your environment (Python version, OS, cloud provider).
- Steps to reproduce it (minimal code is ideal).
- The full traceback or error output (please redact any secrets!).

### Have an idea?

Open an issue describing the problem you're trying to solve and, if you have one, a rough sketch of how you'd approach it. I'm open to suggestions and happy to discuss before you start coding.

### Want to code?

Go for it! PRs are welcome for bug fixes, new providers, docs improvements, performance tweaks — pretty much anything. If it's a big change, consider opening an issue first so we can align on the approach.

---

## Development Setup

```bash
# 1. Fork & clone
git clone https://github.com/<your-username>/auto_proxy_vpn.git
cd auto_proxy_vpn

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate    # macOS / Linux
# .venv\Scripts\activate     # Windows

# 3. Install in editable mode
pip install -e .

# 4. Install provider deps (only what you need)
pip install google-cloud-compute                          # Google Cloud
pip install azure-identity azure-mgmt-subscription \
            azure-mgmt-resource azure-mgmt-network \
            azure-mgmt-compute                            # Azure
# DigitalOcean — no extra packages needed

# 5. Create a branch
git checkout -b feature/my-feature
```

Branch naming is flexible, but something like `feature/…`, `fix/…`, or `docs/…` keeps things clear.

---

## Project Structure

```
auto_proxy_vpn/
├── __init__.py              # CloudProvider enum, public exports
├── configs.py               # Provider config dataclasses
├── manager_register.py      # ProxyManagers registry + auto-discovery
├── proxy_pool.py            # ProxyPool orchestrator
├── providers/
│   ├── azure/               # Azure provider
│   ├── digitalocean/        # DigitalOcean provider
│   ├── google/              # Google Cloud provider
│   ├── aws/                 # (planned)
│   ├── alibaba/             # (planned)
│   └── oracle/              # (planned)
└── utils/
    ├── base_proxy.py        # BaseProxy, BaseProxyManager, ProxyBatch
    ├── base_vpn.py          # Base VPN classes
    ├── exceptions.py        # Shared exceptions
    ├── files_utils.py       # Squid config generator
    ├── ssh_client.py        # SSH helpers
    └── util.py              # Public IP detection
```

A few conventions worth noting:

- Each provider is its own sub-package under `providers/`.
- Provider helpers go in `<provider>_utils.py`, custom exceptions in `<provider>_exceptions.py`.
- Anything shared across providers lives in `utils/`.

---

## Coding Guidelines

Nothing too rigid — just try to stay consistent with the existing code. Here's the gist:

### Style

- [PEP 8](https://peps.python.org/pep-0008/), 4-space indentation, ~120 char line length.
- Single quotes for strings (unless the string itself contains one).
- f-strings over `.format()` or `%`.

### Type Hints

- All public functions should have type hints for params and return values.
- Use `X | Y` union syntax (we target Python 3.12+).
- Use `typing.Literal` for constrained string args (e.g. `size`, `on_exit`).

### Docstrings

NumPy-style for public classes and methods. Quick example:

```python
def get_proxy(self, port: int = 0) -> BaseProxy:
    """Create and start a new proxy instance.

    Parameters
    ----------
    port : int, optional
        TCP port for the proxy. If ``0``, a random port is selected.

    Returns
    -------
    BaseProxy
        The created proxy instance.

    Raises
    ------
    ValueError
        If the port number is out of range.
    """
```

### Commit Messages

I like [Conventional Commits](https://www.conventionalcommits.org/) — it keeps the history readable:

```
feat(azure): add support for custom VM images
fix(digitalocean): handle 422 response on region capacity error
docs(google): add service account setup instructions
```

Common types:

- `feat` — a new feature or capability.
- `fix` — a bug fix.
- `docs` — documentation only (README, docstrings, comments).
- `refactor` — code restructuring that doesn't change behavior.
- `test` — adding or updating tests.
- `chore` — maintenance stuff (CI, build config, dependency bumps).

---

## Adding a New Cloud Provider

This is probably the most impactful contribution you can make. The project is designed to make this straightforward — here's the step-by-step:

### 1. Create the provider package

```
auto_proxy_vpn/providers/your_provider/
├── __init__.py
├── your_provider_proxy.py
├── your_provider_utils.py        # optional
└── your_provider_exceptions.py   # optional
```

### 2. Add the enum entry

In `auto_proxy_vpn/__init__.py`:

```python
class CloudProvider(str, Enum):
    GOOGLE = "google"
    AZURE = "azure"
    DIGITALOCEAN = "digitalocean"
    YOUR_PROVIDER = "your_provider"      # ← must match the package name
```

### 3. Implement the manager and proxy classes

```python
from auto_proxy_vpn import CloudProvider, ProxyManagers
from auto_proxy_vpn.utils.base_proxy import BaseProxy, BaseProxyManager

class YourProviderProxy(BaseProxy):
    # Implement: __init__, is_active, _stop_proxy

@ProxyManagers.register(CloudProvider.YOUR_PROVIDER)
class ProxyManagerYourProvider(BaseProxyManager[YourProviderProxy]):
    # Implement: __init__, from_config, get_proxy, get_proxy_by_name, get_running_proxy_names
```

The key methods you need to implement:

**`BaseProxyManager`:**

| Method | What it does |
|---|---|
| `from_config(cls, config, runtime_config)` | Build the manager from config objects |
| `get_proxy(...)` | Create and return a single proxy |
| `get_proxy_by_name(name, ...)` | Reload an existing proxy by name |
| `get_running_proxy_names()` | List all active proxy names |

**`BaseProxy`:**

| Method | What it does |
|---|---|
| `is_active(wait)` | Check (or wait for) readiness |
| `_stop_proxy(wait)` | Destroy or preserve cloud resources |

### 4. Add a config dataclass

In `auto_proxy_vpn/configs.py`:

```python
@dataclass
class YourProviderConfig(BaseConfig):
    provider: ClassVar = CloudProvider.YOUR_PROVIDER
    # Add provider-specific fields (token, project_id, etc.)

    def unique_key(self) -> tuple[CloudProvider, str]:
        return (self.provider, "<unique credential identifier>")
```

### 5. Export from the provider's `__init__.py`

```python
from .your_provider_proxy import ProxyManagerYourProvider, YourProviderProxy
```

### 6. Add a provider README

Create a `README.md` inside your provider package. Check out the existing ones (e.g. `providers/azure/README.md`) for the format.

> **Tip:** Looking at an existing provider like DigitalOcean or Azure is the fastest way to understand how everything fits together.
<!-- hide testing -->
---

## Testing

The project has a comprehensive test suite built with [pytest](https://docs.pytest.org/). For the full testing guide — including how to run tests, write new ones, mock providers, and set up integration tests — see the **[Testing documentation](tests/README.md)**.

The quick version:

```bash
# Install test deps and run unit tests
pip install -e ".[test]"
pytest
```
<!-- /hide testing -->
---

## Updating Documentation

The project uses [Sphinx](https://www.sphinx-doc.org/) with the [furo](https://pradyunsg.me/furo/) theme to generate HTML documentation from:

- **Markdown files** — `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, and each provider's `README.md`  are pulled into Sphinx via [MyST-Parser](https://myst-parser.readthedocs.io/).
- **Docstrings** — API reference pages are auto-generated from NumPy-style docstrings in the source code.

### Install docs dependencies

```bash
pip install sphinx furo myst-parser sphinx-autodoc-typehints
```

### Build the docs locally

```bash
cd docs
make html          # output lands in docs/_build/html/
```

Open `docs/_build/html/index.html` in your browser to preview.

### When should you update docs?

- **Changed a public API** (new parameter, renamed method, new class) → update the docstring in the source file. Sphinx picks it up automatically on the next build.
- **Added a new provider** → create a `README.md` inside your provider package, then add a MyST include wrapper at `docs/providers/<provider>.md`:

  ```markdown
  ```{include} ../../auto_proxy_vpn/providers/<provider>/README.md
  ```
  ```

  And register it in `docs/index.rst` under the *Provider Guides* toctree.

- **Edited README.md or CONTRIBUTING.md** → the Sphinx docs include these files automatically, so your changes will appear after a rebuild. Note that `docs/readme.md` uses split includes (`:end-before:` / `:start-after:`) to adapt some sections for Sphinx — if you add or move major sections in `README.md`, check that the include markers still align.

### Docs structure at a glance

```
docs/
├── conf.py              # Sphinx configuration
├── index.rst            # Main toctree
├── readme.md            # Includes ../README.md (with split sections)
├── contributing.md       # Includes ../CONTRIBUTING.md
├── security.md          # Includes ../SECURITY.md
├── providers/
│   ├── google.md        # Includes Google provider README
│   ├── azure.md         # Includes Azure provider README
│   └── digitalocean.md  # Includes DigitalOcean provider README
└── api/
    ├── core.rst         # ProxyPool, ProxyManagers, CloudProvider
    ├── configs.rst      # Config dataclasses
    ├── providers.rst    # Provider manager & proxy classes
    └── utils.rst        # Base classes, SSH, utilities
```

### Tips

- Run `make clean html` (not just `make html`) when you change the structure — Sphinx caches aggressively.
- The build should finish with **0 warnings**. If you see new warnings, fix them before submitting.
- Docstrings must use **NumPy style** with the `param : type` format (see [Coding Guidelines](#coding-guidelines) above).

---

## Submitting a Pull Request

1. **Rebase on `main`** before submitting:

   ```bash
   git fetch origin
   git rebase origin/main
   ```

2. **Read through your own diff** — you'd be surprised how many issues you catch this way.

3. **Write a clear PR description** — what it does, why, and whether there are any breaking changes.

4. **Keep it focused** — one feature or fix per PR. Smaller PRs are easier (and faster) to review.

5. I'll review it as soon as I can. If I request changes, just push updates to the same branch.

6. Once everything looks good, I'll merge it into `main`.
