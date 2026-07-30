import importlib.machinery
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "portal" / "backend"
sys.path.insert(0, str(BACKEND))

import portal_lib  # noqa: E402


loader = importlib.machinery.SourceFileLoader(
    "portal_api_test", str(ROOT / "portal" / "api.cgi")
)
spec = importlib.util.spec_from_loader(loader.name, loader)
portal_api = importlib.util.module_from_spec(spec)
loader.exec_module(portal_api)


class UploadWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.incoming_dir = self.data_dir / "incoming"
        self.submissions_dir = self.data_dir / "submissions"
        self.incoming_dir.mkdir()
        self.submissions_dir.mkdir()

        self.patches = ExitStack()
        self.patches.enter_context(mock.patch.object(portal_api, "DATA_DIR", self.data_dir))
        self.patches.enter_context(
            mock.patch.object(portal_api, "INCOMING_DIR", self.incoming_dir)
        )
        self.patches.enter_context(
            mock.patch.object(portal_api, "SUBMISSIONS_DIR", self.submissions_dir)
        )
        self.patches.enter_context(
            mock.patch.object(portal_api, "LOG_DIR", self.data_dir / "logs")
        )

        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        portal_lib.init_schema(self.con)
        self.con.execute(
            """
            INSERT INTO users(
                id, email, name, institution, role, status, password_salt,
                password_hash, created_at, updated_at
            )
            VALUES (1, 'modeler@example.org', 'Modeler', 'HKUST', 'modeler',
                    'approved', 'salt', 'hash', '2026-01-01T00:00:00Z',
                    '2026-01-01T00:00:00Z')
            """
        )
        self.con.commit()
        self.user = {
            "id": 1,
            "email": "modeler@example.org",
            "name": "Modeler",
            "institution": "HKUST",
            "role": "modeler",
            "status": "approved",
        }
        self.patches.enter_context(
            mock.patch.object(
                portal_api, "require_approved_user", return_value=self.user
            )
        )

    def tearDown(self):
        self.con.close()
        self.patches.close()
        self.temp_dir.cleanup()

    def insert_upload(
        self,
        upload_id,
        status,
        content=b"sample",
        file_name="RUMI-GFS-FC-MODEL-HRAIN2025-20250804000000.nc",
        sha256=None,
        replaces_upload_id=None,
    ):
        temp_path = self.incoming_dir / f"{upload_id}.part"
        if status in ("receiving", "validating"):
            temp_path.write_bytes(content)
        else:
            temp_path = None
        self.con.execute(
            """
            INSERT INTO uploads(
                upload_id, user_id, file_name, file_size, received_bytes,
                file_kind, status, experiment, model, event, metadata_json,
                temp_path, sha256, replaces_upload_id, created_at, updated_at
            )
            VALUES (?, 1, ?, ?, ?, 'netcdf', ?, 'RUMI-GFS-FC', 'MODEL',
                    'HRAIN2025', ?, ?, ?, ?, ?, ?)
            """,
            (
                upload_id,
                file_name,
                len(content),
                len(content),
                status,
                json.dumps(
                    {
                        "experiment": "RUMI-GFS-FC",
                        "model": "MODEL",
                        "event": "HRAIN2025",
                    }
                ),
                str(temp_path) if temp_path else None,
                sha256,
                replaces_upload_id,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        self.con.commit()
        return temp_path

    def finish(self, upload_id, validation):
        with (
            mock.patch.object(
                portal_api, "read_json", return_value={"upload_id": upload_id}
            ),
            mock.patch.object(
                portal_api, "validate_submission", return_value=validation
            ),
        ):
            return portal_api.handle_upload_finish(self.con)

    def test_validation_errors_reject_without_finalizing(self):
        temp_path = self.insert_upload("new-upload", "receiving")
        result = self.finish(
            "new-upload",
            {
                "errors": ["Missing core 2D variables: T2M"],
                "warnings": [],
                "summary": {},
            },
        )

        self.assertEqual(result["upload"]["status"], "rejected")
        self.assertTrue(temp_path.exists())
        self.assertIsNone(result["upload"].get("stored_path"))

    def test_same_filename_requires_explicit_replacement(self):
        self.insert_upload("existing-upload", "validated")
        payload = {
            "file_name": "RUMI-GFS-FC-MODEL-HRAIN2025-20250804000000.nc",
            "file_size": 123,
            "experiment": "RUMI-GFS-FC",
            "model": "MODEL",
            "event": "HRAIN2025",
        }

        with mock.patch.object(portal_api, "read_json", return_value=payload):
            with self.assertRaises(portal_lib.PortalError) as raised:
                portal_api.handle_upload_start(self.con)

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.details["code"], "duplicate_filename")

        payload["replace_upload_id"] = "existing-upload"
        with mock.patch.object(portal_api, "read_json", return_value=payload):
            result = portal_api.handle_upload_start(self.con)
        row = self.con.execute(
            "SELECT replaces_upload_id FROM uploads WHERE upload_id = ?",
            (result["upload_id"],),
        ).fetchone()
        self.assertEqual(row["replaces_upload_id"], "existing-upload")

    def test_identical_content_is_rejected_as_duplicate(self):
        digest = portal_lib.hashlib.sha256(b"same").hexdigest()
        self.insert_upload(
            "accepted-upload",
            "validated",
            content=b"same",
            file_name="RUMI-GFS-FC-OLD-HRAIN2025-20250804000000.nc",
            sha256=digest,
        )
        temp_path = self.insert_upload(
            "duplicate-upload",
            "receiving",
            content=b"same",
            file_name="RUMI-GFS-FC-NEW-HRAIN2025-20250804000000.nc",
        )

        result = self.finish(
            "duplicate-upload", {"errors": [], "warnings": [], "summary": {}}
        )

        self.assertEqual(result["upload"]["status"], "duplicate")
        self.assertFalse(temp_path.exists())
        self.assertEqual(
            result["upload"]["validation"]["summary"]["duplicate_upload_id"],
            "accepted-upload",
        )

    def test_valid_replacement_supersedes_existing_upload(self):
        self.insert_upload(
            "existing-upload",
            "validated",
            content=b"old",
            sha256=portal_lib.hashlib.sha256(b"old").hexdigest(),
        )
        self.insert_upload(
            "replacement-upload",
            "receiving",
            content=b"new",
            replaces_upload_id="existing-upload",
        )

        result = self.finish(
            "replacement-upload", {"errors": [], "warnings": [], "summary": {}}
        )
        old_status = self.con.execute(
            "SELECT status FROM uploads WHERE upload_id = 'existing-upload'"
        ).fetchone()["status"]
        stored_path = self.con.execute(
            "SELECT stored_path FROM uploads WHERE upload_id = 'replacement-upload'"
        ).fetchone()["stored_path"]

        self.assertEqual(result["upload"]["status"], "validated")
        self.assertEqual(old_status, "superseded")
        self.assertTrue(Path(stored_path).exists())

    def test_finalization_error_becomes_terminal_server_error(self):
        self.insert_upload("blocked-upload", "receiving", content=b"valid")
        blocked_path = self.data_dir / "not-a-directory"
        blocked_path.write_text("blocked", encoding="utf-8")

        with mock.patch.object(portal_api, "SUBMISSIONS_DIR", blocked_path):
            result = self.finish(
                "blocked-upload", {"errors": [], "warnings": [], "summary": {}}
            )

        self.assertEqual(result["upload"]["status"], "server_error")
        self.assertIn(
            "No submission was accepted",
            result["upload"]["validation"]["errors"][0],
        )

    def test_admin_upload_list_includes_uploader_identity(self):
        self.insert_upload("admin-visible-upload", "rejected")
        self.user["role"] = "admin"

        result = portal_api.handle_uploads(self.con)

        self.assertEqual(
            result["uploads"][0]["uploader"],
            {
                "name": "Modeler",
                "email": "modeler@example.org",
                "institution": "HKUST",
            },
        )

    def test_modeler_upload_list_does_not_expose_uploader_identity(self):
        self.insert_upload("modeler-visible-upload", "rejected")

        result = portal_api.handle_uploads(self.con)

        self.assertNotIn("uploader", result["uploads"][0])


class NetcdfValidationTests(unittest.TestCase):
    def core_coordinates(self):
        spacing = portal_lib.CORE_GRID["resolution_degrees"]
        return {
            "lat": [
                portal_lib.CORE_GRID["lat_south"] + index * spacing
                for index in range(portal_lib.CORE_GRID["nlat"])
            ],
            "lon": [
                portal_lib.CORE_GRID["lon_west"] + index * spacing
                for index in range(portal_lib.CORE_GRID["nlon"])
            ],
        }

    def test_filename_parses_complete_experiment_and_model(self):
        parsed = portal_lib.parse_rumi_filename(
            "RUMI-GFS-FC-MPAS-HRAIN2025-20250804000000.nc"
        )

        self.assertEqual(parsed["experiment"], "RUMI-GFS-FC")
        self.assertEqual(parsed["model"], "MPAS")

    def test_previous_filename_without_mode_is_rejected(self):
        parsed = portal_lib.parse_rumi_filename(
            "RUMI-ERA5-WRF-MANGKHUT2018-20180916120000.nc"
        )

        self.assertIsNone(parsed)

    def test_coordinate_dump_requests_full_precision(self):
        completed = mock.Mock(
            returncode=0,
            stdout="netcdf sample { data:\n lat = 22.12;\n lon = 113.82;\n}",
            stderr="",
        )
        with (
            mock.patch.object(
                portal_lib,
                "ncdump_executable",
                return_value="/usr/bin/ncdump",
            ),
            mock.patch.object(
                portal_lib,
                "run_command",
                return_value=completed,
            ) as runner,
        ):
            coordinates = portal_lib.netcdf_coordinates(Path("sample.nc"))

        runner.assert_called_once_with(
            [
                "/usr/bin/ncdump",
                "-p",
                "15,15",
                "-v",
                "lat,lon",
                "sample.nc",
            ],
            timeout=90,
        )
        self.assertEqual(coordinates, {"lat": [22.12], "lon": [113.82]})

    def test_missing_core_variable_is_an_error(self):
        variables = [
            name for name in portal_lib.CORE_2D_VARS if name != "T2M"
        ]
        declarations = "\n".join(f"float {name}(time, lat, lon) ;" for name in variables)
        header = f"""
        dimensions:
            time = 1 ;
            lat = 171 ;
            lon = 234 ;
        variables:
            {declarations}
        """
        with (
            mock.patch.object(portal_lib, "netcdf_kind", return_value="netCDF-4"),
            mock.patch.object(portal_lib, "netcdf_header", return_value=header),
            mock.patch.object(
                portal_lib,
                "netcdf_coordinates",
                return_value=self.core_coordinates(),
            ),
        ):
            result = portal_lib.validate_netcdf(
                Path("sample.nc"),
                "RUMI-GFS-FC-MODEL-HRAIN2025-20250804000000.nc",
                {
                    "experiment": "RUMI-GFS-FC",
                    "model": "MODEL",
                    "event": "HRAIN2025",
                },
            )

        self.assertIn("Missing core 2D variables: T2M", result["errors"])

    def test_filename_metadata_mismatch_is_an_error(self):
        declarations = "\n".join(
            f"float {name}(time, lat, lon) ;"
            for name in portal_lib.CORE_2D_VARS
        )
        header = f"""
        dimensions:
            time = 1 ;
            lat = 171 ;
            lon = 234 ;
        variables:
            {declarations}
        """
        with (
            mock.patch.object(portal_lib, "netcdf_kind", return_value="netCDF-4"),
            mock.patch.object(portal_lib, "netcdf_header", return_value=header),
            mock.patch.object(
                portal_lib,
                "netcdf_coordinates",
                return_value=self.core_coordinates(),
            ),
        ):
            result = portal_lib.validate_netcdf(
                Path("sample.nc"),
                "RUMI-GFS-FC-MPAS-HRAIN2025-20250804000000.nc",
                {
                    "experiment": "RUMI-ERA5-AN",
                    "model": "WRF",
                    "event": "HRAIN2025",
                },
            )

        self.assertIn(
            "File name experiment does not match the submitted metadata.",
            result["errors"],
        )
        self.assertIn(
            "File name model does not match the submitted metadata.",
            result["errors"],
        )

    def test_previous_15_arc_second_grid_is_rejected(self):
        declarations = "\n".join(
            f"float {name}(time, lat, lon) ;"
            for name in portal_lib.CORE_2D_VARS
        )
        header = f"""
        dimensions:
            time = 1 ;
            lat = 111 ;
            lon = 152 ;
        variables:
            {declarations}
        """
        old_spacing = 15 / 3600.0
        old_coordinates = {
            "lat": [22.12 + index * old_spacing for index in range(111)],
            "lon": [113.82 + index * old_spacing for index in range(152)],
        }
        with (
            mock.patch.object(portal_lib, "netcdf_kind", return_value="netCDF-4"),
            mock.patch.object(portal_lib, "netcdf_header", return_value=header),
            mock.patch.object(
                portal_lib,
                "netcdf_coordinates",
                return_value=old_coordinates,
            ),
        ):
            result = portal_lib.validate_netcdf(
                Path("sample.nc"),
                "RUMI-ERA5-AN-WRF-MANGKHUT2018-20180916120000.nc",
                {
                    "experiment": "RUMI-ERA5-AN",
                    "model": "WRF",
                    "event": "MANGKHUT2018",
                },
            )

        self.assertIn(
            "Standard core grid dimensions must be 171 lat by 234 lon "
            "(9.7 arc-seconds).",
            result["errors"],
        )

    def test_archive_members_use_the_same_netcdf_validator(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "batch.zip"
            member_name = (
                "results/RUMI-GFS-FC-MPAS-HRAIN2025-20250804000000.nc"
            )
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(member_name, b"not-a-real-netcdf")
                archive.writestr("technical-notes.txt", "test")

            with mock.patch.object(
                portal_lib,
                "validate_netcdf",
                return_value={
                    "errors": ["Standard core grid dimensions must be 171 lat by 234 lon."],
                    "warnings": [],
                    "summary": {},
                },
            ) as validator:
                result = portal_lib.validate_archive(
                    archive_path,
                    archive_path.name,
                    {
                        "experiment": "RUMI-GFS-FC",
                        "model": "MPAS",
                        "event": "HRAIN2025",
                    },
                )

        validator.assert_called_once()
        self.assertEqual(result["summary"]["validated_netcdf_files"], 1)
        self.assertIn(
            member_name
            + ": Standard core grid dimensions must be 171 lat by 234 lon.",
            result["errors"],
        )


if __name__ == "__main__":
    unittest.main()
