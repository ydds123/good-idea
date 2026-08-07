from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "goodidea.cli", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


class GoodIdeaCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "vault"
        initialized = run_cli("init", str(self.root))
        self.assertEqual(initialized.returncode, 0, initialized.stderr)

    def tearDown(self):
        self.temp.cleanup()

    def test_init_capture_and_verify_public_commands(self):
        app = json.loads((self.root / ".obsidian/app.json").read_text(encoding="utf-8"))
        appearance = json.loads(
            (self.root / ".obsidian/appearance.json").read_text(encoding="utf-8")
        )
        plugins = json.loads(
            (self.root / ".obsidian/core-plugins.json").read_text(encoding="utf-8")
        )
        self.assertEqual(app["propertiesInDocument"], "hidden")
        self.assertEqual(app["attachmentFolderPath"], ".goodidea/assets")
        self.assertEqual(app["defaultViewMode"], "preview")
        self.assertEqual(app["newLinkFormat"], "absolute")
        self.assertFalse(app["showInlineTitle"])
        self.assertIn("goodidea", appearance["enabledCssSnippets"])
        self.assertFalse(plugins["sync"])
        self.assertTrue((self.root / ".obsidian/snippets/goodidea.css").is_file())
        tracked = subprocess.run(
            ["git", "ls-files", ".obsidian"], cwd=self.root, check=True,
            text=True, capture_output=True,
        ).stdout
        self.assertIn(".obsidian/app.json", tracked)
        self.assertIn(".obsidian/snippets/goodidea.css", tracked)
        (self.root / ".obsidian/workspace.json").write_text("{}\n", encoding="utf-8")
        ignored = subprocess.run(
            ["git", "check-ignore", ".obsidian/workspace.json"], cwd=self.root,
            check=False, text=True, capture_output=True,
        )
        self.assertEqual(ignored.returncode, 0)
        fresh_schema = (self.root / "schema.md").read_text(encoding="utf-8")
        self.assertIn("YYYY-MM-DD-标题.md", fresh_schema)
        self.assertIn("内部 ID", fresh_schema)
        self.assertIn("Obsidian", fresh_schema)

        captured = run_cli(
            "--root",
            str(self.root),
            "capture",
            "flash",
            "--text",
            "这是一条通过真实 CLI 入口捕捉的闪念",
            "--transaction-id",
            "cli-capture-1",
        )
        self.assertEqual(captured.returncode, 0, captured.stderr)
        result = json.loads(captured.stdout)
        self.assertTrue((self.root / result["result"]["path"]).is_file())
        path = Path(result["result"]["path"])
        self.assertRegex(path.name, r"^\d{4}-\d{2}-\d{2}-.+\.md$")
        self.assertNotIn(result["result"]["id"], path.name)

        maintained = run_cli(
            "--root",
            str(self.root),
            "maintain",
            "filenames",
            "--transaction-id",
            "cli-maintain-filenames-noop",
        )
        self.assertEqual(maintained.returncode, 0, maintained.stderr)
        self.assertTrue(json.loads(maintained.stdout)["result"]["no_change"])

        verified = run_cli("--root", str(self.root), "verify")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(verified.stdout)["ok"])

        app["alwaysUpdateLinks"] = False
        (self.root / ".obsidian/app.json").write_text(
            json.dumps(app, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        drifted = run_cli("--root", str(self.root), "verify")
        self.assertEqual(drifted.returncode, 1)
        self.assertIn("Obsidian 未启用自动更新链接", drifted.stdout)

    def test_preview_cannot_write_inside_repository(self):
        markdown = self.base / "article.md"
        markdown.write_text("# 标题\n\n正文内容足够用于预读。", encoding="utf-8")
        forbidden = self.root / ".goodidea" / "preview.json"
        preview = run_cli(
            "--root",
            str(self.root),
            "source",
            "preview",
            "--url",
            "https://example.com/article",
            "--markdown-file",
            str(markdown),
            "--title",
            "示例文章",
            "--output",
            str(forbidden),
        )
        self.assertEqual(preview.returncode, 2)
        error = json.loads(preview.stderr)
        self.assertEqual(error["error"]["code"], "validation_error")
        self.assertFalse(forbidden.exists())

    def test_source_gate_and_atomic_cli_commit(self):
        preview_file = self.base / "preview.json"
        preview_file.write_text(
            json.dumps(
                {
                    "url": "https://example.com/source",
                    "canonical_url": "https://example.com/source",
                    "title": "CLI 来源",
                    "author": "测试作者",
                    "published_at": "2026-08-04",
                    "markdown": "这是一段通过 CLI 保存的完整来源正文。",
                    "images": [],
                    "status": "complete",
                    "error": "",
                    "extractor": "test-cli",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        rejected = run_cli(
            "--root",
            str(self.root),
            "source",
            "commit",
            "--preview-file",
            str(preview_file),
            "--motivation",
            "确认",
            "--transaction-id",
            "cli-source-rejected",
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertFalse(any((self.root / "溯源空间").glob("*.md")))

        accepted = run_cli(
            "--root",
            str(self.root),
            "source",
            "commit",
            "--preview-file",
            str(preview_file),
            "--motivation",
            "我想用它验证命令行入口是否保持来源和个人动机的边界",
            "--transaction-id",
            "cli-source-accepted",
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        result = json.loads(accepted.stdout)["result"]
        self.assertTrue((self.root / result["source_path"]).is_file())
        self.assertTrue((self.root / result["flash_path"]).is_file())

        replay = run_cli(
            "--root",
            str(self.root),
            "source",
            "commit",
            "--preview-file",
            str(preview_file),
            "--motivation",
            "我想用它验证命令行入口是否保持来源和个人动机的边界",
            "--transaction-id",
            "cli-source-accepted",
        )
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertTrue(json.loads(replay.stdout)["idempotent"])

    def test_public_cli_covers_review_all_card_types_and_connections(self):
        preview_file = self.base / "cognition-preview.json"
        preview_file.write_text(
            json.dumps(
                {
                    "url": "https://example.com/cognition",
                    "canonical_url": "https://example.com/cognition",
                    "title": "认知系统来源",
                    "author": "测试作者",
                    "published_at": "2026-08-04",
                    "markdown": "系统必须把生成能力、人的判断和现实反馈连接起来。",
                    "images": [],
                    "status": "complete",
                    "error": "",
                    "extractor": "test-cli-lifecycle",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        source_commit = run_cli(
            "--root",
            str(self.root),
            "source",
            "commit",
            "--preview-file",
            str(preview_file),
            "--motivation",
            "我想检验系统是否真正连接了生成、判断与现实反馈",
            "--transaction-id",
            "cli-lifecycle-source",
        )
        self.assertEqual(source_commit.returncode, 0, source_commit.stderr)
        source_result = json.loads(source_commit.stdout)["result"]

        for kind, text, txid in [
            ("interesting", "这个外部现象值得以后比较", "cli-interesting"),
            ("todo", "以后检查一次真实使用反馈", "cli-todo"),
        ]:
            captured = run_cli(
                "--root",
                str(self.root),
                "capture",
                kind,
                "--text",
                text,
                "--transaction-id",
                txid,
            )
            self.assertEqual(captured.returncode, 0, captured.stderr)

        reviewed = run_cli("--root", str(self.root), "review")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        review_result = json.loads(reviewed.stdout)
        self.assertFalse(review_result["write"])
        self.assertGreaterEqual(review_result["count"], 1)

        permanent_draft = self.base / "permanent.md"
        permanent_body = """# 生成能力必须接受人的判断

生成数量不是价值，人的解释和现实反馈决定什么值得保留。

否则系统只会扩大噪声。格式维护可以自动化，价值判断不能自动接纳。
"""
        permanent_draft.write_text(permanent_body, encoding="utf-8")
        permanent_proposal = run_cli(
            "--root", str(self.root), "permanent", "propose",
            "--type", "permanent", "--draft-file", str(permanent_draft),
            "--source-ids", source_result["source_id"],
            "--from-ids", source_result["flash_id"],
            "--transaction-id", "cli-permanent-propose",
        )
        self.assertEqual(permanent_proposal.returncode, 0, permanent_proposal.stderr)
        permanent_proposal_id = json.loads(permanent_proposal.stdout)["result"][
            "proposal_id"
        ]
        rejected = run_cli(
            "--root", str(self.root), "permanent", "accept",
            "--proposal-id", permanent_proposal_id,
            "--transaction-id", "cli-permanent-rejected",
        )
        self.assertEqual(rejected.returncode, 2)
        permanent_accept = run_cli(
            "--root", str(self.root), "permanent", "accept",
            "--proposal-id", permanent_proposal_id,
            "--confirm-user-authored",
            "--transaction-id", "cli-permanent-accept",
        )
        self.assertEqual(permanent_accept.returncode, 0, permanent_accept.stderr)
        permanent_result = json.loads(permanent_accept.stdout)["result"]
        permanent_id = permanent_result["card_id"]
        formal_text = (self.root / permanent_result["card_path"]).read_text(encoding="utf-8")
        self.assertTrue(formal_text.endswith(permanent_body))
        self.assertNotIn("机器数据", formal_text)

        mother_draft = self.base / "mother.md"
        mother_draft.write_text(
            """# 怎样判断持续生成产生了价值

哪些可观察变化能区分认知增量与内容噪声？

这个问题需要跨来源和行动反复回答。我会持续观察判断和行动是否改善。
""",
            encoding="utf-8",
        )
        mother_proposal = run_cli(
            "--root", str(self.root), "permanent", "propose",
            "--type", "mother", "--draft-file", str(mother_draft),
            "--source-ids", source_result["source_id"],
            "--transaction-id", "cli-mother-propose",
        )
        self.assertEqual(mother_proposal.returncode, 0, mother_proposal.stderr)
        mother_proposal_id = json.loads(mother_proposal.stdout)["result"][
            "proposal_id"
        ]
        mother_accept = run_cli(
            "--root", str(self.root), "permanent", "accept",
            "--proposal-id", mother_proposal_id, "--confirm-user-authored",
            "--transaction-id", "cli-mother-accept",
        )
        self.assertEqual(mother_accept.returncode, 0, mother_accept.stderr)
        mother_id = json.loads(mother_accept.stdout)["result"]["card_id"]

        connection_proposal = run_cli(
            "--root",
            str(self.root),
            "connect",
            "propose",
            "--from-id",
            permanent_id,
            "--to-id",
            mother_id,
            "--relation",
            "回应母题",
            "--rationale",
            "永久卡片给出了区分增量价值与噪声的一条当前判断。",
            "--transaction-id",
            "cli-connect-propose",
        )
        self.assertEqual(connection_proposal.returncode, 0, connection_proposal.stderr)
        connection_id = json.loads(connection_proposal.stdout)["result"][
            "proposal_id"
        ]
        connection_accept = run_cli(
            "--root",
            str(self.root),
            "connect",
            "accept",
            "--proposal-id",
            connection_id,
            "--transaction-id",
            "cli-connect-accept",
        )
        self.assertEqual(connection_accept.returncode, 0, connection_accept.stderr)

        action_draft = self.base / "action.md"
        action_draft.write_text(
            """# 用一次输出检验噪声抑制

在首次完整 CLI 生命周期里，我判断现实反馈比生成数量更能检验价值。

我要选取一次 AI 输出，让一位真实读者指出无用内容，并记录结果与下一次调整。
""",
            encoding="utf-8",
        )
        action_proposal = run_cli(
            "--root", str(self.root), "permanent", "propose",
            "--type", "action", "--draft-file", str(action_draft),
            "--transaction-id", "cli-action-propose",
        )
        self.assertEqual(action_proposal.returncode, 0, action_proposal.stderr)
        action_proposal_id = json.loads(action_proposal.stdout)["result"][
            "proposal_id"
        ]
        action_accept = run_cli(
            "--root", str(self.root), "permanent", "accept",
            "--proposal-id", action_proposal_id, "--confirm-user-authored",
            "--transaction-id", "cli-action-accept",
        )
        self.assertEqual(action_accept.returncode, 0, action_accept.stderr)
        action_id = json.loads(action_accept.stdout)["result"]["card_id"]
        action_feedback = run_cli(
            "--root",
            str(self.root),
            "permanent",
            "feedback",
            "--card-id",
            action_id,
            "--result",
            "读者指出两段内容只是重复表达，没有增加判断依据。",
            "--adjustment",
            "以后生成后先删除无法改变判断或行动的段落。",
            "--confirm-user-authored",
            "--transaction-id",
            "cli-action-feedback",
        )
        self.assertEqual(action_feedback.returncode, 0, action_feedback.stderr)

        index_draft = self.base / "index.md"
        index_draft.write_text(
            """# 持续生成质量入口

这个入口组织持续生成、人的判断和现实反馈相关卡片，让我从长期问题进入当前判断与行动反馈，而不是按关键词堆放文件。
""",
            encoding="utf-8",
        )
        index_proposal = run_cli(
            "--root", str(self.root), "permanent", "propose",
            "--type", "index", "--draft-file", str(index_draft),
            "--source-ids", f"{permanent_id},{mother_id},{action_id}",
            "--transaction-id", "cli-index-propose",
        )
        self.assertEqual(index_proposal.returncode, 0, index_proposal.stderr)
        index_proposal_id = json.loads(index_proposal.stdout)["result"][
            "proposal_id"
        ]
        index_accept = run_cli(
            "--root", str(self.root), "permanent", "accept",
            "--proposal-id", index_proposal_id, "--confirm-user-authored",
            "--transaction-id", "cli-index-accept",
        )
        self.assertEqual(index_accept.returncode, 0, index_accept.stderr)
        index_id = json.loads(index_accept.stdout)["result"]["card_id"]

        for directory in (
            "闪念空间", "溯源空间", "有意思空间", "待办空间",
            "永久空间/永久卡片", "永久空间/母题卡片",
            "永久空间/行动卡片", "永久空间/索引卡片",
        ):
            notes = list((self.root / directory).glob("*.md"))
            self.assertTrue(notes, directory)
            for note in notes:
                self.assertRegex(note.name, r"^\d{4}-\d{2}-\d{2}-.+\.md$")
                self.assertNotRegex(note.name, r"^[A-Z]+-(?:\d{8}-)?[0-9a-f]+-")

        for card_id, note, status, txid in [
            (
                mother_id,
                "新增观察：能否主动删除噪声，是持续生成质量提升的可观察指标。",
                "evolving",
                "cli-mother-revise",
            ),
            (
                index_id,
                "把完成反馈的行动卡保留为现实校验入口。",
                "revised",
                "cli-index-revise",
            ),
        ]:
            revised = run_cli(
                "--root",
                str(self.root),
                "permanent",
                "revise",
                "--card-id",
                card_id,
                "--note",
                note,
                "--status",
                status,
                "--confirm-user-authored",
                "--transaction-id",
                txid,
            )
            self.assertEqual(revised.returncode, 0, revised.stderr)

        linted = run_cli("--root", str(self.root), "lint")
        self.assertEqual(linted.returncode, 0, linted.stderr)
        self.assertTrue(json.loads(linted.stdout)["ok"])
        verified = run_cli("--root", str(self.root), "verify")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(verified.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
