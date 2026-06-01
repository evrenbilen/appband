import json
import unittest
from pathlib import Path

_LOCALES = Path(__file__).parent.parent / "appband" / "web" / "locales"


class LocaleParityTest(unittest.TestCase):
    def _keys(self, name):
        return set(json.loads((_LOCALES / name).read_text()))

    def test_en_tr_have_identical_keys(self):
        # Guards against a half-translated UI (a key added to one locale only
        # silently falls back to the raw key string in the other).
        en, tr = self._keys("en.json"), self._keys("tr.json")
        self.assertEqual(
            en, tr, f"locale key mismatch — en-only={en - tr}, tr-only={tr - en}"
        )


if __name__ == "__main__":
    unittest.main()
