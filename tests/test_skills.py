from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class ProjectSkillTests(unittest.TestCase):
    def test_all_seven_skill_packages_expose_the_expected_cli_contract(self):
        expected = {
            "goodidea-capture-flash": ["capture flash", "interesting", "todo", "不在 Frontmatter 保存 `summary`"],
            "goodidea-record-literature": ["source preview", "--local-file", ".markdown", "source commit", "source refresh", "--confirm-proposal", "不创建文献笔记层", "不写内容摘要或 `summary` 元数据"],
            "goodidea-review-process": ["goodidea --root <仓库> review", "review --expire"],
            "goodidea-form-permanent": ["permanent propose", "--draft-file", "一次一个问题", "--confirm-user-approved-structure", "--confirm-user-approved", "permanent withdraw"],
            "goodidea-review-permanent": ["permanent accept", "不生成正文候选内容", "完整待确认草稿", "每轮只提出一个"],
            "goodidea-connect-cards": ["connect propose", "connect accept", "零连接节点"],
            "goodidea-lint": ["goodidea --root <仓库> lint", "goodidea --root <仓库> verify", "goodidea maintain metadata"],
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
        self.assertIn("人的即时观点、疑问和念头只写入闪念空间", literature)
        self.assertIn("随手粘贴的无链接摘录改用 goodidea-capture-flash", literature)
        self.assertIn("本地 PDF 报告为 v0.1 不支持", literature)
        self.assertIn("不保存绝对路径，也不伪造 URL", literature)
        review_process = (skills_root / "goodidea-review-process" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("来源快照不是待加工的认知材料", review_process)
        permanent = (skills_root / "goodidea-form-permanent" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("提炼一个典型标题", permanent)
        self.assertIn("不得补入用户未表达的内容", permanent)
        self.assertIn("不一次抛出问题清单", permanent)
        review = (skills_root / "goodidea-review-permanent" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("审查意见只留在审查对话", review)
        self.assertIn("不是用户主动发起创建", review)
        connect = (skills_root / "goodidea-connect-cards" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("等待明确确认", connect)
        self.assertIn("已入网，当前零连接", connect)
        self.assertIn("不调用 `connect propose`", connect)


if __name__ == "__main__":
    unittest.main()
