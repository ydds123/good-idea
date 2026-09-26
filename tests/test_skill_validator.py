from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "scripts" / "validate-skills.py"


class SkillValidatorTests(unittest.TestCase):
    def test_validates_every_discovered_skill_with_explicit_validator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skills_root = root / "skills"
            for name in ("alpha-skill", "beta-skill"):
                skill = skills_root / name
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: test\n---\n",
                    encoding="utf-8",
                )
            validator = root / "quick_validate.py"
            validator.write_text(
                "import pathlib, sys\n"
                "raise SystemExit(0 if (pathlib.Path(sys.argv[1]) / 'SKILL.md').is_file() else 1)\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--validator",
                    str(validator),
                    "--skills-root",
                    str(skills_root),
                ],
                cwd=PROJECT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("全部通过：2/2 Skills", result.stdout)

    def test_reports_missing_validator_without_traceback(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--validator",
                "/definitely/missing/quick_validate.py",
            ],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("找不到 skill-creator 官方校验器", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
