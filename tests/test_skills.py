from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class ProjectSkillTests(unittest.TestCase):
    def test_all_seven_skill_packages_expose_the_expected_cli_contract(self):
        expected = {
            "goodidea-capture-flash": ["capture flash", "interesting", "todo"],
            "goodidea-record-literature": ["source preview", "source commit"],
            "goodidea-review-process": ["goodidea --root <仓库> review", "review --expire"],
            "goodidea-form-permanent": ["permanent propose", "permanent", "mother", "action", "index"],
            "goodidea-review-permanent": ["permanent accept", "用户原话"],
            "goodidea-connect-cards": ["connect propose", "connect accept"],
            "goodidea-lint": ["goodidea --root <仓库> lint", "goodidea --root <仓库> verify"],
        }
        skills_root = PROJECT / ".agents" / "skills"
        discovered = {path.name for path in skills_root.iterdir() if path.is_dir()}
        self.assertEqual(discovered, set(expected))

        for name, markers in expected.items():
            with self.subTest(skill=name):
                skill_file = skills_root / name / "SKILL.md"
                agent_file = skills_root / name / "agents" / "openai.yaml"
                self.assertTrue(skill_file.is_file())
                self.assertTrue(agent_file.is_file())
                skill = skill_file.read_text(encoding="utf-8")
                agent = agent_file.read_text(encoding="utf-8")
                self.assertRegex(skill, rf"(?m)^name:\s*{re.escape(name)}$")
                self.assertRegex(skill, r"(?m)^description:\s*.+$")
                self.assertIn("uv run goodidea", skill)
                self.assertIn(f"${name}", agent)
                for marker in markers:
                    self.assertIn(marker, skill)

        literature = (skills_root / "goodidea-record-literature" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("预读阶段禁止写 Good idea 仓库", literature)
        self.assertIn("用户未回答或放弃时停止，不调用任何写命令", literature)
        permanent = (skills_root / "goodidea-form-permanent" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("不要直接接受候选", permanent)
        review = (skills_root / "goodidea-review-permanent" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("纯确认无效", review)
        connect = (skills_root / "goodidea-connect-cards" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("等待明确确认", connect)


if __name__ == "__main__":
    unittest.main()
