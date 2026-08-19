"""Run the browser-side upload harness from the one test command everyone uses.

The resumable upload logic lives in portal/assets/app.js and cannot be reached
from Python. tests/js/resumable_upload_test.js drives the real app.js against a
scripted fetch and a fake DOM; this wrapper keeps it inside
`python3 -m unittest discover -s tests` so it cannot quietly rot.
"""
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "js" / "resumable_upload_test.js"


class BrowserUploadTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_resumable_upload_harness_passes(self):
        proc = subprocess.run(
            ["node", str(HARNESS)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
            cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("ALL CHECKS PASSED", proc.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_app_js_parses(self):
        proc = subprocess.run(
            ["node", "--check", str(ROOT / "portal" / "assets" / "app.js")],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)


if __name__ == "__main__":
    unittest.main()
