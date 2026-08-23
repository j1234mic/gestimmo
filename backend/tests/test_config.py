"""Lecture des variables d'environnement et rate limiting global."""

import os
import tempfile
import unittest

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-config-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DIR}/tests.db")
os.environ.setdefault("DEBUG", "false")

from app.config import parse_bool, parse_csv_list, parse_float, parse_int, settings  # noqa: E402
from app.middleware.rate_limit import RateLimiter  # noqa: E402


class EnvParsingTest(unittest.TestCase):
    def test_parse_bool(self):
        self.assertTrue(parse_bool("true", False))
        self.assertTrue(parse_bool("YES", False))
        self.assertTrue(parse_bool("1", False))
        self.assertFalse(parse_bool("false", True))
        self.assertFalse(parse_bool(None, False))
        self.assertTrue(parse_bool("  ", True))

    def test_parse_int_and_float(self):
        self.assertEqual(parse_int("30", 1), 30)
        self.assertEqual(parse_int("abc", 7), 7)
        self.assertEqual(parse_int(None, 12), 12)
        self.assertEqual(parse_float("25.5", 1.0), 25.5)
        self.assertEqual(parse_float("nope", 3.0), 3.0)

    def test_parse_csv_list(self):
        self.assertEqual(
            parse_csv_list("http://localhost:3000, http://localhost:5173"),
            ["http://localhost:3000", "http://localhost:5173"],
        )
        self.assertEqual(parse_csv_list("", ["*"]), ["*"])
        self.assertEqual(parse_csv_list(None, ["*"]), ["*"])

    def test_settings_expose_env_defaults(self):
        self.assertGreaterEqual(settings.ACCESS_TOKEN_EXPIRE_MINUTES, 1)
        self.assertGreaterEqual(settings.REFRESH_TOKEN_EXPIRE_DAYS, 1)
        self.assertGreaterEqual(settings.RATE_LIMIT_REQUESTS, 1)
        self.assertGreaterEqual(settings.RATE_LIMIT_WINDOW, 1)
        self.assertGreater(settings.MAX_UPLOAD_SIZE, 0)
        self.assertTrue(settings.ALLOWED_ORIGINS)
        self.assertTrue(settings.LOG_LEVEL)
        self.assertIn("jpg", settings.ALLOWED_EXTENSIONS)


class RateLimiterTest(unittest.TestCase):
    def test_blocks_after_max_requests(self):
        limiter = RateLimiter(max_requests=2, window=60)
        self.assertFalse(limiter.is_limited("1.2.3.4"))
        self.assertFalse(limiter.is_limited("1.2.3.4"))
        self.assertTrue(limiter.is_limited("1.2.3.4"))
        self.assertFalse(limiter.is_limited("9.9.9.9"))


if __name__ == "__main__":
    unittest.main()
