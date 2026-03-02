from random import choice
from typing import Any, TYPE_CHECKING, Literal
from sys import stderr
from collections import defaultdict

from auto_proxy_vpn.utils.files_utils import get_squid_file

if TYPE_CHECKING:
    from .google_proxy import ProxyManagerGoogle

def wait_for_extended_operation(operation, timeout: int = 200) -> Any:
    """Waits for the extended (long-running) operation to complete.

    If the operation is successful, it will return its result.
    If the operation ends with an error, an exception will be raised.
    If there were any warnings during the execution of the operation
    they will be printed to sys.stderr.

    Parameters
    ----------
    operation
        A long-running operation you want to wait on.
    timeout : int
        How long (in seconds) to wait for operation to finish. If None, wait
        indefinitely.

    Returns
    -------
    object
        Whatever the operation.result() returns.

    Raises
    ------
    RuntimeError
        If the operation has an error code but no exception set.
    concurrent.futures.TimeoutError
        If the operation takes longer than ``timeout`` seconds.
    """
    
    result = operation.result(timeout=timeout)
    
    if operation.error_code:
        raise operation.exception() or RuntimeError(operation.error_message)
    
    if operation.warnings:
        print(f"Warnings during operation:\n", file=stderr, flush=True)
        for warning in operation.warnings:
            print(f" - {warning.code}: {warning.message}", file=stderr, flush=True)
    
    return result

def get_avaliable_regions_by_size(compute_v1, machine_types_client, project: str, instance_proxy_sizes: dict[Literal["small", "medium", "large"], str]) -> tuple[list[tuple[str, list[str]]], dict[Literal["small", "medium", "large"], list[str] | list[tuple[str, list[str]]]]]:
    """Returns a list of all available regions and zones in Google Cloud, and a mapping of instance sizes to their available regions.
    
    Parameters
    ----------
    compute_v1
        The Google Compute Engine client library.
    machine_types_client
        The Google Compute Engine MachineTypesClient instance.
    project : str
        The Google Cloud project ID.
    instance_proxy_sizes : dict
        A dictionary mapping size labels ("small", "medium", "large") to
        Google Cloud machine type slugs.
    
    Returns
    -------
    tuple
        A list of tuples, where each tuple contains a region name and a list
        of its zones. And a dictionary mapping size labels to either a list
        of regions or a list of tuples (region name and its zones) where
        that size is available.
    
    Raises
    ------
    Exception
        Propagates exceptions raised by the Google Compute API clients while
        fetching regions and machine types.
    """
    
    region_by_size: dict[Literal["small", "medium", "large"], list[str] | list[tuple[str, list[str]]]] = {size: [] for size in instance_proxy_sizes.keys()}
    
    # For a faster initialization only the first vm size will be called with de google api because the rest of the sizes has the same avaliable regions as the first one
    request = compute_v1.AggregatedListMachineTypesRequest(project=project, filter=f'name={instance_proxy_sizes['small']}')
    zones = machine_types_client.aggregated_list(request=request)
    
    regions_dict: defaultdict[str, list[str]] = defaultdict(list)
    for zone, found_instances in zones:
        if found_instances.machine_types:
            zone = str(zone).split("/")[-1]
            region = "-".join(zone.split("-")[:-1])
            if not zone in regions_dict[region]:
                regions_dict[region].append(zone)
    
    for size in instance_proxy_sizes.keys():
        region_by_size[size] = [(region, zs) for region, zs in regions_dict.items()]
    
    return [(region, zones) for region, zones in regions_dict.items()], region_by_size
    
def start_proxy(proxy_manager: "ProxyManagerGoogle", proxy_name: str, port: int, region: str, zone: str, zones: list[str], machine_type: str, allowed_ips: list[str], user: str = '', password: str = '', is_async: bool = False, firewall: bool = True) -> tuple[str, bool]:
    """Create and start a Google Compute Engine proxy instance.

    This helper optionally creates a firewall rule, provisions a VM configured
    with a Squid startup script, waits for completion when requested, and
    returns the instance public IP address.

    Parameters
    ----------
    proxy_manager : ProxyManagerGoogle
        Manager instance that provides Google Compute clients and project
        configuration.
    proxy_name : str
        Name of the VM and related firewall/tag resources.
    port : int
        Proxy TCP port exposed by Squid.
    region : str
        Google Cloud region used to resolve the default subnet.
    zone : str
        Google Cloud zone where the VM is created.
    machine_type : str
        Compute Engine machine type slug (for example ``'e2-micro'``).
    allowed_ips : list[str]
        Source IPs/ranges allowed to access the proxy port.
    user : str, optional
        Basic-auth username injected in the startup script. Defaults to
        ``''``.
    password : str, optional
        Basic-auth password injected in the startup script. Defaults to
        ``''``.
    is_async : bool, optional
        If True, do not wait for the create operation to finish before
        continuing. Defaults to ``False``.
    firewall : bool, optional
        If True, create a firewall rule named ``{proxy_name}-firewall``
        before creating the VM. Defaults to ``True``.

    Returns
    -------
    tuple[str, bool]
        ``(public_ip, error)`` where ``public_ip`` is the assigned IPv4
        address and ``error`` indicates whether provisioning failed.

    Raises
    ------
    Exception
        Propagates exceptions raised by the Google Compute API clients while
        creating firewall rules, creating the instance, or fetching instance
        network information.
    """
    
    # First of all a firewall must be created. Openning the proxy port for the IPs the user specified
    if firewall:
        rule = proxy_manager._compute_v1.Firewall(
            name=f'{proxy_name}-firewall',
            network=f"projects/{proxy_manager.project}/global/networks/default",
            allowed=[{'I_p_protocol': 'tcp', 'ports': [str(port)]}],
            source_ranges=allowed_ips,
            target_tags=[proxy_name]
        )
        
        _ = proxy_manager._firewall_client.insert(project=proxy_manager.project, firewall_resource=rule)
    
    config = {
        "can_ip_forward": False,
        "confidential_instance_config": {
            "enable_confidential_compute": False
        },
        "deletion_protection": False,
        "description": "Proxy generated by auto-proxy-vpn python package",
        "disks": [
            {
            "auto_delete": True,
            "boot": True,
            "initialize_params": {
                    "disk_size_gb": "10",
                    "disk_type": f"projects/{proxy_manager.project}/zones/{zone}/diskTypes/pd-standard",
                    "source_image": f"projects/ubuntu-os-cloud/global/images/{proxy_manager.proxy_image}"
                }
            }
        ],
        "display_device": {
            "enable_display": False
        },
        "machine_type": f"projects/{proxy_manager.project}/zones/{zone}/machineTypes/{machine_type}",
        "metadata": {
            "items": [
                {
                    "key": "startup-script",
                    "value": get_squid_file(port, user=user, password=password, allowed_ips=allowed_ips)
                },
                {
                    "key": "ssh-keys",
                    "value": "\n".join([f"ubuntu:{ssh_key}" for ssh_key in proxy_manager.ssh_keys])
                }
            ]
        },
        "name": proxy_name,
        "network_interfaces": [
            {
            "access_configs": [
                {
                "network_tier": 'STANDARD'
                }
            ],
            "subnetwork": f"projects/{proxy_manager.project}/regions/{region}/subnetworks/default"
            }
        ],
        "reservation_affinity": {
            "consume_reservation_type": "NO_RESERVATION"
        },
        "zone": f"projects/{proxy_manager.project}/zones/{zone}",
        "tags": {
            "items": [
                proxy_name,
                "proxy"
            ]
        }
    }
    
    request = proxy_manager._compute_v1.InsertInstanceRequest(
        project = proxy_manager.project,
        zone = zone,
        instance_resource=config
    )
    
    response = proxy_manager._instances_client.insert(request=request)
    
    if not is_async:
        try:
            _ = wait_for_extended_operation(response)
        except proxy_manager._google_exceptions.ServiceUnavailable:
            if proxy_manager.logger:
                proxy_manager.logger.warning(f"Zone {zone} is currently unavailable. Trying to start the proxy in another zone of the same region.")
            
            if not zones:
                # No more zones to try, the proxy cannot be started in this region
                return '', True
            
            # If the zone is unavailable, try to start the proxy in another zone of the same region
            zone = choice(zones)
            return start_proxy(proxy_manager, proxy_name, port, region, zone, [x for x in zones if x != zone], machine_type, allowed_ips, user, password, is_async, firewall=False)
    
    instance_request = proxy_manager._compute_v1.GetInstanceRequest(instance=proxy_name, project=proxy_manager.project, zone=zone)
    proxy_instance_ip = proxy_manager._instances_client.get(instance_request).network_interfaces[0].access_configs[0].nat_i_p
    
    return proxy_instance_ip, False