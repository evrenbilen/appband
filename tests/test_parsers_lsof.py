import unittest
from pathlib import Path

from appband.parsers.lsof import _split_endpoint, parse_lsof_connections

SAMPLE = (
    "COMMAND     PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME\n"
    "Google     1234 evren   42u IPv4 0x1234567890abcd      0t0  TCP 192.168.1.42:54321->142.250.190.78:443 (ESTABLISHED)\n"
    "zoom.us    5678 evren   12u IPv4 0xaabbccddeeff0011    0t0  UDP 192.168.1.42:50001->18.234.10.20:8801\n"
    "Slack      9999 evren    8u IPv6 0x111122223333         0t0  TCP [::1]:12345->[::1]:6789 (ESTABLISHED)\n"
    "Local      1111 evren    9u IPv4 0x222233334444         0t0  TCP 127.0.0.1:5000 (LISTEN)\n"
    "Local2     2222 evren   10u IPv4 0x33334444             0t0  TCP 192.168.1.42:65000->192.168.1.1:53 (ESTABLISHED)\n"
)


class ParseLsofTest(unittest.TestCase):
    def test_returns_established_outbound_connections(self):
        rows = parse_lsof_connections(SAMPLE)
        names = {r["process_name"] for r in rows}
        self.assertIn("Google", names)
        self.assertIn("zoom.us", names)
        self.assertNotIn("Local", names)
        self.assertNotIn("Slack", names)

    def test_extracts_fields(self):
        rows = parse_lsof_connections(SAMPLE)
        google = next(r for r in rows if r["process_name"] == "Google")
        self.assertEqual(google["pid"], 1234)
        self.assertEqual(google["remote_ip"], "142.250.190.78")
        self.assertEqual(google["remote_port"], 443)
        self.assertEqual(google["protocol"], "tcp")

    def test_udp_protocol(self):
        rows = parse_lsof_connections(SAMPLE)
        zoom = next(r for r in rows if r["process_name"] == "zoom.us")
        self.assertEqual(zoom["protocol"], "udp")

    def test_skips_listen_rows(self):
        rows = parse_lsof_connections(SAMPLE)
        for r in rows:
            self.assertNotEqual(r["process_name"], "Local")

    def test_classifies_scope_internet(self):
        rows = parse_lsof_connections(SAMPLE)
        google = next(r for r in rows if r["process_name"] == "Google")
        self.assertEqual(google["scope"], "internet")

    def test_classifies_scope_lan(self):
        rows = parse_lsof_connections(SAMPLE)
        local2 = next(r for r in rows if r["process_name"] == "Local2")
        self.assertEqual(local2["scope"], "lan")


SAMPLE_V6 = (
    "COMMAND     PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME\n"
    "Safari      501 evren   30u IPv6 0x1               0t0  TCP [2606:4700::1]:5000->[2607:f8b0::200e]:443 (ESTABLISHED)\n"
    "vpnd         88 evren    9u IPv6 0x2               0t0  TCP [fd00::1]:5000->[fd12:3456::99]:443 (ESTABLISHED)\n"
    "Mail         90 evren    4u IPv6 0x3               0t0  TCP [::1]:5000->[::1]:993 (ESTABLISHED)\n"
    "Web          99 evren    5u IPv6 0x4               0t0  TCP [fe80::a%en0]:5000->[2620:0:1::5%en0]:443 (ESTABLISHED)\n"
)


class ParseLsofIPv6Test(unittest.TestCase):
    def test_ipv6_endpoints_port_scope_and_zone_strip(self):
        rows = parse_lsof_connections(SAMPLE_V6)
        ips = {r["remote_ip"]: r for r in rows}
        # Global IPv6 kept with correct port + scope.
        self.assertIn("2607:f8b0::200e", ips)
        self.assertEqual(ips["2607:f8b0::200e"]["remote_port"], 443)
        self.assertEqual(ips["2607:f8b0::200e"]["scope"], "internet")
        # Unique-local (fd00::/8) is LAN.
        self.assertEqual(ips["fd12:3456::99"]["scope"], "lan")
        # Loopback dropped.
        self.assertNotIn("::1", ips)
        # Zone ids (%en0) must never be stored on the IP.
        self.assertFalse(any("%" in ip for ip in ips))
        self.assertIn("2620:0:1::5", ips)


class SplitEndpointTest(unittest.TestCase):
    def test_ipv4_host_port(self):
        self.assertEqual(_split_endpoint("1.2.3.4:443"), ("1.2.3.4", 443))

    def test_bracketed_ipv6(self):
        self.assertEqual(_split_endpoint("[2606:4700::1]:443"), ("2606:4700::1", 443))
        self.assertEqual(_split_endpoint("[fe80::a%en0]:22"), ("fe80::a", 22))

    def test_bare_ipv6_no_port_is_not_mangled(self):
        # macOS lsof brackets IPv6 when a port is present, so a bare multi-colon
        # token is an address with no port — must not be split on the last colon.
        self.assertEqual(_split_endpoint("2620:0:1::5"), ("2620:0:1::5", None))
        self.assertEqual(_split_endpoint("fe80::a%en0"), ("fe80::a", None))


class ParseLsofFixtureTest(unittest.TestCase):
    def test_real_capture_invariants(self):
        # The 30KB real macOS capture exercises quirks the inline samples don't.
        text = (Path(__file__).parent / "fixtures" / "lsof_i.txt").read_text()
        rows = parse_lsof_connections(text)
        self.assertGreater(len(rows), 0)
        for r in rows:
            self.assertTrue(r["process_name"])
            self.assertIsInstance(r["pid"], int)
            self.assertIn(r["protocol"], ("tcp", "udp"))
            self.assertIn(r["scope"], ("internet", "lan"))
            # No excluded address survives, no zone/bracket leaks onto the IP.
            self.assertNotIn("%", r["remote_ip"])
            self.assertNotIn("[", r["remote_ip"])
            self.assertNotEqual(r["remote_ip"], "::1")
            self.assertFalse(r["remote_ip"].startswith(("127.", "169.254.", "fe80")))
            if r["remote_port"] is not None:
                self.assertTrue(0 < r["remote_port"] <= 65535)


if __name__ == "__main__":
    unittest.main()
