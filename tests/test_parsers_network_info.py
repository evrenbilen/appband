import unittest

from netmon.parsers.network_info import (
    parse_default_interface,
    parse_airport_ssid,
    parse_ifconfig,
    classify_link_type,
)


class ParseDefaultInterfaceTest(unittest.TestCase):
    def test_extracts_interface(self):
        text = (
            "   route to: default\n"
            "destination: default\n"
            "       mask: default\n"
            "    gateway: 192.168.1.1\n"
            "  interface: en0\n"
            "      flags: <UP,GATEWAY,DONE,STATIC,PRCLONING>\n"
        )
        self.assertEqual(parse_default_interface(text), "en0")

    def test_returns_none_when_no_route(self):
        self.assertIsNone(parse_default_interface("route: writing to socket: No such process\n"))


class ParseAirportSsidTest(unittest.TestCase):
    def test_extracts_ssid(self):
        self.assertEqual(
            parse_airport_ssid("Current Wi-Fi Network: Office-5G\n"),
            "Office-5G",
        )

    def test_returns_none_when_not_associated(self):
        self.assertIsNone(parse_airport_ssid("You are not associated with an AirPort network.\n"))

    def test_handles_ssid_with_colon(self):
        self.assertEqual(
            parse_airport_ssid("Current Wi-Fi Network: My:Weird:Name\n"),
            "My:Weird:Name",
        )


class ParseIfconfigTest(unittest.TestCase):
    def test_extracts_inet_and_ether(self):
        text = (
            "en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n"
            "\tether a4:83:e7:00:11:22\n"
            "\tinet6 fe80::aa:bb:cc:dd%en0 prefixlen 64 secured scopeid 0x4\n"
            "\tinet 192.168.1.42 netmask 0xffffff00 broadcast 192.168.1.255\n"
            "\tmedia: autoselect\n"
            "\tstatus: active\n"
        )
        result = parse_ifconfig(text)
        self.assertEqual(result["ip_address"], "192.168.1.42")
        self.assertEqual(result["mac"], "a4:83:e7:00:11:22")
        self.assertEqual(result["media"], "autoselect")
        self.assertEqual(result["status"], "active")


class ClassifyLinkTypeTest(unittest.TestCase):
    def test_wifi_when_ssid_present(self):
        self.assertEqual(
            classify_link_type(interface="en0", ssid="Office-5G", media=""),
            "wifi",
        )

    def test_iphone_hotspot_pattern(self):
        for ssid in ("iPhone", "Evren's iPhone", "Android-AP", "Galaxy S22"):
            self.assertEqual(
                classify_link_type(interface="en0", ssid=ssid, media=""),
                "iphone-hotspot",
            )

    def test_usb_tether_by_media(self):
        self.assertEqual(
            classify_link_type(interface="en6", ssid=None, media="autoselect (USB 10/100/1000)"),
            "usb-tether",
        )

    def test_ethernet_default(self):
        self.assertEqual(
            classify_link_type(interface="en0", ssid=None, media="autoselect (1000baseT <full-duplex>)"),
            "ethernet",
        )


if __name__ == "__main__":
    unittest.main()
