import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "portal" / "backend"
sys.path.insert(0, str(BACKEND))

import portal_lib  # noqa: E402


class ParticipationProfileTests(unittest.TestCase):
    def setUp(self):
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
            VALUES (5, 'shixm@ust.hk', 'Xiaoming Bill SHI', 'HKUST', 'admin',
                    'approved', 'salt', 'hash', 'now', 'now')
            """
        )
        self.con.commit()

    def tearDown(self):
        self.con.close()

    def test_institution_aliases_use_canonical_short_name(self):
        self.assertEqual(
            portal_lib.canonical_institution(
                "The Hong Kong University of Science and Technology"
            ),
            "HKUST",
        )
        self.assertEqual(portal_lib.canonical_institution(" HKUST "), "HKUST")
        self.assertEqual(portal_lib.canonical_institution("KNMI"), "KNMI")

    def test_known_poc_is_seeded_from_participation_registry(self):
        portal_lib.seed_participation_profiles(self.con)

        user = self.con.execute(
            "SELECT poc_surname, participants FROM users WHERE id = 5"
        ).fetchone()
        profiles = portal_lib.participation_profiles_for_user(self.con, 5)

        self.assertEqual(user["poc_surname"], "SHI")
        self.assertIn("Fei Chen", user["participants"])
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["group_name"], "HKUST MPAS")
        self.assertEqual(profiles[0]["model"], "MPAS")
        self.assertEqual(profiles[0]["forcing_sources"], "ERA5, GFS")

    def test_seed_does_not_overwrite_account_values_or_duplicate_profiles(self):
        self.con.execute(
            "UPDATE users SET poc_surname = 'CUSTOM', participants = 'Custom Team' WHERE id = 5"
        )
        portal_lib.seed_participation_profiles(self.con)
        portal_lib.seed_participation_profiles(self.con)

        user = self.con.execute(
            "SELECT poc_surname, participants FROM users WHERE id = 5"
        ).fetchone()
        count = self.con.execute(
            "SELECT COUNT(*) AS count FROM participation_profiles WHERE poc_user_id = 5"
        ).fetchone()["count"]

        self.assertEqual(dict(user), {"poc_surname": "CUSTOM", "participants": "Custom Team"})
        self.assertEqual(count, 1)

    def test_me_exposes_registered_profiles(self):
        loader_path = ROOT / "portal" / "api.cgi"
        import importlib.machinery
        import importlib.util

        loader = importlib.machinery.SourceFileLoader(
            "participation_api_test", str(loader_path)
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        api = importlib.util.module_from_spec(spec)
        loader.exec_module(api)

        user = self.con.execute("SELECT * FROM users WHERE id = 5").fetchone()
        portal_lib.seed_participation_profiles(self.con)
        with mock.patch.object(api, "current_user", return_value=dict(user)):
            result = api.handle_me(self.con)

        self.assertEqual(result["user"]["participation_profiles"][0]["model"], "MPAS")

    def test_upload_identity_comes_from_database_profile(self):
        loader_path = ROOT / "portal" / "api.cgi"
        import importlib.machinery
        import importlib.util

        loader = importlib.machinery.SourceFileLoader(
            "participation_upload_api_test", str(loader_path)
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        api = importlib.util.module_from_spec(spec)
        loader.exec_module(api)

        user = dict(self.con.execute("SELECT * FROM users WHERE id = 5").fetchone())
        portal_lib.seed_participation_profiles(self.con)
        payload = {
            "file_name": "HKUST-MPAS-HRAIN2025-SHI.zip",
            "file_size": 1,
            "participants": "Forged participant list",
        }
        with (
            mock.patch.object(api, "require_approved_user", return_value=user),
            mock.patch.object(api, "read_json", return_value=payload),
        ):
            result = api.handle_upload_start(self.con)

        row = self.con.execute(
            "SELECT poc, model, event, participants FROM uploads WHERE upload_id = ?",
            (result["upload_id"],),
        ).fetchone()
        self.assertEqual(row["poc"], "SHI")
        self.assertEqual(row["model"], "MPAS")
        self.assertEqual(row["event"], "HRAIN2025")
        self.assertIn("Fei Chen", row["participants"])
        self.assertNotIn("Forged participant list", row["participants"])


if __name__ == "__main__":
    unittest.main()
