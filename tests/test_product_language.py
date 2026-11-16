"""Static guard against non-product wording in UI, prompts, docs, and identifiers."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProductLanguageTest(unittest.TestCase):
    def test_no_external_context_in_project_sources(self):
        disallowed = (
            "국" + "비", "부트" + "캠프", "교" + "육기관",
            "Chat" + "GPT", "다른_" + "채팅", "Replit " + "Agent",
            "강" + "의", "외부_" + "과제", "졸" + "업작품",
        )
        extensions = {".py", ".md", ".json", ".yaml", ".sql", ".txt", ".toml", ".css"}
        violations = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in extensions or any(
                part in ("__pycache__", "data") for part in path.relative_to(ROOT).parts
            ):
                continue
            payload = path.read_text(encoding="utf-8")
            for phrase in disallowed:
                if phrase in str(path.relative_to(ROOT)) or phrase in payload:
                    violations.append(f"{path.relative_to(ROOT)}: {phrase}")
        self.assertEqual(violations, [], "Unexpected non-product wording found")


if __name__ == "__main__":
    unittest.main()
