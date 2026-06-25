# AGENTS.md

This file defines the working context for AI coding agents and human reviewers.
It is intentionally concise: it should explain how to make safe, consistent
changes without duplicating the README or provider documentation.

## Project Context

`auto_proxy_vpn` is a Python library for creating short-lived HTTP(S) proxies on
cloud providers. A manager provisions a VM, installs Squid, exposes a proxy, and
cleans up the cloud resources when the proxy is closed.

Supported proxy providers are AWS, Azure, DigitalOcean, and Google Cloud.
The current public interface is library-first. Future CLI work should keep the
same package and expose an optional `apv` command through a `cli` extra, with
separate command families for `apv proxy ...` and `apv vpn ...`.

## Commands

Use tox as the primary validation entrypoint.

```bash
python -m pip install tox
tox
tox -e py314 -- tests/unit/
tox -e lint
tox -e coverage
tox -e docs
tox -e package
tox -e audit
```

Ruff checks are part of tox, but can also be run directly:

```bash
python -m ruff format --check .
python -m ruff check .
```

Integration tests create real cloud resources and can cost money. Do not run
tests under `tests/integration/` unless the task explicitly asks for real cloud
validation and the required credentials are available.

## Architecture

- `auto_proxy_vpn/__init__.py` exposes the public API and package version.
- `cloud_provider.py`, `configs.py`, and `manager_register.py` define provider
  identity, configuration objects, and manager registration.
- `proxy_pool.py` orchestrates manager selection, batch creation, and
  multi-provider workflows. Keep provider-specific cloud logic out of this file.
- `providers/<provider>/` contains each cloud implementation. Provider managers
  register with `ProxyManagers` and implement the shared manager contract.
- `utils/base_proxy.py` defines `BaseProxy`, `BaseProxyManager`, and
  `ProxyBatch`, which are the shared lifecycle abstractions.
- `utils/proxy_auth.py`, `utils/files_utils.py`, `utils/ssh_client.py`, and
  `utils/util.py` contain security-sensitive shared helpers.
- `docs/` is built with Sphinx; provider README files are source material for
  public documentation.
- `tests/unit/` must stay fully mocked and deterministic. `tests/integration/`
  is reserved for real provider calls.

## Public API Rules

- Preserve existing public signatures unless a change is deliberate and
  documented.
- `get_proxy_by_name` must keep `name` and `is_async` as positional-compatible
  parameters; `auth` should remain optional and keyword-friendly for recovered
  authenticated proxies.
- Use `None` for mutable defaults such as `auth` and `allowed_ips`.
- Keep provider dependencies optional. Import AWS, Azure, and Google SDKs inside
  provider-specific modules or guarded paths, not from the package root.
- If CLI code is added, it must be a thin layer over reusable services. Importing
  `auto_proxy_vpn` must not import Typer, Rich, prompt libraries, or
  platform-specific system proxy code.

## Security Rules

- Never persist proxy passwords, provider tokens, private keys, or cloud secrets
  in plaintext.
- Proxy basic-auth passwords are verified through PBKDF2-SHA256 metadata in
  `utils/proxy_auth.py`. Do not restore the old plaintext metadata behavior.
- Redact credentials in string representations, logs, exceptions, docs examples,
  and diagnostic output.
- Avoid `shell=True` and command string interpolation for local subprocesses.
  Prefer argv lists and quote remote shell fragments intentionally.
- Validate IP addresses and CIDRs with `ipaddress`; do not add regex-only IP
  validation.
- External HTTP calls must have explicit timeouts.
- Keep cloud cleanup behavior conservative. Disposable resources should default
  to `on_exit="destroy"` unless the user explicitly asks to keep them.

## Coding Conventions

- Target Python 3.10+ and prefer the standard library when it is sufficient.
- Keep changes scoped to the relevant provider, utility, tests, and docs.
- Use type hints for public functions and provider contracts.
- Use explicit exceptions for runtime validation instead of `assert`.
- Put class-level documentation under the class docstring. Do not duplicate
  class documentation in `__init__` docstrings.
- Follow existing NumPy-style docstrings for public classes and methods.
- Do not add broad abstractions unless they remove real duplication across
  providers or prepare a documented public workflow.

## Testing Expectations

- Add or update unit tests for every behavior change.
- Provider changes should mock external SDKs or HTTP APIs in unit tests.
- Auth or Squid-generation changes must verify that plaintext passwords do not
  appear in generated config, logs, or object string output.
- Public API changes require README/provider docs updates.
- Before handing off a change, run the smallest relevant tox environment and
  state clearly if the full suite was not run.

## Documentation Rules

- Keep README content user-facing and concise.
- Put detailed provider setup in `auto_proxy_vpn/providers/<provider>/README.md`.
- Update `SECURITY.md` when authentication, SSH, credentials, cloud metadata, or
  cleanup behavior changes.
- Use `docs/` for rendered documentation changes and verify with `tox -e docs`.

## Agent Workflow

1. Inspect the current repo state before editing.
2. Read the relevant provider, utility, tests, and docs before changing code.
3. Prefer `rg` for search and keep edits focused.
4. Do not overwrite unrelated local changes.
5. Run relevant validation.
6. Summarize changed files, validation performed, and any remaining risk.
