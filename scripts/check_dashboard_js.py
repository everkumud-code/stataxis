#!/usr/bin/env python3
"""Validate inline JavaScript in dashboard HTML files with Node's parser."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_RE = re.compile(r"<script(?:\s[^>]*)?>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures = 0
    checked = 0

    for html_path in sorted((root / "dashboard").glob("*.html")):
        source = html_path.read_text(encoding="utf-8")
        for index, match in enumerate(SCRIPT_RE.finditer(source), start=1):
            checked += 1
            code = match.group(1)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".js", delete=False
            ) as handle:
                handle.write(code)
                script_path = Path(handle.name)
            try:
                result = subprocess.run(
                    ["node", "--check", str(script_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                script_path.unlink(missing_ok=True)
            if result.returncode != 0:
                failures += 1
                print(f"{html_path}:{index}: JavaScript syntax error")
                if result.stderr:
                    print(result.stderr.rstrip())

    if failures:
        print(f"Dashboard JavaScript check failed: {failures} inline script(s)")
        return 1

    print(f"Dashboard JavaScript syntax check passed: {checked} inline script(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
