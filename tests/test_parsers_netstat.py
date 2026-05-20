import unittest
from pathlib import Path

from netmon.parsers.netstat import parse_netstat_ibn

FIXTURE = Path(__file__).parent / "fixtures" / "netstat_ibn.txt"


class ParseNetstatTest(unittest.TestCase):
    def test_returns_dict_keyed_by_interface(self):
        text = FIXTURE.read_text()
        result = parse_netstat_ibn(text)
        self.assertIsInstance(result, dict)
        self.assertIn("lo0", result)

    def test_aggregates_multiple_rows_per_interface(self):
        # netstat emits one row per address per iface; we want the Link# row
        # (the row whose Network starts with "<Link#"), which carries the
        # cumulative byte counters.
        text = FIXTURE.read_text()
        result = parse_netstat_ibn(text)
        for iface, stats in result.items():
            self.assertIn("bytes_in", stats)
            self.assertIn("bytes_out", stats)
            self.assertGreaterEqual(stats["bytes_in"], 0)
            self.assertGreaterEqual(stats["bytes_out"], 0)

    def test_synthetic_input(self):
        text = (
            "Name  Mtu   Network       Address            Ipkts Ierrs     Ibytes    Opkts Oerrs     Obytes  Coll\n"
            "lo0   16384 <Link#1>                            10     0        100       10     0        100     0\n"
            "en0   1500  <Link#4>      a4:83:e7:00:00:00    20     0        200       20     0        200     0\n"
            "en0   1500  192.168.1     192.168.1.42          0     0          0        0     0          0     0\n"
        )
        result = parse_netstat_ibn(text)
        self.assertEqual(result["lo0"]["bytes_in"], 100)
        self.assertEqual(result["lo0"]["bytes_out"], 100)
        self.assertEqual(result["en0"]["bytes_in"], 200)
        self.assertEqual(result["en0"]["bytes_out"], 200)

    def test_ignores_header_and_blanks(self):
        result = parse_netstat_ibn("Name  Mtu\n\n")
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
