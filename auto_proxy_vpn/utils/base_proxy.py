from abc import ABC, abstractmethod
from random import shuffle
from typing import Iterator, Literal, TypeVar, Generic, Optional, overload
from time import sleep

from auto_proxy_vpn import ManagerRuntimeConfig
from .util import get_public_ip
from .exceptions import ProxyIpNotAvailableException

T = TypeVar("T", bound="BaseProxy")

class BaseProxy(ABC):
    ip: str
    name: str
    port: int
    user: str
    password: str
    output: bool
    log: bool
    destroy: bool
    active: bool
    is_async: bool
    
    def get_proxy_str(self) -> str:
        '''
        Returns the url of the proxy. Empty string if no public IP yet.
        '''
        if not self.ip:
            return ''
        return f'http://{f"{self.user}:{self.password}@" if self.user else ""}{self.ip}:{self.port}'
    
    def get_proxy(self) -> Optional[dict[str, str]]:
        '''
        Returns the proxy in a format that can be used by the requests library. Empty dict if no public IP yet.
        '''
        proxy_str = self.get_proxy_str()
        if not proxy_str:
            return None
        return {'http': proxy_str, 'https': proxy_str}
    
    def is_active(self, wait: bool = False) -> bool:
        """
        Checks if proxy is active.
        
        Parameters
        ----------
        wait : bool
            Always wait until the proxy is active, even if it is asynchronous.
        """
        if not self.active:
            if not self.get_proxy_str():
                raise ProxyIpNotAvailableException("Couldn't get the proxy IP address!")
            if self.is_async and not wait:
                try:
                    assert get_public_ip(timeout=10, proxy=self.get_proxy()) == self.ip
                    self.active = True
                finally:
                    return self.active
            else:
                times = 0
                while not self.active and times < 40:
                    try:
                        assert get_public_ip(timeout=10, proxy=self.get_proxy()) == self.ip
                        self.active = True
                    except OSError as e:
                        if 'Tunnel connection failed: 407 Proxy Authentication Required' in str(e):
                            return self.active
                        times += 1
                        sleep(5)
                    except:
                        times += 1
                        sleep(5)
        return self.active
    
    @abstractmethod
    def _stop_proxy(self, wait: bool = True):
        """
        Stops and kills the proxy. If the proxy is not asynchronous, it will wait until the proxy is fully removed.
        """
        ...
    
    def __str__(self):
        return f"Proxy {self.name} {self.get_proxy_str()} {'(active)' if self.active else '(inactive)'}"
    
    def __repr__(self) -> str:
        return self.__str__()
    
    def __enter__(self):
        if self.is_active(wait=True):
            return self
        else:
            raise TimeoutError("The proxy couldn't be activated!")
    
    def __exit__(self, exc_type, exc_value, exc_traceback):
        self._stop_proxy()
    
    def close(self, wait: bool = True):
        """
        Closes the proxy, destroying it if on_exit is set to 'destroy' or keeping it if on_exit is set to 'keep'.
        
        Parameters
        ----------
        wait : bool
            Whether to wait until the proxy is fully removed when closing it.
            If the proxy is not asynchronous and wait is False, it will return
            immediately without waiting for the proxy to be fully removed. For
            asynchronous proxies, this parameter has no effect and the method
            will never wait for the proxy to be fully removed before returning.
        """
        self._stop_proxy(wait=wait)

class ProxyBatch(Generic[T]):
    def __init__(self, proxies: list[T]):
        """Container for a group of proxies with iteration and lifecycle control.

        The batch shuffles the incoming proxies on creation to avoid predictable
        ordering. It behaves as an iterable and iterator, supports indexing, and
        can be used as a context manager to ensure all proxies are closed when the
        batch is no longer needed.

        Parameters
        ----------
        proxies : list[BaseProxy]
            Proxies included in the batch.

        Notes
        -----
        - Once closed, most operations raise ``RuntimeError``.
        - Make sure to call ``close()`` when done to release resources if not
          using a context manager.

        Examples
        --------
        Context manager usage:

        >>> with pool.create_batch(3) as batch:
        ...     for proxy in batch:
        ...         print(proxy)

        Manual close:

        >>> batch = pool.create_batch(3)
        >>> for proxy in batch:
        ...     print(proxy)
        >>> batch.close()
        """
        
        shuffle(proxies)
        self.proxies = proxies
        self._closed = False
        self._next_index = 0
    
    def _ensure_open(self):
        """Raise ``RuntimeError`` if the batch has already been closed."""
        if self._closed:
            raise RuntimeError("ProxyBatch is closed")
    
    def __len__(self) -> int:
        """Return the number of proxies in the batch."""
        self._ensure_open()
        return len(self.proxies)
    
    def __iter__(self) -> Iterator[T]:
        """Return an iterator over the proxies in the batch."""
        self._ensure_open()
        return iter(self.proxies)
    
    @overload
    def __getitem__(self, index: int) -> T: ...
    @overload
    def __getitem__(self, index: slice) -> list[T]: ...

    def __getitem__(self, index: int | slice):
        """Access a proxy (or sub-list of proxies) by index or slice."""
        self._ensure_open()
        return self.proxies[index]
    
    def __next__(self) -> T:
        """Return the next proxy for iterator-style consumption."""
        self._ensure_open()
        if self._next_index >= len(self.proxies):
            self._next_index = 0
            raise StopIteration
        item = self.proxies[self._next_index]
        self._next_index += 1
        return item
    
    def __enter__(self) -> "ProxyBatch":
        """Enter context manager mode and return this batch."""
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb):
        """Close all proxies when leaving context manager scope."""
        self.close()
    
    def close(self):
        """Close every proxy in the batch and mark the batch as closed."""
        
        if self._closed:
            return
        for proxy in self.proxies:
            proxy.close()
        self._closed = True

class BaseProxyManager(ABC, Generic[T]):
    _sizes_regions: dict[Literal["small", "medium", "large"], list[str] | list[tuple[str, list[str]]]]
    
    @classmethod
    @abstractmethod
    def from_config(cls, config = None, runtime_config: ManagerRuntimeConfig | None = None) -> 'BaseProxyManager':
        ...
    
    @abstractmethod
    def get_proxy(self,
                  port: int = 0,
                  size: Literal['small', 'medium', 'large'] = 'medium',
                  region: str = '',
                  auth: dict[Literal['user', 'password'], str] = {},
                  allowed_ips: str | list[str] = [],
                  is_async: bool = False,
                  retry: bool = True,
                  proxy_name: str = '',
                  on_exit: Literal['keep', 'destroy'] = 'destroy') -> T:
        ...
    
    @abstractmethod
    def get_proxy_by_name(self, name: str, is_async: bool = False, on_exit: Literal['destroy', 'keep'] = 'destroy') -> T:
        ...
    
    def get_proxies(self,
                    number: int,
                    ports: list[int] | int = 0,
                    sizes: list[Literal['small', 'medium', 'large']] | Literal['small', 'medium', 'large'] = 'medium',
                    regions: list[str] | str = '',
                    auths: list[dict[Literal['user', 'password'], str]] | dict[Literal['user', 'password'], str] = {},
                    allowed_ips: list[str] | str = [],
                    is_async: bool = True,
                    retry: bool = True,
                    proxy_names: list[str] | str = '',
                    on_exit: Literal['keep', 'destroy'] = 'destroy') -> ProxyBatch[T]:
        """
        Gets multiple proxies at once. The parameters can be a single value or a list of values. 
        If a single value is provided, it will be used for all proxies. If a list of values is 
        provided, it must have the same length as the number of proxies to create.

        Parameters
        ----------
        number : int
            Number of proxies to get.
        ports : list[int] or int
            Port or list of ports to use.
        sizes : list or str
            Size or list of sizes to use.
        regions : list[str] or str
            Region or list of regions to use.
        auths : list[dict] or dict
            Auth or list of auths to use.
        allowed_ips : list[str] or str
            Allowed IP or list of allowed IPs to use in all proxies.
        is_async : bool
            Whether the proxies should be async or not.
        retry : bool
            Whether to retry if a proxy fails to start.
        proxy_names : list[str] or str
            Proxy name or list of proxy names to use.
        on_exit : {'keep', 'destroy'}
            Whether to keep or destroy the proxies when the program ends.

        Returns
        -------
        ProxyBatch
            Batch of proxy instances.
        
        Raises
        ------
        ValueError
            If the length of the ports, sizes, regions, auths or proxy_names
            lists is not equal to the number of proxies to create, or if any
            of the sizes or regions is invalid.
        TypeError
            If any of the auths is not a dict, or if allowed_ips is not a
            list of strings or a string.
        KeyError
            If any of the auth dicts does not have the keys 'user' and
            'password'.
        """
        
        # check if the variables of instance list has the same length as the number of proxies to create, if not, raise an error
        if isinstance(ports, list) and len(ports) != number:
            raise ValueError("The length of the ports list must be equal to the number of proxies to create.")
        if isinstance(sizes, list) and len(sizes) != number:
            raise ValueError("The length of the sizes list must be equal to the number of proxies to create.")
        if isinstance(regions, list) and len(regions) != number:
            raise ValueError("The length of the regions list must be equal to the number of proxies to create.")
        if isinstance(auths, list) and len(auths) != number:
            raise ValueError("The length of the auths list must be equal to the number of proxies to create.")
        if isinstance(proxy_names, list) and len(proxy_names) != number:
            raise ValueError("The length of the proxy_names list must be equal to the number of proxies to create.")
        
        # check if sizes are valid
        if isinstance(sizes, list):
            for size in sizes:
                if size not in ['small', 'medium', 'large']:
                    raise ValueError("Invalid size. Valid sizes are: 'small', 'medium', 'large'.")
        elif sizes and sizes not in ['small', 'medium', 'large']:
            raise ValueError("Invalid size. Valid sizes are: 'small', 'medium', 'large'.")
        
        # check if regions are valid
        if isinstance(regions, list):
            for region in regions:
                if region not in self.get_regions_by_size('small'):
                    raise ValueError(f"Invalid region! Check the valid regions calling get_regions_by_size()")
        elif regions and regions not in self.get_regions_by_size('small'):
            raise ValueError(f"Invalid region! Check the valid regions calling get_regions_by_size()")
        
        # check if auths are valid
        if isinstance(auths, list):
            for auth in auths:
                if not isinstance(auth, dict):
                    raise TypeError('Bad auth format, auth must be a dict')
                
                if 'user' not in auth.keys() or 'password' not in auth.keys():
                    raise KeyError('Auth dict must have two keys name and password')
        elif auths:
            if not isinstance(auths, dict):
                raise TypeError('Bad auth format, auth must be a dict')
            
            if 'user' not in auths.keys() or 'password' not in auths.keys():
                raise KeyError('Auth dict must have two keys name and password')
        
        # create the proxies
        proxies = []
        for i in range(number):
            # try to create the proxy
            try:
                proxies.append(self.get_proxy(
                    port=ports[i] if isinstance(ports, list) else ports,
                    size=sizes[i] if isinstance(sizes, list) else sizes,
                    region=regions[i] if isinstance(regions, list) else regions,
                    auth=auths[i] if isinstance(auths, list) else auths,
                    allowed_ips=allowed_ips,
                    is_async=is_async,
                    retry=retry,
                    proxy_name=proxy_names[i] if isinstance(proxy_names, list) else proxy_names,
                    on_exit=on_exit
                ))
            finally:
                continue
        
        return ProxyBatch[T](proxies)
    
    def get_sizes_and_regions(self) -> dict[Literal["small", "medium", "large"], list[str] | list[tuple[str, list[str]]]]:
        """
        Get all sizes and regions avaliable.
        """
        return self._sizes_regions
    
    def get_regions_by_size(self, size: Literal["small", "medium", "large"]) -> list[str] | list[tuple[str, list[str]]]:
        """
        Returns a list of regions for a sepecific size
        """
        if size not in ['small', 'medium', 'large']:
            raise NameError('Unavaliable server size')
        return self._sizes_regions[size]
    
    @abstractmethod
    def get_running_proxy_names(self) -> list[str]:
        """
        Get list of running proxy names
        """
        ...