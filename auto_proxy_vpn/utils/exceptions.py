class CountryNotAvailableException(Exception):
    def __init__(self, *args):
        super().__init__(*args)

class ProxyIpNotAvailableException(Exception):
    def __init__(self, *args):
        super().__init__(*args)