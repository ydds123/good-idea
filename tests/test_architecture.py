from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArchitectureTests(unittest.TestCase):
    def test_active_root_exposes_layers_not_legacy_product_spaces(self):
        for required in ("rules", "data", "skills", "kernel", "tests"):
            self.assertTrue((ROOT / required).is_dir(), required)
        for legacy in (
            "闪念空间",
            "溯源空间",
            "永久空间",
            "有意思空间",
            "待办空间",
            ".agents",
            "src",
        ):
            self.assertFalse((ROOT / legacy).exists(), legacy)

    def test_data_layer_contains_only_core_objects_and_events(self):
        actual = {path.name for path in (ROOT / "data/current").iterdir() if path.is_dir()}
        self.assertEqual(
            {"sessions", "flashes", "insights", "sources", "events"}, actual
        )

    def test_legacy_project_is_only_a_relative_read_only_reference(self):
        reference = json.loads(
            (ROOT / "data/legacy/reference.json").read_text(encoding="utf-8")
        )
        self.assertEqual("read_only_reference", reference["mode"])
        self.assertEqual("../../../good-idea", reference["project"])
        self.assertFalse(Path(reference["project"]).is_absolute())
        resolved = (ROOT / "data/legacy" / reference["project"]).resolve()
        self.assertEqual(ROOT.parent / "good-idea", resolved)
        self.assertTrue((resolved / ".git").is_dir())

    def test_no_skill_is_prematurely_implemented(self):
        self.assertEqual([], list((ROOT / "skills").rglob("SKILL.md")))


if __name__ == "__main__":
    unittest.main()
