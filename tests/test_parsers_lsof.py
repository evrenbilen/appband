import unittest

from appband.parsers.lsof import parse_lsof_connections

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


if __name__ == "__main__":
    unittest.main()
