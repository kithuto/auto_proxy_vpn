class CountryNotAvailableException(Exception):
    def __init__(self, *args):
        super().__init__(*args)


class ProxyIpNotAvailableException(Exception):
    def __init__(self, *args):
        super().__init__(*args)


class ProxyAuthRequiredError(Exception):
    def __init__(self, *args):
        super().__init__(*args)


class ProxyAuthenticationError(Exception):
    def __init__(self, *args):
        super().__init__(*args)


class UnsupportedLegacyProxyAuthError(Exception):
    def __init__(self, *args):
        super().__init__(*args)
