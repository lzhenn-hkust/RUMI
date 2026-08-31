import io
import json
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "portal" / "backend"
sys.path.insert(0, str(BACKEND))

import portal_lib  # noqa: E402
import validate_worker  # noqa: E402


CLEAN = {
    "errors": [],
    "warnings": [],
    "summary": {"checked_netcdf_files": 5, "passed_netcdf_files": 5},
}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.incoming_dir = self.data_dir / "incoming"
        self.submissions_dir = self.data_dir / "submissions"
        self.extracted_dir = self.data_dir / "extracted"
        self.manifests_dir = self.data_dir / "manifests"
        self.incoming_dir.mkdir()
        self.submissions_dir.mkdir()

        self.patches = ExitStack()
        for name, value in (
            ("DATA_DIR", self.data_dir),
            ("INCOMING_DIR", self.incoming_dir),
            ("SUBMISSIONS_DIR", self.submissions_dir),
            ("EXTRACTED_DIR", self.extracted_dir),
            ("MANIFESTS_DIR", self.manifests_dir),
            ("LOG_DIR", self.data_dir / "logs"),
        ):
            self.patches.enter_context(mock.patch.object(portal_lib, name, value))

        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        portal_lib.init_schema(self.con)
        self.con.execute(
            """
            INSERT INTO users(id, email, name, institution, role, status,
                              password_salt, password_hash, created_at, updated_at)
            VALUES (1, 'm@example.org', 'M', 'HKUST', 'modeler', 'approved',
                    's', 'h', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """
        )
        self.con.commit()
        # The worker opens its own connection; give it the test one instead.
        self.patches.enter_context(
            mock.patch.object(validate_worker, "connect_db", return_value=self.con)
        )

    def tearDown(self):
        self.patches.close()
        self.con.close()
        self.temp_dir.cleanup()

    def archive_bytes(self, member_name="package/README.txt", content=b"archive"):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            info = tarfile.TarInfo(member_name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        return buffer.getvalue()

    def insert(self, upload_id, status="queued", content=None):
        content = self.archive_bytes() if content is None else content
        temp_path = self.incoming_dir / f"{upload_id}.part"
        temp_path.write_bytes(content)
        self.con.execute(
            """
            INSERT INTO uploads(
                upload_id, user_id, institution, file_name, file_size,
                received_bytes, file_kind, status, experiment, model, event,
                member, config_id, metadata_json, temp_path, created_at, updated_at
            )
            VALUES (?, 1, 'HKUST',
                    'HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01.tar.gz',
                    ?, ?, 'tar', ?, '(archive)', 'MPAS', 'HRAIN2025',
                    'MEM01', 'CONFIG01', '{}', ?,
                    '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """,
            (upload_id, len(content), len(content), status, str(temp_path)),
        )
        self.con.commit()
        return temp_path

    def row(self, upload_id):
        return self.con.execute(
            "SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)
        ).fetchone()

    def test_claim_ignores_uploads_that_are_not_queued(self):
        self.insert("still-receiving", status="receiving")
        self.assertIsNone(validate_worker.claim(self.con, "still-receiving"))

    def test_second_worker_for_the_same_upload_does_nothing(self):
        self.insert("archive")
        self.assertIsNotNone(validate_worker.claim(self.con, "archive"))
        self.assertIsNone(validate_worker.claim(self.con, "archive"))

    def test_clean_archive_is_stored_and_marked_validated(self):
        temp_path = self.insert("archive")
        with mock.patch.object(validate_worker, "validate_archive", return_value=dict(CLEAN)):
            self.assertEqual(validate_worker.validate_upload("archive"), 0)

        row = self.row("archive")
        self.assertEqual(row["status"], "validated")
        self.assertFalse(temp_path.exists())
        stored = Path(row["stored_path"])
        self.assertTrue(stored.exists())
        # Archives span several experiments, so they are filed by event and model.
        self.assertEqual(
            stored.parent.relative_to(self.submissions_dir).parts,
            ("hkust", "HRAIN2025", "mpas"),
        )
        self.assertEqual(row["rules_version"], portal_lib.RULES_VERSION)
        self.assertIsNone(row["worker_pid"])
        self.assertEqual(row["extraction_status"], "ready")
        self.assertEqual(row["extracted_files"], 1)
        self.assertTrue(Path(row["extracted_path"]).joinpath("package/README.txt").exists())
        manifest = json.loads(Path(row["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["archive"]["config_id"], "CONFIG01")
        self.assertEqual(manifest["archive"]["member"], "MEM01")

    def test_extraction_failure_keeps_original_archive(self):
        self.insert("archive", content=b"not-an-archive")
        with mock.patch.object(validate_worker, "validate_archive", return_value=dict(CLEAN)):
            self.assertEqual(validate_worker.validate_upload("archive"), 1)

        row = self.row("archive")
        self.assertEqual(row["status"], "validated")
        self.assertEqual(row["extraction_status"], "failed")
        self.assertIn("analysis copy", row["extraction_error"])
        self.assertTrue(Path(row["stored_path"]).exists())

    def test_extraction_rejects_path_traversal(self):
        self.insert("archive", content=self.archive_bytes("../escape.txt"))
        with mock.patch.object(validate_worker, "validate_archive", return_value=dict(CLEAN)):
            self.assertEqual(validate_worker.validate_upload("archive"), 1)

        row = self.row("archive")
        self.assertEqual(row["extraction_status"], "failed")
        self.assertFalse((self.data_dir / "escape.txt").exists())

    def test_extraction_enforces_total_member_limit(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for name in ("package/one.txt", "package/two.txt"):
                info = tarfile.TarInfo(name)
                info.size = 1
                archive.addfile(info, io.BytesIO(b"x"))
        self.insert("archive", content=buffer.getvalue())

        with (
            mock.patch.object(validate_worker, "validate_archive", return_value=dict(CLEAN)),
            mock.patch.object(portal_lib, "MAX_ARCHIVE_MEMBERS", 1),
        ):
            self.assertEqual(validate_worker.validate_upload("archive"), 1)

        row = self.row("archive")
        self.assertEqual(row["extraction_status"], "failed")
        self.assertTrue(Path(row["stored_path"]).exists())

    def test_rejected_archive_is_not_stored(self):
        temp_path = self.insert("archive")
        rejected = {"errors": ["Init-0/: missing"], "warnings": [], "summary": {}}
        with mock.patch.object(validate_worker, "validate_archive", return_value=rejected):
            validate_worker.validate_upload("archive")

        row = self.row("archive")
        self.assertEqual(row["status"], "rejected")
        self.assertIsNone(row["stored_path"])
        self.assertTrue(temp_path.exists(), "a rejected upload keeps its file for retry")

    def test_missing_temporary_file_is_a_terminal_server_error(self):
        temp_path = self.insert("archive")
        temp_path.unlink()
        self.assertEqual(validate_worker.validate_upload("archive"), 1)
        row = self.row("archive")
        self.assertEqual(row["status"], "server_error")
        self.assertIn(
            "No submission was accepted",
            json.loads(row["validation_json"])["errors"][0],
        )

    def test_validation_crash_is_recorded_not_swallowed(self):
        self.insert("archive")
        with mock.patch.object(
            validate_worker, "validate_archive", side_effect=RuntimeError("boom")
        ):
            self.assertEqual(validate_worker.validate_upload("archive"), 1)
        row = self.row("archive")
        self.assertEqual(row["status"], "server_error")
        self.assertIn("Reference:", json.loads(row["validation_json"])["errors"][0])

    def test_progress_is_published_while_validating(self):
        self.insert("archive")
        seen = []

        def fake_validate(path, filename, metadata, progress=None):
            for done in range(1, 41):
                progress(done, 40)
                seen.append(
                    self.row("archive")["validation_done"]
                )
            return dict(CLEAN)

        with mock.patch.object(validate_worker, "validate_archive", fake_validate):
            validate_worker.validate_upload("archive")

        self.assertEqual(seen[-1], 40, "the final count must reach the browser")
        self.assertGreater(max(seen), 0, "progress must be visible before the end")
        self.assertEqual(self.row("archive")["validation_total"], 40)

    def test_status_moves_to_validating_while_work_is_in_flight(self):
        self.insert("archive")
        observed = {}

        def fake_validate(path, filename, metadata, progress=None):
            observed["status"] = self.row("archive")["status"]
            observed["pid"] = self.row("archive")["worker_pid"]
            return dict(CLEAN)

        with mock.patch.object(validate_worker, "validate_archive", fake_validate):
            validate_worker.validate_upload("archive")

        self.assertEqual(observed["status"], "validating")
        self.assertIsNotNone(observed["pid"])


if __name__ == "__main__":
    unittest.main()
