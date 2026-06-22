from typing import TYPE_CHECKING
from ipaddress import ip_network

from auto_proxy_vpn.utils.files_utils import get_squid_file
from auto_proxy_vpn.utils.util import normalize_allowed_ips
from .aws_exceptions import AwsUnauthorizedOperationError

if TYPE_CHECKING:
    from .aws_proxy import ProxyManagerAws


def _ip_permission(port: int, allowed_ips: list[str]) -> dict:
    ipv4_ranges = []
    ipv6_ranges = []
    for allowed_ip in allowed_ips:
        cidr = ip_network(allowed_ip, strict=False)
        if cidr.version == 4:
            ipv4_ranges.append({"CidrIp": str(cidr)})
        else:
            ipv6_ranges.append({"CidrIpv6": str(cidr)})

    permission = {
        "IpProtocol": "tcp",
        "FromPort": port,
        "ToPort": port,
    }
    if ipv4_ranges:
        permission["IpRanges"] = ipv4_ranges
    if ipv6_ranges:
        permission["Ipv6Ranges"] = ipv6_ranges
    return permission


def get_region_instances(
    proxy_manager: "ProxyManagerAws", region: str
) -> list[tuple[str, str]]:
    """List active proxy instances in a specific AWS region.

    This helper queries EC2 instances tagged as proxy resources and returns
    their names paired with the region where they are running.

    Parameters
    ----------
    proxy_manager : ProxyManagerAws
        Manager instance that provides configured boto3 access and AWS
        credentials.
    region : str
        AWS region name used to query EC2 instances.

    Returns
    -------
    list[tuple[str, str]]
        List of tuples ``(instance_name, region)`` for instances in
        ``pending`` or ``running`` states.

    Raises
    ------
    Exception
        Propagates exceptions raised by the AWS SDK request.
    """
    client = proxy_manager._boto3.client(
        "ec2",
        region_name=region,
        aws_access_key_id=proxy_manager._aws_access_key_id,
        aws_secret_access_key=proxy_manager._aws_secret_access_key,
    )
    response = client.describe_instances(
        Filters=[
            {"Name": "tag:Type", "Values": ["proxy"]},
            {"Name": "instance-state-name", "Values": ["pending", "running"]},
        ]
    )
    instance_names = []
    if response["Reservations"]:
        for reservation in response["Reservations"]:
            for instance in reservation["Instances"]:
                instance_name = [
                    tag["Value"]
                    for tag in instance.get("Tags", [])
                    if tag["Key"] == "Name"
                ]
                if instance_name:
                    instance_names.append((instance_name[0], region))

    return instance_names


def start_proxy(
    proxy_manager: "ProxyManagerAws",
    proxy_name: str,
    port: int,
    region: str,
    machine_type: str,
    allowed_ips: list[str],
    user: str = "",
    password: str = "",
    is_async: bool = False,
) -> tuple[str, str, str, bool]:
    """Create and start an EC2 instance configured as an HTTP proxy.

    This helper resolves the latest AMI that matches configured filters,
    creates a dedicated security group, opens SSH/proxy ingress for allowed
    IPs, and launches a tagged EC2 instance with Squid startup user data.

    Parameters
    ----------
    proxy_manager : ProxyManagerAws
        Manager instance that provides boto3 clients/resources, credentials,
        AMI filters, and SSH keys.
    proxy_name : str
        Name used for the EC2 instance tag and associated security group.
    port : int
        TCP port exposed by the proxy service.
    region : str
        AWS region where the proxy instance is created.
    machine_type : str
        EC2 instance type (for example ``'t3.micro'``).
    allowed_ips : list[str]
        Source IPs/CIDRs allowed to access SSH and proxy ports.
    user : str, optional
        Basic-auth username for Squid configuration. Defaults to ``''``.
    password : str, optional
        Basic-auth password for Squid configuration. Defaults to ``''``.
    is_async : bool, optional
        If True, return before waiting for instance running state.
        Defaults to ``False``.

    Returns
    -------
    tuple[str, str, str, bool]
        A tuple ``(public_ip, instance_id, security_group_id, error)`` where
        ``error`` is True when provisioning cannot continue or no capacity is
        available.

    Raises
    ------
    AwsUnauthorizedOperationError
        If AWS denies instance creation permissions for the selected region.
    Exception
        Propagates non-handled AWS SDK errors.
    """

    ec2 = proxy_manager._boto3.resource(
        "ec2",
        region_name=region,
        aws_access_key_id=proxy_manager._aws_access_key_id,
        aws_secret_access_key=proxy_manager._aws_secret_access_key,
    )
    client = proxy_manager._boto3.client(
        "ec2",
        region_name=region,
        aws_access_key_id=proxy_manager._aws_access_key_id,
        aws_secret_access_key=proxy_manager._aws_secret_access_key,
    )

    # search for the image ami id
    response = client.describe_images(Filters=proxy_manager._os_image_filters)
    try:
        ami_id = sorted(
            response["Images"], key=lambda x: x["CreationDate"], reverse=True
        )[0]["ImageId"]
    except Exception:
        return "", "", "", True

    # First of all a firewall must be created or reloaded. Openning the proxy port for the IPs the user specified
    security_group_name = f"{proxy_name}-firewall"
    response = client.create_security_group(
        GroupName=security_group_name,
        Description=f"Security group for {security_group_name} automatically created by auto_proxy_vpn library",
    )
    security_group_id = response["GroupId"]

    allowed_ips = normalize_allowed_ips(allowed_ips)

    # allow ssh and proxy port
    client.authorize_security_group_ingress(
        GroupId=security_group_id,
        IpPermissions=[
            _ip_permission(22, allowed_ips),
            _ip_permission(port, allowed_ips),
        ],
    )

    # create the instance with the user data script that will install and start the proxy
    try:
        instances = ec2.create_instances(  # type: ignore
            ImageId=ami_id,
            InstanceType=machine_type,
            MinCount=1,
            MaxCount=1,
            SecurityGroupIds=[security_group_id],
            TagSpecifications=[
                {
                    "ResourceType": "instance",
                    "Tags": [
                        {"Key": "Name", "Value": proxy_name},
                        {"Key": "Type", "Value": "proxy"},
                    ],
                }
            ],
            UserData=get_squid_file(
                port,
                user=user,
                password=password,
                allowed_ips=allowed_ips,
                ssh_keys=proxy_manager.ssh_keys,
            ),
        )
    except proxy_manager._aws_ClientError as e:
        # remove the security group created for the proxy in case of any error to avoid leaving unused resources in the cloud
        client.delete_security_group(GroupId=security_group_id)

        error_code = e.response["Error"]["Code"]

        if error_code == "UnauthorizedOperation":
            raise AwsUnauthorizedOperationError(
                "Check in the AWS console the regions where your credentials have permissions to create instances and use those regions when creating proxies."
            )
        elif error_code == "InsufficientInstanceCapacity":
            return "", "", "", True
        else:
            raise e

    instance = instances[0]
    if not is_async:
        instance.wait_until_running()
        instance.reload()

    return instance.public_ip_address, instance.id, security_group_id, False
