"""scripts/init_env.py : génération de clés stables et alignement de DATABASE_URL."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "init_env.py"
_spec = importlib.util.spec_from_file_location("init_env", _SCRIPT)
init_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(init_env)  # type: ignore[union-attr]


class InitEnvTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gestimmo-init-env-")
        self.addCleanup(self._tmp.cleanup)
        self.env_file = Path(self._tmp.name) / ".env"
        self._orig_env_file = init_env.ENV_FILE
        init_env.ENV_FILE = self.env_file
        self.addCleanup(setattr, init_env, "ENV_FILE", self._orig_env_file)

    def write(self, content: str) -> None:
        self.env_file.write_text(content, encoding="utf-8")

    def read(self) -> str:
        return self.env_file.read_text(encoding="utf-8")

    def apply(self, db_host=None):
        lines = init_env.load_env_lines()
        new_lines, touched = init_env.apply(lines, db_host)
        init_env.write_env(new_lines)
        return touched

    def test_generates_missing_keys(self):
        self.write("DATABASE_URL=postgresql://immo_user:immo_password_2024@localhost:5432/immo_db\n")
        touched = self.apply()
        self.assertIn("SECRET_KEY", touched)
        self.assertIn("SECURE_ID_KEY", touched)
        content = self.read()
        for key in ("SECRET_KEY", "SECURE_ID_KEY"):
            value = next(line for line in content.splitlines() if line.startswith(f"{key}=")).split("=", 1)[1]
            self.assertGreaterEqual(len(value), 32)
        # Une clé Fernet valide fait 44 caractères base64 url-safe.
        secure_key = next(line for line in content.splitlines() if line.startswith("SECURE_ID_KEY=")).split("=", 1)[1]
        self.assertEqual(len(secure_key), 44)

    def test_replaces_placeholder_secret(self):
        self.write("SECRET_KEY=changez-cette-cle-secrete-minimum-32-caracteres\n")
        touched = self.apply()
        self.assertIn("SECRET_KEY", touched)
        self.assertNotIn("changez-cette-cle-secrete", self.read())

    def test_existing_values_preserved(self):
        self.write("SECRET_KEY=une-cle-deja-configuree-suffisamment-longue-pour-le-jwt\nSECURE_ID_KEY=QKv_PYSNfbjeDsnZjKuISHB-uSnplMhWIjjn-JOfJwo=\n")
        touched = self.apply()
        self.assertEqual(touched, {})
        self.assertIn("une-cle-deja-configuree", self.read())

    def test_idempotent(self):
        self.write("# commentaire conservé\nDATABASE_URL=postgresql://u:p@postgres:5432/immo_db\n")
        self.apply()
        first = self.read()
        self.apply()
        self.assertEqual(self.read(), first)
        self.assertIn("# commentaire conservé", first)

    def test_db_host_rewritten(self):
        self.write("DATABASE_URL=postgresql://immo_user:immo_password_2024@postgres:5432/immo_db\n")
        self.apply(db_host="localhost")
        self.assertIn(
            "DATABASE_URL=postgresql://immo_user:immo_password_2024@localhost:5432/immo_db", self.read()
        )
        self.apply(db_host="postgres")
        self.assertIn(
            "DATABASE_URL=postgresql://immo_user:immo_password_2024@postgres:5432/immo_db", self.read()
        )

    def test_check_reports_missing_keys_without_writing(self):
        self.write("DATABASE_URL=postgresql://u:p@localhost:5432/immo_db\n")
        actions = init_env.changes_needed(init_env.load_env_lines(), None)
        self.assertTrue(any("SECRET_KEY" in action for action in actions))
        self.assertTrue(any("SECURE_ID_KEY" in action for action in actions))
        self.assertEqual(self.read(), "DATABASE_URL=postgresql://u:p@localhost:5432/immo_db\n")

    def test_comments_and_order_preserved(self):
        original = (
            "# Environnement\n"
            "ENVIRONMENT=development\n"
            "\n"
            "# Base de données\n"
            "DATABASE_URL=postgresql://u:p@localhost:5432/immo_db # dev local\n"
        )
        self.write(original)
        self.apply()
        content = self.read()
        self.assertLess(content.index("ENVIRONMENT=development"), content.index("SECRET_KEY="))
        self.assertIn("# Environnement", content)

    def test_replace_db_host_keeps_everything_else(self):
        url = "postgresql://immo_user:immo_p@ss@postgres:5433/immo_db?sslmode=disable"
        new = init_env.replace_db_host(url, "localhost")
        self.assertEqual(new, "postgresql://immo_user:immo_p@ss@localhost:5433/immo_db?sslmode=disable")


if __name__ == "__main__":
    unittest.main()
