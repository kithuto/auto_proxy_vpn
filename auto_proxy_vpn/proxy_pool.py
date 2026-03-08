from random import shuffle
from logging import INFO, Logger, basicConfig, getLogger
from typing import Literal
from concurrent.futures import ThreadPoolExecutor, as_completed

from auto_proxy_vpn import ProxyManagers, BaseConfig, ManagerRuntimeConfig, CloudProvider
from auto_proxy_vpn.utils.base_proxy import BaseProxyManager, BaseProxy, ProxyBatch

class RandomManagerPicker:
    def __init__(self, managers: list[tuple[CloudProvider, BaseProxyManager]]):
        """Round-robin random picker for proxy managers.

        The picker keeps a shuffled "bag" of manager instances and returns one
        manager at a time via :meth:`next`. Once the bag is empty, it is refilled
        and shuffled again. This guarantees each manager is selected at most once
        per cycle while still randomizing the order between cycles.

        Parameters
        ----------
        managers : list[tuple[CloudProvider, BaseProxyManager]]
            List of manager instances.

        Notes
        -----
        - Selection is random per cycle, not weighted.
        - If only one manager is provided, it is always returned.
        """
        self._managers: list[tuple[CloudProvider, BaseProxyManager]] = managers
        self._bag = []
        self._refill_bag()
    
    def _refill_bag(self):
        """Refill the internal bag with all managers and shuffle it in place."""
        self._bag = self._managers.copy()
        shuffle(self._bag)
    
    def next(self) -> tuple[CloudProvider, BaseProxyManager]:
        """Return the next manager, refilling the bag when needed."""
        if not self._bag:
            self._refill_bag()
        return self._bag.pop()
    
    def __iter__(self):
        return self
    
    def __next__(self) -> tuple[CloudProvider, BaseProxyManager]:
        return self.next()

class ProxyPool:
    """High-level orchestrator for creating proxies across cloud providers.

    ``ProxyPool`` initializes one manager per selected provider and exposes
    convenience methods to create a single proxy or a batch of proxies. When
    multiple providers are configured, manager selection is randomized per
    cycle using :class:`RandomManagerPicker`.

    Notes
    -----
    - Duplicate providers are not allowed.
    - At most one configuration per provider is accepted.
    - Manager-specific validation is delegated to each provider manager.
    """
    def __init__(self,
                 *provider_configs: BaseConfig,
                 log: bool = True,
                 log_file: str | None = None,
                 log_format: str = '%(asctime)-10s %(levelname)-5s %(message)s',
                 logger: Logger | None = None):
        """Build a proxy pool and initialize provider managers. Supports multiple 
        accounts per provider by passing multiple configurations. To be able to use multiple 
        managers for the same provider the credentials must be different, otherwise an error 
        will be raised since the managers would be indistinguishable.

        Parameters
        ----------
        *provider_configs : tuple[BaseConfig, ...]
            One or more provider-specific configuration objects.

            Example::

                # will create 4 managers (2 google managers with different accounts)
                ProxyPool(GoogleConfig(...), AzureConfig(...), GoogleConfig(credentials='credentials_2.json', ...), DigitalOceanConfig(...))
        log : bool, optional
            Enable logging for manager runtime. Defaults to ``True``.
        log_file : str | None, optional
            Path to a log file. If ``None``, logging goes to the default handler.
        log_format : str, optional
            Format string used when configuring logging.
        logger : Logger | None, optional
            Shared logger instance passed to all managers.

        Raises
        ------
        ValueError
            If no providers are supplied, if providers contain duplicates, or
            if provider configurations are duplicated by provider.
        
        Examples
        --------
        Single provider with config::

            from auto_proxy_vpn import ProxyPool, GoogleConfig
            google_config = GoogleConfig(project='my-google-project', ssh_key='ssh_keys')
            pool = ProxyPool(google_config)
            batch = pool.create_batch(3)
            for proxy in batch:
                print(proxy)
            batch.close()

        Multiple providers with shared logger::

            from auto_proxy_vpn import ProxyPool, CloudProvider, GoogleConfig, AzureConfig
            google_config = GoogleConfig(project='my-google-project', ssh_key='ssh_keys')
            azure_config = AzureConfig(ssh_key='ssh_keys')
            pool = ProxyPool(google_config, azure_config)
            with pool.create_one() as proxy:
                # do something with the proxy
                pass
        
        """
        
        self.managers: list[tuple[CloudProvider, BaseProxyManager]] = []
        self._check_provider_configs(provider_configs)
        self._initialize_managers(provider_configs, log, log_file, log_format, logger)
        self.random_manager_picker = RandomManagerPicker(self.managers)
    
    def _check_provider_configs(self, provider_configs: tuple[BaseConfig, ...]):
        """Validate provider configurations for duplicates and consistency.

        This method checks that:
        - At least one provider configuration is supplied.
        - No duplicate providers are present.
        - No duplicate configurations exist for the same provider.

        Raises
        ------
        ValueError
            If any of the above conditions are violated.
        """
        
        if not provider_configs:
            raise ValueError("At least one provider configuration must be supplied.")
        
        seen_configs = set()
        for config in provider_configs:
            if config.unique_key() in seen_configs:
                raise ValueError(f"Duplicate configuration detected for provider {config.provider}")
            seen_configs.add(config.unique_key())
    
    def _initialize_managers(self, provider_configs: tuple[BaseConfig, ...], log: bool, log_file: str | None, log_format: str, logger: Logger | None):
        """Instantiate and store one manager per configured provider.

        This method sets up a shared logger (when requested and no external
        logger is provided), resolves the manager class for each provider, and
        creates manager instances using ``from_config``.
        """
        
        # all the managers will always share the same logger
        self.logger = logger
        if log and not logger:
            basicConfig(filename=log_file,
                    format=log_format,
                    filemode='a',
                    datefmt='%d-%b-%Y %H:%M:%S',
                    level=INFO)
            self.logger = getLogger('proxy_logger')
        
        for provider_config in provider_configs:
            manager_cls = ProxyManagers.get_manager(provider_config.provider)
            runtime_config = ManagerRuntimeConfig(log=log, logger=self.logger)
            manager = manager_cls.from_config(provider_config, runtime_config)
            self.managers.append((provider_config.provider, manager))
    
    def create_one(self,
                   port: int = 0,
                   size: Literal['small', 'medium', 'large'] = 'medium',
                   region: dict[CloudProvider, str] = {},
                   auth: dict[Literal['user', 'password'], str] = {},
                   allowed_ips: str | list[str] = [],
                   is_async: bool = False,
                   retry: bool = True,
                   proxy_name: str = '',
                   on_exit: Literal['keep', 'destroy'] = 'destroy') -> BaseProxy:
        """Create a single proxy using the next randomly selected manager.

        Parameters
        ----------
        port : int, optional
            Desired proxy port. Defaults to ``0`` (random).
        size : Literal['small', 'medium', 'large'], optional
            Desired proxy size. Defaults to ``'medium'``.
        region : str, optional
            Desired proxy region. Defaults to ``''`` (any).
        auth : dict[Literal['user', 'password'], str], optional
            Authentication credentials. Defaults to empty dict.
        allowed_ips : str | list[str], optional
            Allowed IPs for proxy access. Defaults to empty list.
        is_async : bool, optional
            Whether to create the proxy asynchronously. Defaults to ``False``.
        retry : bool, optional
            Whether to retry on failure. Defaults to ``True``.
        proxy_name : str, optional
            Optional name for the proxy. Defaults to empty string.
        on_exit : Literal['keep', 'destroy'], optional
            Action to take when the proxy is closed. Defaults to ``'destroy'``.

        Returns
        -------
        BaseProxy
            The created proxy instance.
        """
        
        cloud_provider, manager = self.random_manager_picker.next()
        return manager.get_proxy(port, size, region.get(cloud_provider, ''), auth, allowed_ips, is_async, retry, proxy_name, on_exit)
    
    def create_batch(self,
                     count: int,
                     ports: list[int] | int = 0,
                     sizes: list[Literal['small', 'medium', 'large']] | Literal['small', 'medium', 'large'] = 'medium',
                     regions: dict[CloudProvider, list[str] | str] = {},
                     auths: list[dict[Literal['user', 'password'], str]] | dict[Literal['user', 'password'], str] = {},
                     allowed_ips: list[str] | str = [],
                     is_async: bool = True,
                     retry: bool = True,
                     proxy_names: list[str] | str = '',
                     on_exit: Literal['keep', 'destroy'] = 'destroy') -> ProxyBatch[BaseProxy]:
        """Create multiple proxies distributed as evenly as possible.

        The requested ``count`` is split across configured providers using an
        even distribution with remainder. For each non-zero share, one manager
        is selected from :class:`RandomManagerPicker` and asked to create its
        assigned number of proxies.

        Parameters are forwarded to each manager's ``get_proxies`` method.

        Returns
        -------
        ProxyBatch
            Batch containing all successfully created proxies.

        Notes
        -----
        If a provider manager handles internal failures by returning fewer
        proxies, the resulting batch may contain fewer proxies than requested.
        """
        
        base = count // len(self.managers)
        remainder = count % len(self.managers)
        
        distribution = [base + (1 if i < remainder else 0) for i in range(len(self.managers))]
        
        proxies = []
        futures = []
        with ThreadPoolExecutor(max_workers=min((10, len(self.managers)))) as executor:
            for num_proxies in distribution:
                if num_proxies > 0:
                    cloud_provider, manager = self.random_manager_picker.next()
                    futures.append(
                        executor.submit(
                            manager.get_proxies,
                            num_proxies,
                            ports,
                            sizes,
                            regions.get(cloud_provider, ''),
                            auths,
                            allowed_ips,
                            is_async,
                            retry,
                            proxy_names,
                            on_exit,
                        )
                    )
            for future in as_completed(futures):
                proxies.extend(future.result().proxies)
        
        return ProxyBatch[BaseProxy](proxies)
    
    def get_sizes_and_regions(self, provider: CloudProvider) -> dict[Literal['small', 'medium', 'large'], list[str] | list[tuple[str, list[str]]]]:
        """Get available regions for a specific provider.

        Parameters
        ----------
        provider : CloudProvider
            The cloud provider for which to retrieve regions.

        Returns
        -------
        dict[Literal['small', 'medium', 'large'], list[str] | list[tuple[str, list[str]]]]
            A dictionary mapping proxy sizes to their available regions.

        Raises
        ------
        ValueError
            If the specified provider is not configured in the pool.
        """
        
        for cloud_provider, manager in self.managers:
            if cloud_provider == provider:
                return manager.get_sizes_and_regions()
        
        raise ValueError(f"Provider {provider} is not configured in this ProxyPool.")
    
    def get_regions_by_size(self, provider: CloudProvider, size: Literal['small', 'medium', 'large']) -> list[str] | list[tuple[str, list[str]]]:
        """Get available regions for a specific provider and proxy size.

        Parameters
        ----------
        provider : CloudProvider
            The cloud provider for which to retrieve regions.
        size : Literal['small', 'medium', 'large']
            The proxy size for which to retrieve regions.

        Returns
        -------
        list[str] | list[tuple[str, list[str]]]
            A list of regions where the specified proxy size is available.

        Raises
        ------
        ValueError
            If the specified provider is not configured in the pool or if the
            specified size is invalid for that provider.
        """
        
        sizes_and_regions = self.get_sizes_and_regions(provider)
        if size not in sizes_and_regions:
            raise ValueError(f"Size {size} is not valid.")
        
        return sizes_and_regions[size]
    
    def get_running_proxy_names(self) -> dict[CloudProvider, dict[str, list[str] | list[tuple[str, str]]]]:
        """Get names of currently running proxies grouped by provider and account.

        This method supports multiple accounts for a single provider. For each 
        provider, entries are grouped by account order using keys ``account_1``, 
        ``account_2``, etc. 
        Account numbering preserves the same order used when configs were
        passed to :class:`ProxyPool` during initialization.

        Returns
        -------
        dict[CloudProvider, dict[str, list[str] | list[tuple[str, str]]]]
            Nested mapping where each provider contains one dictionary per
            configured account/manager, and each account value is the exact
            output returned by that manager's ``get_running_proxy_names()``.

        Examples
        --------
        Example output::

            {
                CloudProvider.GOOGLE: {
                    "account_1": ["proxy1", "proxy2"],
                    "account_2": ["proxy1"],
                },
                CloudProvider.AWS: {
                    "account_1": [("proxy1", "proxy2")],
                },
            }
        """

        running_names_by_account: dict[CloudProvider, dict[str, list[str] | list[tuple[str, str]]]] = {}
        provider_counts: dict[CloudProvider, int] = {}

        for cloud_provider, manager in self.managers:
            provider_counts[cloud_provider] = provider_counts.get(cloud_provider, 0) + 1
            account_key = f"account_{provider_counts[cloud_provider]}"
            running_names_by_account.setdefault(cloud_provider, {})[account_key] = manager.get_running_proxy_names()

        return running_names_by_account