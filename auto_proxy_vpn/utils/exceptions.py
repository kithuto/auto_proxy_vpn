class CountryNotAvailableException(Exception):
    """Raised when a requested country or region is unavailable."""


class ProxyIpNotAvailableException(Exception):
    """Raised when a proxy has no usable public IP address."""


class ProxyAuthRequiredError(Exception):
    """Raised when recovering an authenticated proxy without credentials."""


class ProxyAuthenticationError(Exception):
    """Raised when provided proxy recovery credentials do not match."""


class UnsupportedLegacyProxyAuthError(Exception):
    """Raised when an authenticated proxy lacks supported secure metadata."""
