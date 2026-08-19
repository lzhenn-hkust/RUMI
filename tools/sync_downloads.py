#!/usr/bin/env python3
"""Refresh the files the portal hands to participants.

`portal/downloads/` is served to participants, but the sources live at the
repository root. They drifted once already: the portal was still handing out a
script that produced the previous naming convention, so every file a
participant generated from it would have been rejected on upload.

    python3 tools/sync_downloads.py            # refresh
    python3 tools/sync_downloads.py --check    # fail if stale (used by tests)
"""
import argparse
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "portal" / "downloads"
SCRIPT = "create_ncdf.py"
TEMPLATE = "RUMI_template_2d.nc"


def build_template(destination):
    subprocess.run(
        [sys.executable, str(ROOT / SCRIPT), "--template", str(destination)],
        check=True,
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
    )


def template_is_current(path):
    """Compare the served template against a freshly generated one.

    NetCDF files embed no timestamp here, but comparing bytes is still brittle,
    so compare the header text instead.
    """
    if not path.is_file():
        return False
    fresh = ROOT / ".rumi-template-check.nc"
    try:
        build_template(fresh)
        return _header(fresh) == _header(path)
    finally:
        fresh.unlink(missing_ok=True)


VOLATILE = (":history", ":creation_date")


def _header(path):
    """ncdump header with the parts that legitimately differ removed.

    The first line carries the file's own name, and history/creation_date carry
    the generation time, so a byte comparison would always report drift.
    """
    proc = subprocess.run(
        ["ncdump", "-h", str(path)], stdout=subprocess.PIPE, text=True, check=False
    )
    lines = proc.stdout.splitlines()
    if lines and lines[0].startswith("netcdf "):
        lines = lines[1:]
    return "\n".join(
        line for line in lines if not any(token in line for token in VOLATILE)
    )


def main():
    parser = argparse.ArgumentParser(description="Sync portal/downloads/")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    stale = []
    if not filecmp.cmp(ROOT / SCRIPT, DOWNLOADS / SCRIPT, shallow=False):
        stale.append(SCRIPT)
    if not template_is_current(DOWNLOADS / TEMPLATE):
        stale.append(TEMPLATE)

    if args.check:
        if stale:
            print("stale downloads: " + ", ".join(stale), file=sys.stderr)
            print("run: python3 tools/sync_downloads.py", file=sys.stderr)
            return 1
        print("portal/downloads/ is up to date.")
        return 0

    shutil.copy2(ROOT / SCRIPT, DOWNLOADS / SCRIPT)
    build_template(ROOT / TEMPLATE)
    shutil.copy2(ROOT / TEMPLATE, DOWNLOADS / TEMPLATE)
    print(f"refreshed {SCRIPT} and {TEMPLATE} in portal/downloads/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
