import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    "crypto" + "-pair-research",
    "quant" + "-research",
)
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".mjs", ".txt"}


class CleanRoomTests(unittest.TestCase):
    def test_no_prohibited_framework_reference(self):
        violations = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            if ".git" in path.parts or "runtime" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for token in FORBIDDEN:
                if token in text:
                    violations.append(f"{path.relative_to(ROOT)}: {token}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
