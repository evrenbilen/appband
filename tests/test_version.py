import re
import unittest
from pathlib import Path

import appband


class VersionTest(unittest.TestCase):
    def test_version_exists(self):
        self.assertTrue(hasattr(appband, "__version__"))

    def test_version_is_semver(self):
        self.assertRegex(appband.__version__, r"^\d+\.\d+\.\d+$")

    def test_readme_download_lines_match_version(self):
        # README is the single source seen by users; it must mirror the package
        # version so a release can't ship a stale download link. Matched by
        # regex (version-specific but tolerant of surrounding formatting).
        readme = (Path(__file__).parent.parent / "README.md").read_text()
        v = re.escape(appband.__version__)
        self.assertRegex(readme, rf"AppBand[ -]{v}\b")   # download mention
        self.assertRegex(readme, rf"AppBand-{v}\.dmg")    # install filename


if __name__ == "__main__":
    unittest.main()
