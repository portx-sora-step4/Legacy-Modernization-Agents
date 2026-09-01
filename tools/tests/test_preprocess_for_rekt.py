#!/usr/bin/env python3
import os
import shutil
import subprocess
import unicodedata
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "preprocess-for-rekt.sh"


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
WORK_ROOT = REPO_ROOT / "tools" / "tests" / "_work"


class PreprocessForRektTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        self.work_dir = WORK_ROOT / self._testMethodName
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)
        self.work_dir.mkdir()
        self.source_dir = self.work_dir / "source with 'quotes and spaces"
        self.source_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)
        if WORK_ROOT.exists() and not any(WORK_ROOT.iterdir()):
            WORK_ROOT.rmdir()

    def run_preprocessor(self):
        env = os.environ.copy()
        env["REKT_NO_STUB_COPYBOOKS"] = "true"
        command = [str(SCRIPT_PATH), str(self.source_dir)]
        if os.name == "nt":
            command.insert(0, bash_executable())
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            check=True,
            encoding="utf-8",
            text=True,
        )

    def preprocessed_text(self, filename, encoding="latin-1"):
        return (self.source_dir / ".preprocessed" / filename).read_text(
            encoding=encoding
        )

    @staticmethod
    def as_cobol_comment(line):
        return f"{line[:6]}*{line[7:]}" if len(line) >= 7 else f"*{line}"

    def test_handles_quotes_and_spaces_in_program_and_copybook_paths(self):
        copybook_dir = self.source_dir / "copybooks 'quoted'"
        program_dir = self.source_dir / "programs 'quoted'"
        copybook_dir.mkdir()
        program_dir.mkdir()

        copybook_name = "quoted ' copybook.cpy"
        program_name = "quoted ' program.cbl"

        (copybook_dir / copybook_name).write_text(
            "\n".join(
                [
                    "       01  SAMPLE-FIELD COMP-2.",
                    "",
                ]
            ),
            encoding="latin-1",
        )
        (program_dir / program_name).write_text(
            "\n".join(
                [
                    "       IDENTIFICATION DIVISION.",
                    "       PROGRAM-ID. QUOTEDP.",
                    "       DATA DIVISION.",
                    "       WORKING-STORAGE SECTION.",
                    "       01  WS-FLAG PIC 9.",
                    "       PROCEDURE DIVISION.",
                    "           MOVE 0(1) TO WS-FLAG.",
                    "           GOBACK.",
                    "",
                ]
            ),
            encoding="latin-1",
        )

        result = self.run_preprocessor()

        self.assertIn("Preprocessed 1 program(s) and 1 copybook(s)", result.stdout)
        self.assertIn("PIC X(8)", self.preprocessed_text(copybook_name))
        self.assertIn("MOVE 0 TO WS-FLAG.", self.preprocessed_text(program_name))

    def test_preserves_unsupported_in_conditions_as_opaque(self):
        arithmetic_if = "           IF WS-VALUE IN WS-GROUP + 1"
        arithmetic_and = "              AND WS-OTHER = 1"
        comparison_if = "           IF WS-VALUE IN WS-GROUP > 1"
        opaque_if = "           IF REKT-OPAQUE-IN-CONDITION"

        (self.source_dir / "unsupported-in.cbl").write_text(
            "\n".join(
                [
                    "       IDENTIFICATION DIVISION.",
                    "       PROGRAM-ID. INQUAL.",
                    "       PROCEDURE DIVISION.",
                    arithmetic_if,
                    arithmetic_and,
                    "               DISPLAY 'ARITH'.",
                    "           END-IF.",
                    comparison_if,
                    "               DISPLAY 'COMPARE'.",
                    "           END-IF.",
                    "           GOBACK.",
                    "",
                ]
            ),
            encoding="latin-1",
        )

        self.run_preprocessor()
        output = self.preprocessed_text("unsupported-in.cbl")

        self.assertNotIn("IF TRUE", output)
        self.assertEqual(2, output.count(opaque_if))
        self.assertIn(
            "\n".join(
                [
                    self.as_cobol_comment(arithmetic_if),
                    self.as_cobol_comment(arithmetic_and),
                    opaque_if,
                ]
            ),
            output,
        )
        self.assertIn(
            "\n".join(
                [
                    self.as_cobol_comment(comparison_if),
                    opaque_if,
                ]
            ),
            output,
        )

    def test_preserves_utf8_text_and_strips_fixed_format_sequence_area(self):
        content = "       01  WS-LABEL PIC X(20) VALUE '港在庫一覧表'."
        fixed_format_line = content.ljust(72) + "00007500"
        fixed_format_comment = "  |   * change-history comment".ljust(72) + "00007500"
        unicode_prefix = "               ' 入力して下さい。 '"
        while sum(
            2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
            for char in unicode_prefix
        ) < 72:
            unicode_prefix += " "
        unicode_fixed_format_line = unicode_prefix + "00010700"
        (self.source_dir / "utf8-fixed-format.cbl").write_text(
            "\n".join(
                [
                    "       IDENTIFICATION DIVISION.",
                    "       PROGRAM-ID. UTF8TEST.",
                    "       DATA DIVISION.",
                    "       WORKING-STORAGE SECTION.",
                    fixed_format_line,
                    fixed_format_comment,
                    unicode_fixed_format_line,
                    "       PROCEDURE DIVISION.",
                    "           GOBACK.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self.run_preprocessor()
        output = self.preprocessed_text("utf8-fixed-format.cbl", encoding="utf-8")

        self.assertIn("港在庫一覧表", output)
        self.assertNotIn("00007500", output)
        self.assertNotIn("00010700", output)
        self.assertNotIn("æ¸¯", output)


if __name__ == "__main__":
    unittest.main()
