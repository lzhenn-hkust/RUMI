import datetime as dt
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "portal" / "backend"))

import portal_lib  # noqa: E402
import rumi_protocol  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures shared across the three test groups below.
# ---------------------------------------------------------------------------

STEM = "HKUST-MPAS-HRAIN2025-LIU-CONFIG01-r01"
ARCHIVE_NAME = f"{STEM}.zip"
EXPERIMENT = "ERA5-AN"
MODEL = "MPAS"
EVENT = "HRAIN2025"
DOC_MEMBER = f"{STEM}/Participant_Model_Documentation.pdf"

# The required ~1 km / sub-km hourly series for HRAIN2025, taken straight from
# rumi_protocol so the test data can never silently drift from the protocol
# module it is meant to exercise.
KM_SERIES = rumi_protocol.expected_timestamps("HRAIN2025", "km")
SUBKM_SERIES = rumi_protocol.expected_timestamps("HRAIN2025", "subkm")


def stamp_from_iso(iso):
    return rumi_protocol.parse_utc(iso).strftime("%Y%m%d%H%M%S")


def nc_filename(experiment, model, event, iso):
    """Build a v3 NetCDF file name: <experiment>-<Model>-<Event>-<stamp>.nc."""
    return f"{experiment}-{model}-{event}-{stamp_from_iso(iso)}.nc"


def nc_path(stem, dir_experiment, init_label, model, event, iso, file_experiment=None):
    """Build a full <stem>/<EXPERIMENT>/<Init-*>/<file>.nc archive member path.

    ``file_experiment`` lets a test encode a different experiment into the
    file name itself than the directory it is placed under, to exercise the
    "file name must match its directory" checks.
    """
    experiment_for_name = file_experiment or dir_experiment
    name = nc_filename(experiment_for_name, model, event, iso)
    return f"{stem}/{dir_experiment}/{init_label}/{name}"


def build_members(timestamps, attribute, attribute_value, resolution="1 km"):
    """Build ``validate_init_directory`` member dicts sharing one attribute value."""
    return [
        {
            "name": f"member-{index}.nc",
            "timestamp": ts,
            "time_metadata": {attribute: attribute_value, "horizontal_resolution": resolution},
        }
        for index, ts in enumerate(timestamps)
    ]


def clean_validate_netcdf(path, filename, metadata):
    """A stand-in for validate_netcdf that always reports a clean AN/Init-0 file."""
    return {
        "errors": [],
        "warnings": [],
        "summary": {
            "time_metadata": {
                "simulation_start_time": "2025-08-03T00:00:00Z",
                "initialization_time": "2025-08-03T00:00:00Z",
                "forecast_initialization_time": "",
                "forecast_lead_time_hours": "72",
                "horizontal_resolution": "1 km",
            }
        },
    }


class RumiTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def make_zip(self, filename, members):
        """members: iterable of (arcname, bytes) written into a fresh zip file."""
        path = self.dir / filename
        with zipfile.ZipFile(path, "w") as archive:
            for arcname, content in members:
                archive.writestr(arcname, content)
        return path

    def assert_message(self, messages, fragment):
        self.assertTrue(
            any(fragment in message for message in messages),
            f"{fragment!r} not found in {messages}",
        )

    def assert_no_message(self, messages, fragment):
        self.assertFalse(
            any(fragment in message for message in messages),
            f"{fragment!r} unexpectedly found in {messages}",
        )


# ---------------------------------------------------------------------------
# Structure layer: validate_archive_structure() / validate_archive() acting
# only on member paths.
# ---------------------------------------------------------------------------


class ArchiveStructureTests(RumiTestCase):
    def test_valid_archive_passes(self):
        names = [DOC_MEMBER] + [
            nc_path(STEM, EXPERIMENT, "Init-0", MODEL, EVENT, ts) for ts in KM_SERIES
        ]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["layout"]), len(KM_SERIES))

    def test_bad_archive_name_is_rejected(self):
        result = portal_lib.validate_archive_structure([], "submission.tar.gz")

        self.assert_message(
            result["errors"],
            "Archive name must be <INSTITUTE>-<MODEL>-<EVENT>-<POC>-<CONFIG>-r<NN>",
        )

    def test_hyphen_in_model_token_is_rejected(self):
        result = portal_lib.validate_archive_structure(
            [], "HKUST-WRF-ARW-HRAIN2025-LIU-C01-r01.zip"
        )

        self.assert_message(
            result["errors"],
            "Archive name must be <INSTITUTE>-<MODEL>-<EVENT>-<POC>-<CONFIG>-r<NN>",
        )

    def test_lead_directory_is_rejected(self):
        names = [
            DOC_MEMBER,
            f"{STEM}/{EXPERIMENT}/lead_024h/"
            f"{nc_filename(EXPERIMENT, MODEL, EVENT, KM_SERIES[0])}",
        ]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assert_message(result["errors"], "Initialization directories must be Init-5")

    def test_reversed_experiment_dir_is_rejected(self):
        names = [
            DOC_MEMBER,
            f"{STEM}/AN-ERA5/Init-0/{nc_filename(EXPERIMENT, MODEL, EVENT, KM_SERIES[0])}",
        ]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assert_message(result["errors"], "canonical RUMI identifier")

    def test_wrong_nesting_depth_is_rejected(self):
        names = [
            DOC_MEMBER,
            f"{STEM}/{EXPERIMENT}/{nc_filename(EXPERIMENT, MODEL, EVENT, KM_SERIES[0])}",
        ]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assert_message(result["errors"], "Every NetCDF file must be stored as")

    def test_two_top_level_directories_rejected(self):
        names = [
            nc_path(STEM, EXPERIMENT, "Init-0", MODEL, EVENT, KM_SERIES[0]),
            f"OtherDir/{nc_filename(EXPERIMENT, MODEL, EVENT, KM_SERIES[1])}",
        ]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assert_message(result["errors"], "exactly one top-level directory")

    def test_top_directory_must_match_archive_name(self):
        names = [
            "WrongTop/Participant_Model_Documentation.pdf",
            f"WrongTop/{EXPERIMENT}/Init-0/"
            f"{nc_filename(EXPERIMENT, MODEL, EVENT, KM_SERIES[0])}",
        ]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assert_message(result["errors"], f"named {STEM}")

    def test_mixed_events_rejected(self):
        names = [
            DOC_MEMBER,
            nc_path(STEM, EXPERIMENT, "Init-0", MODEL, EVENT, KM_SERIES[0]),
            nc_path(STEM, EXPERIMENT, "Init-0", MODEL, "HEAT2024", "2022-07-22T00:00:00Z"),
        ]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assert_message(result["errors"], "An archive holds one event only")

    def test_filename_model_must_match_archive_model(self):
        names = [
            DOC_MEMBER,
            nc_path(STEM, EXPERIMENT, "Init-0", "WRF", EVENT, KM_SERIES[0]),
        ]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assert_message(result["errors"], "does not match the archive model")

    def test_filename_experiment_must_match_directory(self):
        names = [
            DOC_MEMBER,
            nc_path(
                STEM,
                EXPERIMENT,
                "Init-0",
                MODEL,
                EVENT,
                KM_SERIES[0],
                file_experiment="GFS-FC",
            ),
        ]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assert_message(result["errors"], "does not match the experiment directory")

    def test_missing_documentation_is_error(self):
        names = [nc_path(STEM, EXPERIMENT, "Init-0", MODEL, EVENT, KM_SERIES[0])]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assert_message(result["errors"], "Participant_Model_Documentation")

    def test_unsafe_paths_rejected(self):
        names = [DOC_MEMBER, f"{STEM}/../evil.txt"]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assert_message(result["errors"], "unsafe paths")

    def test_absolute_init_directory_accepted(self):
        names = [
            DOC_MEMBER,
            nc_path(STEM, EXPERIMENT, "Init-2025080300", MODEL, EVENT, KM_SERIES[0]),
        ]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assertEqual(result["errors"], [])

    def test_invalid_absolute_init_directory_rejected(self):
        names = [
            DOC_MEMBER,
            nc_path(STEM, EXPERIMENT, "Init-2025083200", MODEL, EVENT, KM_SERIES[0]),
        ]
        result = portal_lib.validate_archive_structure(names, ARCHIVE_NAME)

        self.assert_message(result["errors"], "Initialization directories must be Init-5")

    def test_structure_errors_skip_per_file_checks(self):
        bad_member = (
            f"{STEM}/{EXPERIMENT}/{nc_filename(EXPERIMENT, MODEL, EVENT, KM_SERIES[0])}"
        )
        zip_path = self.make_zip(
            ARCHIVE_NAME,
            [(DOC_MEMBER, b"%PDF-1.4 fake"), (bad_member, b"fake netcdf bytes")],
        )
        metadata = {"experiment": EXPERIMENT, "model": MODEL, "event": EVENT}
        validator = mock.Mock(side_effect=clean_validate_netcdf)

        with mock.patch.object(portal_lib, "validate_netcdf", validator):
            result = portal_lib.validate_archive(zip_path, ARCHIVE_NAME, metadata)

        validator.assert_not_called()
        self.assert_message(result["errors"], "Every NetCDF file must be stored as")
        self.assert_message(result["warnings"], "Per-file checks were skipped")


# ---------------------------------------------------------------------------
# Init directory layer: validate_init_directory() called directly.
# ---------------------------------------------------------------------------


class InitDirectoryTests(RumiTestCase):
    def test_missing_final_timestamp_is_error(self):
        members = build_members(KM_SERIES[:-1], "initialization_time", KM_SERIES[0])

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "ERA5-AN", "Init-0", members
        )

        self.assert_message(result["errors"], "required final timestamp")

    def test_missing_first_timestamp_is_warning(self):
        members = build_members(KM_SERIES[1:], "initialization_time", KM_SERIES[0])

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "ERA5-AN", "Init-0", members
        )

        self.assert_message(result["warnings"], "required period starts at")
        self.assert_no_message(result["errors"], "required period starts at")
        self.assertEqual(result["errors"], [])

    def test_hourly_gap_is_warning(self):
        gapped = KM_SERIES[:10] + KM_SERIES[13:]
        members = build_members(gapped, "initialization_time", KM_SERIES[0])

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "ERA5-AN", "Init-0", members
        )

        self.assert_message(result["warnings"], "3 hourly timestamps are missing")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["coverage"]["missing"], 3)

    def test_many_missing_timestamps_are_truncated(self):
        gapped = KM_SERIES[:10] + KM_SERIES[30:]
        members = build_members(gapped, "initialization_time", KM_SERIES[0])

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "ERA5-AN", "Init-0", members
        )

        self.assertEqual(result["coverage"]["missing"], 20)
        self.assert_message(result["warnings"], "20 hourly timestamps are missing")
        self.assert_message(result["warnings"], "and 10 more")

    def test_duplicate_timestamp_is_error(self):
        members = build_members(KM_SERIES, "initialization_time", KM_SERIES[0])
        duplicate = dict(members[5])
        duplicate["name"] = "duplicate-of-5.nc"
        members = members + [duplicate]

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "ERA5-AN", "Init-0", members
        )

        self.assert_message(result["errors"], "two files carry the timestamp")

    def test_fc_initialization_exact_match_is_clean(self):
        expected_init = rumi_protocol.INIT_TIMES["HRAIN2025"]["Init-1"]
        timestamps = rumi_protocol.expected_timestamps("HRAIN2025", "km", expected_init)
        members = build_members(timestamps, "forecast_initialization_time", expected_init)

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "GFS-FC", "Init-1", members
        )

        self.assertEqual(result["errors"], [])
        self.assert_no_message(result["warnings"], "nearest available forecast cycle")

    def test_fc_initialization_within_6h_is_warning(self):
        expected_init = rumi_protocol.INIT_TIMES["HRAIN2025"]["Init-1"]
        actual_init = rumi_protocol.iso_z(
            rumi_protocol.parse_utc(expected_init) + dt.timedelta(hours=3)
        )
        timestamps = rumi_protocol.expected_timestamps("HRAIN2025", "km", actual_init)
        members = build_members(timestamps, "forecast_initialization_time", actual_init)

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "GFS-FC", "Init-1", members
        )

        self.assertEqual(result["errors"], [])
        self.assert_message(result["warnings"], "nearest available forecast cycle")

    def test_fc_initialization_beyond_6h_is_error(self):
        expected_init = rumi_protocol.INIT_TIMES["HRAIN2025"]["Init-1"]
        actual_init = rumi_protocol.iso_z(
            rumi_protocol.parse_utc(expected_init) + dt.timedelta(hours=30)
        )
        # Once the offset exceeds tolerance, validate_init_directory falls
        # back to the canonical Init-1 time to compute required coverage.
        timestamps = rumi_protocol.expected_timestamps("HRAIN2025", "km", expected_init)
        members = build_members(timestamps, "forecast_initialization_time", actual_init)

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "GFS-FC", "Init-1", members
        )

        self.assert_message(result["errors"], "30 hours from the Init-1 time")

    def test_provisional_init_label_beyond_tolerance_is_a_warning(self):
        self.assertIn("Init-0.25", rumi_protocol.PROVISIONAL_INIT_LABELS)
        expected_init = rumi_protocol.INIT_TIMES["HRAIN2025"]["Init-0.25"]
        actual_init = rumi_protocol.iso_z(
            rumi_protocol.parse_utc(expected_init) + dt.timedelta(hours=30)
        )
        # Provisional labels do not fall back to the canonical time, so the
        # member files (and the required coverage derived from them) follow
        # the declared actual_init, not the nominal Init-0.25 time.
        timestamps = rumi_protocol.expected_timestamps("HRAIN2025", "km", actual_init)
        members = build_members(timestamps, "forecast_initialization_time", actual_init)

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "GFS-FC", "Init-0.25", members
        )

        self.assertEqual(result["errors"], [])
        self.assert_message(result["warnings"], "provisional")

    def test_regular_init_label_beyond_tolerance_is_still_an_error(self):
        self.assertNotIn("Init-1", rumi_protocol.PROVISIONAL_INIT_LABELS)
        expected_init = rumi_protocol.INIT_TIMES["HRAIN2025"]["Init-1"]
        actual_init = rumi_protocol.iso_z(
            rumi_protocol.parse_utc(expected_init) + dt.timedelta(hours=30)
        )
        timestamps = rumi_protocol.expected_timestamps("HRAIN2025", "km", expected_init)
        members = build_members(timestamps, "forecast_initialization_time", actual_init)

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "GFS-FC", "Init-1", members
        )

        self.assert_message(result["errors"], "30 hours from the Init-1 time")
        self.assert_no_message(result["warnings"], "provisional")

    def test_an_init0_inconsistent_init_times_rejected(self):
        members = [
            {
                "name": "a.nc",
                "timestamp": KM_SERIES[0],
                "time_metadata": {
                    "initialization_time": "2025-08-03T00:00:00Z",
                    "horizontal_resolution": "1 km",
                },
            },
            {
                "name": "b.nc",
                "timestamp": KM_SERIES[-1],
                "time_metadata": {
                    "initialization_time": "2025-08-03T06:00:00Z",
                    "horizontal_resolution": "1 km",
                },
            },
        ]

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "ERA5-AN", "Init-0", members
        )

        self.assert_message(result["errors"], "must declare the same initialization_time")

    def test_absolute_init_dir_must_match_attribute(self):
        members = build_members(KM_SERIES, "initialization_time", "2025-08-01T00:00:00Z")

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "ERA5-AN", "Init-2025080300", members
        )

        self.assert_message(result["errors"], "hours from the Init-2025080300 time")

    def test_subkm_resolution_selects_shorter_period(self):
        self.assertEqual(len(SUBKM_SERIES), 28)
        members = build_members(
            SUBKM_SERIES, "initialization_time", SUBKM_SERIES[0], resolution="500 m"
        )

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "ERA5-AN", "Init-0", members
        )

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["coverage"]["category"], "subkm")

    def test_unparseable_resolution_warns_and_assumes_km(self):
        members = build_members(
            KM_SERIES, "initialization_time", KM_SERIES[0], resolution="high"
        )

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "ERA5-AN", "Init-0", members
        )

        self.assert_message(result["warnings"], "could not be interpreted")
        self.assertEqual(result["coverage"]["category"], "km")

    def test_staggered_fc_start_follows_actual_initialization(self):
        expected_init = rumi_protocol.INIT_TIMES["HRAIN2025"]["Init-0.25"]
        timestamps = rumi_protocol.expected_timestamps("HRAIN2025", "km", expected_init)
        self.assertEqual(len(timestamps), 34)
        members = build_members(timestamps, "forecast_initialization_time", expected_init)

        result = portal_lib.validate_init_directory(
            "HRAIN2025", "GFS-FC", "Init-0.25", members
        )

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["coverage"]["expected"], 34)


# ---------------------------------------------------------------------------
# Full pipeline layer: validate_archive() over a real zip, validate_netcdf
# mocked out.
# ---------------------------------------------------------------------------


class ArchiveFlowTests(RumiTestCase):
    def build_valid_archive_zip(self, extra_members=None):
        members = [(DOC_MEMBER, b"%PDF-1.4 fake pdf content")]
        for ts in KM_SERIES:
            members.append(
                (nc_path(STEM, EXPERIMENT, "Init-0", MODEL, EVENT, ts), b"fake netcdf bytes")
            )
        if extra_members:
            members.extend(extra_members)
        return self.make_zip(ARCHIVE_NAME, members)

    def run_validate_archive(self, extra_members=None, progress=None, validator_side_effect=None):
        zip_path = self.build_valid_archive_zip(extra_members)
        metadata = {"experiment": EXPERIMENT, "model": MODEL, "event": EVENT}
        validator = mock.Mock(side_effect=validator_side_effect or clean_validate_netcdf)
        with mock.patch.object(portal_lib, "validate_netcdf", validator):
            result = portal_lib.validate_archive(
                zip_path, ARCHIVE_NAME, metadata, progress=progress
            )
        return result, validator

    def test_progress_callback_reports_each_file(self):
        calls = []
        result, _ = self.run_validate_archive(
            progress=lambda done, total: calls.append((done, total))
        )

        self.assertEqual(result["errors"], [])
        self.assertEqual(calls[-1], (len(KM_SERIES), len(KM_SERIES)))

    def test_summary_reports_experiments_and_inits(self):
        result, _ = self.run_validate_archive()

        self.assertEqual(result["errors"], [])
        init0 = result["summary"]["experiments"][EXPERIMENT]["Init-0"]
        self.assertEqual(init0["files"], len(KM_SERIES))
        self.assertIn("required_end", init0)
        self.assertIn("category", init0)

    def test_summary_keeps_ui_contract_keys(self):
        result, _ = self.run_validate_archive()

        summary = result["summary"]
        for key in ("checked_netcdf_files", "passed_netcdf_files", "rules_version"):
            self.assertIn(key, summary)
        self.assertEqual(summary["checked_netcdf_files"], len(KM_SERIES))
        self.assertEqual(summary["passed_netcdf_files"], len(KM_SERIES))
        self.assertEqual(summary["rules_version"], rumi_protocol.RULES_VERSION)

    def test_manifest_version_mismatch_is_warning(self):
        manifest = json.dumps({"rules_version": "old-version"}).encode("utf-8")

        result, _ = self.run_validate_archive(
            extra_members=[(f"{STEM}/rumi_manifest.json", manifest)]
        )

        self.assert_message(result["warnings"], "old-version")
        self.assert_message(result["warnings"], "download rumi_validate.py again")

    def test_manifest_matching_version_is_clean(self):
        manifest = json.dumps({"rules_version": rumi_protocol.RULES_VERSION}).encode("utf-8")

        result, _ = self.run_validate_archive(
            extra_members=[(f"{STEM}/rumi_manifest.json", manifest)]
        )

        self.assert_no_message(result["warnings"], "download rumi_validate.py again")
        self.assertIn("manifest", result["summary"])
        self.assertEqual(
            result["summary"]["manifest"]["rules_version"], rumi_protocol.RULES_VERSION
        )

    def test_archive_without_netcdf_is_rejected(self):
        zip_path = self.make_zip(ARCHIVE_NAME, [(DOC_MEMBER, b"%PDF-1.4 fake pdf content")])
        metadata = {"experiment": EXPERIMENT, "model": MODEL, "event": EVENT}
        validator = mock.Mock(side_effect=clean_validate_netcdf)

        with mock.patch.object(portal_lib, "validate_netcdf", validator):
            result = portal_lib.validate_archive(zip_path, ARCHIVE_NAME, metadata)

        self.assert_message(result["errors"], "does not contain any .nc files")


if __name__ == "__main__":
    unittest.main()


class RealNetcdfArchiveTests(unittest.TestCase):
    """Drive validate_archive with the real reader, not a mocked one.

    Every other archive test patches ``validate_netcdf`` so it can run fast and
    without a NetCDF toolchain. That blind spot let a real defect ship: the
    portal stores ``experiment = "(archive)"`` for archive uploads, passed that
    archive-level metadata down to every member file, and so compared each
    file's ``ERA5-AN`` against the placeholder and rejected every submission.
    The structure checks and the local validator both passed, so nothing else
    would have caught it. This test opens actual NetCDF files.
    """

    @classmethod
    def setUpClass(cls):
        try:
            portal_lib.ncdump_executable()
        except Exception as exc:  # noqa: BLE001 - any failure means no toolchain
            raise unittest.SkipTest(f"no usable ncdump: {exc}")
        try:
            import netCDF4  # noqa: F401, PLC0415
        except ImportError:
            raise unittest.SkipTest("netCDF4 is needed to write the fixture")
        sys.path.insert(0, str(ROOT / "tests"))
        from fixtures.make_fixture_archive import make_fixture  # noqa: PLC0415

        cls._tmp = tempfile.TemporaryDirectory()
        cls.result = make_fixture(
            cls._tmp.name,
            hours=4,
            real_netcdf=True,
            archive="tar.gz",
        )
        cls.archive = cls.result["archive"]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_archive_metadata_does_not_reject_every_member(self):
        """The experiment must be read per directory, not from the upload row."""
        result = portal_lib.validate_archive(
            self.archive,
            self.archive.name,
            # Exactly what api.cgi writes into uploads.metadata_json for an
            # archive: the experiment cannot be one value for the whole file.
            {"experiment": "(archive)", "model": MODEL, "event": EVENT},
        )
        self.assertEqual(
            result["errors"],
            [],
            "a well-formed archive of real NetCDF files must validate cleanly",
        )
        self.assertGreater(result["summary"]["checked_netcdf_files"], 0)
        self.assertEqual(
            result["summary"]["checked_netcdf_files"],
            result["summary"]["passed_netcdf_files"],
        )

    def test_portal_and_shipped_validator_agree(self):
        """A disagreement here means the two have drifted apart."""
        import subprocess  # noqa: PLC0415

        portal_result = portal_lib.validate_archive(
            self.archive,
            self.archive.name,
            {"experiment": "(archive)", "model": MODEL, "event": EVENT},
        )
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "portal" / "downloads" / "rumi_validate.py"),
                "--json",
                str(self.archive),
            ],
            capture_output=True,
            text=True,
        )
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        local = json.loads(proc.stdout)
        self.assertEqual(
            bool(portal_result["errors"]),
            bool(local["errors"]),
            "portal and rumi_validate.py disagree on whether this archive is "
            f"acceptable:\nportal={portal_result['errors']}\nlocal={local['errors']}",
        )
