"""Deployment must refuse unsafe environments before external commands."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase


class DeployEnvironmentTests(SimpleTestCase):
    def test_missing_or_nonproduction_environment_refused_before_commands(self):
        candidate = Path("C:/Program Files/Git/bin/bash.exe")
        bash = str(candidate) if os.name == "nt" and candidate.exists() else shutil.which("bash")
        if not bash:
            self.skipTest("Bash unavailable")
        script = Path(__file__).resolve().parents[1] / "deploy/deploy.sh"
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / "production.env"
            environment = {**os.environ, "ENV_FILE": env_file.as_posix()}
            missing = subprocess.run([bash, script.as_posix()], env=environment, capture_output=True, text=True)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("Cannot read production environment", missing.stderr)
            env_file.write_text("FLUXTRACK_ENV=development\n", encoding="utf-8")
            wrong = subprocess.run([bash, script.as_posix()], env=environment, capture_output=True, text=True)
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn("requires FLUXTRACK_ENV=production", wrong.stderr)
