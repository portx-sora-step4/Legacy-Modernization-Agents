#!/usr/bin/env python3
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR_SCRIPT = REPO_ROOT / "doctor.sh"


def bash_executable():
    if os.name != "nt":
        return "bash"
    candidates = [
        os.environ.get("GIT_BASH"),
        str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("Git Bash was not found; set GIT_BASH to bash.exe")


class DoctorRektContractTests(unittest.TestCase):
    def run_function(self, function_call: str, *, repo_root: Path | None = None):
        env = os.environ.copy()
        env["DOCTOR_SH_LIBRARY_ONLY"] = "true"
        if repo_root is not None:
            function_call = f'REPO_ROOT="$2"; {function_call}'
            args = [bash_executable(), "-c", f'source "$1"; {function_call}', "--", str(DOCTOR_SCRIPT), str(repo_root)]
        else:
            args = [bash_executable(), "-c", f'source "$1"; {function_call}', "--", str(DOCTOR_SCRIPT)]
        return subprocess.run(
            args,
            env=env,
            capture_output=True,
            encoding="utf-8",
            text=True,
        )

    def test_finish_rekt_parse_returns_success_when_no_program_failed(self):
        result = self.run_function("finish_rekt_parse 0")

        self.assertEqual(0, result.returncode, result.stderr)

    def test_finish_rekt_parse_returns_failure_when_any_program_failed(self):
        result = self.run_function("finish_rekt_parse 1")

        self.assertEqual(1, result.returncode)
        self.assertIn("REKT parse failed for 1 program", result.stdout)

    def test_prepare_rekt_output_dir_creates_host_bind_mount_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            result = self.run_function("prepare_rekt_output_dir", repo_root=repo_root)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((repo_root / "output" / "rekt").is_dir())


if __name__ == "__main__":
    unittest.main()
