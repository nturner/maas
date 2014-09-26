# Copyright 2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for networking preseed code."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    ]

from collections import defaultdict
from random import randint
from textwrap import dedent

from maasserver import networking_preseed
from maasserver.dns import zonegenerator
from maasserver.enum import (
    NODEGROUP_STATUS,
    NODEGROUPINTERFACE_MANAGEMENT,
    )
from maasserver.exceptions import UnresolvableHost
from maasserver.networking_preseed import (
    add_ip_to_mapping,
    compose_debian_network_interfaces_file,
    compose_debian_network_interfaces_ipv4_stanza,
    compose_debian_network_interfaces_ipv6_stanza,
    compose_linux_udev_rules_file,
    extract_mac_string,
    extract_network_interfaces,
    generate_dns_server_entry,
    generate_ethernet_link_entry,
    generate_network_entry,
    generate_networking_config,
    generate_route_entries,
    has_static_ipv6_address,
    list_dns_servers,
    map_gateways,
    map_static_ips,
    normalise_mac,
    )
import maasserver.networking_preseed as networking_preseed_module
from maasserver.testing.factory import factory
from maasserver.testing.testcase import MAASServerTestCase
from maastesting.matchers import MockCalledOnceWith
from mock import ANY
from netaddr import IPAddress
from testtools.matchers import HasLength


def make_denormalised_mac():
    return ' %s ' % factory.make_mac_address().upper()


class TestExtractNetworkInterfaces(MAASServerTestCase):

    def test__returns_nothing_if_no_lshw_output_found(self):
        node = factory.make_Node()
        self.assertEqual([], extract_network_interfaces(node))

    def test__returns_nothing_if_no_network_description_found_in_lshw(self):
        node = factory.make_Node()
        lshw_output = """
            <list xmlns:lldp="lldp" xmlns:lshw="lshw">
              <lshw:list>
              </lshw:list>
            </list>
            """
        factory.make_NodeResult_for_commissioning(
            node=node, name='00-maas-01-lshw.out', script_result=0,
            data=lshw_output.encode('ascii'))
        self.assertEqual([], extract_network_interfaces(node))

    def test__extracts_interface_data(self):
        node = factory.make_Node()
        interface = factory.make_name('eth')
        mac = factory.make_mac_address()
        lshw_output = """
            <node id="network" claimed="true" class="network">
             <logicalname>%(interface)s</logicalname>
             <serial>%(mac)s</serial>
            </node>
            """ % {'interface': interface, 'mac': mac}
        factory.make_NodeResult_for_commissioning(
            node=node, name='00-maas-01-lshw.out', script_result=0,
            data=lshw_output.encode('ascii'))
        self.assertEqual([(interface, mac)], extract_network_interfaces(node))

    def test__finds_network_interface_on_motherboard(self):
        node = factory.make_Node()
        interface = factory.make_name('eth')
        mac = factory.make_mac_address()
        # Stripped-down version of real lshw output:
        lshw_output = """
            <!-- generated by lshw-B.02.16 -->
            <list>
            <node id="mynode" claimed="true" class="system" handle="DMI:0002">
              <node id="core" claimed="true" class="bus" handle="DMI:0003">
               <description>Motherboard</description>
                <node id="pci" claimed="true" class="bridge" \
                      handle="PCIBUS:0000:00">
                 <description>Host bridge</description>
                  <node id="network" claimed="true" class="network" \
                      handle="PCI:0000:00:19.0">
                   <description>Ethernet interface</description>
                   <product>82566DM-2 Gigabit Network Connection</product>
                   <vendor>Intel Corporation</vendor>
                   <logicalname>%(interface)s</logicalname>
                   <serial>%(mac)s</serial>
                   <configuration>
                    <setting id="ip" value="10.99.99.1" />
                   </configuration>
                  </node>
                </node>
              </node>
            </node>
            </list>
            """ % {'interface': interface, 'mac': mac}
        factory.make_NodeResult_for_commissioning(
            node=node, name='00-maas-01-lshw.out', script_result=0,
            data=lshw_output.encode('ascii'))
        self.assertEqual([(interface, mac)], extract_network_interfaces(node))

    def test__finds_network_interface_on_pci_bus(self):
        node = factory.make_Node()
        interface = factory.make_name('eth')
        mac = factory.make_mac_address()
        # Stripped-down version of real lshw output:
        lshw_output = """
            <!-- generated by lshw-B.02.16 -->
            <list>
            <node id="mynode" claimed="true" class="system" handle="DMI:0002">
              <node id="core" claimed="true" class="bus" handle="DMI:0003">
               <description>Motherboard</description>
                <node id="pci" claimed="true" class="bridge" \
                    handle="PCIBUS:0000:00">
                 <description>Host bridge</description>
                  <node id="pci:2" claimed="true" class="bridge" \
                      handle="PCIBUS:0000:07">
                   <description>PCI bridge</description>
                    <node id="network" claimed="true" class="network" \
                        handle="PCI:0000:07:04.0">
                     <description>Ethernet interface</description>
                     <logicalname>%(interface)s</logicalname>
                     <serial>%(mac)s</serial>
                     <configuration>
                      <setting id="ip" value="192.168.1.114" />
                     </configuration>
                    </node>
                  </node>
                </node>
              </node>
            </node>
            </list>
            """ % {'interface': interface, 'mac': mac}
        factory.make_NodeResult_for_commissioning(
            node=node, name='00-maas-01-lshw.out', script_result=0,
            data=lshw_output.encode('ascii'))
        self.assertEqual([(interface, mac)], extract_network_interfaces(node))

    def test__ignores_nodes_without_interface_name(self):
        node = factory.make_Node()
        mac = factory.make_mac_address()
        lshw_output = """
            <node id="network" claimed="true" class="network">
             <serial>%s</serial>
            </node>
            """ % mac
        factory.make_NodeResult_for_commissioning(
            node=node, name='00-maas-01-lshw.out', script_result=0,
            data=lshw_output.encode('ascii'))
        self.assertEqual([], extract_network_interfaces(node))

    def test__ignores_nodes_without_mac(self):
        node = factory.make_Node()
        interface = factory.make_name('eth')
        lshw_output = """
            <node id="network" claimed="true" class="network">
             <logicalname>%s</logicalname>
            </node>
            """ % interface
        factory.make_NodeResult_for_commissioning(
            node=node, name='00-maas-01-lshw.out', script_result=0,
            data=lshw_output.encode('ascii'))
        self.assertEqual([], extract_network_interfaces(node))

    def test__normalises_mac(self):
        node = factory.make_Node()
        interface = factory.make_name('eth')
        mac = make_denormalised_mac()
        self.assertNotEqual(normalise_mac(mac), mac)
        lshw_output = """
            <node id="network" claimed="true" class="network">
             <logicalname>%(interface)s</logicalname>
             <serial>%(mac)s</serial>
            </node>
            """ % {'interface': interface, 'mac': mac}
        factory.make_NodeResult_for_commissioning(
            node=node, name='00-maas-01-lshw.out', script_result=0,
            data=lshw_output.encode('ascii'))
        [entry] = extract_network_interfaces(node)
        _, extracted_mac = entry
        self.assertEqual(normalise_mac(mac), extracted_mac)


class TestNormaliseMAC(MAASServerTestCase):

    def test__normalises_case(self):
        mac = factory.make_mac_address()
        self.assertEqual(
            normalise_mac(mac.lower()),
            normalise_mac(mac.upper()))

    def test__strips_whitespace(self):
        mac = factory.make_mac_address()
        self.assertEqual(
            normalise_mac(mac),
            normalise_mac(' %s ' % mac))

    def test__is_idempotent(self):
        mac = factory.make_mac_address()
        self.assertEqual(
            normalise_mac(mac),
            normalise_mac(normalise_mac(mac)))


class TestGenerateEthernetLinkEntry(MAASServerTestCase):

    def test__generates_dict(self):
        interface = factory.make_name('eth')
        mac = factory.make_mac_address()
        self.assertEqual(
            {
                'id': interface,
                'type': 'phy',
                'ethernet_mac_address': mac,
            },
            generate_ethernet_link_entry(interface, mac))


class TestGenerateDNServerEntry(MAASServerTestCase):

    def test__returns_dict(self):
        address = factory.make_ipv4_address()
        self.assertEqual(
            {
                'type': 'dns',
                'address': address,
            },
            generate_dns_server_entry(address))


def patch_dns_servers(testcase, ipv4_dns=None, ipv6_dns=None):
    """Patch `get_dns_server_address` to return the given addresses.

    The fake will return `ipv4_dns` or `ipv6_dns` as appropriate to the
    arguments.  For that reason, this patch does not use a `Mock`.
    """

    def fake_get_maas_facing_server_address(cluster, ipv4=True, ipv6=True):
        result = None
        if ipv4:
            result = ipv4_dns
        if result is None and ipv6:
            result = ipv6_dns
        if result is None:
            raise UnresolvableHost()
        return result

    testcase.patch(
        zonegenerator, 'get_maas_facing_server_address',
        fake_get_maas_facing_server_address)
    testcase.patch(zonegenerator, 'warn_loopback')


class ListDNSServers(MAASServerTestCase):

    def test__includes_ipv4_and_ipv6_by_default(self):
        ipv4_dns = factory.make_ipv4_address()
        ipv6_dns = factory.make_ipv6_address()
        patch_dns_servers(self, ipv4_dns=ipv4_dns, ipv6_dns=ipv6_dns)
        node = factory.make_Node(disable_ipv4=False)
        self.assertItemsEqual([ipv4_dns, ipv6_dns], list_dns_servers(node))

    def test__omits_ipv4_if_disabled_for_node(self):
        ipv4_dns = factory.make_ipv4_address()
        ipv6_dns = factory.make_ipv6_address()
        patch_dns_servers(self, ipv4_dns=ipv4_dns, ipv6_dns=ipv6_dns)
        node = factory.make_Node(disable_ipv4=True)
        self.assertItemsEqual([ipv6_dns], list_dns_servers(node))

    def test__omits_ipv4_if_unvailable(self):
        ipv6_dns = factory.make_ipv6_address()
        patch_dns_servers(self, ipv6_dns=ipv6_dns)
        node = factory.make_Node(disable_ipv4=False)
        self.assertItemsEqual([ipv6_dns], list_dns_servers(node))

    def test__omits_ipv6_if_unavailable(self):
        ipv4_dns = factory.make_ipv4_address()
        patch_dns_servers(self, ipv4_dns=ipv4_dns)
        node = factory.make_Node(disable_ipv4=False)
        self.assertItemsEqual([ipv4_dns], list_dns_servers(node))


def make_cluster_interface(network=None, **kwargs):
    return factory.make_NodeGroupInterface(
        factory.make_NodeGroup(), network=network, **kwargs)


class TestGenerateRouteEntries(MAASServerTestCase):

    def test__generates_IPv4_default_route_if_available(self):
        network = factory.make_ipv4_network()
        router = factory.pick_ip_in_network(network)
        cluster_interface = make_cluster_interface(network, router_ip=router)
        self.assertEqual(
            [
                {
                    'network': '0.0.0.0',
                    'netmask': '0.0.0.0',
                    'gateway': unicode(router),
                },
            ],
            generate_route_entries(cluster_interface))

    def test__generates_IPv6_default_route_if_available(self):
        network = factory.make_ipv6_network()
        router = factory.pick_ip_in_network(network)
        cluster_interface = make_cluster_interface(network, router_ip=router)
        self.assertEqual(
            [
                {
                    'network': '::',
                    'netmask': '::',
                    'gateway': unicode(router),
                },
            ],
            generate_route_entries(cluster_interface))

    def test__generates_empty_list_if_no_route_available(self):
        network = factory.make_ipv4_network()
        cluster_interface = make_cluster_interface(
            network, management=NODEGROUPINTERFACE_MANAGEMENT.UNMANAGED,
            router_ip='')
        self.assertEqual([], generate_route_entries(cluster_interface))


class TestGenerateNetworkEntry(MAASServerTestCase):

    def test__generates_IPv4_dict(self):
        network = factory.make_ipv4_network()
        network_interface = factory.make_name('eth')
        cluster_interface = make_cluster_interface(network)
        ip = factory.pick_ip_in_network(network)

        entry = generate_network_entry(
            network_interface, cluster_interface, ip=ip)

        del entry['routes']
        self.assertEqual(
            {
                'type': 'ipv4',
                'link': network_interface,
                'ip_address': unicode(ip),
                'netmask': unicode(network.netmask),
            },
            entry)

    def test__generates_IPv6_dict(self):
        slash = randint(48, 64)
        network = factory.make_ipv6_network(slash=slash)
        network_interface = factory.make_name('eth')
        cluster_interface = make_cluster_interface(network)
        ip = factory.pick_ip_in_network(network)

        entry = generate_network_entry(
            network_interface, cluster_interface, ip=ip)

        del entry['routes']
        self.assertEqual(
            {
                'type': 'ipv6',
                'link': network_interface,
                'ip_address': '%s/%d' % (ip, slash),
            },
            entry)

    def test__omits_IP_if_not_given(self):
        network = factory.make_ipv4_network()
        network_interface = factory.make_name('eth')
        cluster_interface = make_cluster_interface(network)

        entry = generate_network_entry(network_interface, cluster_interface)

        del entry['routes']
        self.assertEqual(
            {
                'type': 'ipv4',
                'link': network_interface,
                'netmask': unicode(network.netmask),
            },
            entry)

    def test__tells_IPv4_from_IPv6_even_without_IP(self):
        cluster_interface = make_cluster_interface(factory.make_ipv6_network())
        entry = generate_network_entry(
            factory.make_name('eth'), cluster_interface)
        self.assertEqual('ipv6', entry['type'])

    def test__includes_IPv4_routes_on_IPv4_network(self):
        network = factory.make_ipv4_network()
        router = factory.pick_ip_in_network(network)
        cluster_interface = make_cluster_interface(
            network, management=NODEGROUPINTERFACE_MANAGEMENT.DHCP,
            router_ip=router)

        entry = generate_network_entry(
            factory.make_name('eth'), cluster_interface)

        self.assertThat(entry['routes'], HasLength(1))
        [route] = entry['routes']
        self.assertEqual(unicode(router), route['gateway'])

    def test__includes_IPv6_routes_on_IPv6_network(self):
        network = factory.make_ipv6_network()
        router = factory.pick_ip_in_network(network)
        cluster_interface = make_cluster_interface(
            network, management=NODEGROUPINTERFACE_MANAGEMENT.DHCP,
            router_ip=router)

        entry = generate_network_entry(
            factory.make_name('eth'), cluster_interface)

        self.assertThat(entry['routes'], HasLength(1))
        [route] = entry['routes']
        self.assertEqual(unicode(router), route['gateway'])


class TestGenerateNetworkingConfig(MAASServerTestCase):

    def patch_interfaces(self, interface_mac_pairs):
        patch = self.patch_autospec(
            networking_preseed, 'extract_network_interfaces')
        patch.return_value = interface_mac_pairs
        return patch

    def test__returns_config_dict(self):
        self.patch_interfaces([])
        patch_dns_servers(self)
        config = generate_networking_config(factory.make_Node())
        self.assertIsInstance(config, dict)
        self.assertEqual("MAAS", config['provider'])

    def test__includes_links(self):
        patch_dns_servers(self)
        node = factory.make_Node()
        interface = factory.make_name('eth')
        mac = factory.make_mac_address()
        patch = self.patch_interfaces([(interface, mac)])

        config = generate_networking_config(node)

        self.assertThat(patch, MockCalledOnceWith(node))
        self.assertEqual(
            [
                {
                    'id': interface,
                    'type': 'phy',
                    'ethernet_mac_address': mac,
                },
            ],
            config['network_info']['links'])

    def test__includes_networks(self):
        # This section is not yet implemented, so expect an empty list.
        patch_dns_servers(self)
        self.patch_interfaces([])
        config = generate_networking_config(factory.make_Node())
        self.assertEqual([], config['network_info']['networks'])

    def test__includes_dns_servers(self):
        dns_address = factory.make_ipv4_address()
        patch_dns_servers(self, dns_address)
        self.patch_interfaces([])
        config = generate_networking_config(
            factory.make_Node(disable_ipv4=False))
        self.assertEqual(
            [
                {
                    'type': 'dns',
                    'address': dns_address,
                },
            ],
            config['network_info']['services'])


class TestComposeDebianNetworkInterfaceIPv4Stanza(MAASServerTestCase):

    def test__produces_dhcp_stanza(self):
        interface = factory.make_name('eth')
        expected = "iface %s inet dhcp" % interface
        self.assertEqual(
            expected.strip(),
            compose_debian_network_interfaces_ipv4_stanza(interface).strip())


class TestComposeDebianNetworkInterfacesIPv6Stanza(MAASServerTestCase):

    def test__produces_static_stanza(self):
        ip = factory.make_ipv6_address()
        interface = factory.make_name('eth')
        expected = dedent("""\
            iface %s inet6 static
            \tnetmask 64
            \taddress %s
            """) % (interface, ip)
        self.assertEqual(
            expected.strip(),
            compose_debian_network_interfaces_ipv6_stanza(
                interface, ip).strip())

    def test__includes_gateway_if_given(self):
        ip = factory.make_ipv6_address()
        interface = factory.make_name('eth')
        gateway = factory.make_ipv6_address()
        expected = dedent("""\
            iface %s inet6 static
            \tnetmask 64
            \taddress %s
            \tgateway %s
            """) % (interface, ip, gateway)
        self.assertEqual(
            expected.strip(),
            compose_debian_network_interfaces_ipv6_stanza(
                interface, ip, gateway).strip())


class TestExtractMACString(MAASServerTestCase):

    def test__returns_string(self):
        self.assertIsInstance(
            extract_mac_string(factory.make_MACAddress()),
            unicode)

    def test__returns_MAC_address(self):
        mac = factory.make_mac_address()
        self.assertEqual(
            normalise_mac(mac),
            extract_mac_string(factory.make_MACAddress(address=mac)))

    def test__works_even_if_mac_address_is_already_string(self):
        # The ORM normally presents MACAddress.mac_address as a MAC object.
        # But a string will work too.
        mac_string = factory.make_mac_address()
        mac = factory.make_MACAddress()
        mac.mac_address = mac_string
        self.assertIsInstance(mac.mac_address, unicode)
        self.assertEqual(normalise_mac(mac_string), extract_mac_string(mac))


class TestAddIPToMapping(MAASServerTestCase):

    def make_mapping(self):
        return defaultdict(set)

    def test__adds_to_empty_entry(self):
        mapping = self.make_mapping()
        mac = factory.make_MACAddress()
        ip = factory.make_ipv4_address()
        add_ip_to_mapping(mapping, mac, ip)
        self.assertEqual(
            {mac.mac_address: {IPAddress(ip)}},
            mapping)

    def test__adds_to_nonempty_entry(self):
        mapping = self.make_mapping()
        mac = factory.make_MACAddress()
        ip1 = factory.make_ipv4_address()
        add_ip_to_mapping(mapping, mac, ip1)
        ip2 = factory.make_ipv4_address()
        add_ip_to_mapping(mapping, mac, ip2)
        self.assertEqual(
            {mac.mac_address: {IPAddress(ip1), IPAddress(ip2)}},
            mapping)

    def test__does_not_add_None(self):
        mapping = self.make_mapping()
        mac = factory.make_MACAddress()
        add_ip_to_mapping(mapping, mac, None)
        self.assertEqual({}, mapping)

    def test__does_not_add_empty_string(self):
        mapping = self.make_mapping()
        mac = factory.make_MACAddress()
        add_ip_to_mapping(mapping, mac, '')
        self.assertEqual({}, mapping)


class TestMapStaticIPs(MAASServerTestCase):

    def test__returns_empty_if_none_found(self):
        self.assertEqual({}, map_static_ips(factory.make_Node()))

    def test__finds_IPv4_address(self):
        node = factory.make_Node()
        mac = factory.make_MACAddress(node=node)
        ip = factory.make_ipv4_address()
        factory.make_StaticIPAddress(ip=ip, mac=mac)
        self.assertEqual(
            {mac.mac_address: {IPAddress(ip)}},
            map_static_ips(node))

    def test__finds_IPv6_address(self):
        node = factory.make_Node()
        mac = factory.make_MACAddress(node=node)
        ip = factory.make_ipv6_address()
        factory.make_StaticIPAddress(ip=ip, mac=mac)
        self.assertEqual(
            {mac.mac_address: {IPAddress(ip)}},
            map_static_ips(node))

    def test__finds_addresses_on_multiple_MACs(self):
        node = factory.make_Node()
        mac1 = factory.make_MACAddress(node=node)
        mac2 = factory.make_MACAddress(node=node)
        ip1 = factory.make_ipv4_address()
        factory.make_StaticIPAddress(ip=ip1, mac=mac1)
        ip2 = factory.make_ipv4_address()
        factory.make_StaticIPAddress(ip=ip2, mac=mac2)
        self.assertEqual(
            {
                mac1.mac_address: {IPAddress(ip1)},
                mac2.mac_address: {IPAddress(ip2)},
            },
            map_static_ips(node))

    def test__finds_multiple_addresses_on_MAC(self):
        node = factory.make_Node()
        mac = factory.make_MACAddress(node=node)
        ipv4 = factory.make_ipv4_address()
        ipv6 = factory.make_ipv6_address()
        factory.make_StaticIPAddress(ip=ipv4, mac=mac)
        factory.make_StaticIPAddress(ip=ipv6, mac=mac)
        self.assertEqual(
            {mac.mac_address: {IPAddress(ipv4), IPAddress(ipv6)}},
            map_static_ips(node))


class TestMapGateways(MAASServerTestCase):

    def test__returns_empty_if_none_found(self):
        self.assertEqual({}, map_gateways(factory.make_Node()))

    def test__finds_IPv4_gateway(self):
        network = factory.make_ipv4_network(slash=24)
        gateway = factory.pick_ip_in_network(network)
        cluster = factory.make_NodeGroup(status=NODEGROUP_STATUS.ACCEPTED)
        cluster_interface = factory.make_NodeGroupInterface(
            cluster, network=network, router_ip=gateway,
            management=NODEGROUPINTERFACE_MANAGEMENT.DHCP)
        node = factory.make_Node(nodegroup=cluster)
        mac = factory.make_MACAddress(
            node=node, cluster_interface=cluster_interface)

        self.assertEqual(
            {mac.mac_address: {IPAddress(gateway)}},
            map_gateways(node))

    def test__finds_IPv6_gateway(self):
        network = factory.make_ipv6_network()
        gateway = factory.pick_ip_in_network(network)
        cluster = factory.make_NodeGroup(status=NODEGROUP_STATUS.ACCEPTED)
        net_interface = factory.make_name('eth')
        ipv4_interface = factory.make_NodeGroupInterface(
            cluster, interface=net_interface,
            management=NODEGROUPINTERFACE_MANAGEMENT.UNMANAGED)
        factory.make_NodeGroupInterface(
            cluster, network=network, router_ip=gateway,
            interface=net_interface,
            management=NODEGROUPINTERFACE_MANAGEMENT.DHCP)
        node = factory.make_Node(nodegroup=cluster)
        mac = factory.make_MACAddress(
            node=node, cluster_interface=ipv4_interface)

        self.assertEqual(
            {mac.mac_address: {IPAddress(gateway)}},
            map_gateways(node))

    def test__finds_gateways_on_multiple_MACs(self):
        cluster = factory.make_NodeGroup(status=NODEGROUP_STATUS.ACCEPTED)
        node = factory.make_Node(nodegroup=cluster)
        network1 = factory.make_ipv4_network(slash=24)
        gateway1 = factory.pick_ip_in_network(network1)
        cluster_interface1 = factory.make_NodeGroupInterface(
            cluster, network=network1, router_ip=gateway1,
            management=NODEGROUPINTERFACE_MANAGEMENT.DHCP)
        mac1 = factory.make_MACAddress(
            node=node, cluster_interface=cluster_interface1)
        network2 = factory.make_ipv4_network(slash=24)
        gateway2 = factory.pick_ip_in_network(network2)
        cluster_interface2 = factory.make_NodeGroupInterface(
            cluster, network=network2, router_ip=gateway2,
            management=NODEGROUPINTERFACE_MANAGEMENT.DHCP)
        mac2 = factory.make_MACAddress(
            node=node, cluster_interface=cluster_interface2)

        self.assertEqual(
            {
                mac1.mac_address: {IPAddress(gateway1)},
                mac2.mac_address: {IPAddress(gateway2)},
            },
            map_gateways(node))

    def test__finds_multiple_gateways_on_MAC(self):
        cluster = factory.make_NodeGroup(status=NODEGROUP_STATUS.ACCEPTED)
        net_interface = factory.make_name('eth')
        ipv4_network = factory.make_ipv4_network(slash=24)
        ipv4_gateway = factory.pick_ip_in_network(ipv4_network)
        ipv4_interface = factory.make_NodeGroupInterface(
            cluster, network=ipv4_network, router_ip=ipv4_gateway,
            interface=net_interface,
            management=NODEGROUPINTERFACE_MANAGEMENT.DHCP)
        ipv6_network = factory.make_ipv6_network()
        ipv6_gateway = factory.pick_ip_in_network(ipv6_network)
        factory.make_NodeGroupInterface(
            cluster, network=ipv6_network, router_ip=ipv6_gateway,
            interface=net_interface,
            management=NODEGROUPINTERFACE_MANAGEMENT.DHCP)
        node = factory.make_Node(nodegroup=cluster)
        mac = factory.make_MACAddress(
            node=node, cluster_interface=ipv4_interface)

        self.assertEqual(
            {
                mac.mac_address: {
                    IPAddress(ipv4_gateway),
                    IPAddress(ipv6_gateway),
                    },
            },
            map_gateways(node))


class TestHasStaticIPv6Address(MAASServerTestCase):

    def make_mapping(self):
        return defaultdict(set)

    def test__returns_False_for_empty_mapping(self):
        self.assertFalse(has_static_ipv6_address(self.make_mapping()))

    def test__finds_IPv6_address(self):
        mapping = self.make_mapping()
        add_ip_to_mapping(
            mapping, factory.make_MACAddress(), factory.make_ipv6_address())
        self.assertTrue(has_static_ipv6_address(mapping))

    def test__ignores_IPv4_address(self):
        mapping = self.make_mapping()
        add_ip_to_mapping(
            mapping, factory.make_MACAddress(), factory.make_ipv4_address())
        self.assertFalse(has_static_ipv6_address(mapping))

    def test__finds_IPv6_address_among_IPv4_addresses(self):
        mapping = self.make_mapping()
        add_ip_to_mapping(
            mapping, factory.make_MACAddress(), factory.make_ipv4_address())
        mac = factory.make_MACAddress()
        add_ip_to_mapping(mapping, mac, factory.make_ipv4_address())
        add_ip_to_mapping(mapping, mac, factory.make_ipv6_address())
        add_ip_to_mapping(mapping, mac, factory.make_ipv4_address())
        add_ip_to_mapping(
            mapping, factory.make_MACAddress(), factory.make_ipv4_address())
        self.assertTrue(has_static_ipv6_address(mapping))


class TestComposeDebianNetworkInterfacesFile(MAASServerTestCase):

    def patch_node_interfaces(self, interfaces):
        """Inject given network interfaces data into `node`.

        The network interfaces data should be an iterabl of tuples, each of
        an interface name and a MAC address.
        """
        fake = self.patch_autospec(
            networking_preseed_module, 'extract_network_interfaces')
        fake.return_value = [
            (interface, normalise_mac(mac))
            for interface, mac in interfaces
            ]

    def test__always_generates_lo(self):
        self.assertIn(
            'auto lo',
            compose_debian_network_interfaces_file(factory.make_Node()))

    def test__generates_DHCPv4_config_if_IPv4_not_disabled(self):
        interface = factory.make_name('eth')
        node = factory.make_node_with_mac_attached_to_nodegroupinterface(
            disable_ipv4=False)
        mac = node.get_primary_mac()
        ipv6_network = factory.make_ipv6_network()
        factory.make_NodeGroupInterface(
            node.nodegroup, network=ipv6_network,
            management=NODEGROUPINTERFACE_MANAGEMENT.DHCP)
        factory.make_StaticIPAddress(
            ip=factory.pick_ip_in_network(ipv6_network), mac=mac)
        self.patch_node_interfaces([(interface, mac.mac_address.get_raw())])

        self.assertIn(
            "\niface %s inet dhcp\n" % interface,
            compose_debian_network_interfaces_file(node))

    def test__generates_DHCPv4_config_if_no_IPv6_configured(self):
        interface = factory.make_name('eth')
        node = factory.make_node_with_mac_attached_to_nodegroupinterface(
            disable_ipv4=True)
        mac = node.get_primary_mac()
        self.patch_node_interfaces([(interface, mac.mac_address.get_raw())])
        self.assertIn(
            "\niface %s inet dhcp\n" % interface,
            compose_debian_network_interfaces_file(node))

    def test__generates_no_DHCPv4_config_if_node_should_use_IPv6_only(self):
        interface = factory.make_name('eth')
        ipv6_network = factory.make_ipv6_network()
        node = factory.make_node_with_mac_attached_to_nodegroupinterface(
            disable_ipv4=True)
        mac = node.get_primary_mac()
        factory.make_NodeGroupInterface(
            node.nodegroup, network=ipv6_network,
            management=NODEGROUPINTERFACE_MANAGEMENT.DHCP)
        factory.make_StaticIPAddress(
            ip=factory.pick_ip_in_network(ipv6_network), mac=mac)
        self.patch_node_interfaces([(interface, mac.mac_address.get_raw())])

        # The space is significant: this should not match the inet6 line!
        self.assertNotIn(
            " inet ",
            compose_debian_network_interfaces_file(node))

    def test__generates_static_IPv6_config(self):
        interface = factory.make_name('eth')
        ipv6_network = factory.make_ipv6_network()
        node = factory.make_node_with_mac_attached_to_nodegroupinterface()
        mac = node.get_primary_mac()
        factory.make_NodeGroupInterface(
            node.nodegroup, network=ipv6_network,
            management=NODEGROUPINTERFACE_MANAGEMENT.DHCP)
        factory.make_StaticIPAddress(
            ip=factory.pick_ip_in_network(ipv6_network), mac=mac)
        self.patch_node_interfaces([(interface, mac.mac_address.get_raw())])
        self.assertIn(
            "\niface %s inet6 static" % interface,
            compose_debian_network_interfaces_file(node))

    def test__passes_ip_and_gateway_when_creating_IPv6_stanza(self):
        interface = factory.make_name('eth')
        ipv6_network = factory.make_ipv6_network()
        node = factory.make_node_with_mac_attached_to_nodegroupinterface()
        [ipv4_interface] = node.nodegroup.nodegroupinterface_set.all()
        mac = node.get_primary_mac()
        gateway = factory.pick_ip_in_network(ipv6_network)
        factory.make_NodeGroupInterface(
            node.nodegroup, network=ipv6_network, router_ip=gateway,
            interface=ipv4_interface.interface,
            management=NODEGROUPINTERFACE_MANAGEMENT.DHCP)
        static_ipv6 = factory.pick_ip_in_network(ipv6_network)
        factory.make_StaticIPAddress(ip=static_ipv6, mac=mac)
        self.patch_node_interfaces([(interface, mac.mac_address.get_raw())])
        fake = self.patch_autospec(
            networking_preseed_module,
            'compose_debian_network_interfaces_ipv6_stanza')
        fake.return_value = factory.make_name('stanza')

        compose_debian_network_interfaces_file(node)

        self.assertThat(
            fake,
            MockCalledOnceWith(
                interface, IPAddress(static_ipv6), IPAddress(gateway)))

    def test__omits_gateway_if_not_set(self):
        interface = factory.make_name('eth')
        ipv6_network = factory.make_ipv6_network()
        node = factory.make_node_with_mac_attached_to_nodegroupinterface()
        [ipv4_interface] = node.nodegroup.nodegroupinterface_set.all()
        mac = node.get_primary_mac()
        factory.make_NodeGroupInterface(
            node.nodegroup, network=ipv6_network, router_ip='',
            interface=ipv4_interface.interface,
            management=NODEGROUPINTERFACE_MANAGEMENT.UNMANAGED)
        static_ipv6 = factory.pick_ip_in_network(ipv6_network)
        factory.make_StaticIPAddress(ip=static_ipv6, mac=mac)
        self.patch_node_interfaces([(interface, mac.mac_address.get_raw())])
        fake = self.patch_autospec(
            networking_preseed_module,
            'compose_debian_network_interfaces_ipv6_stanza')
        fake.return_value = factory.make_name('stanza')

        compose_debian_network_interfaces_file(node)

        self.assertThat(
            fake,
            MockCalledOnceWith(interface, ANY, None))

    def test__writes_auto_lines(self):
        interface = factory.make_name('eth')
        node = factory.make_node_with_mac_attached_to_nodegroupinterface()
        self.patch_node_interfaces(
            [(interface, node.get_primary_mac().mac_address.get_raw())])
        interfaces_file = compose_debian_network_interfaces_file(node)
        self.assertIn('auto %s' % interface, interfaces_file)
        self.assertEqual(1, interfaces_file.count('auto %s' % interface))


class TestComposeLinuxUdevRulesFile(MAASServerTestCase):

    def test__generates_udev_rule(self):
        interface = factory.make_name('eth')
        mac = factory.make_mac_address()
        expected_rule = (
            '\nSUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", '
            'ATTR{address}=="%(mac)s", NAME="%(interface)s"\n'
            ) % {'mac': mac, 'interface': interface}
        self.assertIn(
            expected_rule,
            compose_linux_udev_rules_file([(interface, mac)]))
