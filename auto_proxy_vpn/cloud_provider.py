from enum import Enum


class CloudProvider(str, Enum):
    """Supported cloud providers."""

    GOOGLE = "google"
    AZURE = "azure"
    DIGITALOCEAN = "digitalocean"
    AWS = "aws"
