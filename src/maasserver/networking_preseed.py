# Copyright 2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Network configuration preseed code.

This will eventually generate installer networking configuration like:

   https://gist.github.com/jayofdoom/b035067523defec7fb53

A different version of the format is documented here:

    http://bit.ly/1uqWvC8

The installer running on a node will use this to set up the node's networking
according to MAAS's specifications.
"""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    'generate_networking_config',
    ]

from collections import defaultdict
from textwrap import dedent

from lxml import etree
from maasserver.dns.zonegenerator import get_dns_server_address
from maasserver.exceptions import UnresolvableHost
from maasserver.models.nodeprobeddetails import get_probed_details
from maasserver.models.staticipaddress import StaticIPAddress
from netaddr import (
    IPAddress,
    IPNetwork,
    )


def extract_network_interface_data(element):
    """Extract network interface name and MAC address from XML element.

    :return: A tuple of network interface name and MAC address as found in
        the XML.  If either is not found, it will be `None`.
    """
    interfaces = element.xpath("logicalname")
    macs = element.xpath("serial")
    if len(interfaces) == 0 or len(macs) == 0:
        # Not enough data.
        return None, None
    assert len(interfaces) == 1
    assert len(macs) == 1
    return interfaces[0].text, macs[0].text


def normalise_mac(mac):
    """Return a MAC's normalised representation.

    This doesn't actually parse all the different formats for writing MAC
    addresses, but it does eliminate case differences.  In practice, any MAC
    address this code is likely to will equal another version of itself after
    normalisation, even if they were originally different spellings.
    """
    return mac.strip().lower()


def extract_network_interfaces(node):
    """Extract network interfaces from node's `lshw` output.

    :param node: A `Node`.
    :return: A list of tuples describing the network interfaces.
        Each tuple consists of an interface name and a MAC address.
    """
    node_details = get_probed_details([node.system_id])
    if node.system_id not in node_details:
        return []
    lshw_xml = node_details[node.system_id].get('lshw')
    if lshw_xml is None:
        return []
    network_nodes = etree.fromstring(lshw_xml).xpath("//node[@id='network']")
    interfaces = [
        extract_network_interface_data(xml_node)
        for xml_node in network_nodes
        ]
    return [
        (interface, normalise_mac(mac))
        for interface, mac in interfaces
        if interface is not None and mac is not None
        ]


def generate_ethernet_link_entry(interface, mac):
    """Generate the `links` list entry for the given ethernet interface.

    :param interface: Network interface name, e.g. `eth0`.
    :param mac: MAC address, e.g. `00:11:22:33:44:55`.
    :return: A dict specifying the network interface, with keys
        `id`, `type`, and `ethernet_mac_address` (and possibly more).
    """
    return {
        'id': interface,
        'type': 'phy',
        'ethernet_mac_address': mac,
        }


def generate_dns_server_entry(dns_address):
    """Generate the `services` list entry for the given DNS server.

    :param dns_address: IP address for a DNS server, in text form.
    :return: A dict specifying the DNS server as a network service, with
        keys `address` and `type` (and possibly more).
    """
    return {
        'type': 'dns',
        'address': dns_address,
        }


def list_dns_servers(node):
    """Return DNS servers, IPv4 and IPv6 as appropriate, for use by `node`.

    These are always the MAAS-controlled DNS servers.
    """
    cluster = node.nodegroup
    servers = []
    if not node.disable_ipv4:
        try:
            servers.append(
                get_dns_server_address(cluster, ipv4=True, ipv6=False))
        except UnresolvableHost:
            # No IPv4 DNS server.
            pass
    try:
        servers.append(get_dns_server_address(cluster, ipv4=False, ipv6=True))
    except UnresolvableHost:
        # No IPv6 DNS server.
        pass
    return [dns_server for dns_server in servers if dns_server is not None]


def generate_route_entries(cluster_interface):
    """Generate `routes` list entries for a cluster interface.

    Actually this returns exactly one route (the default route) if
    `cluster_interface` has a router set; or none otherwise.
    """
    if cluster_interface.router_ip in ('', None):
        # No routes available.
        return []
    elif IPAddress(cluster_interface.ip).version == 4:
        return [
            {
                'network': '0.0.0.0',
                'netmask': '0.0.0.0',
                'gateway': unicode(cluster_interface.router_ip),
            },
            ]
    else:
        return [
            {
                'network': '::',
                'netmask': '::',
                'gateway': unicode(cluster_interface.router_ip),
            },
            ]


def generate_network_entry(network_interface, cluster_interface, ip=None):
    """Generate the `networks` list entry for the given network connection.

    :param network_interface: Name of the network interface (on the node) that
        connects to this network.
    :param cluster_interface: The `NodeGroupInterface` responsible for this
        network.  (Do not confuse its `interface` property, which is a network
        interface on the cluster controller, with the `network_interface`
        parameter which is a network interface on the node.)
    :param ip: Optional IP address.  If not given, use DHCP.
    """
    network_types = {
        4: 'ipv4',
        6: 'ipv6',
        }
    network = cluster_interface.network

    # Still lacking a few entries that we don't have enough information about:
    # * id -- does this need to match anything anywhere?
    # * network_id -- what is this, and how do we compose it?
    #
    # It's tempting to use cluster_interface.name for the 'id,' but that
    # could be confusing: it was probably generated based on the name of its
    # network interface on the cluster.  Which will probably often match the
    # name of the node cluster interface, but is completely unrelated to it.
    entry = {
        'link': network_interface,
        # The example we have does not show IPv6 netmasks.  Should we pass
        # width in bits?
        'type': network_types[network.version],
        'routes': generate_route_entries(cluster_interface)
        }
    if ip is not None:
        # Set static IP address.
        # How do we tell the node to request a dynamic IP address over DHCP?
        # Is just omitting ip_address the appropriate behaviour?
        if network.version == 4:
            entry['ip_address'] = ip
        else:
            # Include network size directly in IPv6 address.
            entry['ip_address'] = unicode(
                IPNetwork("%s/%s" % (ip, network.netmask)))
    if network.version == 4:
        entry['netmask'] = unicode(network.netmask)
    return entry


def generate_networking_config(node):
    """Generate a networking preseed for `node`.

    :param node: A `Node`.
    :return: A dict along the lines of the example in
        https://gist.github.com/jayofdoom/b035067523defec7fb53 -- just
        json-encode it to get a file in that format.
    """
    interfaces = extract_network_interfaces(node)
    return {
        'provider': "MAAS",
        'network_info': {
            'services': [
                generate_dns_server_entry(dns_server)
                for dns_server in list_dns_servers(node)
                ],
            'networks': [
                # Write network specs here.
                ],
            'links': [
                generate_ethernet_link_entry(interface, mac)
                for interface, mac in interfaces
                ],
            },
        }


def compose_debian_network_interfaces_ipv4_stanza(interface):
    """Return a Debian `/etc/network/interfaces` stanza for DHCPv4."""
    return "iface %s inet dhcp" % interface


def compose_debian_network_interfaces_ipv6_stanza(interface, ip, gateway=None):
    """Return a Debian `/etc/network/interfaces` stanza for IPv6.

    The stanza will configure a static address.
    """
    lines = [
        'iface %s inet6 static' % interface,
        '\tnetmask 64',
        '\taddress %s' % ip,
        ]
    if gateway is not None:
        lines.append('\tgateway %s' % gateway)
    return '\n'.join(lines)


def extract_mac_string(mac):
    """Return normalised MAC address string from `MACAddress` model object."""
    return normalise_mac(unicode(mac))


def add_ip_to_mapping(mapping, macaddress, ip):
    """Add IP address to a `defaultdict` keyed by MAC string.

    :param mapping: A `defaultdict` (defaulting to the empty set) mapping
        normalised MAC address strings to sets of `IPAddress`.
    :param macaddress: A `MACAddress`.
    :param ip: An IP address string.  If it is empty or `None`, it will not
        be added to the mapping.
    """
    if ip in (None, ''):
        return
    assert isinstance(ip, (unicode, bytes, IPAddress))
    mac = extract_mac_string(macaddress)
    ip = IPAddress(ip)
    mapping[mac].add(ip)


def extract_ip(mapping, mac, ip_version):
    """Extract IP address for `mac` and given IP version from `mapping`.

    :param mapping: A mapping as returned by `map_static_ips` or
        `map_gateways`.
    :param mac: A normalised MAC address string.
    :param ip_version: Either 4 or 6 (for IPv4 or IPv6 respectively).  Only a
        static address for this version will be returned.
    :return: A matching IP address, or `None`.
    """
    for ip in mapping[mac]:
        if ip.version == ip_version:
            return ip
    return None


def map_static_ips(node):
    """Return a `defaultdict` mapping node's MAC addresses to their static IPs.

    :param node: A `Node`.
    :return: A `defaultdict` (defaulting to the empty set) mapping normalised
        MAC address strings to sets of `IPAddress`.
    """
    mapping = defaultdict(set)
    for sip in StaticIPAddress.objects.filter(macaddress__node=node):
        for mac in sip.macaddress_set.all():
            add_ip_to_mapping(mapping, mac, sip.ip)
    return mapping


def map_gateways(node):
    """Return a `defaultdict` mapping node's MAC addresses to their gateways.

    :param node: A `Node`.
    :return: A `defaultdict` (defaulting to the empty set) mapping normalised
        MAC address strings to sets of `IPAddress`.
    """
    mapping = defaultdict(set)
    for mac in node.macaddress_set.all():
        for cluster_interface in mac.get_cluster_interfaces():
            if cluster_interface.manages_static_range():
                add_ip_to_mapping(mapping, mac, cluster_interface.router_ip)
    return mapping


def has_static_ipv6_address(mapping):
    """Does `mapping` contain an IPv6 address?

    :param mapping: A mapping as returned by `map_static_ips`.
    :return bool:
    """
    for ips in mapping.values():
        for ip in ips:
            if ip.version == 6:
                return True
    return False


def compose_debian_network_interfaces_file(node):
    """Return contents for a node's `/etc/network/interfaces` file."""
    static_ips = map_static_ips(node)
    # Should we disable IPv4 on this node?  For safety's sake, we won't do this
    # if the node has no static IPv6 addresses.  Otherwise it might become
    # accidentally unaddressable: it may have IPv6 addresses, but apart from
    # being able to guess autoconfigured addresses, we won't know what they
    # are.
    disable_ipv4 = (node.disable_ipv4 and has_static_ipv6_address(static_ips))
    gateways = map_gateways(node)
    stanzas = [
        'auto lo',
        ]
    for interface, mac in extract_network_interfaces(node):
        stanzas.append('auto %s' % interface)
        if not disable_ipv4:
            stanzas.append(
                compose_debian_network_interfaces_ipv4_stanza(interface))
        static_ipv6 = extract_ip(static_ips, mac, 6)
        if static_ipv6 is not None:
            gateway = extract_ip(gateways, mac, 6)
            stanzas.append(
                compose_debian_network_interfaces_ipv6_stanza(
                    interface, static_ipv6, gateway))
    return '%s\n' % '\n\n'.join(stanzas)


def compose_udev_equality(key, value):
    """Return a udev comparison clause, like `ACTION=="add"`."""
    assert key == key.upper()
    return '%s=="%s"' % (key, value)


def compose_udev_attr_equality(attribute, value):
    """Return a udev attribute comparison clause, like `ATTR{type}=="1"`."""
    assert attribute == attribute.lower()
    return 'ATTR{%s}=="%s"' % (attribute, value)


def compose_udev_setting(key, value):
    """Return a udev assignment clause, like `NAME="eth0"`."""
    assert key == key.upper()
    return '%s="%s"' % (key, value)


def compose_udev_rule(interface, mac):
    """Return a udev rule to set the name of network interface with `mac`.

    The rule ends up as a single line looking something like:

        SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*",
        ATTR{address}="ff:ee:dd:cc:bb:aa", NAME="eth0"

    (Note the difference between `=` and `==`: they both occur.)
    """
    rule = ', '.join([
        compose_udev_equality('SUBSYSTEM', 'net'),
        compose_udev_equality('ACTION', 'add'),
        compose_udev_equality('DRIVERS', '?*'),
        compose_udev_attr_equality('address', mac),
        compose_udev_setting('NAME', interface),
        ])
    return '%s\n' % rule


def compose_linux_udev_rules_file(interfaces):
    """Return text for a udev persistent-net rules file.

    These rules assign fixed names to network interfaces.  They ensure that
    the same network interface cards come up with the same interface names on
    every boot.  Otherwise, the kernel may assign interface names in different
    orders on every boot, and so network interfaces can "switch identities"
    every other time the machine reboots.

    :param interfaces: List of tuples of interface name and MAC address.
    :return: Text to write into a udev rules file.
    """
    rules = [
        compose_udev_rule(interface, mac)
        for interface, mac in interfaces
        ]
    return dedent("""\
        # MAAS-assigned network interface names.
        %s
        # End of MAAS-assigned network interface names.
        """) % '\n\n'.join(rules)
