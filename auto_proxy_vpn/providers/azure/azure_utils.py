from typing import TYPE_CHECKING
from base64 import b64encode

from auto_proxy_vpn.utils.files_utils import get_squid_file

if TYPE_CHECKING:
    from .azure_proxy import ProxyManagerAzure

def get_last_avaliable_sku_version(compute_client, publisher: str, offer: str, sku: str, location: str) -> str:
    """Return the latest available VM image version for a given Azure image SKU.

    Parameters
    ----------
    compute_client
        Azure Compute management client with access to
        ``virtual_machine_images.list``.
    publisher : str
        Image publisher (for example ``'Canonical'``).
    offer : str
        Image offer name.
    sku : str
        Image SKU name.
    location : str
        Azure region used to query available versions.

    Returns
    -------
    str
        Version name considered the latest after descending sort.

    Raises
    ------
    Exception
        Propagates errors raised by the Azure SDK request.
    """
    versions = compute_client.virtual_machine_images.list(location, publisher, offer, sku)
    versions = sorted(versions, key=lambda x: x.name, reverse=True)
    return versions[0].name

def start_proxy(manager: "ProxyManagerAzure", proxy_name: str, port: int, region: str, machine_type: str, allowed_ips: list[str], user: str = '', password: str = '', is_async: bool = False) -> tuple[str, bool]:
    """Create and start an Azure VM configured as an HTTP proxy.

    This helper provisions all required Azure resources for a proxy VM,
    including a resource group, network security group, virtual network,
    public IP, network interface, and the virtual machine itself. The VM is
    initialized with a Squid startup script (cloud-init custom data) generated
    from the provided proxy settings.

    Parameters
    ----------
    manager : ProxyManagerAzure
        Manager instance that provides Azure SDK clients, model classes,
        image information, and SSH keys.
    proxy_name : str
        Base name used for the VM and related Azure resources (resource
        group, NSG, VNet, NIC, etc.).
    port : int
        TCP port exposed by the proxy service.
    region : str
        Azure region where resources are created.
    machine_type : str
        Azure VM size (for example ``'Standard_B1s'``).
    allowed_ips : list[str]
        Source IPs/ranges allowed to access SSH and proxy ports in inbound
        NSG rules.
    user : str, optional
        Basic-auth username embedded in Squid configuration. Defaults to
        ``''``.
    password : str, optional
        Basic-auth password embedded in Squid configuration. Defaults to
        ``''``.
    is_async : bool, optional
        If True, return without waiting for VM creation completion.
        Defaults to ``False``.

    Returns
    -------
    tuple[str, bool]
        A tuple ``(public_ip, error)`` where ``public_ip`` is the assigned
        IPv4 address (or ``''`` when unavailable) and ``error`` indicates
        whether provisioning failed to produce a usable public IP.

    Raises
    ------
    Exception
        Propagates exceptions raised by Azure SDK operations during resource
        creation and VM provisioning.
    """
    
    firewall_name = f"{proxy_name}-firewall"
    vnet_name = f"{proxy_name}-vnet"
    subnet_name = f"{proxy_name}-subnet"
    public_ip_name = f"{proxy_name}-public-ip"
    ip_config_name = f"{proxy_name}-config-ip"
    network_interface_name = f"{proxy_name}-nic"
    os_disk_name = f"{proxy_name}-os"
    username = "proxy-user"
    
    # ssh keys
    ssh_keys = [manager._compute_models.SshPublicKey(path=f"/home/{username}/.ssh/authorized_keys", key_data=key) for key in manager.ssh_keys]
    
    # cloud init custom data
    custom_data = b64encode(get_squid_file(port, user=user, password=password, allowed_ips=allowed_ips).encode('utf-8')).decode('latin-1')
    
    # creating resource group
    _ = manager._resource_client.resource_groups.create_or_update(proxy_name, {'location': region, 'tags': {'type': 'proxy'}}) # type: ignore
    
    # firewall rules
    # allow only trafic from the desired ips to the ssh and proxy ports
    security_rules = [
        manager._network_models.SecurityRule(
            name="allowSSHTrafic",
            priority=900,
            protocol="Tcp",
            access="Allow",
            direction="Inbound",
            source_address_prefix=",".join(allowed_ips),
            source_port_range="*",
            destination_address_prefix="*",
            destination_port_range="22"
        ),
        manager._network_models.SecurityRule(
            name="allowProxyTrafic",
            priority=901,
            protocol="Tcp",
            access="Allow",
            direction="Inbound",
            source_address_prefix=",".join(allowed_ips),
            source_port_range="*",
            destination_address_prefix="*",
            destination_port_range=str(port)
        )
    ]
    
    # create network security group
    network_security_group_creation = manager._network_client.network_security_groups.begin_create_or_update(
        proxy_name,
        firewall_name,
        manager._network_models.NetworkSecurityGroup(
            location=region,
            security_rules=security_rules
        )
    )
    # virtual net and subnet creation
    vnet_creation = manager._network_client.virtual_networks.begin_create_or_update(
        proxy_name,
        vnet_name,
        manager._network_models.VirtualNetwork(
            location=region,
            address_space=manager._network_models.AddressSpace(address_prefixes=['10.0.0.0/16']),
            subnets=[manager._network_models.Subnet(name=subnet_name, address_prefix='10.0.0.0/24')]
        )
    )
    # public ip creation
    public_ip_creation = manager._network_client.public_ip_addresses.begin_create_or_update(
        proxy_name,
        public_ip_name,
        manager._network_models.PublicIPAddress(
            location=region,
            public_ip_allocation_method="Static",
            sku=manager._network_models.PublicIPAddressSku(name="Standard"),
            public_ip_address_version="IPv4",
            zones=None
        )
    )
    
    # wait for all items to be created
    network_security_group = network_security_group_creation.result()
    subnet_id = vnet_creation.result().subnets[0].id # type: ignore
    public_ip = public_ip_creation.result()
    
    if not public_ip.ip_address:
        return '', True
    
    network_interface_creation = manager._network_client.network_interfaces.begin_create_or_update(
        proxy_name,
        network_interface_name,
        manager._network_models.NetworkInterface(
            location=region,
            network_security_group=manager._network_models.NetworkSecurityGroup(id=network_security_group.id),
            ip_configurations=[manager._network_models.NetworkInterfaceIPConfiguration(
                name=ip_config_name,
                subnet=manager._network_models.Subnet(id=subnet_id),
                private_ip_allocation_method="Dynamic",
                public_ip_address=manager._network_models.PublicIPAddress(id=public_ip.id, delete_option='Delete')
            )]
        )
    )
    network_interface = network_interface_creation.result()
    
    # delete NetworkWatcherRG (only if exists) to avoid aditional billing. No need to wait for it to finish
    try:
        _ = manager._resource_client.resource_groups.begin_delete('NetworkWatcherRG')
    except:
        pass
    
    image_version = get_last_avaliable_sku_version(manager._compute_client, manager._image_publisher, manager._image_offer, manager._image_sku, region)
    
    # create the virtual machine
    vm_disk = manager._compute_models.OSDisk(
        name=os_disk_name,
        create_option="fromImage",
        managed_disk=manager._compute_models.ManagedDiskParameters(storage_account_type="Standard_LRS"),
        delete_option="Delete"
    )
    vm_os_image = manager._compute_models.ImageReference(
        publisher=manager._image_publisher,
        offer=manager._image_offer,
        sku=manager._image_sku,
        version=image_version
    )
    vm_os_profile = manager._compute_models.OSProfile(
        computer_name=proxy_name,
        admin_username=username,
        linux_configuration=manager._compute_models.LinuxConfiguration(
            disable_password_authentication=True,
            ssh=manager._compute_models.SshConfiguration(public_keys=ssh_keys)
        ),
        custom_data=custom_data
    )
    proxy_vm = manager._compute_models.VirtualMachine(
        location=region,
        hardware_profile=manager._compute_models.HardwareProfile(vm_size=machine_type),
        storage_profile=manager._compute_models.StorageProfile(
            os_disk=vm_disk,
            image_reference=vm_os_image
        ),
        network_profile=manager._compute_models.NetworkProfile(
            network_interfaces=[manager._compute_models.NetworkInterfaceReference(id=network_interface.id, delete_option="Delete")]
        ),
        security_profile=manager._compute_models.SecurityProfile(
            security_type="TrustedLaunch",
            uefi_settings=manager._compute_models.UefiSettings(secure_boot_enabled=True, v_tpm_enabled=True)
        ),
        additional_capabilities=manager._compute_models.AdditionalCapabilities(hibernation_enabled=False),
        os_profile=vm_os_profile,
        zones=None
    )
    
    virtual_machine_creation = manager._compute_client.virtual_machines.begin_create_or_update(proxy_name, proxy_name, proxy_vm) # type: ignore
    if not is_async:
        _ = virtual_machine_creation.result()
    
    return public_ip.ip_address if public_ip.ip_address else '', False