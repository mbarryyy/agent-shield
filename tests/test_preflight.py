from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "preflight.sh"


class PreflightScriptTests(unittest.TestCase):
    def test_makefile_exposes_preflight_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertRegex(makefile, r"(?m)^preflight:")
        self.assertIn("scripts/preflight.sh", makefile)
        self.assertIn("tests/test_preflight.py", makefile)

    def test_preflight_script_exists_and_is_executable(self) -> None:
        self.assertTrue(SCRIPT.exists())
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_preflight_reports_status_without_printing_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "ANTHROPIC_API_KEY=sk-ant-test-secret-value\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["SHIELD_PREFLIGHT_ENV_FILE"] = str(env_file)
            env["SHIELD_PREFLIGHT_SKIP_SERVICE_REACHABILITY"] = "1"

            result = subprocess.run(
                [str(SCRIPT)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )

        output = result.stdout + result.stderr
        self.assertRegex(output, r"\b(GO|NO-GO)\b")
        self.assertIn("ANTHROPIC_API_KEY", output)
        self.assertNotIn("sk-ant-test-secret-value", output)


if __name__ == "__main__":
    unittest.main()
