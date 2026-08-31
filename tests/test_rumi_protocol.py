import datetime as dt
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "portal" / "backend"))

import rumi_protocol  # noqa: E402


class InitTimeInvariantTests(unittest.TestCase):
    def test_init_half_day_labels_match_peak_offsets(self):
        for event, info in rumi_protocol.EVENTS.items():
            peak_start = rumi_protocol.parse_utc(info["peak_start"])
            expected_half = rumi_protocol.iso_z(peak_start - dt.timedelta(hours=12))
            expected_quarter = rumi_protocol.iso_z(peak_start - dt.timedelta(hours=6))
            self.assertEqual(
                rumi_protocol.INIT_TIMES[event]["Init-0.5"],
                expected_half,
                msg=f"{event} Init-0.5",
            )
            self.assertEqual(
                rumi_protocol.INIT_TIMES[event]["Init-0.25"],
                expected_quarter,
                msg=f"{event} Init-0.25",
            )

    def test_hrain2023_init_times_match_agreed_table(self):
        self.assertEqual(
            rumi_protocol.INIT_TIMES["HRAIN2023"]["Init-0.5"], "2023-09-07T02:00:00Z"
        )
        self.assertEqual(
            rumi_protocol.INIT_TIMES["HRAIN2023"]["Init-0.25"], "2023-09-07T08:00:00Z"
        )

    def test_init_1_is_not_24h_before_peak(self):
        peak_start = rumi_protocol.parse_utc(
            rumi_protocol.EVENTS["HRAIN2023"]["peak_start"]
        )
        init_1 = rumi_protocol.parse_utc(
            rumi_protocol.INIT_TIMES["HRAIN2023"]["Init-1"]
        )
        delta = peak_start - init_1
        self.assertEqual(delta, dt.timedelta(hours=38))
        self.assertNotEqual(delta, dt.timedelta(hours=24))

    def test_every_event_has_all_init_labels(self):
        required_labels = [
            "Init-5",
            "Init-4",
            "Init-3",
            "Init-2",
            "Init-1",
            "Init-0.5",
            "Init-0.25",
        ]
        for event in rumi_protocol.EVENTS:
            self.assertIn(event, rumi_protocol.INIT_TIMES)
            for label in required_labels:
                self.assertIn(
                    label,
                    rumi_protocol.INIT_TIMES[event],
                    msg=f"{event} missing {label}",
                )


class RequiredPeriodTests(unittest.TestCase):
    def test_required_periods_match_agreed_table(self):
        expected = {
            "MANGKHUT2018": {
                "km": ("2018-09-15T00:00:00Z", "2018-09-17T00:00:00Z"),
                "subkm": ("2018-09-16T00:00:00Z", "2018-09-17T00:00:00Z"),
            },
            "HRAIN2023": {
                "km": ("2023-09-06T00:00:00Z", "2023-09-09T00:00:00Z"),
                "subkm": ("2023-09-07T14:00:00Z", "2023-09-08T20:00:00Z"),
            },
            "HRAIN2025": {
                "km": ("2025-08-03T00:00:00Z", "2025-08-06T00:00:00Z"),
                "subkm": ("2025-08-04T21:00:00Z", "2025-08-06T00:00:00Z"),
            },
            "HEAT2022": {
                "km": ("2022-07-22T00:00:00Z", "2022-07-25T00:00:00Z"),
                "subkm": ("2022-07-23T00:00:00Z", "2022-07-25T00:00:00Z"),
            },
            "HEAT2024": {
                "km": ("2024-08-27T00:00:00Z", "2024-08-29T00:00:00Z"),
                "subkm": ("2024-08-28T00:00:00Z", "2024-08-29T00:00:00Z"),
            },
        }
        self.assertEqual(rumi_protocol.REQUIRED_PERIODS, expected)

    def test_subkm_period_starts_at_peak_and_ends_12h_after(self):
        for event, info in rumi_protocol.EVENTS.items():
            peak_start = rumi_protocol.parse_utc(info["peak_start"])
            peak_end = rumi_protocol.parse_utc(info["peak_end"])
            subkm_start, subkm_end = rumi_protocol.REQUIRED_PERIODS[event]["subkm"]
            self.assertEqual(
                subkm_start,
                rumi_protocol.iso_z(peak_start),
                msg=f"{event} subkm start",
            )
            self.assertEqual(
                subkm_end,
                rumi_protocol.iso_z(peak_end + dt.timedelta(hours=12)),
                msg=f"{event} subkm end",
            )

    def test_subkm_timestamp_counts_match_agreed_table(self):
        expected_counts = {
            "MANGKHUT2018": 25,
            "HRAIN2023": 31,
            "HRAIN2025": 28,
            "HEAT2022": 49,
            "HEAT2024": 25,
        }
        for event, count in expected_counts.items():
            with self.subTest(event=event):
                self.assertEqual(
                    len(rumi_protocol.expected_timestamps(event, "subkm")), count
                )

    def test_km_periods_unchanged(self):
        expected_km = {
            "MANGKHUT2018": ("2018-09-15T00:00:00Z", "2018-09-17T00:00:00Z"),
            "HRAIN2023": ("2023-09-06T00:00:00Z", "2023-09-09T00:00:00Z"),
            "HRAIN2025": ("2025-08-03T00:00:00Z", "2025-08-06T00:00:00Z"),
            "HEAT2022": ("2022-07-22T00:00:00Z", "2022-07-25T00:00:00Z"),
            "HEAT2024": ("2024-08-27T00:00:00Z", "2024-08-29T00:00:00Z"),
        }
        for event, period in expected_km.items():
            with self.subTest(event=event):
                self.assertEqual(rumi_protocol.REQUIRED_PERIODS[event]["km"], period)


class ArchiveNameTests(unittest.TestCase):
    def test_parse_archive_name_accepts_optional_config_and_member(self):
        cases = {
            "HKUST-MPAS-HRAIN2025-LIU.tar.gz": ("", ""),
            "HKUST-MPAS-HRAIN2025-LIU-CONFIG01.tar.gz": ("CONFIG01", ""),
            "HKUST-MPAS-HRAIN2025-LIU-MEM01.zip": ("", "MEM01"),
            "HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01.tar.gz": (
                "CONFIG01",
                "MEM01",
            ),
        }
        for name, (config, member) in cases.items():
            with self.subTest(name=name):
                parsed = rumi_protocol.parse_archive_name(name)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed["institution"], "HKUST")
                self.assertEqual(parsed["model"], "MPAS")
                self.assertEqual(parsed["event"], "HRAIN2025")
                self.assertEqual(parsed["poc"], "LIU")
                self.assertEqual(parsed["config"], config)
                self.assertEqual(parsed["member"], member)
                self.assertEqual(parsed["version"], "")

    def test_parse_archive_name_rejects_bad_forms(self):
        bad_names = [
            "HKUST-MPAS-HRAIN2025.tar.gz",  # missing POC
            "HKUST-MPAS-HRAIN2025-LIU-MEM01-CONFIG01.tar.gz",  # wrong order
            "HKUST-MPAS-HRAIN2025-LIU-CONFIG1.tar.gz",  # short config number
            "HKUST-MPAS-HRAIN2025-LIU-MEMBER01.tar.gz",  # wrong member prefix
            "HKUST-WRF-ARW-HRAIN2025-LIU.tar.gz",  # hyphenated token
            "HKUST-MPAS-NOSUCHEVENT-LIU.tar.gz",  # unknown event
            "hkust-MPAS-HRAIN2025-LIU.tar.gz",  # lowercase token
            "HKUST-MPAS-HRAIN2025-LIU.tgz",  # unsupported extension
        ]
        for name in bad_names:
            with self.subTest(name=name):
                self.assertIsNone(rumi_protocol.parse_archive_name(name))

    def test_parse_archive_name_accepts_zip_and_tar_gz(self):
        zip_parsed = rumi_protocol.parse_archive_name(
            "HKUST-MPAS-HRAIN2025-LIU-MEM02.zip"
        )
        tar_parsed = rumi_protocol.parse_archive_name(
            "HKUST-MPAS-HRAIN2025-LIU-CONFIG02.tar.gz"
        )
        self.assertIsNotNone(zip_parsed)
        self.assertEqual(zip_parsed["extension"], "zip")
        self.assertEqual(zip_parsed["stem"], "HKUST-MPAS-HRAIN2025-LIU-MEM02")
        self.assertIsNotNone(tar_parsed)
        self.assertEqual(tar_parsed["extension"], "tar.gz")
        self.assertEqual(tar_parsed["stem"], "HKUST-MPAS-HRAIN2025-LIU-CONFIG02")


class ResolutionCategoryTests(unittest.TestCase):
    def test_resolution_category(self):
        cases = [
            ("1 km", "km"),
            ("1km", "km"),
            ("0.5 km", "subkm"),
            ("500 m", "subkm"),
            ("500m", "subkm"),
            ("250 m", "subkm"),
            ("1000 m", "km"),
            ("~1 km", "km"),
            ("1.0 km", "km"),
            ("", None),
            (None, None),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(rumi_protocol.resolution_category(value), expected)


class ExpectedTimestampsTests(unittest.TestCase):
    def test_expected_timestamps_km_covers_full_period(self):
        timestamps = rumi_protocol.expected_timestamps("HRAIN2025", "km")
        self.assertEqual(len(timestamps), 73)
        self.assertEqual(timestamps[0], "2025-08-03T00:00:00Z")
        self.assertEqual(timestamps[-1], "2025-08-06T00:00:00Z")

    def test_expected_timestamps_respects_actual_initialization(self):
        timestamps = rumi_protocol.expected_timestamps(
            "HRAIN2025", "km", "2025-08-04T15:00:00Z"
        )
        self.assertEqual(len(timestamps), 34)
        self.assertEqual(timestamps[0], "2025-08-04T15:00:00Z")
        self.assertEqual(timestamps[-1], "2025-08-06T00:00:00Z")


class InitDirRegexTests(unittest.TestCase):
    def test_init_dir_re(self):
        accepted = ["Init-5", "Init-0.5", "Init-0.25", "Init-0", "Init-2025080300"]
        rejected = ["Init-0.75", "lead_024h", "Init-", "init-5"]
        for value in accepted:
            with self.subTest(value=value):
                self.assertIsNotNone(rumi_protocol.INIT_DIR_RE.match(value))
        for value in rejected:
            with self.subTest(value=value):
                self.assertIsNone(rumi_protocol.INIT_DIR_RE.match(value))


class ParseAbsoluteInitLabelTests(unittest.TestCase):
    def test_parse_absolute_init_label(self):
        self.assertEqual(
            rumi_protocol.parse_absolute_init_label("Init-2025080300"),
            "2025-08-03T00:00:00Z",
        )
        self.assertIsNone(rumi_protocol.parse_absolute_init_label("Init-5"))
        self.assertIsNone(rumi_protocol.parse_absolute_init_label("Init-0.5"))
        self.assertIsNone(rumi_protocol.parse_absolute_init_label("Init-202508030"))
        self.assertIsNone(rumi_protocol.parse_absolute_init_label("Init-"))


COMPLIANT_FACTS_FILENAME = "ERA5-AN-MPAS-HRAIN2025-20250804210000.nc"


def make_compliant_facts():
    """Return a NetCDF ``facts`` dict that satisfies every rule currently in
    ``rumi_protocol.validate_netcdf_facts``.

    Individual tests remove/replace entries on the returned dict to exercise
    one violation at a time, instead of hand-rolling a large literal per test.
    Values are taken from ``rumi_protocol`` constants (never hardcoded var
    lists) so this helper tracks the module instead of drifting from it.
    """
    attributes = {name: f"test-{name}" for name in rumi_protocol.KNOWN_ATTRIBUTES}
    attributes["Conventions"] = "CF-1.8"
    attributes["event"] = "HRAIN2025"
    attributes["experiment"] = "ERA5-AN"
    attributes["model"] = "MPAS"
    attributes["horizontal_resolution"] = "1 km"
    variables = sorted(
        rumi_protocol.CORE_2D_VARS
        + rumi_protocol.RECOMMENDED_RADIATION_VARS
        + rumi_protocol.RECOMMENDED_3D_LEVEL_VARS
        + ["OMEGA"]
    )
    return {
        "kind": "netCDF-4",
        "attributes": attributes,
        "variables": variables,
        "dimensions": {
            "time": 1,
            "lat": rumi_protocol.CORE_GRID["nlat"],
            "lon": rumi_protocol.CORE_GRID["nlon"],
        },
        "lat": [
            rumi_protocol.CORE_GRID["lat_south"]
            + i * rumi_protocol.CORE_GRID["resolution_degrees"]
            for i in range(rumi_protocol.CORE_GRID["nlat"])
        ],
        "lon": [
            rumi_protocol.CORE_GRID["lon_west"]
            + i * rumi_protocol.CORE_GRID["resolution_degrees"]
            for i in range(rumi_protocol.CORE_GRID["nlon"])
        ],
    }


class KnownVariablesCoverageTests(unittest.TestCase):
    def test_every_mandatory_variable_is_visible_to_the_reader(self):
        # Regression guard for a real bug: ALL_KNOWN_VARS is the list
        # netcdf_facts_from_header() scans the ncdump header for, so any
        # core/recommended variable missing from it can never be reported as
        # present, no matter what the submitted file actually contains.
        # RECOMMENDED_RADIATION_VARS was previously left out entirely.
        required_names = (
            list(rumi_protocol.CORE_2D_VARS)
            + list(rumi_protocol.RECOMMENDED_RADIATION_VARS)
            + list(rumi_protocol.RECOMMENDED_3D_LEVEL_VARS)
        )
        for alternatives in rumi_protocol.RECOMMENDED_3D_ALTERNATIVES:
            required_names.extend(alternatives)

        known = set(rumi_protocol.ALL_KNOWN_VARS)
        missing = sorted({name for name in required_names if name not in known})
        self.assertEqual(missing, [])


class ValidateNetcdfFactsTests(unittest.TestCase):
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

    def test_compliant_facts_pass_with_no_errors_or_warnings(self):
        # Sanity check for the helper itself: every other test in this class
        # deletes one thing from a facts dict that is otherwise clean.
        result = rumi_protocol.validate_netcdf_facts(
            COMPLIANT_FACTS_FILENAME, make_compliant_facts()
        )
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])

    def test_each_file_must_contain_one_time_step(self):
        for time_size in (None, 2):
            with self.subTest(time_size=time_size):
                facts = make_compliant_facts()
                facts["dimensions"]["time"] = time_size
                result = rumi_protocol.validate_netcdf_facts(
                    COMPLIANT_FACTS_FILENAME, facts
                )
                self.assert_message(result["errors"], "exactly one time step")

    def test_missing_radiation_variable_is_a_warning(self):
        # Radiation variables are recommended, not required: a submission
        # missing one is still accepted, and is only ever reported as a
        # warning, never as an error.
        facts = make_compliant_facts()
        facts["variables"] = [v for v in facts["variables"] if v != "SWNET"]

        result = rumi_protocol.validate_netcdf_facts(COMPLIANT_FACTS_FILENAME, facts)

        self.assert_message(result["warnings"], "Recommended radiation variables not found")
        self.assert_message(result["warnings"], "SWNET")
        self.assert_message(result["warnings"], "The submission is accepted")
        self.assert_no_message(result["errors"], "radiation")
        self.assertEqual(result["errors"], [])

    def test_present_radiation_variables_do_not_warn(self):
        # Symptom-level regression test for a real bug: ALL_KNOWN_VARS used
        # to omit RECOMMENDED_RADIATION_VARS, so the header reader could
        # never mark a radiation variable as present, and every submission
        # got a bogus "missing radiation" warning regardless of what the
        # file contained.
        facts = make_compliant_facts()
        self.assertTrue(
            set(rumi_protocol.RECOMMENDED_RADIATION_VARS).issubset(set(facts["variables"]))
        )

        result = rumi_protocol.validate_netcdf_facts(COMPLIANT_FACTS_FILENAME, facts)

        self.assert_no_message(result["warnings"], "radiation")

    def test_missing_core_2d_variable_is_still_an_error(self):
        facts = make_compliant_facts()
        facts["variables"] = [v for v in facts["variables"] if v != "PSFC"]

        result = rumi_protocol.validate_netcdf_facts(COMPLIANT_FACTS_FILENAME, facts)

        self.assert_message(result["errors"], "core 2D")

    def test_missing_recommended_3d_variable_is_a_warning(self):
        # Was previously an error; pressure-level variables are now
        # recommended rather than required, so a missing one only warns and
        # the submission is still accepted.
        facts = make_compliant_facts()
        facts["variables"] = [v for v in facts["variables"] if v != "Q"]

        result = rumi_protocol.validate_netcdf_facts(COMPLIANT_FACTS_FILENAME, facts)

        matches = [
            m
            for m in result["warnings"]
            if "pressure-level" in m and "850 hPa" in m and "Q" in m
        ]
        self.assertTrue(matches, result["warnings"])
        self.assert_message(result["warnings"], "The submission is accepted")
        self.assertEqual(result["errors"], [])

    def test_omega_satisfies_the_vertical_motion_requirement(self):
        facts = make_compliant_facts()
        self.assertIn("OMEGA", facts["variables"])
        self.assertNotIn("W", facts["variables"])

        result = rumi_protocol.validate_netcdf_facts(COMPLIANT_FACTS_FILENAME, facts)

        self.assert_no_message(result["errors"], "3D")
        self.assert_no_message(result["warnings"], "pressure-level")

    def test_w_satisfies_the_vertical_motion_requirement(self):
        facts = make_compliant_facts()
        facts["variables"] = sorted(
            [v for v in facts["variables"] if v != "OMEGA"] + ["W"]
        )

        result = rumi_protocol.validate_netcdf_facts(COMPLIANT_FACTS_FILENAME, facts)

        self.assert_no_message(result["errors"], "3D")
        self.assert_no_message(result["warnings"], "pressure-level")

    def test_missing_both_omega_and_w_is_a_warning(self):
        # Was previously an error; vertical motion (OMEGA or W) is part of
        # the recommended pressure-level group, so missing both is a
        # warning, not a rejection.
        facts = make_compliant_facts()
        facts["variables"] = [v for v in facts["variables"] if v != "OMEGA"]
        self.assertNotIn("W", facts["variables"])

        result = rumi_protocol.validate_netcdf_facts(COMPLIANT_FACTS_FILENAME, facts)

        self.assert_message(result["warnings"], "OMEGA or W")
        self.assert_no_message(result["errors"], "OMEGA or W")
        self.assertEqual(result["errors"], [])

    def test_missing_core_2d_variable_is_the_only_variable_rejection(self):
        # A missing core 2D variable is still the only thing that rejects a
        # submission: the same facts missing recommended radiation and
        # pressure-level variables instead produce warnings only.
        facts = make_compliant_facts()
        facts["variables"] = [v for v in facts["variables"] if v != "PSFC"]

        result = rumi_protocol.validate_netcdf_facts(COMPLIANT_FACTS_FILENAME, facts)

        self.assert_message(result["errors"], "Missing core 2D variables")
        self.assert_message(result["errors"], "PSFC")

        recommended = (
            set(rumi_protocol.RECOMMENDED_RADIATION_VARS)
            | set(rumi_protocol.RECOMMENDED_3D_LEVEL_VARS)
            | {"OMEGA", "W"}
        )
        facts_recommended_missing = make_compliant_facts()
        facts_recommended_missing["variables"] = [
            v for v in facts_recommended_missing["variables"] if v not in recommended
        ]

        result2 = rumi_protocol.validate_netcdf_facts(
            COMPLIANT_FACTS_FILENAME, facts_recommended_missing
        )

        self.assertEqual(result2["errors"], [])
        self.assert_message(
            result2["warnings"], "Recommended radiation variables not found"
        )
        self.assert_message(
            result2["warnings"], "Recommended pressure-level variables not found"
        )

    def test_legacy_rumi_prefixed_filename_is_rejected(self):
        # The old RUMI-<experiment>-<mode>-... naming is no longer valid: the
        # parsed experiment ends up as "RUMI-ERA5-AN", which is not in
        # EXPERIMENTS, so it is rejected with a dedicated message rather than
        # silently accepted or misparsed.
        facts = make_compliant_facts()

        result = rumi_protocol.validate_netcdf_facts(
            "RUMI-ERA5-AN-MPAS-HRAIN2025-20250803000000.nc", facts
        )

        self.assert_message(result["errors"], "is not a RUMI experiment identifier")

    def test_v_style_version_suffix_warns(self):
        # A version written the old way (_v02) parses as a member label, not
        # a version, and is reported so the participant can rename to _r02.
        facts = make_compliant_facts()

        result = rumi_protocol.validate_netcdf_facts(
            "ERA5-AN-MPAS-HRAIN2025-20250803000000_v02.nc", facts
        )

        self.assert_message(result["warnings"], "member label")


class ParseRumiFilenameVersionSuffixTests(unittest.TestCase):
    """Regression coverage for a real bug: '_r02' used to be swallowed
    whole by the member group instead of being recognized as a version
    suffix, and a member name containing an underscore right before '_rNN'
    used to lose part of its name to the version parser."""

    def test_r_suffix_is_parsed_as_version_not_member(self):
        parsed = rumi_protocol.parse_rumi_filename(
            "GFS-FC-WRFARW-HEAT2024-20240828000000_r02.nc"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["member"], "")
        self.assertEqual(parsed["version"], "02")

    def test_member_with_underscores_keeps_its_name_before_r_suffix(self):
        parsed = rumi_protocol.parse_rumi_filename(
            "ERA5-AN-WRF-MANGKHUT2018-20180916120000_mem_01_r03.nc"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["member"], "mem_01")
        self.assertEqual(parsed["version"], "03")


class InitTimeForTests(unittest.TestCase):
    def test_init_time_for_known_label(self):
        self.assertEqual(
            rumi_protocol.init_time_for("HRAIN2023", "Init-0.5"),
            "2023-09-07T02:00:00Z",
        )

    def test_init_time_for_init_0_returns_none(self):
        self.assertIsNone(rumi_protocol.init_time_for("HRAIN2023", "Init-0"))

    def test_init_time_for_absolute_label_returns_none(self):
        self.assertIsNone(
            rumi_protocol.init_time_for("HRAIN2023", "Init-2023090600")
        )

    def test_init_time_for_unknown_event_or_label_returns_none(self):
        self.assertIsNone(rumi_protocol.init_time_for("NOSUCHEVENT", "Init-1"))
        self.assertIsNone(rumi_protocol.init_time_for("HRAIN2023", "Init-99"))


if __name__ == "__main__":
    unittest.main()
