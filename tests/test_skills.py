from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class ProjectSkillTests(unittest.TestCase):
    def test_all_skill_packages_expose_the_expected_cli_contract(self):
        expected = {
            "goodidea-capture-flash": ["capture start", "capture append", "capture propose", "capture finalize", "capture flash", "不在 Frontmatter 保存 `summary`"],
            "goodidea-record-literature": ["source preview", "--local-file", ".markdown", "source commit", "--attach-flash-ids", "source refresh", "--confirm-proposal", "不创建文献笔记层", "不写内容摘要或 `summary` 元数据"],
            "goodidea-review-process": ["goodidea --root <仓库> review", "动态标记陈旧闪念"],
            "goodidea-form-permanent": ["permanent propose", "--draft-file", "一次一个问题", "审查标准", "完整待确认草稿", "--confirm-user-approved-structure", "--confirm-user-approved-sources", "--direct-source-file", "--confirm-user-approved", "permanent withdraw"],
            "goodidea-connect-cards": ["connect propose", "connect accept", "当前无需新增语义连接"],
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
        self.assertIn("用户正在表达或展开想法时立即交给 goodidea-capture-flash", literature)
        capture = (skills_root / "goodidea-capture-flash" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("任何新表达都会使旧候选失效", capture)
        self.assertIn("不自动进入永久卡片", capture)
        review_process = (skills_root / "goodidea-review-process" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("来源快照不是待加工的认知材料", review_process)
        permanent = (skills_root / "goodidea-form-permanent" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("提炼一个典型标题", permanent)
        self.assertIn("不得补入用户未表达的内容", permanent)
        self.assertIn("不一次抛出问题清单", permanent)
        connect = (skills_root / "goodidea-connect-cards" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("等待明确确认", connect)
        self.assertIn("当前无需新增语义连接", connect)
        self.assertIn("不调用 `connect propose`", connect)


if __name__ == "__main__":
    unittest.main()
