from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "scripts" / "evaluate-skill-routing.py"
CASES = PROJECT / "tests" / "fixtures" / "skill-routing-cases.json"
LATEST_REPORT = PROJECT / "reports" / "skill-routing" / "latest.json"


def run_evaluator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=PROJECT,
        text=True,
        capture_output=True,
        check=False,
    )


class SkillRoutingTests(unittest.TestCase):
    def test_static_contract_covers_all_skills_and_only_declared_overlap(self):
        with tempfile.TemporaryDirectory() as temporary:
            report_dir = Path(temporary) / "report"
            result = run_evaluator("--report-dir", str(report_dir))
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((report_dir / "latest.json").read_text(encoding="utf-8"))

        self.assertEqual(report["skill_count"], 7)
        self.assertEqual(report["case_count"], 43)
        self.assertEqual(report["contract_errors"], [])
        static = report["static_overlap"]
        self.assertTrue(static["ok"])
        self.assertEqual(static["unapproved_high_overlaps"], [])
        declared = static["declared_high_overlaps"]
        self.assertEqual(len(declared), 1)
        self.assertEqual(
            set(declared[0]["skills"]),
            {"goodidea-form-permanent", "goodidea-review-permanent"},
        )
        self.assertEqual(len(report["semantic_risk_hypotheses"]), 4)
        self.assertEqual(len(report["recall_risk_hypotheses"]), 1)

    def test_prediction_gate_accepts_handoffs_and_rejects_same_stage_conflict(self):
        contract = json.loads(CASES.read_text(encoding="utf-8"))
        passing = {
            "results": [
                {
                    "case_id": case["id"],
                    "primary_skill": case["expected_primary"],
                    "supporting_skills": case["required_supporting"],
                    "conflict": case["expected_conflict"],
                    "reason": "确定性测试夹具",
                }
                for case in contract["cases"]
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            predictions = root / "passing.json"
            predictions.write_text(
                json.dumps(passing, ensure_ascii=False), encoding="utf-8"
            )
            passed = run_evaluator(
                "--predictions-file",
                str(predictions),
                "--report-dir",
                str(root / "passing-report"),
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)

            passing["results"][0]["conflict"] = True
            conflict = root / "conflict.json"
            conflict.write_text(
                json.dumps(passing, ensure_ascii=False), encoding="utf-8"
            )
            failed = run_evaluator(
                "--predictions-file",
                str(conflict),
                "--report-dir",
                str(root / "failed-report"),
            )
            self.assertEqual(failed.returncode, 1)
            failed_report = json.loads(
                (root / "failed-report/latest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(failed_report["status"], "failed")
            self.assertIn(
                "conflict 期望 False，实际 True",
                failed_report["model_evaluation"]["failures"][0]["failures"],
            )

            passing["results"][0]["conflict"] = False
            passing["results"][31]["supporting_skills"] = [
                "goodidea-form-permanent",
                "goodidea-form-permanent",
            ]
            duplicate = root / "duplicate.json"
            duplicate.write_text(
                json.dumps(passing, ensure_ascii=False), encoding="utf-8"
            )
            duplicate_failed = run_evaluator(
                "--predictions-file",
                str(duplicate),
                "--report-dir",
                str(root / "duplicate-report"),
            )
            self.assertEqual(duplicate_failed.returncode, 1)
            duplicate_report = json.loads(
                (root / "duplicate-report/latest.json").read_text(encoding="utf-8")
            )
            self.assertIn(
                "supporting_skills 包含重复 Skill",
                duplicate_report["model_evaluation"]["failures"][0]["failures"],
            )

    def test_latest_report_matches_current_descriptions(self):
        self.assertTrue(LATEST_REPORT.is_file(), "缺少最新 Skill 路由评测报告")
        latest = json.loads(LATEST_REPORT.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            report_dir = Path(temporary) / "static-report"
            static = run_evaluator("--report-dir", str(report_dir))
            self.assertEqual(static.returncode, 0, static.stderr)
            current = json.loads(
                (report_dir / "latest.json").read_text(encoding="utf-8")
            )
        self.assertEqual(
            latest["description_fingerprint"],
            current["description_fingerprint"],
            "Skill description 已变化，必须重新运行模型路由评测",
        )
        self.assertIn(
            latest["evidence_kind"],
            {"static_description_scan", "model_backed_batch_classifier"},
        )
        if latest["evidence_kind"] == "model_backed_batch_classifier":
            self.assertIsNotNone(latest["model_evaluation"])


if __name__ == "__main__":
    unittest.main()
