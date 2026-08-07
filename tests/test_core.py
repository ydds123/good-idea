from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from goodidea.errors import GitError, IntegrityError, TransactionError, ValidationError
from goodidea.metadata import parse_document, replace_frontmatter
from goodidea.notes import extract_snapshot, validate_source_note
from goodidea.repository import Repository, initialize_vault
from goodidea.service import GoodIdeaService, _rewrite_wiki_paths


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

    def test_init_refuses_nonempty_directory_without_overwrite(self):
        other = Path(self.temp.name) / "existing"
        other.mkdir()
        sentinel = other / "AGENTS.md"
        sentinel.write_text("用户原有文件", encoding="utf-8")
        with self.assertRaises(ValidationError):
            initialize_vault(other)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "用户原有文件")
        self.assertFalse((other / ".git").exists())

    def test_transaction_id_and_symlink_ancestor_cannot_escape_repository(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        with self.assertRaises(ValidationError):
            self.service.capture(
                "flash",
                text="非法事务编号不得在仓库外产生任何文件。",
                transaction_id="../../escape",
            )
        self.assertEqual(list(outside.iterdir()), [])

        assets = self.root / ".goodidea/assets"
        assets.rmdir()
        assets.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(TransactionError):
            self.repo._atomic_apply(
                {Path(".goodidea/assets/new/image.bin"): b"x"},
                set(),
                "safe-test",
                "test",
            )
        self.assertEqual(list(outside.iterdir()), [])

    def test_preseeded_backup_symlink_cannot_redirect_transaction_copy(self):
        outside = Path(self.temp.name) / "outside-backup.txt"
        outside.write_text("不可覆盖", encoding="utf-8")
        planted = self.root / ".goodidea/transactions/safe-preseed/backup"
        planted.mkdir(parents=True)
        (planted / "log.md").symlink_to(outside)
        self.service.capture(
            "flash",
            text="随机且全新的事务备份目录不会使用攻击者预先种下的链接。",
            transaction_id="safe-preseed",
        )
        self.assertEqual(outside.read_text(encoding="utf-8"), "不可覆盖")

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
        source_meta, source_body = parse_document(source)
        flash_meta, _ = parse_document(flash)
        self.assertIn(data["flash_id"], source_meta["flash_ids"])
        self.assertIn(data["source_id"], flash_meta["source_ids"])
        self.assertNotIn(data["flash_id"], source_body)
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

    def test_human_filenames_hide_ids_and_handle_same_day_collisions(self):
        first = self.service.capture(
            "flash",
            text="相同标题下的第一条闪念正文，用于验证人类可读文件名。",
            title="相同标题",
            transaction_id="tx-readable-name-1",
        )
        second = self.service.capture(
            "flash",
            text="相同标题下的第二条闪念正文，用于验证碰撞后缀。",
            title="相同标题",
            transaction_id="tx-readable-name-2",
        )
        first_path = Path(first["result"]["path"])
        second_path = Path(second["result"]["path"])
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        self.assertEqual(first_path.name, f"{today}-相同标题.md")
        self.assertEqual(second_path.name, f"{today}-相同标题-2.md")
        self.assertNotIn(first["result"]["id"], first_path.name)
        self.assertNotIn(second["result"]["id"], second_path.name)
        index = (self.root / "index.md").read_text(encoding="utf-8")
        self.assertNotIn(first["result"]["id"], index)
        self.assertIn("待处理", index)

    def test_lint_checks_obsidian_reading_baseline(self):
        app_path = self.root / ".obsidian/app.json"
        app = json.loads(app_path.read_text(encoding="utf-8"))
        app["propertiesInDocument"] = "visible"
        app_path.write_text(
            json.dumps(app, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        lint = self.service.lint()
        self.assertFalse(lint["ok"])
        self.assertIn("Obsidian 未默认隐藏机器 Frontmatter", lint["issues"])

    def test_filename_maintenance_renames_legacy_paths_and_repairs_links(self):
        captured = self.service.source_commit(
            self.preview(),
            motivation="我要验证改文件名后来源和闪念仍保持双向关联",
            transaction_id="tx-before-filename-maintenance",
        )["result"]
        source_rel = Path(captured["source_path"])
        flash_rel = Path(captured["flash_path"])
        legacy_source_rel = Path("溯源空间") / f"{captured['source_id']}-旧来源.md"
        legacy_flash_rel = Path("闪念空间") / f"{captured['flash_id']}-旧闪念.md"

        source_text = (self.root / source_rel).read_text(encoding="utf-8").replace(
            f"[[{flash_rel.with_suffix('').as_posix()}",
            f"[[{legacy_flash_rel.with_suffix('').as_posix()}",
        )
        original_snapshot = extract_snapshot(source_text)[0]
        flash_text = (self.root / flash_rel).read_text(encoding="utf-8").replace(
            f"[[{source_rel.with_suffix('').as_posix()}",
            f"[[{legacy_source_rel.with_suffix('').as_posix()}",
        )
        (self.root / source_rel).rename(self.root / legacy_source_rel)
        (self.root / flash_rel).rename(self.root / legacy_flash_rel)
        (self.root / legacy_source_rel).write_text(source_text, encoding="utf-8")
        (self.root / legacy_flash_rel).write_text(flash_text, encoding="utf-8")
        state = self.repo.read_state()
        state["sources"]["https://example.com/article"]["path"] = (
            legacy_source_rel.as_posix()
        )
        transaction_result = state["transactions"][
            "tx-before-filename-maintenance"
        ]["result"]
        transaction_result["source_path"] = legacy_source_rel.as_posix()
        transaction_result["flash_path"] = legacy_flash_rel.as_posix()
        (self.root / ".goodidea/state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        git(self.root, "add", "-A")
        git(self.root, "commit", "-m", "test fixture: legacy id-prefixed filenames")

        migrated = self.service.maintain_filenames(
            transaction_id="tx-maintain-readable-filenames"
        )
        self.assertEqual(migrated["result"]["count"], 2)
        self.assertFalse((self.root / legacy_source_rel).exists())
        self.assertFalse((self.root / legacy_flash_rel).exists())
        self.assertTrue((self.root / source_rel).is_file())
        self.assertTrue((self.root / flash_rel).is_file())
        repaired_source = (self.root / source_rel).read_text(encoding="utf-8")
        repaired_flash = (self.root / flash_rel).read_text(encoding="utf-8")
        self.assertIn(f"[[{flash_rel.with_suffix('').as_posix()}", repaired_source)
        self.assertIn(f"[[{source_rel.with_suffix('').as_posix()}", repaired_flash)
        validate_source_note(repaired_source, source_rel.as_posix())
        self.assertEqual(extract_snapshot(repaired_source)[0], original_snapshot)
        self.assertEqual(
            self.repo.read_state()["sources"]["https://example.com/article"]["path"],
            source_rel.as_posix(),
        )
        replay = self.service.source_commit(
            self.preview(),
            motivation="我要验证改文件名后来源和闪念仍保持双向关联",
            transaction_id="tx-before-filename-maintenance",
        )
        self.assertTrue(replay["idempotent"])
        self.assertEqual(replay["result"]["source_path"], source_rel.as_posix())
        self.assertEqual(replay["result"]["flash_path"], flash_rel.as_posix())
        self.assertTrue(self.service.lint()["ok"])
        self.service.rollback(migrated["commit"], confirmed=True)
        self.assertTrue((self.root / legacy_source_rel).is_file())
        self.assertTrue((self.root / legacy_flash_rel).is_file())
        restored_state = self.repo.read_state()
        self.assertEqual(
            restored_state["sources"]["https://example.com/article"]["path"],
            legacy_source_rel.as_posix(),
        )
        self.assertIn(
            legacy_source_rel.with_suffix("").as_posix(),
            (self.root / legacy_flash_rel).read_text(encoding="utf-8"),
        )

    def test_filename_maintenance_plans_final_layout_without_false_suffix(self):
        first = self.service.capture(
            "flash", text="第一条记录将从错误的 X 文件名移动到 Y。", title="Y",
            transaction_id="tx-layout-y",
        )["result"]
        second = self.service.capture(
            "flash", text="第二条记录应当占用最终空出来的 X 文件名。", title="X",
            transaction_id="tx-layout-x",
        )["result"]
        first_rel = Path(first["path"])
        second_rel = Path(second["path"])
        witness = self.service.capture(
            "interesting",
            text=(
                f"[[{first_rel.with_suffix('').as_posix()}|Y]] 与 "
                f"[[{second_rel.with_suffix('').as_posix()}|X]] 必须始终指向不同对象。"
            ),
            title="交换见证",
            transaction_id="tx-layout-witness",
        )["result"]
        witness_rel = Path(witness["path"])
        date = first_rel.name[:10]
        wrong_x = first_rel.with_name(f"{date}-X.md")
        legacy_x = second_rel.with_name("legacy-X.md")
        (self.root / second_rel).rename(self.root / legacy_x)
        (self.root / first_rel).rename(self.root / wrong_x)
        witness_text = (self.root / witness_rel).read_text(encoding="utf-8")
        witness_text = _rewrite_wiki_paths(
            witness_text,
            {
                first_rel.with_suffix("").as_posix(): wrong_x.with_suffix("").as_posix(),
                second_rel.with_suffix("").as_posix(): legacy_x.with_suffix("").as_posix(),
            },
        )
        (self.root / witness_rel).write_text(witness_text, encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-m", "test fixture: crossing filename migration")
        self.service.maintain_filenames(transaction_id="tx-final-layout")
        self.assertTrue((self.root / first_rel).is_file())
        self.assertTrue((self.root / second_rel).is_file())
        self.assertFalse((self.root / second_rel.with_name(f"{date}-X-2.md")).exists())
        repaired_witness = (self.root / witness_rel).read_text(encoding="utf-8")
        self.assertIn(f"[[{first_rel.with_suffix('').as_posix()}|Y]]", repaired_witness)
        self.assertIn(f"[[{second_rel.with_suffix('').as_posix()}|X]]", repaired_witness)

    def test_filename_maintenance_rejects_dirty_target_without_side_effects(self):
        captured = self.service.capture(
            "flash", text="脏文件不应被迁移事务覆盖。", transaction_id="tx-dirty-base"
        )["result"]
        proper = Path(captured["path"])
        legacy = proper.with_name("legacy-dirty.md")
        (self.root / proper).rename(self.root / legacy)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-m", "test fixture: dirty migration target")
        dirty_text = (self.root / legacy).read_text(encoding="utf-8") + "\n用户未提交修改\n"
        (self.root / legacy).write_text(dirty_text, encoding="utf-8")
        before_head = git(self.root, "rev-parse", "HEAD")
        with self.assertRaises(GitError):
            self.service.maintain_filenames(transaction_id="tx-dirty-rejected")
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), before_head)
        self.assertEqual((self.root / legacy).read_text(encoding="utf-8"), dirty_text)
        self.assertFalse((self.root / proper).exists())

    def test_wiki_path_rewrite_requires_an_exact_target_boundary(self):
        text = (
            "[[闪念空间/foo|短目标]]\n"
            "[[闪念空间/foo#段落|带锚点]]\n"
            "[[闪念空间/foobar|相似但不同的目标]]\n"
        )
        updated = _rewrite_wiki_paths(
            text,
            {"闪念空间/foo": "闪念空间/2026-08-07-foo"},
        )
        self.assertIn("[[闪念空间/2026-08-07-foo|短目标]]", updated)
        self.assertIn("[[闪念空间/2026-08-07-foo#段落|带锚点]]", updated)
        self.assertIn("[[闪念空间/foobar|相似但不同的目标]]", updated)
        swapped = _rewrite_wiki_paths(
            "[[闪念空间/A|甲]] 与 [[闪念空间/B|乙]]",
            {"闪念空间/A": "闪念空间/B", "闪念空间/B": "闪念空间/A"},
        )
        self.assertEqual(swapped, "[[闪念空间/B|甲]] 与 [[闪念空间/A|乙]]")

    def test_noop_filename_maintenance_is_idempotently_recorded(self):
        captured = self.service.capture(
            "flash",
            text="这条闪念已经使用符合规范的人类可读文件名。",
            transaction_id="tx-readable-before-noop",
        )
        first = self.service.maintain_filenames(
            transaction_id="tx-filename-noop"
        )
        self.assertTrue(first["result"]["no_change"])
        original_rel = Path(captured["result"]["path"])
        legacy_rel = original_rel.with_name(f"{captured['result']['id']}-旧文件.md")
        (self.root / original_rel).rename(self.root / legacy_rel)
        replay = self.service.maintain_filenames(
            transaction_id="tx-filename-noop"
        )
        self.assertTrue(replay["idempotent"])
        self.assertTrue((self.root / legacy_rel).is_file())

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

    def test_refresh_title_change_atomically_renames_and_repairs_backlink(self):
        initial = self.service.source_commit(
            self.preview(), motivation="我要确认来源改标题时不会留下断链。",
            transaction_id="tx-refresh-title-source",
        )["result"]
        changed = self.preview("标题变化后的正文")
        changed["title"] = "更新后的示例文章"
        proposal = self.service.source_refresh(
            initial["source_id"], preview=changed,
            transaction_id="tx-refresh-title-proposal",
        )["result"]
        accepted = self.service.source_refresh(
            initial["source_id"], confirm_proposal=proposal["proposal_id"],
            transaction_id="tx-refresh-title-accept",
        )["result"]
        old_path = Path(initial["source_path"])
        new_path = Path(accepted["source_path"])
        self.assertNotEqual(old_path, new_path)
        self.assertFalse((self.root / old_path).exists())
        self.assertIn("更新后的示例文章", new_path.name)
        flash = self.repo.find_note(initial["flash_id"])
        self.assertIn(new_path.with_suffix("").as_posix(), flash[1])
        self.assertIn(f"|更新后的示例文章]]", flash[1])
        self.assertNotIn(f"|示例文章]]", flash[1])
        source_record = self.repo.read_state()["sources"]["https://example.com/article"]
        self.assertEqual(source_record["path"], new_path.as_posix())
        self.assertEqual(source_record["title"], "更新后的示例文章")
        self.assertTrue(self.service.lint()["ok"])

    def test_permanent_gate_connections_and_action_feedback(self):
        captured = self.service.source_commit(
            self.preview(),
            motivation="我认为系统成功必须同时改善外部知识和人的判断能力",
            transaction_id="tx-cognition-source",
        )
        ids = captured["result"]
        permanent_draft = """# 系统成功必须包含人的能力增长

如果外部系统更强但人的判断更弱，认知系统仍然失败。

我认为系统目标不是答案产量，而是长期改善判断与行动。机械维护可以自动化，但价值判断不能外包。
"""
        proposal = self.service.permanent_propose(
            "permanent",
            draft=permanent_draft,
            source_ids=[ids["source_id"]],
            from_ids=[ids["flash_id"]],
            transaction_id="tx-permanent-propose",
        )
        proposal_text = (
            self.root / proposal["result"]["proposal_path"]
        ).read_text(encoding="utf-8")
        proposal_meta, proposal_body = parse_document(proposal_text)
        self.assertEqual(proposal_body, permanent_draft)
        self.assertEqual(proposal_meta["authoring_mode"], "user_verbatim")
        self.assertNotIn("机器数据", proposal_text)
        with self.assertRaises(ValidationError):
            self.service.permanent_accept(
                proposal["result"]["proposal_id"],
                confirmed_by_user=False,
                transaction_id="tx-permanent-reject",
            )
        accepted = self.service.permanent_accept(
            proposal["result"]["proposal_id"],
            confirmed_by_user=True,
            transaction_id="tx-permanent-accept",
        )
        formal_text = (self.root / accepted["result"]["card_path"]).read_text(
            encoding="utf-8"
        )
        _, formal_body = parse_document(formal_text)
        self.assertEqual(formal_body, permanent_draft)
        self.assertNotIn("机器数据", formal_text)
        flash = self.repo.find_note(ids["flash_id"])
        self.assertEqual(flash[2]["status"], "processed")

        mother_proposal = self.service.permanent_propose(
            "mother",
            draft="""# 怎样判断认知系统真的改善了我

哪些可观察变化能证明系统提高了判断与行动，而非只增加笔记？

这是需要跨时间和实践反复回答的问题。我会观察自己是否更早发现关键问题，并能用行动结果修正旧判断。
""",
            source_ids=[ids["source_id"]],
            transaction_id="tx-mother-propose",
        )
        mother = self.service.permanent_accept(
            mother_proposal["result"]["proposal_id"],
            confirmed_by_user=True,
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
            draft="""# 用一次回顾检验认知转化

情境是系统首次真实使用。我的判断是主动解释比自动摘要更能暴露理解缺口。

我要选择一条闪念，完成一次卡片形成并在次日复盘，以是否发现理解缺口作为反馈。
""",
            source_ids=[ids["source_id"]],
            transaction_id="tx-action-propose",
        )
        action = self.service.permanent_accept(
            action_proposal["result"]["proposal_id"],
            confirmed_by_user=True,
            transaction_id="tx-action-accept",
        )
        with self.assertRaises(ValidationError):
            self.service.action_feedback(
                action["result"]["card_id"],
                result_text="这段内容不能在没有用户作者确认时写入。",
                adjustment="系统也不能替用户生成后续修正。",
                confirmed_by_user=False,
                transaction_id="tx-action-feedback-rejected",
            )
        feedback = self.service.action_feedback(
            action["result"]["card_id"],
            result_text="实际复述时发现原先没有说明系统失败的判断标准。",
            adjustment="以后每张卡片都补一个可被现实否定的条件。",
            confirmed_by_user=True,
            transaction_id="tx-action-feedback",
        )
        self.assertEqual(feedback["result"]["status"], "reviewed")
        feedback_card = self.repo.find_note(action["result"]["card_id"])
        self.assertIn("实际复述时发现原先没有说明系统失败的判断标准。", feedback_card[1])
        self.assertIn("以后每张卡片都补一个可被现实否定的条件。", feedback_card[1])
        evolved = self.service.permanent_revise(
            mother["result"]["card_id"],
            note="新增判断：能否更早识别反例，是比笔记数量更可靠的变化指标。",
            confirmed_by_user=True,
            status="evolving",
            transaction_id="tx-mother-evolve",
        )
        self.assertEqual(evolved["result"]["status"], "evolving")
        evolved_card = self.repo.find_note(mother["result"]["card_id"])
        self.assertIn("新增判断：能否更早识别反例，是比笔记数量更可靠的变化指标。", evolved_card[1])
        index_proposal = self.service.permanent_propose(
            "index",
            draft="""# 判断能力增长入口

这个入口组织关于认知系统是否改善人的判断能力的卡片，让我从衡量标准进入具体判断和长期问题，而不是按关键词堆放文件。
""",
            source_ids=[
                accepted["result"]["card_id"],
                mother["result"]["card_id"],
            ],
            transaction_id="tx-index-propose",
        )
        index_card = self.service.permanent_accept(
            index_proposal["result"]["proposal_id"],
            confirmed_by_user=True,
            transaction_id="tx-index-accept",
        )
        revised_index = self.service.permanent_revise(
            index_card["result"]["card_id"],
            note="把完成反馈的行动卡加入入口，以便从判断追到现实校验。",
            confirmed_by_user=True,
            status="revised",
            transaction_id="tx-index-revise",
        )
        self.assertEqual(revised_index["result"]["status"], "revised")
        lint = self.service.lint()
        self.assertTrue(lint["ok"], lint["issues"])

    def test_permanent_draft_tampering_and_withdrawal_are_enforced(self):
        proposal = self.service.permanent_propose(
            "permanent",
            draft="""# 这是一张由用户写成的草稿

这段正文完整表达了用户自己的判断，也为后续审查保留了足够上下文和可质疑空间。
""",
            transaction_id="tx-user-draft",
        )
        proposal_id = proposal["result"]["proposal_id"]
        proposal_path = self.root / proposal["result"]["proposal_path"]
        proposal_path.write_text(
            proposal_path.read_text(encoding="utf-8").replace("自己的判断", "被改写的判断"),
            encoding="utf-8",
        )
        with self.assertRaises(IntegrityError):
            self.service.permanent_accept(
                proposal_id,
                confirmed_by_user=True,
                transaction_id="tx-tampered-draft-accept",
            )

        # Restore the tracked proposal before exercising a normal withdrawal.
        subprocess.run(
            ["git", "restore", "--", proposal["result"]["proposal_path"]],
            cwd=self.root,
            check=True,
        )
        clean_text = proposal_path.read_text(encoding="utf-8")
        tampered_meta, _ = parse_document(clean_text)
        tampered_meta["status"] = "withdrawn"
        proposal_path.write_text(
            replace_frontmatter(clean_text, tampered_meta), encoding="utf-8"
        )
        with self.assertRaises(IntegrityError):
            self.service.permanent_accept(
                proposal_id,
                confirmed_by_user=True,
                transaction_id="tx-frontmatter-tampered-accept",
            )
        subprocess.run(
            ["git", "restore", "--", proposal["result"]["proposal_path"]],
            cwd=self.root,
            check=True,
        )

        state = self.repo.read_state()
        state["proposals"][proposal_id]["card_type"] = "invalid"
        (self.root / ".goodidea/state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(IntegrityError):
            self.service.permanent_accept(
                proposal_id,
                confirmed_by_user=True,
                transaction_id="tx-state-tampered-accept",
            )
        subprocess.run(
            ["git", "restore", "--", ".goodidea/state.json"],
            cwd=self.root,
            check=True,
        )

        withdrawn = self.service.permanent_withdraw(
            proposal_id,
            reason="用户决定撤销这份草稿，不让它进入永久空间",
            transaction_id="tx-user-draft-withdraw",
        )
        self.assertEqual(withdrawn["result"]["status"], "withdrawn")
        withdrawn_text = proposal_path.read_text(encoding="utf-8")
        self.assertNotIn("这段正文完整表达", withdrawn_text)
        self.assertNotIn("机器数据", withdrawn_text)
        with self.assertRaises(ValidationError):
            self.service.permanent_accept(
                proposal_id,
                confirmed_by_user=True,
                transaction_id="tx-withdrawn-draft-accept",
            )

    def test_legacy_agent_proposal_is_rejected_and_neutralized(self):
        proposal = self.service.permanent_propose(
            "permanent",
            draft="# 用户占位草稿\r\n\r\n这段由用户写成的文字没有末尾换行",
            transaction_id="tx-before-legacy-shape",
        )
        proposal_id = proposal["result"]["proposal_id"]
        proposal_path = self.root / proposal["result"]["proposal_path"]
        _, canonical_body = parse_document(proposal_path.read_text(encoding="utf-8"))
        self.assertEqual(
            canonical_body,
            "# 用户占位草稿\n\n这段由用户写成的文字没有末尾换行\n",
        )

        state = self.repo.read_state()
        record = state["proposals"][proposal_id]
        record.pop("authoring_mode")
        record.pop("draft_sha256")
        record.pop("title")
        (self.root / ".goodidea/state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        proposal_path.write_text(
            f'''---
id: "{proposal_id}"
type: "permanent_proposal"
title: "候选：系统越权生成的旧标题"
status: "pending"
card_type: "permanent"
created_at: "2026-08-04T00:00:00+08:00"
updated_at: "2026-08-04T00:00:00+08:00"
---
# 候选：系统越权生成的旧标题

## 候选内容

这段错误正文不是用户写的。

## 机器数据

<!-- goodidea:proposal-json:start -->
{{"claim": "这段错误正文不是用户写的。"}}
<!-- goodidea:proposal-json:end -->
''',
            encoding="utf-8",
        )
        git(self.root, "add", ".goodidea/state.json", proposal["result"]["proposal_path"])
        git(self.root, "commit", "-m", "test fixture: legacy agent proposal")
        with self.assertRaises(ValidationError):
            self.service.permanent_accept(
                proposal_id,
                confirmed_by_user=True,
                transaction_id="tx-legacy-accept-rejected",
            )
        withdrawn = self.service.permanent_withdraw(
            proposal_id,
            reason="这份旧候选由系统越权生成，按用户要求撤销",
            transaction_id="tx-legacy-withdraw",
        )
        self.assertEqual(withdrawn["result"]["status"], "withdrawn")
        tombstone = proposal_path.read_text(encoding="utf-8")
        self.assertNotIn("系统越权生成的旧标题", tombstone)
        self.assertNotIn("这段错误正文不是用户写的", tombstone)
        self.assertNotIn("机器数据", tombstone)
        self.assertIn(f"# 已撤销候选 {proposal_id}", tombstone)
        self.assertNotIn("title", self.repo.read_state()["proposals"][proposal_id])
        self.assertTrue(self.service.lint()["ok"])

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

    def test_image_download_failure_is_partial_and_never_leaves_remote_dependency(self):
        preview = self.preview("正文仍然应该可读")
        preview["images"][0]["data_base64"] = "not-valid-base64"
        result = self.service.source_commit(
            preview,
            motivation="即使图片抓取失败，我也要看到明确状态而不是静默依赖远程地址",
            transaction_id="tx-image-failure",
        )
        source_note = self.repo.find_note(result["result"]["source_id"])
        self.assertEqual(source_note[2]["capture_status"], "partial")
        self.assertTrue(source_note[2]["image_failures"])
        self.assertIn("图片未能保存", source_note[1])
        self.assertNotIn("](https://example.com/image.png)", source_note[1])

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
