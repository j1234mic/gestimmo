"""Tests unitaires — chiffrement des identifiants (secure_id).

Vérifie la réversibilité du chiffrement, le rejet des jetons altérés et la
distinction entier / secure_id. Aucune base de données n'est mobilisée.
"""

import os
import tempfile
import unittest

# Clé Fernet de test stable pour toute la session de tests.
_TEST_KEY = os.getenv("SECURE_ID_KEY") or "QKv_PYSNfbjeDsnZjKuISHB-uSnplMhWIjjn-JOfJwo="
os.environ.setdefault("SECURE_ID_KEY", _TEST_KEY)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/x.db")

from app.hexagon.infrastructure.security.id_cipher import (  # noqa: E402
    decrypt_id,
    encrypt_id,
    is_secure_id,
)


class IdCipherUnitTest(unittest.TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        for value in (0, 1, 42, 999999):
            token = encrypt_id(value)
            self.assertIsInstance(token, str)
            self.assertEqual(decrypt_id(token), value)

    def test_secure_id_is_not_the_plain_integer(self):
        token = encrypt_id(123)
        self.assertNotIn("123", token)
        self.assertFalse(token.isdigit())

    def test_is_secure_id_discriminates(self):
        self.assertFalse(is_secure_id(123))
        self.assertFalse(is_secure_id("123"))
        self.assertTrue(is_secure_id(encrypt_id(7)))
        self.assertFalse(is_secure_id("short"))

    def test_decrypt_invalid_token_raises(self):
        with self.assertRaises(ValueError):
            decrypt_id("not-a-valid-token")
        with self.assertRaises(ValueError):
            # Jeton bien formé mais altéré.
            decrypt_id(encrypt_id(5)[:-1] + ("A" if encrypt_id(5)[-1] != "A" else "B"))


if __name__ == "__main__":
    unittest.main()
