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


if __name__ == "__main__":
    unittest.main()
