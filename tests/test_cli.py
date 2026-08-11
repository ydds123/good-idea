from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import initialize_test_vault


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
        initialize_test_vault(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_capture_and_verify_public_commands(self):
        app = json.loads((self.root / ".obsidian/app.json").read_text(encoding="utf-8"))
        appearance = json.loads(
            (self.root / ".obsidian/appearance.json").read_text(encoding="utf-8")
        )
        plugins = json.loads(
            (self.root / ".obsidian/core-plugins.json").read_text(encoding="utf-8")
        )
        self.assertEqual(app["propertiesInDocument"], "visible")
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
        self.assertIn("正式内容 Frontmatter 禁止 `summary`", fresh_schema)

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
        self.assertNotIn(
            "summary:",
            (self.root / path).read_text(encoding="utf-8"),
        )

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

        maintained_index = run_cli(
            "--root",
            str(self.root),
            "maintain",
            "index",
            "--transaction-id",
            "cli-maintain-index-noop",
        )
        self.assertEqual(maintained_index.returncode, 0, maintained_index.stderr)
        self.assertTrue(
            json.loads(maintained_index.stdout)["result"]["no_change"]
        )

        maintained_metadata = run_cli(
            "--root",
            str(self.root),
            "maintain",
            "metadata",
            "--transaction-id",
            "cli-maintain-metadata-noop",
        )
        self.assertEqual(
            maintained_metadata.returncode, 0, maintained_metadata.stderr
        )
        self.assertTrue(
            json.loads(maintained_metadata.stdout)["result"]["no_change"]
        )

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

    def test_direct_expression_formation_witness_public_cli(self):
        draft = self.base / "direct-permanent.md"
        draft.write_text(
            "# 直接表达需要可寻址的形成见证\n\n"
            "普通永久卡片可以直接形成于本轮表达，但不能以此为由丢失形成情境。\n",
            encoding="utf-8",
        )
        direct_source = self.base / "direct-source.txt"
        direct_source.write_text(
            "这张卡形成于用户明确要求无形成链接就不接纳普通永久卡片的讨论。\n",
            encoding="utf-8",
        )

        missing_confirmation = run_cli(
            "--root", str(self.root), "permanent", "propose",
            "--type", "permanent", "--draft-file", str(draft),
            "--direct-source-file", str(direct_source),
            "--transaction-id", "cli-direct-missing-confirmation",
        )
        self.assertEqual(missing_confirmation.returncode, 2)

        proposed = run_cli(
            "--root", str(self.root), "permanent", "propose",
            "--type", "permanent", "--draft-file", str(draft),
            "--direct-source-file", str(direct_source),
            "--confirm-user-approved-sources",
            "--transaction-id", "cli-direct-propose",
        )
        self.assertEqual(proposed.returncode, 0, proposed.stderr)
        proposal_id = json.loads(proposed.stdout)["result"]["proposal_id"]

        accepted = run_cli(
            "--root", str(self.root), "permanent", "accept",
            "--proposal-id", proposal_id,
            "--confirm-user-approved",
            "--transaction-id", "cli-direct-accept",
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        result = json.loads(accepted.stdout)["result"]
        witness_path = self.root / result["formation_witness_path"]
        self.assertTrue(witness_path.is_file())
        card_text = (self.root / result["card_path"]).read_text(encoding="utf-8")
        self.assertIn(result["formation_witness_id"], card_text)
        self.assertIn("## 形成来源", card_text)

        verified = run_cli("--root", str(self.root), "verify")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(verified.stdout)["ok"])

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

    def test_multi_turn_capture_public_cli_and_discard_paths(self):
        before_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, check=True,
            text=True, capture_output=True,
        ).stdout.strip()
        started = run_cli(
            "--root", str(self.root), "capture", "start",
            "--text", "第一条用户想法。",
            "--context-ref", "https://example.com/context",
            "--transaction-id", "cli-session-start",
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        start_data = json.loads(started.stdout)
        session_id = start_data["session_id"]
        appended = run_cli(
            "--root", str(self.root), "capture", "append",
            "--session-id", session_id,
            "--text", "第二条用户想法。",
            "--transaction-id", "cli-session-append",
        )
        self.assertEqual(appended.returncode, 0, appended.stderr)
        append_data = json.loads(appended.stdout)
        self.assertEqual(append_data["entry_count"], 2)
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=self.root, check=True,
                text=True, capture_output=True,
            ).stdout.strip(),
            before_head,
        )
        manifest = self.base / "capture-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "flashes": [
                        {
                            "title": "第一条用户想法",
                            "body": "第一条用户想法。",
                            "entry_ids": [start_data["entry_id"]],
                            "context_refs": ["https://example.com/context"],
                        },
                        {
                            "title": "第二条用户想法",
                            "body": "第二条用户想法。",
                            "entry_ids": [append_data["entry_id"]],
                            "context_refs": [],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        proposed = run_cli(
            "--root", str(self.root), "capture", "propose",
            "--session-id", session_id,
            "--manifest-file", str(manifest),
            "--transaction-id", "cli-session-propose",
        )
        self.assertEqual(proposed.returncode, 0, proposed.stderr)
        proposal_id = json.loads(proposed.stdout)["proposal_id"]
        rejected = run_cli(
            "--root", str(self.root), "capture", "finalize",
            "--session-id", session_id,
            "--proposal-id", proposal_id,
            "--transaction-id", "cli-session-finalize-rejected",
        )
        self.assertEqual(rejected.returncode, 2)
        finalized = run_cli(
            "--root", str(self.root), "capture", "finalize",
            "--session-id", session_id,
            "--proposal-id", proposal_id,
            "--confirm-discussion-complete",
            "--transaction-id", "cli-session-finalize",
        )
        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        final_data = json.loads(finalized.stdout)["result"]
        self.assertEqual(final_data["flash_count"], 2)
        self.assertEqual(len(final_data["maintenance_job_ids"]), 1)

        discarded_start = run_cli(
            "--root", str(self.root), "capture", "start",
            "--text", "这轮最后放弃。",
            "--transaction-id", "cli-discard-start",
        )
        discarded_id = json.loads(discarded_start.stdout)["session_id"]
        discarded = run_cli(
            "--root", str(self.root), "capture", "discard",
            "--session-id", discarded_id,
            "--confirm-user-abandoned",
            "--transaction-id", "cli-discard",
        )
        self.assertEqual(discarded.returncode, 0, discarded.stderr)
        self.assertEqual(json.loads(discarded.stdout)["status"], "abandoned")

    def test_local_file_preview_is_read_only_and_does_not_leak_source_path(self):
        source_dir = self.base / "imports"
        source_dir.mkdir()
        image_data = b"cli-local-image"
        (source_dir / "figure.png").write_bytes(image_data)
        local_file = source_dir / "本地材料.md"
        local_file.write_text(
            """---
title: 本地材料标题
author: 本地作者
published_at: 2026-08-09
canonical_url: https://example.com/declared-only
---
# 本地材料标题

这是需要保留的正文。\n\n![图](figure.png)
""",
            encoding="utf-8",
        )
        output = self.base / "local-preview.json"
        before_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        before_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout

        preview = run_cli(
            "--root",
            str(self.root),
            "source",
            "preview",
            "--local-file",
            str(local_file),
            "--output",
            str(output),
        )

        self.assertEqual(preview.returncode, 0, preview.stderr)
        result = json.loads(preview.stdout)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["origin_filename"], "本地材料.md")
        self.assertEqual(payload["title"], "本地材料标题")
        self.assertEqual(payload["markdown"], "这是需要保留的正文。\n\n![图](figure.png)")
        self.assertNotIn("url", payload)
        self.assertNotIn("canonical_url", payload)
        self.assertNotIn("source", payload)
        self.assertNotIn("source_kind", payload)
        self.assertNotIn(str(local_file), json.dumps(payload, ensure_ascii=False))
        self.assertEqual(result["preview_file"], str(output.resolve()))
        self.assertTrue(payload["images"][0]["data_base64"])
        after_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        after_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout
        self.assertEqual(after_head, before_head)
        self.assertEqual(after_status, before_status)

    def test_local_file_preview_rejects_conflicting_and_invalid_inputs(self):
        local_file = self.base / "article.md"
        local_file.write_text("# 标题\n\n正文", encoding="utf-8")
        markdown_file = self.base / "other.md"
        markdown_file.write_text("正文", encoding="utf-8")
        conflicting_identity = run_cli(
            "source",
            "preview",
            "--url",
            "https://example.com/article",
            "--local-file",
            str(local_file),
        )
        self.assertEqual(conflicting_identity.returncode, 2)
        self.assertIn("not allowed with argument", conflicting_identity.stderr)

        conflicting_input = run_cli(
            "source",
            "preview",
            "--local-file",
            str(local_file),
            "--markdown-file",
            str(markdown_file),
        )
        self.assertEqual(conflicting_input.returncode, 2)
        error = json.loads(conflicting_input.stderr)
        self.assertEqual(error["error"]["code"], "validation_error")
        self.assertIn("不能与", error["error"]["message"])

        missing = run_cli(
            "source",
            "preview",
            "--local-file",
            str(self.base / "missing.txt"),
        )
        self.assertEqual(missing.returncode, 2)
        error = json.loads(missing.stderr)
        self.assertEqual(error["error"]["code"], "validation_error")
        self.assertIn("不存在", error["error"]["message"])

        original = local_file.read_text(encoding="utf-8")
        overwrite = run_cli(
            "source",
            "preview",
            "--local-file",
            str(local_file),
            "--output",
            str(local_file),
        )
        self.assertEqual(overwrite.returncode, 2)
        error = json.loads(overwrite.stderr)
        self.assertIn("不能覆盖", error["error"]["message"])
        self.assertEqual(local_file.read_text(encoding="utf-8"), original)

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
        source_text = (self.root / result["source_path"]).read_text(encoding="utf-8")
        self.assertNotIn("source_url:", source_text)
        self.assertLess(source_text.index("## 原文快照"), source_text.index("## 关联闪念"))
        self.assertNotIn("## 文献笔记", source_text)
        maintained = run_cli(
            "--root", str(self.root), "maintain", "sources",
            "--transaction-id", "cli-source-layout-noop",
        )
        self.assertEqual(maintained.returncode, 0, maintained.stderr)
        self.assertEqual(json.loads(maintained.stdout)["result"]["count"], 0)

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
            "--confirm-user-approved-structure",
            "--source-ids", source_result["source_id"],
            "--from-ids", source_result["flash_id"],
            "--confirm-user-approved-sources",
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
            "--confirm-user-approved",
            "--transaction-id", "cli-permanent-accept",
        )
        self.assertEqual(permanent_accept.returncode, 0, permanent_accept.stderr)
        permanent_result = json.loads(permanent_accept.stdout)["result"]
        permanent_id = permanent_result["card_id"]
        formal_text = (self.root / permanent_result["card_path"]).read_text(encoding="utf-8")
        self.assertIn(permanent_body, formal_text)
        self.assertIn("## 形成来源", formal_text)
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

    def test_capture_revise_transition_connect_withdraw_disconnect_cli(self):
        todo = run_cli(
            "--root", str(self.root), "capture", "todo",
            "--text", "CLI 层验证轻量记录追加与状态流转",
            "--context", "CLI 测试产生情境，更新后应保留",
            "--transaction-id", "cli-revise-todo",
        )
        self.assertEqual(todo.returncode, 0, todo.stderr)
        todo_id = json.loads(todo.stdout)["result"]["id"]

        # 无确认时拒绝追加
        rejected = run_cli(
            "--root", str(self.root), "capture", "revise",
            "--id", todo_id,
            "--text", "未经确认的追加内容",
            "--transaction-id", "cli-revise-no-confirm",
        )
        self.assertEqual(rejected.returncode, 2, rejected.stderr)
        self.assertIn(
            "只能逐字追加用户亲自写下的内容",
            json.loads(rejected.stderr)["error"]["message"],
        )

        revised = run_cli(
            "--root", str(self.root), "capture", "revise",
            "--id", todo_id,
            "--text", "CLI 追加的演化记录内容",
            "--confirm-user-authored",
            "--transaction-id", "cli-revise-do",
        )
        self.assertEqual(revised.returncode, 0, revised.stderr)
        todo_note = (self.root / json.loads(todo.stdout)["result"]["path"]).read_text(
            encoding="utf-8"
        )
        self.assertIn("## 演化记录", todo_note)
        self.assertIn("CLI 追加的演化记录内容", todo_note)

        transitioned = run_cli(
            "--root", str(self.root), "capture", "transition",
            "--id", todo_id,
            "--status", "done",
            "--transaction-id", "cli-transition-done",
        )
        self.assertEqual(transitioned.returncode, 0, transitioned.stderr)
        self.assertEqual(
            json.loads(transitioned.stdout)["result"]["status"], "done"
        )

        # 整体更新：替换原始记录正文，保留产生情境
        update_text = "更新后的完整正文：这是通过 CLI 整体更新写入的第二版内容，包含完整设计框架。"
        updated = run_cli(
            "--root", str(self.root), "capture", "update",
            "--id", todo_id,
            "--text", update_text,
            "--confirm-user-authored",
            "--transaction-id", "cli-update-do",
        )
        self.assertEqual(updated.returncode, 0, updated.stderr)
        todo_note_after = (self.root / json.loads(todo.stdout)["result"]["path"]).read_text(
            encoding="utf-8"
        )
        self.assertIn("## 原始记录\n\n更新后的完整正文", todo_note_after)
        self.assertNotIn(
            "## 原始记录\n\nCLI 层验证轻量记录追加与状态流转", todo_note_after
        )
        self.assertIn("CLI 追加的演化记录内容", todo_note_after)
        self.assertIn("## 产生情境", todo_note_after)

        # 非法状态被 CLI 拒绝
        bad = run_cli(
            "--root", str(self.root), "capture", "transition",
            "--id", todo_id,
            "--status", "processed",
            "--transaction-id", "cli-transition-bad",
        )
        self.assertEqual(bad.returncode, 2, bad.stderr)

        # 来源 + 两张永久卡片 + 连接：走完整正向与逆向 CLI 链路
        source = run_cli(
            "--root", str(self.root), "source", "preview",
            "--url", "https://example.com/cli-connect",
            "--markdown-file", "-",
            "--title", "CLI 连接测试来源",
        )
        self.assertEqual(source.returncode, 0, source.stderr)
        preview_file = self.base / "preview.json"
        preview_file.write_text(source.stdout, encoding="utf-8")
        committed = run_cli(
            "--root", str(self.root), "source", "commit",
            "--preview-file", str(preview_file),
            "--motivation", "为 CLI 连接链路提供来源依据",
            "--transaction-id", "cli-connect-source",
        )
        self.assertEqual(committed.returncode, 0, committed.stderr)
        source_id = json.loads(committed.stdout)["result"]["source_id"]

        card_ids = []
        for index, (title, body, txp, txa) in enumerate(
            [
                ("CLI 左卡片",
                 "连接测试用的左卡片，作为语义连接的起点，需要足够长的正文才能通过草稿门禁。",
                 "cli-connect-left-propose", "cli-connect-left-accept"),
                ("CLI 右卡片",
                 "连接测试用的右卡片，作为语义连接的终点，同样需要足够长的正文来表达判断。",
                 "cli-connect-right-propose", "cli-connect-right-accept"),
            ]
        ):
            draft = self.base / f"draft-{index}.md"
            draft.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
            proposed = run_cli(
                "--root", str(self.root), "permanent", "propose",
                "--type", "permanent",
                "--draft-file", str(draft),
                "--source-ids", source_id,
                "--from-ids", source_id,
                "--confirm-user-approved-sources",
                "--transaction-id", txp,
            )
            self.assertEqual(proposed.returncode, 0, proposed.stderr)
            accepted = run_cli(
                "--root", str(self.root), "permanent", "accept",
                "--proposal-id", json.loads(proposed.stdout)["result"]["proposal_id"],
                "--confirm-user-authored",
                "--transaction-id", txa,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            card_ids.append(json.loads(accepted.stdout)["result"]["card_id"])

        proposed_conn = run_cli(
            "--root", str(self.root), "connect", "propose",
            "--from-id", card_ids[0],
            "--to-id", card_ids[1],
            "--relation", "互为印证",
            "--rationale", "CLI 链路验证两张卡片的关系。",
            "--transaction-id", "cli-connect-propose",
        )
        self.assertEqual(proposed_conn.returncode, 0, proposed_conn.stderr)
        proposal_id = json.loads(proposed_conn.stdout)["result"]["proposal_id"]
        accepted_conn = run_cli(
            "--root", str(self.root), "connect", "accept",
            "--proposal-id", proposal_id,
            "--transaction-id", "cli-connect-accept",
        )
        self.assertEqual(accepted_conn.returncode, 0, accepted_conn.stderr)

        disconnected = run_cli(
            "--root", str(self.root), "connect", "disconnect",
            "--proposal-id", proposal_id,
            "--reason", "CLI 链路验证完成后断开连接",
            "--transaction-id", "cli-connect-disconnect",
        )
        self.assertEqual(disconnected.returncode, 0, disconnected.stderr)
        left_note = (self.root / "永久空间/永久卡片").glob("*.md")
        combined = "".join(
            path.read_text(encoding="utf-8") for path in left_note
        )
        self.assertNotIn("## 连接", combined)

        # 新候选走 withdraw 撤回
        pending_conn = run_cli(
            "--root", str(self.root), "connect", "propose",
            "--from-id", card_ids[0],
            "--to-id", card_ids[1],
            "--relation", "临时候选",
            "--rationale", "这条候选将被撤回。",
            "--transaction-id", "cli-connect-withdraw-propose",
        )
        self.assertEqual(pending_conn.returncode, 0, pending_conn.stderr)
        pending_id = json.loads(pending_conn.stdout)["result"]["proposal_id"]
        withdrawn = run_cli(
            "--root", str(self.root), "connect", "withdraw",
            "--proposal-id", pending_id,
            "--reason", "候选理由不成立，撤回",
            "--transaction-id", "cli-connect-withdraw",
        )
        self.assertEqual(withdrawn.returncode, 0, withdrawn.stderr)
        self.assertFalse(
            (self.root / json.loads(pending_conn.stdout)["result"]["proposal_path"]).exists()
        )

        linted = run_cli("--root", str(self.root), "lint")
        self.assertEqual(linted.returncode, 0, linted.stderr)
        self.assertTrue(json.loads(linted.stdout)["ok"])
        verified = run_cli("--root", str(self.root), "verify")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(verified.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
