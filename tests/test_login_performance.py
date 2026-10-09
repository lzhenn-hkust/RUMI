import importlib.machinery
import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "portal" / "backend"))
import portal_lib  # noqa: E402

loader = importlib.machinery.SourceFileLoader("login_api_test", str(ROOT / "portal" / "api.cgi"))
spec = importlib.util.spec_from_loader(loader.name, loader)
api = importlib.util.module_from_spec(spec)
loader.exec_module(api)


class DatabaseLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name, value in {
            "DATA_DIR": root / "private",
            "DB_PATH": root / "private" / "portal.sqlite3",
            "INCOMING_DIR": root / "private" / "incoming",
            "SUBMISSIONS_DIR": root / "private" / "submissions",
            "EXTRACTED_DIR": root / "private" / "extracted",
            "MANIFESTS_DIR": root / "private" / "manifests",
            "LOG_DIR": root / "private" / "logs",
        }.items():
            self.stack.enter_context(mock.patch.object(portal_lib, name, value))

    def test_missing_database_is_not_silently_created_by_a_request(self):
        with self.assertRaises(sqlite3.OperationalError):
            portal_lib.connect_db()
        self.assertFalse(portal_lib.DATA_DIR.exists())

    def test_explicit_initialization_prepares_schema_and_private_directories(self):
        con = portal_lib.connect_db(initialize=True)
        self.addCleanup(con.close)
        self.assertEqual(con.execute("SELECT count(*) FROM users").fetchone()[0], 0)
        self.assertEqual(con.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertTrue(portal_lib.INCOMING_DIR.is_dir())
        self.assertIn("Deny from all", (portal_lib.DATA_DIR / ".htaccess").read_text())
        self.assertEqual(portal_lib.DB_PATH.stat().st_mode & 0o777, 0o660)

    def test_ordinary_connection_does_not_write_or_run_initialization(self):
        portal_lib.connect_db(initialize=True).close()
        before = portal_lib.DB_PATH.read_bytes()
        with mock.patch.object(portal_lib, "ensure_dirs") as dirs, mock.patch.object(
            portal_lib, "init_schema"
        ) as schema, mock.patch.object(Path, "chmod") as chmod:
            con = portal_lib.connect_db()
            try:
                self.assertEqual(con.total_changes, 0)
                self.assertFalse(con.in_transaction)
                self.assertEqual(con.execute("SELECT count(*) FROM users").fetchone()[0], 0)
            finally:
                con.close()
        dirs.assert_not_called()
        schema.assert_not_called()
        chmod.assert_not_called()
        self.assertEqual(portal_lib.DB_PATH.read_bytes(), before)


class LoginTransactionTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.addCleanup(self.con.close)
        self.con.row_factory = sqlite3.Row
        portal_lib.init_schema(self.con)
        salt, digest = portal_lib.hash_password("correct-password")
        self.con.execute(
            """INSERT INTO users(email, name, institution, status, password_salt,
               password_hash, created_at, updated_at)
               VALUES ('login@example.org', 'Test', 'HKUST', 'approved', ?, ?, 'old', 'old')""",
            (salt, digest),
        )
        self.con.commit()

    def login(self, password="correct-password"):
        with mock.patch.object(api, "read_json", return_value={
            "email": "login@example.org", "password": password,
        }):
            return api.handle_login(self.con)

    def test_success_commits_audit_session_and_timestamp_together(self):
        statements = []
        self.con.set_trace_callback(statements.append)
        result = self.login()
        self.assertTrue(result["payload"]["ok"])
        self.assertEqual(sum(s == "COMMIT" for s in statements), 1)
        self.assertEqual(self.con.execute("SELECT success FROM login_attempts").fetchone()[0], 1)
        self.assertEqual(self.con.execute("SELECT count(*) FROM sessions").fetchone()[0], 1)
        self.assertIsNotNone(self.con.execute("SELECT last_login FROM users").fetchone()[0])
        token = result["cookies"][0].split(";", 1)[0].split("=", 1)[1]
        self.assertEqual(portal_lib.get_session_user(self.con, token)["email"], "login@example.org")

    def test_late_failure_rolls_back_success_record_and_session(self):
        self.con.execute("""CREATE TRIGGER fail_login_timestamp BEFORE UPDATE OF last_login
                            ON users BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        self.con.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.login()
        self.assertEqual(self.con.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT count(*) FROM login_attempts").fetchone()[0], 0)
        self.assertIsNone(self.con.execute("SELECT last_login FROM users").fetchone()[0])

    def test_failed_attempts_remain_committed_and_rate_limited(self):
        for _ in range(10):
            with self.assertRaises(portal_lib.PortalError) as raised:
                with self.con:
                    self.login("incorrect-password")
            self.assertEqual(raised.exception.status, 401)
        with self.assertRaises(portal_lib.PortalError) as raised:
            self.login()
        self.assertEqual(raised.exception.status, 429)
        self.assertEqual(self.con.execute("SELECT count(*) FROM login_attempts").fetchone()[0], 10)
        self.assertEqual(self.con.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)

    def test_disabled_user_cannot_create_a_session(self):
        self.con.execute("UPDATE users SET status = 'disabled'")
        self.con.commit()
        with self.assertRaises(portal_lib.PortalError) as raised:
            with self.con:
                self.login()
        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(self.con.execute("SELECT success FROM login_attempts").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)

    def test_anonymous_me_returns_public_payload_without_database(self):
        with mock.patch.dict(os.environ, {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=me",
                                          "HTTP_COOKIE": ""}), mock.patch.object(
            api, "connect_db", side_effect=AssertionError("anonymous request opened DB")
        ) as connect, mock.patch.object(api, "send_json") as send:
            api.main()
        connect.assert_not_called()
        send.assert_called_once_with(api.me_payload(None, None))

    def test_session_cookie_still_looks_up_and_authenticates_user(self):
        token, _ = portal_lib.create_session(self.con, 1)
        with mock.patch.dict(os.environ, {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=me",
                                          "HTTP_COOKIE": "rumi_session=" + token}), mock.patch.object(
            api, "connect_db", return_value=self.con
        ) as connect, mock.patch.object(api, "send_json") as send:
            api.main()
        connect.assert_called_once()
        self.assertEqual(send.call_args.args[0]["user"]["email"], "login@example.org")

    def test_invalid_session_cookie_does_not_authenticate_user(self):
        with mock.patch.dict(os.environ, {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=me",
                                          "HTTP_COOKIE": "rumi_session=invalid"}), mock.patch.object(
            api, "connect_db", return_value=self.con
        ), mock.patch.object(api, "send_json") as send:
            api.main()
        self.assertIsNone(send.call_args.args[0]["user"])


if __name__ == "__main__":
    unittest.main()
