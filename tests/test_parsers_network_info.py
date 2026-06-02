import unittest

from appband.parsers.network_info import (
    parse_default_interface,
    parse_airport_ssid,
    parse_ifconfig,
    parse_ipconfig_summary,
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


class ParseIpconfigSummaryTest(unittest.TestCase):
    def test_extracts_ssid_and_interface_type(self):
        text = (
            "  Network Service : Wi-Fi\n"
            "  BSSID : aa:bb:cc:dd:ee:ff\n"
            "  InterfaceType : WiFi\n"
            "  SSID : sylwen 5GHZ\n"
            "  Security : WPA2 Personal\n"
        )
        r = parse_ipconfig_summary(text)
        self.assertEqual(r["ssid"], "sylwen 5GHZ")
        self.assertEqual(r["interface_type"], "WiFi")

    def test_redacted_ssid_treated_as_none(self):
        text = "  InterfaceType : WiFi\n  SSID : <redacted>\n"
        r = parse_ipconfig_summary(text)
        self.assertIsNone(r["ssid"])
        self.assertEqual(r["interface_type"], "WiFi")

    def test_ethernet_interface(self):
        text = "  InterfaceType : Ethernet\n"
        r = parse_ipconfig_summary(text)
        self.assertIsNone(r["ssid"])
        self.assertEqual(r["interface_type"], "Ethernet")

    def test_empty_input(self):
        self.assertEqual(parse_ipconfig_summary(""), {"ssid": None, "interface_type": None})


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

    def test_wifi_when_interface_type_says_wifi_without_ssid(self):
        # SSID redacted but InterfaceType says WiFi -> still wifi
        self.assertEqual(
            classify_link_type(interface="en0", ssid=None, media="", interface_type="WiFi"),
            "wifi",
        )

    def test_iphone_hotspot_via_interface_type_plus_ssid(self):
        self.assertEqual(
            classify_link_type(interface="en0", ssid="iPhone", media="", interface_type="WiFi"),
            "iphone-hotspot",
        )

    def test_vpn_when_tunnel_interface(self):
        # A VPN's default route is a utun/ipsec/ppp device; it used to fall
        # through to "ethernet", silently corrupting by-network grouping.
        for iface in ("utun4", "ipsec0", "ppp0"):
            self.assertEqual(
                classify_link_type(interface=iface, ssid=None, media="", interface_type=None),
                "vpn",
            )

    def test_iphone_hotspot_by_subnet_when_ssid_redacted(self):
        # macOS 14+ redacts the SSID from the headless collector daemon, so the
        # name-pattern heuristic can't catch a hotspot. iPhone Personal Hotspot
        # always hands out 172.20.10.0/28 — classify by subnet regardless of SSID.
        self.assertEqual(
            classify_link_type(interface="en0", ssid=None, media="", interface_type="WiFi", ip_address="172.20.10.3"),
            "iphone-hotspot",
        )

    def test_iphone_hotspot_subnet_wins_over_usb_media(self):
        # iPhone tethered over USB also uses 172.20.10.0/28; the iPhone subnet
        # is more specific than the generic USB-media -> usb-tether default.
        self.assertEqual(
            classify_link_type(interface="en6", ssid=None, media="autoselect (USB 10/100/1000)", ip_address="172.20.10.2"),
            "iphone-hotspot",
        )

    def test_iphone_hotspot_subnet_boundaries(self):
        # 172.20.10.0/28 spans .0-.15 (gateway .1, clients .2-.14, broadcast .15).
        for ip in ("172.20.10.1", "172.20.10.14", "172.20.10.15"):
            self.assertEqual(
                classify_link_type(interface="en0", ssid=None, media="", interface_type="WiFi", ip_address=ip),
                "iphone-hotspot",
            )

    def test_ips_outside_iphone_subnet_stay_wifi(self):
        # Home wifi, the adjacent-but-outside 172.20.11.x, and an Android-hotspot
        # IP must NOT be misread as an iPhone hotspot.
        for ip in ("192.168.0.116", "172.20.11.1", "10.116.186.1"):
            self.assertEqual(
                classify_link_type(interface="en0", ssid=None, media="", interface_type="WiFi", ip_address=ip),
                "wifi",
            )

    def test_invalid_ip_falls_through(self):
        self.assertEqual(
            classify_link_type(interface="en0", ssid=None, media="", interface_type="WiFi", ip_address="not-an-ip"),
            "wifi",
        )


class ParseNetworkInfoFixtureTest(unittest.TestCase):
    def _fix(self, name):
        from pathlib import Path
        return (Path(__file__).parent / "fixtures" / name).read_text()

    def test_route_default_fixture(self):
        self.assertEqual(parse_default_interface(self._fix("route_default.txt")), "en0")

    def test_ipconfig_summary_fixture(self):
        r = parse_ipconfig_summary(self._fix("ipconfig_summary_en0.txt"))
        self.assertEqual(r["ssid"], "sylwen 5GHZ")
        self.assertEqual(r["interface_type"], "WiFi")

    def test_ifconfig_fixture(self):
        r = parse_ifconfig(self._fix("ifconfig_en0.txt"))
        self.assertEqual(r["ip_address"], "192.168.0.116")
        self.assertEqual(r["media"], "autoselect")


if __name__ == "__main__":
    unittest.main()
