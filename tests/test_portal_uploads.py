import importlib.machinery
import importlib.util
import json
import os
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


class CookiePathTests(unittest.TestCase):
    def test_root_mount_uses_one_slash(self):
        with mock.patch.dict(os.environ, {"SCRIPT_NAME": "/api.cgi"}):
            self.assertEqual(portal_api.cookie_path(), "/")

    def test_nested_mount_keeps_trailing_slash(self):
        with mock.patch.dict(
            os.environ, {"SCRIPT_NAME": "/dataview/RUMI/api.cgi"}
        ):
            self.assertEqual(portal_api.cookie_path(), "/dataview/RUMI/")


class UploadWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.incoming_dir = self.data_dir / "incoming"
        self.submissions_dir = self.data_dir / "submissions"
        self.incoming_dir.mkdir()
        self.submissions_dir.mkdir()

        self.patches = ExitStack()
        self.patches.enter_context(
            mock.patch.object(portal_api, "INCOMING_DIR", self.incoming_dir)
        )
        self.patches.enter_context(
            mock.patch.object(portal_api, "LOG_DIR", self.data_dir / "logs")
        )
        for name, value in (
            ("DATA_DIR", self.data_dir),
            ("INCOMING_DIR", self.incoming_dir),
            ("SUBMISSIONS_DIR", self.submissions_dir),
            ("LOG_DIR", self.data_dir / "logs"),
            ("EXTRACTED_DIR", self.data_dir / "extracted"),
            ("MANIFESTS_DIR", self.data_dir / "manifests"),
        ):
            self.patches.enter_context(mock.patch.object(portal_lib, name, value))

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

    def test_password_reset_requires_the_initial_invitation_code(self):
        portal_lib.import_whitelist(self.con, ["modeler@example.org"])
        portal_lib.set_setting(self.con, "registration_code", "RUMI-INVITE")
        payload = {
            "email": "modeler@example.org",
            "registration_code": "wrong-code",
            "new_password": "new-password-123",
        }

        with mock.patch.object(portal_api, "read_json", return_value=payload):
            with self.assertRaises(portal_lib.PortalError) as raised:
                portal_api.handle_password_reset(self.con)

        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(raised.exception.message, "Invalid initial invitation code.")

    def test_password_reset_updates_password_and_invalidates_sessions(self):
        portal_lib.import_whitelist(self.con, ["modeler@example.org"])
        portal_lib.set_setting(self.con, "registration_code", "RUMI-INVITE")
        session_token, _ = portal_lib.create_session(self.con, 1)
        payload = {
            "email": "modeler@example.org",
            "registration_code": "RUMI-INVITE",
            "new_password": "new-password-123",
        }

        with mock.patch.object(portal_api, "read_json", return_value=payload):
            result = portal_api.handle_password_reset(self.con)

        row = self.con.execute(
            "SELECT password_salt, password_hash FROM users WHERE id = 1"
        ).fetchone()
        session = self.con.execute(
            "SELECT 1 FROM sessions WHERE token_hash = ?",
            (portal_lib.token_hash(session_token),),
        ).fetchone()
        self.assertTrue(result["ok"])
        self.assertIn("Password reset complete", result["message"])
        self.assertTrue(
            portal_lib.verify_password(
                "new-password-123", row["password_salt"], row["password_hash"]
            )
        )
        self.assertIsNone(session)

    def test_password_reset_is_rate_limited(self):
        portal_lib.import_whitelist(self.con, ["modeler@example.org"])
        for _ in range(portal_api.PASSWORD_RESET_MAX_FAILED_ATTEMPTS):
            portal_api.record_auth_attempt(
                self.con, "password_reset", "modeler@example.org", False
            )
        payload = {
            "email": "modeler@example.org",
            "registration_code": "RUMI-INVITE",
            "new_password": "new-password-123",
        }

        with mock.patch.object(portal_api, "read_json", return_value=payload):
            with self.assertRaises(portal_lib.PortalError) as raised:
                portal_api.handle_password_reset(self.con)

        self.assertEqual(raised.exception.status, 429)

    def tearDown(self):
        self.con.close()
        self.patches.close()
        self.temp_dir.cleanup()

    def insert_upload(
        self,
        upload_id,
        status,
        content=b"sample",
        file_name="GFS-FC-MODEL-HRAIN2025-20250804000000.nc",
        file_kind="netcdf",
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
                upload_id, user_id, institution, file_name, file_size, received_bytes,
                file_kind, status, experiment, model, event, metadata_json,
                temp_path, sha256, replaces_upload_id, created_at, updated_at
            )
            VALUES (?, 1, 'HKUST', ?, ?, ?, ?, ?, 'GFS-FC', 'MODEL',
                    'HRAIN2025', ?, ?, ?, ?, ?, ?)
            """,
            (
                upload_id,
                file_name,
                len(content),
                len(content),
                file_kind,
                status,
                json.dumps(
                    {
                        "experiment": "GFS-FC",
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
        self.insert_upload(
            "existing-upload",
            "validated",
            file_name="HKUST-MODEL-HRAIN2025-MODELER.zip",
            file_kind="zip",
        )
        payload = {
            "file_name": "HKUST-MODEL-HRAIN2025-MODELER.zip",
            "file_size": 123,
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

    def test_partial_upload_is_reported_as_resumable(self):
        self.con.execute(
            """
            INSERT INTO uploads(
                upload_id, user_id, institution, file_name, file_size,
                received_bytes, file_kind, status, experiment, model, event,
                metadata_json, temp_path, created_at, updated_at
            )
            VALUES ('partial-upload', 1, 'HKUST',
                    'HKUST-MODEL-HRAIN2025-MODELER.zip',
                    1000, 400, 'zip', 'receiving', '(archive)', 'MODEL',
                    'HRAIN2025', '{}', '/tmp/partial.part',
                    '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """
        )
        self.con.commit()
        payload = {
            "file_name": "HKUST-MODEL-HRAIN2025-MODELER.zip",
            "file_size": 1000,
        }
        with mock.patch.object(portal_api, "read_json", return_value=payload):
            with self.assertRaises(portal_lib.PortalError) as raised:
                portal_api.handle_upload_start(self.con)

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.details["code"], "resumable")
        self.assertEqual(
            raised.exception.details["existing"]["received_bytes"], 400
        )

    def test_completed_upload_is_still_a_duplicate_not_a_resume(self):
        self.insert_upload(
            "existing-upload",
            "validated",
            file_name="HKUST-MODEL-HRAIN2025-MODELER.zip",
            file_kind="zip",
        )
        payload = {
            "file_name": "HKUST-MODEL-HRAIN2025-MODELER.zip",
            "file_size": 123,
        }
        with mock.patch.object(portal_api, "read_json", return_value=payload):
            with self.assertRaises(portal_lib.PortalError) as raised:
                portal_api.handle_upload_start(self.con)

        self.assertEqual(raised.exception.details["code"], "duplicate_filename")

    def test_archive_name_drives_metadata(self):
        # The participant retypes nothing: identity comes from the archive name
        # and from the authenticated account.
        payload = {
            "file_name": "HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01.tar.gz",
            "file_size": 123,
        }

        with mock.patch.object(portal_api, "read_json", return_value=payload):
            result = portal_api.handle_upload_start(self.con)

        row = self.con.execute(
            """
            SELECT file_kind, institution, model, event, experiment, poc,
                   config_id, member, archive_version, metadata_json
            FROM uploads WHERE upload_id = ?
            """,
            (result["upload_id"],),
        ).fetchone()
        self.assertEqual(row["file_kind"], "tar")
        self.assertEqual(row["institution"], "HKUST")
        self.assertEqual(row["model"], "MPAS")
        self.assertEqual(row["event"], "HRAIN2025")
        self.assertEqual(row["experiment"], "(archive)")
        self.assertEqual(row["poc"], "LIU")
        self.assertEqual(row["config_id"], "CONFIG01")
        self.assertEqual(row["member"], "MEM01")
        self.assertEqual(row["archive_version"], "")
        metadata = json.loads(row["metadata_json"])
        self.assertEqual(metadata["config_id"], "CONFIG01")
        self.assertEqual(metadata["member"], "MEM01")

    def test_archive_name_accepts_each_optional_suffix_combination(self):
        names = (
            "HKUST-MPAS-HRAIN2025-LIU.zip",
            "HKUST-MPAS-HRAIN2025-LIU-CONFIG02.zip",
            "HKUST-MPAS-HRAIN2025-LIU-MEM02.zip",
            "HKUST-MPAS-HRAIN2025-LIU-CONFIG02-MEM02.zip",
        )
        for name in names:
            with self.subTest(name=name), mock.patch.object(
                portal_api,
                "read_json",
                return_value={"file_name": name, "file_size": 123},
            ):
                result = portal_api.handle_upload_start(self.con)
                self.assertTrue(result["ok"])

    def test_bad_archive_name_is_rejected_with_an_example(self):
        payload = {"file_name": "submission.tar.gz", "file_size": 123}

        with mock.patch.object(portal_api, "read_json", return_value=payload):
            with self.assertRaises(portal_lib.PortalError) as raised:
                portal_api.handle_upload_start(self.con)

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.details["code"], "archive_name")
        self.assertIn(
            "HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01.tar.gz",
            raised.exception.message,
        )

    def test_hyphenated_model_in_archive_name_is_rejected(self):
        payload = {
            "file_name": "HKUST-WRF-ARW-HRAIN2025-LIU-CONFIG01-MEM01.tar.gz",
            "file_size": 123,
        }

        with mock.patch.object(portal_api, "read_json", return_value=payload):
            with self.assertRaises(portal_lib.PortalError) as raised:
                portal_api.handle_upload_start(self.con)

        self.assertIn("WRFARW", raised.exception.message)

    def test_new_uploads_reject_single_files_and_tgz_archives(self):
        for file_name in (
            "GFS-FC-MODEL-HRAIN2025-20250804000000.nc",
            "HKUST-MODEL-HRAIN2025-MODELER.tgz",
        ):
            with self.subTest(file_name=file_name):
                with mock.patch.object(
                    portal_api,
                    "read_json",
                    return_value={"file_name": file_name, "file_size": 123},
                ):
                    with self.assertRaises(portal_lib.PortalError) as raised:
                        portal_api.handle_upload_start(self.con)

                self.assertEqual(raised.exception.status, 400)
                self.assertEqual(raised.exception.details["code"], "archive_only")

    def test_identical_content_is_rejected_as_duplicate(self):
        digest = portal_lib.hashlib.sha256(b"same").hexdigest()
        self.insert_upload(
            "accepted-upload",
            "validated",
            content=b"same",
            file_name="GFS-FC-OLD-HRAIN2025-20250804000000.nc",
            sha256=digest,
        )
        temp_path = self.insert_upload(
            "duplicate-upload",
            "receiving",
            content=b"same",
            file_name="GFS-FC-NEW-HRAIN2025-20250804000000.nc",
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

    def test_identical_content_can_replace_the_selected_upload(self):
        digest = portal_lib.hashlib.sha256(b"same").hexdigest()
        self.insert_upload(
            "existing-upload",
            "validated",
            content=b"same",
            sha256=digest,
        )
        self.insert_upload(
            "replacement-upload",
            "receiving",
            content=b"same",
            replaces_upload_id="existing-upload",
        )

        result = self.finish(
            "replacement-upload", {"errors": [], "warnings": [], "summary": {}}
        )
        old_status = self.con.execute(
            "SELECT status FROM uploads WHERE upload_id = 'existing-upload'"
        ).fetchone()["status"]

        self.assertEqual(result["upload"]["status"], "validated")
        self.assertEqual(old_status, "superseded")

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
        self.assertEqual(
            Path(stored_path).parent.relative_to(self.submissions_dir).parts,
            ("hkust", "gfs-fc", "model", "HRAIN2025"),
        )

    def test_archive_is_queued_for_background_validation(self):
        self.insert_upload(
            "archive-upload",
            "receiving",
            content=b"archive",
            file_name="HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01.zip",
            file_kind="zip",
        )

        with (
            mock.patch.object(
                portal_api, "read_json", return_value={"upload_id": "archive-upload"}
            ),
            mock.patch.object(portal_api.subprocess, "Popen") as popen,
            mock.patch.object(
                portal_api, "validate_submission"
            ) as inline_validator,
        ):
            popen.return_value = mock.Mock(pid=4242)
            result = portal_api.handle_upload_finish(self.con)

        self.assertEqual(result["upload"]["status"], "queued")
        inline_validator.assert_not_called()
        command = popen.call_args[0][0]
        self.assertIn("validate_worker.py", command[1])
        self.assertEqual(command[2:], ["--upload-id", "archive-upload"])
        self.assertTrue(popen.call_args[1]["start_new_session"])
        row = self.con.execute(
            "SELECT worker_pid FROM uploads WHERE upload_id = 'archive-upload'"
        ).fetchone()
        self.assertEqual(row["worker_pid"], 4242)

    def test_failed_worker_launch_is_a_terminal_server_error(self):
        self.insert_upload(
            "archive-upload",
            "receiving",
            content=b"archive",
            file_name="HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01.zip",
            file_kind="zip",
        )

        with (
            mock.patch.object(
                portal_api, "read_json", return_value={"upload_id": "archive-upload"}
            ),
            mock.patch.object(
                portal_api.subprocess, "Popen", side_effect=OSError("no fork")
            ),
        ):
            result = portal_api.handle_upload_finish(self.con)

        self.assertEqual(result["upload"]["status"], "server_error")
        self.assertIn(
            "No submission was accepted",
            result["upload"]["validation"]["errors"][0],
        )

    def test_stale_validation_is_reaped(self):
        self.insert_upload("stuck-upload", "validating", content=b"x")
        self.con.execute(
            "UPDATE uploads SET worker_heartbeat = '2020-01-01T00:00:00Z' "
            "WHERE upload_id = 'stuck-upload'"
        )
        self.con.commit()

        portal_api.handle_uploads(self.con)

        row = self.con.execute(
            "SELECT status FROM uploads WHERE upload_id = 'stuck-upload'"
        ).fetchone()
        self.assertEqual(row["status"], "server_error")

    def test_upload_status_is_scoped_to_the_owner(self):
        self.insert_upload("owned-upload", "queued", content=b"x")
        with mock.patch.object(portal_api, "query_one", return_value="owned-upload"):
            result = portal_api.handle_upload_status(self.con)
            self.assertEqual(result["upload"]["upload_id"], "owned-upload")
            self.user["id"] = 2
            with self.assertRaises(portal_lib.PortalError) as raised:
                portal_api.handle_upload_status(self.con)
        self.assertEqual(raised.exception.status, 404)

    def test_finalization_error_becomes_terminal_server_error(self):
        self.insert_upload("blocked-upload", "receiving", content=b"valid")
        blocked_path = self.data_dir / "not-a-directory"
        blocked_path.write_text("blocked", encoding="utf-8")

        with mock.patch.object(portal_lib, "SUBMISSIONS_DIR", blocked_path):
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
        self.assertEqual(result["uploads"][0]["institution"], "HKUST")

    def test_submission_institution_is_a_historical_snapshot(self):
        self.insert_upload("snapshot-upload", "rejected")
        self.con.execute(
            "UPDATE users SET institution = 'Changed Institution' WHERE id = 1"
        )
        self.con.commit()

        result = portal_api.handle_uploads(self.con)

        self.assertEqual(result["uploads"][0]["institution"], "HKUST")

    def test_modeler_upload_list_does_not_expose_uploader_identity(self):
        self.insert_upload("modeler-visible-upload", "rejected")

        result = portal_api.handle_uploads(self.con)

        self.assertNotIn("uploader", result["uploads"][0])

    def test_modeler_can_delete_own_upload(self):
        temp_path = self.insert_upload("own-upload", "receiving")
        with mock.patch.object(
            portal_api, "read_json", return_value={"upload_id": "own-upload"}
        ):
            result = portal_api.handle_upload_delete(self.con)
        row = self.con.execute(
            "SELECT status, temp_path FROM uploads WHERE upload_id = 'own-upload'"
        ).fetchone()

        self.assertTrue(result["ok"])
        self.assertEqual(row["status"], "deleted")
        self.assertIsNone(row["temp_path"])
        self.assertFalse(temp_path.exists())

    def test_only_admin_can_delete_another_users_upload(self):
        temp_path = self.insert_upload("other-upload", "receiving")
        self.user["id"] = 2
        payload = {"upload_id": "other-upload"}
        with mock.patch.object(portal_api, "read_json", return_value=payload):
            with self.assertRaises(portal_lib.PortalError) as raised:
                portal_api.handle_upload_delete(self.con)

        self.assertEqual(raised.exception.status, 403)
        self.assertTrue(temp_path.exists())

        self.user["role"] = "admin"
        with mock.patch.object(portal_api, "read_json", return_value=payload):
            result = portal_api.handle_upload_delete(self.con)

        self.assertTrue(result["ok"])
        self.assertFalse(temp_path.exists())


class SchemaMigrationTests(unittest.TestCase):
    def test_legacy_uploads_receive_institution_snapshot(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, institution TEXT)")
        con.execute("INSERT INTO users(id, institution) VALUES (1, 'HKUST')")
        con.execute(
            """
            CREATE TABLE uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                upload_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                received_bytes INTEGER NOT NULL DEFAULT 0,
                file_kind TEXT NOT NULL,
                status TEXT NOT NULL,
                experiment TEXT NOT NULL,
                model TEXT NOT NULL,
                event TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            INSERT INTO uploads(
                upload_id, user_id, file_name, file_size, file_kind, status,
                experiment, model, event, metadata_json, created_at, updated_at
            )
            VALUES ('legacy-upload', 1, 'legacy.nc', 1, 'netcdf', 'validated',
                    'GFS-FC', 'MODEL', 'HRAIN2025', '{}', 'now', 'now')
            """
        )

        portal_lib.init_schema(con)

        row = con.execute(
            "SELECT institution FROM uploads WHERE upload_id = 'legacy-upload'"
        ).fetchone()
        self.assertEqual(row["institution"], "HKUST")
        con.close()


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
            "GFS-FC-MPAS-HRAIN2025-20250804000000.nc"
        )

        self.assertEqual(parsed["experiment"], "GFS-FC")
        self.assertEqual(parsed["model"], "MPAS")

    def test_previous_filename_without_mode_is_rejected(self):
        parsed = portal_lib.parse_rumi_filename(
            "ERA5-WRF-MANGKHUT2018-20180916120000.nc"
        )

        self.assertIsNone(parsed)

    def test_archive_name_uses_only_four_identity_fields(self):
        parsed = portal_lib.parse_archive_name("HKUST-MPAS-HRAIN2025-SHI.tar.gz")

        self.assertEqual(
            {key: parsed[key] for key in ("institution", "model", "event", "poc")},
            {
                "institution": "HKUST",
                "model": "MPAS",
                "event": "HRAIN2025",
                "poc": "SHI",
            },
        )
        self.assertEqual(parsed["config"], "")
        self.assertEqual(parsed["version"], "")
        self.assertIsNone(
            portal_lib.parse_archive_name(
                "HKUST-MPAS-HRAIN2025-SHI-CONFIG01-r01.tar.gz"
            )
        )
        self.assertIsNone(portal_lib.parse_archive_name("HKUST-MPAS-HRAIN2025-SHI.tgz"))

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

    def test_numeric_global_attribute_lead_time_is_supported(self):
        header = ':forecast_lead_time_hours = 24LL ;'

        value = portal_lib.header_attr(header, "forecast_lead_time_hours")

        self.assertEqual(portal_lib.parse_lead_time_hours(value), 24)

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
                "GFS-FC-MODEL-HRAIN2025-20250804000000.nc",
                {
                    "experiment": "GFS-FC",
                    "model": "MODEL",
                    "event": "HRAIN2025",
                },
            )

        self.assertIn("Missing core 2D variables: T2M", result["errors"])

    def test_multiple_time_steps_are_rejected(self):
        declarations = "\n".join(
            f"float {name}(time, lat, lon) ;"
            for name in portal_lib.CORE_2D_VARS
        )
        header = f"""
        dimensions:
            time = 2 ;
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
                Path("multi-time.nc"),
                "RUMI-GFS-FC-MODEL-HRAIN2025-20250804000000.nc",
                {
                    "experiment": "RUMI-GFS-FC",
                    "model": "MODEL",
                    "event": "HRAIN2025",
                },
            )

        self.assertIn(
            "Each NetCDF file must contain exactly one time step "
            "(time dimension = 1); received 2.",
            result["errors"],
        )

    def test_unlimited_one_step_time_dimension_is_accepted(self):
        header = "dimensions: time = UNLIMITED ; // (1 currently)"

        self.assertEqual(portal_lib.header_dim(header, "time"), 1)

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
                "GFS-FC-MPAS-HRAIN2025-20250804000000.nc",
                {
                    "experiment": "ERA5-AN",
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
                "ERA5-AN-WRF-MANGKHUT2018-20180916120000.nc",
                {
                    "experiment": "ERA5-AN",
                    "model": "WRF",
                    "event": "MANGKHUT2018",
                },
            )

        self.assertIn(
            "Standard core grid dimensions must be 171 lat by 234 lon "
            "(9.7 arc-seconds).",
            result["errors"],
        )

if __name__ == "__main__":
    unittest.main()
