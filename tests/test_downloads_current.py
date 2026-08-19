"""Guard the files the portal hands to participants.

`portal/downloads/` is a copy of the repository-root sources. It drifted once:
the portal was serving a `create_ncdf.py` that still produced the previous
naming convention, so anything a participant generated from it would have been
rejected on upload. These tests fail loudly instead.
"""
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DownloadsCurrentTests(unittest.TestCase):
    def test_downloaded_files_match_the_sources(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "sync_downloads.py"), "--check"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=180,
            cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_served_template_uses_the_current_experiment_ids(self):
        if not shutil.which("ncdump"):
            self.skipTest("ncdump is not installed")
        sys.path.insert(0, str(ROOT / "portal" / "backend"))
        import rumi_protocol

        proc = subprocess.run(
            ["ncdump", "-h", str(ROOT / "portal" / "downloads" / "RUMI_template_2d.nc")],
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        )
        experiment = next(
            line.split('"')[1]
            for line in proc.stdout.splitlines()
            if ":experiment =" in line
        )
        self.assertIn(experiment, rumi_protocol.EXPERIMENTS)


if __name__ == "__main__":
    unittest.main()
