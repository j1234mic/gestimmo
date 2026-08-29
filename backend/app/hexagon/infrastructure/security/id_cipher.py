"""Chiffrement des identifiants publics (secure_id).

Objectif : ne jamais exposer l'identifiant entier interne d'une entité dans
l'URL / l'API. On stocke en base une colonne ``secure_id`` contenant le
chiffré (Fernet, AES-128-CBC + HMAC SHA256) de l'identifiant entier.

Choix : Fernet produit un jeton non déterministe (IV aléatoire) mais cela
n'est pas un problème car on recherche toujours par correspondance exacte
sur la colonne ``secure_id`` (et non par motif). L'important est la
réversibilité : ``decrypt_id(encrypt_id(n)) == n``.

La clé de chiffrement provient de ``settings.SECURE_ID_KEY`` (variable
d'environnement ``SECURE_ID_KEY``). Si absente, une clé est générée au
démarrage (la persistance des secure_id existants nécessiterait alors la
même clé : on la rend donc configurable en production).
"""

from __future__ import annotations

import base64
import logging
import secrets

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


def _get_fernet_key() -> bytes:
    raw = getattr(settings, "SECURE_ID_KEY", None) or ""
    raw = raw.strip()
    if raw:
        # Une clé Fernet valide fait exactement 44 caractères base64 url-safe.
        if len(raw) == 44:
            try:
                # Fernet accepte directement la chaîne encodée.
                return raw.encode()
            except Exception:
                pass
        # Sinon, dérive une clé Fernet déterministe à partir de la chaîne fournie.
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF

            salt = b"gestimmo-secure-id-v1"
            hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"fernet")
            derived = hkdf.derive(raw.encode())
            # Fernet attend une clé encodée en base64 url-safe (44 caractères).
            return base64.urlsafe_b64encode(derived)
        except Exception:
            logger.warning("SECURE_ID_KEY invalide : utilisation d'une clé de session à la place.")
    # Aucune clé configurée : on génère une clé de session (non persistante).
    logger.warning(
        "SECURE_ID_KEY non configurée : une clé éphémère est générée. "
        "Les secure_id existants ne pourront pas être déchiffrés après redémarrage."
    )
    return Fernet.generate_key()


_FERNET = Fernet(_get_fernet_key())


def encrypt_id(value: int) -> str:
    """Chiffre un identifiant entier en secure_id (chaîne base64 url-safe)."""
    token = _FERNET.encrypt(str(int(value)).encode("utf-8"))
    return token.decode("utf-8")


def decrypt_id(secure_id: str) -> int:
    """Déchiffre un secure_id en identifiant entier.

    Lève ``ValueError`` si le jeton est invalide ou altéré.
    """
    try:
        raw = _FERNET.decrypt(secure_id.encode("utf-8"))
    except (InvalidToken, ValueError) as exc:
        raise ValueError(f"secure_id invalide ou illisible : {secure_id!r}") from exc
    return int(raw.decode("utf-8"))


def is_secure_id(value) -> bool:
    """Vrai si ``value`` ressemble à un secure_id (et n'est pas un entier)."""
    if value is None:
        return False
    if isinstance(value, int):
        return False
    text = str(value)
    if text.isdigit():
        return False
    # Un secure_id Fernet fait ~44–88 caractères base64 url-safe.
    if len(text) < 20:
        return False
    try:
        base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except Exception:
        return False
    return True
