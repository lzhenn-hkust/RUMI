"""Tests for the downloadable single-file local validator.

These tests exercise the *generated* ``portal/downloads/rumi_validate.py``
as an external participant would run it: via ``subprocess`` with
``sys.executable``, never by importing it as a module. This is deliberate --
the whole point of the file is that it works standalone, with no access to
the rest of this repository (or even the ``rumi_protocol`` module on
``sys.path``).

``tools/build_validator.py --check`` (exercised by
``test_generated_file_is_up_to_date``) is the guard that keeps the generated
file in sync with ``portal/backend/rumi_protocol.py`` -- if someone edits a
rule there and forgets to regenerate, this test fails.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from fixtures.make_fixture_archive import make_fixture  # noqa: E402

sys.path.insert(0, str(ROOT / "portal" / "backend"))
import rumi_protocol  # noqa: E402


BUILD_SCRIPT = ROOT / "tools" / "build_validator.py"
GENERATED = ROOT / "portal" / "downloads" / "rumi_validate.py"


def run_validator(args, cwd=None, timeout=120):
    """Run the generated rumi_validate.py in a subprocess, as a participant would."""
    return subprocess.run(
        [sys.executable, str(GENERATED)] + list(args),
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
    )


def ncdump_available():
    return shutil.which("ncdump") is not None


def netcdf4_available():
    return importlib.util.find_spec("netCDF4") is not None


class LocalValidatorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    # -- Build freshness -----------------------------------------------------

    def test_generated_file_is_up_to_date(self):
        """rumi_protocol.py rule changes must be regenerated into rumi_validate.py."""
        proc = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"generated validator is stale; run tools/build_validator.py\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}",
        )

    # -- Clean / broken submissions -------------------------------------------

    def test_clean_directory_exits_zero(self):
        fixture = make_fixture(
            self.dir,
            tree=["ERA5-AN/Init-0"],
            hours=4,
            real_netcdf=True,
        )
        proc = run_validator([str(fixture["root"])])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("RESULT: PASS", proc.stdout)

    def test_missing_final_timestamp_exits_one(self):
        fixture = make_fixture(
            self.dir,
            tree=["ERA5-AN/Init-0"],
            hours=4,
            drop_last=True,
            real_netcdf=True,
        )
        proc = run_validator([str(fixture["root"])])
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("final timestamp", proc.stdout)

    def test_bad_structure_skips_netcdf_reading(self):
        fixture = make_fixture(
            self.dir,
            tree=["ERA5-AN/Init-0"],
            hours=2,
            real_netcdf=False,
        )
        root = fixture["root"]
        init_dir = root / "ERA5-AN" / "Init-0"
        experiment_dir = root / "ERA5-AN"
        for nc_file in init_dir.glob("*.nc"):
            nc_file.rename(experiment_dir / nc_file.name)
        init_dir.rmdir()

        proc = run_validator([str(root)])
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("must be stored as", proc.stdout)
        # The placeholder ("not a real NetCDF file") files would fail any
        # NetCDF-level check; their absence from the report confirms no
        # NetCDF reading was attempted once the structure check failed.
        self.assertNotIn("NetCDF file could not be read", proc.stdout)

    # -- Output shapes ---------------------------------------------------------

    def test_json_output_shape(self):
        fixture = make_fixture(
            self.dir,
            tree=["ERA5-AN/Init-0"],
            hours=4,
            real_netcdf=True,
        )
        proc = run_validator(["--json", str(fixture["root"])])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        for key in ("rules_version", "errors", "warnings", "coverage"):
            self.assertIn(key, payload, f"missing key {key!r} in JSON payload: {payload}")
        self.assertEqual(payload["rules_version"], rumi_protocol.RULES_VERSION)
        self.assertIn("ERA5-AN/Init-0", payload["coverage"])

    def test_reports_rules_version(self):
        fixture = make_fixture(
            self.dir,
            tree=["ERA5-AN/Init-0"],
            hours=4,
            real_netcdf=True,
        )
        proc = run_validator([str(fixture["root"])])
        self.assertIn(rumi_protocol.RULES_VERSION, proc.stdout)

    # -- Manifest ---------------------------------------------------------------

    def test_write_manifest_only_on_success(self):
        clean = make_fixture(
            self.dir / "clean",
            tree=["ERA5-AN/Init-0"],
            hours=4,
            real_netcdf=True,
        )
        proc = run_validator(
            ["--write-manifest", "--participants", "A. One, B. Two", str(clean["root"])]
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        manifest_path = clean["root"] / "rumi_manifest.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["rules_version"], rumi_protocol.RULES_VERSION)
        self.assertEqual(manifest["participants"], "A. One, B. Two")
        init0 = manifest["experiments"]["ERA5-AN"]["Init-0"]
        self.assertEqual(init0["files"], 4)
        self.assertEqual(len(init0["sha256"]), 4)
        for digest in init0["sha256"].values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

        broken = make_fixture(
            self.dir / "broken",
            tree=["ERA5-AN/Init-0"],
            hours=4,
            drop_last=True,
            real_netcdf=True,
        )
        proc = run_validator(["--write-manifest", str(broken["root"])])
        self.assertEqual(proc.returncode, 1)
        self.assertFalse((broken["root"] / "rumi_manifest.json").exists())

    def test_manifest_is_idempotent(self):
        fixture = make_fixture(
            self.dir,
            tree=["ERA5-AN/Init-0"],
            hours=4,
            real_netcdf=True,
        )
        first = run_validator(["--write-manifest", str(fixture["root"])])
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = run_validator(["--write-manifest", str(fixture["root"])])
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

    # -- Reader / input-shape parity ----------------------------------------------

    def test_archive_input_matches_directory_input(self):
        fixture = make_fixture(
            self.dir,
            tree=["ERA5-AN/Init-0"],
            hours=4,
            drop_first=True,
            real_netcdf=True,
            archive="tar.gz",
        )
        dir_proc = run_validator(["--json", str(fixture["root"])])
        archive_proc = run_validator(["--json", str(fixture["archive"])])

        self.assertEqual(dir_proc.returncode, archive_proc.returncode)
        dir_payload = json.loads(dir_proc.stdout)
        archive_payload = json.loads(archive_proc.stdout)
        self.assertEqual(dir_payload["errors"], archive_payload["errors"])
        self.assertEqual(dir_payload["warnings"], archive_payload["warnings"])
        self.assertTrue(dir_payload["warnings"], "expected drop_first to produce a warning")

    def test_ncdump_reader_matches_netcdf4_reader(self):
        if not ncdump_available():
            self.skipTest("ncdump is not available on PATH")
        if not netcdf4_available():
            self.skipTest("the netCDF4 Python package is not installed")

        fixture = make_fixture(
            self.dir,
            tree=["ERA5-AN/Init-0"],
            hours=4,
            real_netcdf=True,
        )
        netcdf4_proc = run_validator(["--json", "--reader", "netcdf4", str(fixture["root"])])
        ncdump_proc = run_validator(["--json", "--reader", "ncdump", str(fixture["root"])])

        self.assertEqual(netcdf4_proc.returncode, 0, netcdf4_proc.stdout + netcdf4_proc.stderr)
        self.assertEqual(ncdump_proc.returncode, 0, ncdump_proc.stdout + ncdump_proc.stderr)
        netcdf4_payload = json.loads(netcdf4_proc.stdout)
        ncdump_payload = json.loads(ncdump_proc.stdout)
        self.assertEqual(netcdf4_payload["errors"], ncdump_payload["errors"])
        self.assertEqual(netcdf4_payload["warnings"], ncdump_payload["warnings"])
        self.assertEqual(netcdf4_payload["coverage"], ncdump_payload["coverage"])


if __name__ == "__main__":
    unittest.main()
