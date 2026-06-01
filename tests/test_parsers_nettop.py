import unittest

from appband.parsers.nettop import parse_nettop


SYNTHETIC = (
    "time,,,,\n"
    "12:34:56.789012,,,,\n"
    ",bytes_in,bytes_out,,\n"
    "Google Chrome.12345,1234567,234567,,\n"
    "zoom.us.6789,4567890,234567,,\n"
    "kernel_task.0,100,200,,\n"
)


class ParseNettopTest(unittest.TestCase):
    def test_extracts_process_rows(self):
        rows = parse_nettop(SYNTHETIC)
        self.assertEqual(len(rows), 3)
        names = {r["process_name"] for r in rows}
        self.assertEqual(names, {"Google Chrome", "zoom.us", "kernel_task"})

    def test_extracts_pid_separately(self):
        rows = parse_nettop(SYNTHETIC)
        chrome = next(r for r in rows if r["process_name"] == "Google Chrome")
        self.assertEqual(chrome["pid"], 12345)
        self.assertEqual(chrome["bytes_in"], 1234567)
        self.assertEqual(chrome["bytes_out"], 234567)

    def test_skips_header_and_blank_rows(self):
        rows = parse_nettop("time,,,,\n,,,,\n")
        self.assertEqual(rows, [])

    def test_handles_process_name_with_dots(self):
        text = (
            ",bytes_in,bytes_out,,\n"
            "com.apple.WebKit.Networking.999,10,20,,\n"
        )
        rows = parse_nettop(text)
        self.assertEqual(rows[0]["process_name"], "com.apple.WebKit.Networking")
        self.assertEqual(rows[0]["pid"], 999)


class ParseNettopFixtureTest(unittest.TestCase):
    def test_real_capture_invariants(self):
        from pathlib import Path

        text = (Path(__file__).parent / "fixtures" / "nettop_sample.txt").read_text()
        rows = parse_nettop(text)
        self.assertGreater(len(rows), 0)
        names = set()
        for r in rows:
            self.assertTrue(r["process_name"])           # no header/column row leaked
            self.assertGreaterEqual(r["bytes_in"], 0)
            self.assertGreaterEqual(r["bytes_out"], 0)
            names.add(r["process_name"])
        self.assertNotIn("", names)
        self.assertNotIn("time", names)


if __name__ == "__main__":
    unittest.main()
