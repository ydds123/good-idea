from __future__ import annotations

import base64
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from goodidea.errors import IntegrityError, ValidationError
from goodidea.metadata import parse_document
from goodidea.repository import Repository, initialize_vault
from goodidea.service import GoodIdeaService


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


class GoodIdeaCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "vault"
        initialize_vault(self.root)
        self.repo = Repository(self.root)
        self.service = GoodIdeaService(self.repo)

    def tearDown(self):
        self.temp.cleanup()

    def preview(self, text: str = "正文第一版", status: str = "complete"):
        image_url = "https://example.com/image.png"
        return {
            "url": "https://example.com/article?utm_source=test",
            "canonical_url": "https://example.com/article",
            "title": "示例文章",
            "author": "作者甲",
            "published_at": "2026-08-04",
            "markdown": f"{text}\n\n![图]({image_url})",
            "images": [
                {
                    "url": image_url,
                    "alt": "图",
                    "content_type": "image/png",
                    "data_base64": base64.b64encode(b"fake-png").decode(),
                }
            ],
            "status": status,
            "error": "" if status == "complete" else "测试状态",
            "extractor": "test",
        }

    def test_motivation_gate_has_zero_writes(self):
        before_head = git(self.root, "rev-parse", "HEAD")
        before_files = sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file() and ".git/" not in path.as_posix()
        )
        with self.assertRaises(ValidationError):
            self.service.source_commit(
                self.preview(), motivation="可以", transaction_id="tx-gate"
            )
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), before_head)
        after_files = sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file() and ".git/" not in path.as_posix()
        )
        self.assertEqual(after_files, before_files)

    def test_source_and_flash_are_atomic_linked_local_and_idempotent(self):
        result = self.service.source_commit(
            self.preview(),
            motivation="这篇文章提醒我，判断必须进入行动才能得到校验",
            transaction_id="tx-source-1",
        )
        data = result["result"]
        source = (self.root / data["source_path"]).read_text(encoding="utf-8")
        flash = (self.root / data["flash_path"]).read_text(encoding="utf-8")
        self.assertIn(data["flash_id"], source)
        self.assertIn(data["source_id"], flash)
        self.assertIn("../.goodidea/assets/", source)
        self.assertNotIn("](https://example.com/image.png)", source)
        files_in_commit = git(
            self.root, "show", "--pretty=", "--name-only", result["commit"]
        ).splitlines()
        self.assertIn(data["source_path"], files_in_commit)
        self.assertIn(data["flash_path"], files_in_commit)
        head = git(self.root, "rev-parse", "HEAD")
        replay = self.service.source_commit(
            self.preview(),
            motivation="这篇文章提醒我，判断必须进入行动才能得到校验",
            transaction_id="tx-source-1",
        )
        self.assertTrue(replay["idempotent"])
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), head)

        second = self.service.source_commit(
            self.preview(),
            motivation="我还想用它检查已有卡片有没有只停留在文字层面",
            transaction_id="tx-source-2",
        )
        self.assertFalse(second["result"]["source_created"])
        self.assertEqual(second["result"]["source_id"], data["source_id"])
        self.assertNotEqual(second["result"]["flash_id"], data["flash_id"])

    def test_tampered_snapshot_blocks_all_writes(self):
        result = self.service.source_commit(
            self.preview(),
            motivation="我需要测试受保护快照是否真的能阻止后续写入",
            transaction_id="tx-tamper-source",
        )
        source_path = self.root / result["result"]["source_path"]
        source_path.write_text(
            source_path.read_text(encoding="utf-8").replace("正文第一版", "被篡改"),
            encoding="utf-8",
        )
        with self.assertRaises(IntegrityError):
            self.service.capture(
                "flash", text="这条记录不应被写入", transaction_id="tx-after-tamper"
            )

    def test_refresh_requires_candidate_and_preserves_old_version(self):
        initial = self.service.source_commit(
            self.preview(),
            motivation="我要追踪网页后续变化，但不能静默覆盖旧内容",
            transaction_id="tx-refresh-source",
        )
        source_id = initial["result"]["source_id"]
        updated_preview = self.preview("正文第二版，包含新的证据")
        proposal = self.service.source_refresh(
            source_id,
            preview=updated_preview,
            transaction_id="tx-refresh-proposal",
        )
        source_path = self.root / initial["result"]["source_path"]
        candidate_text = source_path.read_text(encoding="utf-8")
        self.assertIn("正文第一版", candidate_text)
        self.assertNotIn("正文第二版", candidate_text)
        accepted = self.service.source_refresh(
            source_id,
            confirm_proposal=proposal["result"]["proposal_id"],
            transaction_id="tx-refresh-accept",
        )
        self.assertIn("正文第二版", source_path.read_text(encoding="utf-8"))
        previous = git(
            self.root,
            "show",
            f"{accepted['commit']}^:{initial['result']['source_path']}",
        )
        self.assertIn("正文第一版", previous)

    def test_permanent_gate_connections_and_action_feedback(self):
        captured = self.service.source_commit(
            self.preview(),
            motivation="我认为系统成功必须同时改善外部知识和人的判断能力",
            transaction_id="tx-cognition-source",
        )
        ids = captured["result"]
        proposal = self.service.permanent_propose(
            "permanent",
            title="系统成功必须包含人的能力增长",
            claim="如果外部系统更强但人的判断更弱，认知系统仍然失败。",
            reason="系统目标不是答案产量，而是长期改善判断与行动。",
            boundaries="机械维护可以自动化，但价值判断不能外包。",
            source_ids=[ids["source_id"]],
            from_ids=[ids["flash_id"]],
            transaction_id="tx-permanent-propose",
        )
        with self.assertRaises(ValidationError):
            self.service.permanent_accept(
                proposal["result"]["proposal_id"],
                explanation="同意",
                transaction_id="tx-permanent-reject",
            )
        accepted = self.service.permanent_accept(
            proposal["result"]["proposal_id"],
            explanation=(
                "我理解它是在说，工具节省整理时间只是手段；"
                "只有我能更清楚地解释、选择并根据结果修正，系统才算成功。"
            ),
            transaction_id="tx-permanent-accept",
        )
        flash = self.repo.find_note(ids["flash_id"])
        self.assertEqual(flash[2]["status"], "processed")

        mother_proposal = self.service.permanent_propose(
            "mother",
            title="怎样判断认知系统真的改善了我",
            claim="哪些可观察变化能证明系统提高了判断与行动，而非只增加笔记？",
            reason="这是需要跨时间和实践反复回答的问题。",
            source_ids=[ids["source_id"]],
            transaction_id="tx-mother-propose",
        )
        mother = self.service.permanent_accept(
            mother_proposal["result"]["proposal_id"],
            explanation="我需要观察自己是否更早发现关键问题，并能用行动结果修正旧判断。",
            transaction_id="tx-mother-accept",
        )
        connection = self.service.connect_propose(
            mother["result"]["card_id"],
            accepted["result"]["card_id"],
            relation="母题包含",
            rationale="这张永久卡片给出了衡量母题的一条必要条件。",
            transaction_id="tx-connect-propose",
        )
        self.service.connect_accept(
            connection["result"]["proposal_id"],
            transaction_id="tx-connect-accept",
        )
        left = self.repo.find_note(mother["result"]["card_id"])
        right = self.repo.find_note(accepted["result"]["card_id"])
        self.assertIn(right[2]["title"], left[1])
        self.assertIn(left[2]["title"], right[1])

        action_proposal = self.service.permanent_propose(
            "action",
            title="用一次回顾检验认知转化",
            claim="选择一条闪念，经过解释和行动反馈完成闭环。",
            context="系统首次真实使用",
            judgment="主动解释比自动摘要更能暴露理解缺口",
            action="完成一次卡片形成并在次日复盘",
            source_ids=[ids["source_id"]],
            transaction_id="tx-action-propose",
        )
        action = self.service.permanent_accept(
            action_proposal["result"]["proposal_id"],
            explanation="我会把是否发现理解缺口作为这次行动的反馈，而不是只看有没有生成文件。",
            transaction_id="tx-action-accept",
        )
        feedback = self.service.action_feedback(
            action["result"]["card_id"],
            result_text="实际复述时发现原先没有说明系统失败的判断标准。",
            adjustment="以后每张卡片都补一个可被现实否定的条件。",
            transaction_id="tx-action-feedback",
        )
        self.assertEqual(feedback["result"]["status"], "reviewed")
        evolved = self.service.permanent_revise(
            mother["result"]["card_id"],
            note="新增判断：能否更早识别反例，是比笔记数量更可靠的变化指标。",
            status="evolving",
            transaction_id="tx-mother-evolve",
        )
        self.assertEqual(evolved["result"]["status"], "evolving")
        index_proposal = self.service.permanent_propose(
            "index",
            title="判断能力增长入口",
            claim="组织关于认知系统是否改善人的判断能力的卡片入口。",
            source_ids=[
                accepted["result"]["card_id"],
                mother["result"]["card_id"],
            ],
            transaction_id="tx-index-propose",
        )
        index_card = self.service.permanent_accept(
            index_proposal["result"]["proposal_id"],
            explanation="这个入口让我从衡量标准进入具体判断和长期问题，而不是按关键词堆放文件。",
            transaction_id="tx-index-accept",
        )
        revised_index = self.service.permanent_revise(
            index_card["result"]["card_id"],
            note="把完成反馈的行动卡加入入口，以便从判断追到现实校验。",
            status="revised",
            transaction_id="tx-index-revise",
        )
        self.assertEqual(revised_index["result"]["status"], "revised")
        lint = self.service.lint()
        self.assertTrue(lint["ok"], lint["issues"])

    def test_failed_and_partial_sources_are_explicit(self):
        failed_preview = self.preview("", status="failed")
        failed_preview["markdown"] = ""
        failed_preview["images"] = []
        failed = self.service.source_commit(
            failed_preview,
            motivation="即使暂时抓取失败，我也要保留这个来源和稍后处理的原因",
            transaction_id="tx-failed-source",
        )
        failed_note = self.repo.find_note(failed["result"]["source_id"])
        self.assertEqual(failed_note[2]["capture_status"], "failed")
        self.assertIn("未能取得正文", failed_note[1])

        partial_preview = self.preview("只能取得一部分正文", status="partial")
        partial_preview["url"] = "https://example.com/partial"
        partial_preview["canonical_url"] = "https://example.com/partial"
        partial = self.service.source_commit(
            partial_preview,
            motivation="这份资料目前不完整，但其中的线索值得以后重新抓取",
            transaction_id="tx-partial-source",
        )
        partial_note = self.repo.find_note(partial["result"]["source_id"])
        self.assertEqual(partial_note[2]["capture_status"], "partial")

    def test_expiry_and_non_destructive_rollback(self):
        capture = self.service.capture(
            "flash",
            text="两天后如果仍未处理，这条闪念应失效",
            transaction_id="tx-expire-capture",
        )
        future = datetime.now().astimezone() + timedelta(days=3)
        expired = self.service.review(
            expire=True,
            current_time=future,
            transaction_id="tx-expire-review",
        )
        self.assertIn(capture["result"]["id"], expired["result"]["expired"])
        after = self.repo.find_note(capture["result"]["id"])
        self.assertEqual(after[2]["status"], "expired")

        another = self.service.capture(
            "todo",
            text="这个待办将被非破坏性回滚",
            transaction_id="tx-rollback-target",
        )
        target_path = self.root / another["result"]["path"]
        self.assertTrue(target_path.exists())
        rollback = self.service.rollback(another["commit"], confirmed=True)
        self.assertFalse(target_path.exists())
        self.assertEqual(
            git(self.root, "show", "-s", "--format=%P", rollback["revert_commit"]),
            another["commit"],
        )
        log_text = (self.root / "log.md").read_text(encoding="utf-8")
        self.assertIn("tx=tx-rollback-target", log_text)
        self.assertIn(f"tx={rollback['transaction_id']}", log_text)
        state = self.repo.read_state()
        self.assertEqual(
            state["transactions"]["tx-rollback-target"]["rolled_back_by"],
            rollback["transaction_id"],
        )
        self.assertTrue(self.service.lint()["ok"])


if __name__ == "__main__":
    unittest.main()
