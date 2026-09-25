from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kernel"))

from goodidea import (  # noqa: E402
    DataStore,
    GoodIdea,
    TransactionError,
    ValidationError,
)


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


class Ids:
    def __init__(self) -> None:
        self.values: defaultdict[str, int] = defaultdict(int)

    def __call__(self, prefix: str) -> str:
        self.values[prefix] += 1
        return f"{prefix}-{self.values[prefix]:04d}"


class KernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.ids = Ids()
        self.system = GoodIdea(
            self.root,
            now=self.clock.now,
            make_id=self.ids,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def session(self, message: str = "我突然想到一件事") -> dict:
        return self.system.start_session(message, user_started=True)

    def flash(self, session_id: str, title: str = "值得继续辨析的连接") -> dict:
        candidate = self.system.draft_flash(
            session_id,
            title=title,
            content="异常结果可能暴露了原有解释的隐藏条件。",
            trigger="阅读案例时发现结果与预期相反。",
        )
        return self.system.accept_flash(candidate, user_confirmed=True)

    def test_only_record_closes_complete_session_without_flash(self):
        session = self.session("先记录，不要加工")
        self.system.append_message(
            session["id"], role="assistant", content="已记录，不继续加工。"
        )
        closed = self.system.close_session(session["id"])
        self.assertEqual("closed", closed["status"])
        self.assertEqual(["user", "assistant"], [item["role"] for item in closed["messages"]])
        self.assertEqual([], self.system.store.list("flash"))

    def test_source_failure_does_not_block_claimed_flash(self):
        session = self.session("这篇文章让我想到一个反例")
        source = self.system.register_source(
            material_type="url",
            raw_reference="https://example.com/article?utm_source=chat",
            brought_by="user",
            session_id=session["id"],
        )
        failed = self.system.add_snapshot(
            source["id"], quality="failed", error="network unavailable"
        )
        candidate = self.system.draft_flash(
            session["id"],
            title="反例暴露隐藏前提",
            content="问题可能不是执行失败，而是判断前提错误。",
            trigger="文章案例与原判断冲突。",
            source_ids=[source["id"]],
        )
        flash = self.system.accept_flash(candidate, user_confirmed=True)
        self.assertEqual("failed", failed["status"])
        self.assertEqual("pending", flash["status"])

    def test_user_can_dismiss_without_mature_argument(self):
        flash = self.flash(self.session()["id"])
        dismissed = self.system.decide_flash(
            flash["id"], outcome="dismissed", user_decided=True
        )
        self.assertEqual("dismissed", dismissed["status"])
        self.assertEqual([], self.system.recall("隐藏条件"))

    def test_fermenting_requires_real_gap_and_is_recallable(self):
        flash = self.flash(self.session()["id"])
        with self.assertRaises(ValidationError):
            self.system.decide_flash(
                flash["id"], outcome="fermenting", user_decided=True
            )
        fermented = self.system.decide_flash(
            flash["id"],
            outcome="fermenting",
            user_decided=True,
            analysis="这可能改变我判断失败原因的方式。",
            gap="还没有真实项目经验。",
            retrigger="下一次复盘失败项目时。",
        )
        results = self.system.recall("失败原因")
        self.assertEqual("fermenting", fermented["status"])
        self.assertEqual(flash["id"], results[0]["id"])

    def test_flash_forms_user_claimed_insight_with_evidence(self):
        session = self.session()
        flash = self.flash(session["id"])
        candidate = self.system.draft_insight(
            title="先检查前提再归因执行",
            judgment="异常结果出现时，应先检查判断前提。",
            reason="错误前提会让正确执行稳定地产生坏结果。",
            boundary="适用于结果与预期系统性冲突的情况。",
            evidence=[
                {"kind": "session", "id": session["id"]},
                {"kind": "flash", "id": flash["id"]},
            ],
        )
        insight = self.system.accept_insight(candidate, user_confirmed=True)
        updated_flash = self.system.store.read("flash", flash["id"])
        self.assertEqual("active", insight["status"])
        self.assertEqual("formed", updated_flash["status"])

    def test_mature_judgment_does_not_require_flash(self):
        session = self.session("我已经有成熟判断，直接形成永久认识")
        candidate = self.system.draft_insight(
            title="规则先于应用",
            judgment="规则应先在直接使用中成立，再包装应用。",
            reason="过早包装会固化未经验证的交互方式。",
            boundary="适用于规则仍在试运行的阶段。",
            evidence=[{"kind": "session", "id": session["id"]}],
        )
        insight = self.system.accept_insight(candidate, user_confirmed=True)
        self.assertEqual("active", insight["status"])
        self.assertEqual([], self.system.store.list("flash"))

    def test_recall_respects_object_identity_and_status(self):
        session = self.session("讨论召回规则")
        pending = self.flash(session["id"], "召回待辨析内容")
        fermenting = self.flash(session["id"], "召回发酵内容")
        self.system.decide_flash(
            fermenting["id"],
            outcome="fermenting",
            user_decided=True,
            analysis="召回必须显示身份。",
            gap="缺少使用反馈。",
            retrigger="下一次召回错误时。",
        )
        default = self.system.recall("召回")
        analysis = self.system.recall("召回", mode="analysis")
        self.assertEqual([fermenting["id"]], [item["id"] for item in default])
        self.assertEqual(
            {pending["id"], fermenting["id"]}, {item["id"] for item in analysis}
        )

    def test_source_registry_deduplicates_tracking_links_and_versions(self):
        first = self.system.register_source(
            material_type="url",
            raw_reference="https://example.com/post?utm_medium=im",
            brought_by="user",
            persistence_intent=True,
        )
        second = self.system.register_source(
            material_type="url",
            raw_reference="https://example.com/post",
            brought_by="user",
            persistence_intent=True,
        )
        self.system.add_snapshot(first["id"], quality="complete", content="版本一")
        updated = self.system.add_snapshot(
            second["id"], quality="complete", content="版本二"
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(2, len(updated["snapshots"]))
        self.assertEqual(1, len(self.system.store.list("source")))

    def test_user_declared_file_version_keeps_original_source_identity(self):
        source = self.system.register_source(
            material_type="file",
            raw_reference="report.md",
            filename="report.md",
            content="版本一",
            brought_by="user",
            persistence_intent=True,
        )
        original_identity = source["identity"]
        self.system.add_snapshot(source["id"], quality="complete", content="版本一")
        same_source = self.system.register_source(
            material_type="file",
            raw_reference="report-v2.md",
            filename="report-v2.md",
            content="版本二",
            brought_by="user",
            persistence_intent=True,
            same_source_id=source["id"],
        )
        updated = self.system.add_snapshot(
            same_source["id"], quality="complete", content="版本二"
        )
        self.assertEqual(source["id"], same_source["id"])
        self.assertEqual(original_identity, same_source["identity"])
        self.assertEqual(2, len(updated["snapshots"]))
        self.assertEqual(1, len(self.system.store.list("source")))

    def test_internal_evidence_never_creates_external_source(self):
        session = self.session()
        flash = self.flash(session["id"])
        candidate = self.system.draft_insight(
            title="不伪造来源",
            judgment="没有外部材料时，不应该制造来源对象。",
            reason="会话和闪念已经能说明真实形成过程。",
            evidence=[
                {"kind": "session", "id": session["id"]},
                {"kind": "flash", "id": flash["id"]},
            ],
        )
        self.system.accept_insight(candidate, user_confirmed=True)
        self.assertEqual([], self.system.store.list("source"))

    def test_48_hour_expiry_skips_active_discussion_and_can_restart(self):
        flash = self.flash(self.session()["id"])
        self.clock.advance(hours=48)
        self.assertEqual(
            [], self.system.expire_flashes(active_flash_ids=[flash["id"]])
        )
        expired = self.system.expire_flashes()
        self.assertEqual([flash["id"]], [item["id"] for item in expired])
        self.clock.advance(hours=2)
        reactivated = self.system.reactivate_flash(flash["id"], user_decided=True)
        self.assertEqual("pending", reactivated["status"])
        self.clock.advance(hours=47)
        self.assertEqual([], self.system.expire_flashes())

    def test_local_file_path_is_never_persisted(self):
        source = self.system.register_source(
            material_type="file",
            raw_reference="/Users/example/private/note.md",
            filename="/Users/example/private/note.md",
            content="外部材料",
            brought_by="user",
            persistence_intent=True,
        )
        serialized = json.dumps(source, ensure_ascii=False)
        self.assertNotIn("/Users/example/private", serialized)
        self.assertIn("note.md", serialized)

    def test_formal_objects_require_user_confirmation(self):
        session = self.session()
        candidate = self.system.draft_flash(
            session["id"], title="候选", content="仍是候选", trigger="测试"
        )
        with self.assertRaises(ValidationError):
            self.system.accept_flash(candidate, user_confirmed=False)


class TransactionTests(unittest.TestCase):
    def test_multi_object_failure_restores_previous_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normal = DataStore(root)
            original = {"id": "THO-1", "kind": "session", "status": "recording"}
            normal.commit([original], action="seed", timestamp="2026-09-25T08:00:00+00:00")

            def fail(index: int, _path: Path) -> None:
                if index == 3:
                    raise RuntimeError("injected")

            failing = DataStore(root, fault=fail)
            changed = {"id": "THO-1", "kind": "session", "status": "closed"}
            with self.assertRaises(TransactionError):
                failing.commit(
                    [changed], action="change", timestamp="2026-09-25T09:00:00+00:00"
                )
            self.assertEqual(original, normal.read("session", "THO-1"))
            self.assertEqual(1, len(normal.list("event")))


if __name__ == "__main__":
    unittest.main()
