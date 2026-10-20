"""Façade de stockage : disque local ou Vercel Blob, au choix de l'exploitation.

Pourquoi une façade
-------------------
Le dépôt écrit des fichiers à ~20 endroits (médias de biens, GED, pièces
locataires, preuves de signature, annexes de bail, exports, sauvegardes) et les
relit via ``FileResponse(<chemin>)``. Sur Vercel, le système de fichiers est en
lecture seule hors ``/tmp`` et ``/tmp`` est effacé à la mise à l'échelle à zéro :
rien ne survit. Cette façade permet de basculer sur Vercel Blob **sans réécrire
la logique métier** :

* les écritures restent locales (l'OCR, les miniatures et les hachages
  existants continuent de lire le fichier qu'ils viennent d'écrire) ;
* :func:`mirror` réplique ensuite le fichier vers Blob et renvoie son URL ;
* la référence persistée en base devient cette URL quand la réplication réussit,
  le chemin local sinon (:func:`reference_for`) ;
* les lectures passent par :func:`response`, :func:`read_bytes` ou
  :func:`exists`, qui comprennent les deux formes (chemin local ou URL).

Une réplication en échec ne fait jamais échouer l'appel métier quand
``BLOB_FAIL_OPEN`` est vrai : la copie locale reste utilisable et l'incident est
journalisé. C'est le compromis assumé d'un déploiement serverless sans disque
durable — le fichier est perdu au prochain redémarrage, mais la requête aboutit.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Iterator

from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse

from app.config import settings
from app.services import blob_storage
from app.services.blob_storage import BlobStorageError

logger = logging.getLogger(__name__)

# Préfixes de classement dans le store : ils remplacent les trois racines disque
# (public, privé, sauvegardes) et rendent le contenu listable par module.
PUBLIC_PREFIX = "public"
PRIVATE_PREFIX = "private"
BACKUP_PREFIX = "backups"


# ---------------------------------------------------------------------------
# État du moteur
# ---------------------------------------------------------------------------
def remote_enabled() -> bool:
    """Vrai quand le stockage distant (Vercel Blob) est actif et crédenté."""
    return settings.blob_enabled


def is_remote(reference: str | None) -> bool:
    """Vrai quand la référence est une URL Blob plutôt qu'un chemin local."""
    return blob_storage.is_blob_url(reference)


def describe_backend() -> dict[str, object]:
    """État lisible du moteur de stockage, exposé par /health et /api/cron."""
    if not remote_enabled():
        reason = (
            "STORAGE_BACKEND=blob mais BLOB_READ_WRITE_TOKEN absent"
            if settings.STORAGE_BACKEND == "blob"
            else "STORAGE_BACKEND=local"
        )
        return {"backend": "local", "durable": not _is_ephemeral_root(), "detail": reason}
    return {
        "backend": "blob",
        "durable": True,
        "access": settings.BLOB_ACCESS,
        "api_url": settings.BLOB_API_URL,
    }


def _is_ephemeral_root() -> bool:
    """Vrai quand la racine d'upload pointe vers /tmp (éphémère sur Vercel)."""
    roots = (settings.upload_dir_path, settings.private_upload_dir_path, settings.backup_dir_path)
    return any(str(root).startswith("/tmp") for root in roots)


# ---------------------------------------------------------------------------
# Clés d'objet
# ---------------------------------------------------------------------------
def _roots() -> tuple[tuple[Path, str], ...]:
    return (
        (Path(settings.upload_dir_path), PUBLIC_PREFIX),
        (Path(settings.private_upload_dir_path), PRIVATE_PREFIX),
        (Path(settings.backup_dir_path), BACKUP_PREFIX),
    )


def object_key(local_path: Path | str, *, prefix: str | None = None) -> str:
    """Construit la clé Blob d'un fichier local.

    La clé conserve l'arborescence relative à la racine concernée
    (``ged/12/facture.pdf``, ``12/photo.jpg``, ``backup-2026-10-20.dump``), ce
    qui garde les objets regroupés par module et par entité dans le store.
    """
    path = Path(local_path)
    for root, default_prefix in _roots():
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        chosen = prefix or default_prefix
        return f"{chosen}/{relative.as_posix()}".replace("//", "/")

    # Fichier hors des racines d'upload (export temporaire, pièce jointe
    # générée) : on classe sous le préfixe demandé ou « private ».
    chosen = prefix or PRIVATE_PREFIX
    return f"{chosen}/{path.name}"


def guess_content_type(path: Path | str, fallback: str | None = None) -> str:
    """Devine le type MIME d'un fichier à partir de son extension."""
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or fallback or "application/octet-stream"


# ---------------------------------------------------------------------------
# Écritures
# ---------------------------------------------------------------------------
def store_bytes(
    content: bytes,
    key: str,
    *,
    content_type: str | None = None,
    access: str | None = None,
) -> str | None:
    """Téléverse ``content`` sous ``key`` et renvoie l'URL Blob, ou ``None``.

    ``None`` signifie « réplication indisponible » : moteur local, jeton absent
    ou échec toléré (``BLOB_FAIL_OPEN``). Sans tolérance, l'échec remonte.
    """
    if not remote_enabled():
        return None
    try:
        payload = blob_storage.put_object(
            key, content, content_type=content_type, access=access
        )
    except BlobStorageError as exc:
        if settings.BLOB_FAIL_OPEN:
            logger.error("Vercel Blob : écriture de « %s » en échec, copie locale conservée — %s", key, exc)
            return None
        raise
    return payload.get("url")


def mirror(
    local_path: Path | str,
    key: str | None = None,
    *,
    content_type: str | None = None,
    access: str | None = None,
) -> str | None:
    """Réplique un fichier déjà écrit sur disque vers Vercel Blob.

    C'est le point d'entrée des sites d'écriture existants : ils continuent
    d'écrire localement (nécessaire à l'OCR, aux miniatures et aux hachages),
    puis appellent cette fonction pour rendre le fichier durable.
    """
    path = Path(local_path)
    if not remote_enabled() or not path.is_file():
        return None
    resolved_key = key or object_key(path)
    try:
        content = path.read_bytes()
    except OSError as exc:
        logger.error("Vercel Blob : lecture locale de « %s » impossible — %s", path, exc)
        return None
    return store_bytes(
        content,
        resolved_key,
        content_type=content_type or guess_content_type(path),
        access=access,
    )


def reference_for(local_path: Path | str, remote_url: str | None) -> str:
    """Renvoie la référence à persister en base : URL Blob si disponible.

    La colonne reste un ``String(700)`` : une URL Blob (~110 caractères) y tient
    largement, et les lignes écrites avant la migration continuent de pointer
    vers des chemins locaux valides.
    """
    return remote_url or str(local_path)


# ---------------------------------------------------------------------------
# Lectures
# ---------------------------------------------------------------------------
def local_path(reference: str | None) -> Path | None:
    """Chemin local d'une référence, ou ``None`` si elle est distante."""
    if not reference or is_remote(reference):
        return None
    return Path(reference)


def exists(reference: str | None) -> bool:
    """Teste la disponibilité d'une référence, locale ou distante."""
    if not reference:
        return False
    if is_remote(reference):
        try:
            blob_storage.head_object(reference)
        except BlobStorageError:
            return False
        return True
    return Path(reference).is_file()


def read_bytes(reference: str | None) -> bytes:
    """Lit le contenu d'une référence, locale ou distante.

    Utilisé par l'OCR, les hachages et les exports qui repartent d'un document
    déjà stocké.
    """
    if not reference:
        raise FileNotFoundError("Référence de stockage vide")
    if is_remote(reference):
        return blob_storage.get_object(reference)
    path = Path(reference)
    if not path.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    return path.read_bytes()


def stream(reference: str | None) -> Iterator[bytes]:
    """Flux de lecture par morceaux, local ou distant."""
    if not reference:
        raise FileNotFoundError("Référence de stockage vide")
    if is_remote(reference):
        return blob_storage.stream_object(reference)

    def _local() -> Iterator[bytes]:
        path = Path(reference)
        if not path.is_file():
            raise FileNotFoundError(f"Fichier introuvable : {path}")
        with path.open("rb") as handle:
            while chunk := handle.read(65_536):
                yield chunk

    return _local()


def materialize(reference: str | None, *, suffix: str = "") -> Path:
    """Renvoie un chemin local lisible par les outils qui exigent un fichier.

    L'OCR (``pytesseract``), ``pypdf`` et ``PyMuPDF`` ouvrent un chemin : ils ne
    savent pas lire une URL. Pour une référence distante, l'objet est rapatrié
    dans un fichier temporaire — sous ``/tmp`` sur Vercel, donc dans la seule
    zone inscriptible. Pour une référence locale, le chemin est renvoyé tel quel
    (aucune copie).

    L'appelant est responsable de la suppression du fichier temporaire ;
    :func:`discard_temporary` le fait sans lever s'il a déjà disparu.
    """
    if not reference:
        raise FileNotFoundError("Référence de stockage vide")
    if not is_remote(reference):
        path = Path(reference)
        if not path.is_file():
            raise FileNotFoundError(f"Fichier introuvable : {path}")
        return path

    import tempfile

    resolved_suffix = suffix or Path(reference.split("?")[0]).suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(
        prefix="gestimmo-", suffix=resolved_suffix, delete=False
    )
    try:
        handle.write(read_bytes(reference))
    finally:
        handle.close()
    return Path(handle.name)


def discard_temporary(path: Path | str | None) -> None:
    """Supprime un fichier temporaire de :func:`materialize`, sans lever."""
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Nettoyage du fichier temporaire « %s » en échec — %s", path, exc)


def response(
    reference: str | None,
    *,
    media_type: str | None = None,
    filename: str | None = None,
    inline: bool = False,
) -> Response:
    """Construit la réponse HTTP de téléchargement d'une référence.

    Trois cas :

    * **chemin local** — ``FileResponse``, comportement historique inchangé ;
    * **URL Blob + store public + lecture en ligne** — redirection 302 vers le
      CDN : l'octet ne transite pas par la Function (ni coût, ni limite de
      corps de réponse) ;
    * **URL Blob + pièce jointe nommée ou store privé** — flux relayé par l'API,
      seul moyen de poser ``Content-Disposition`` avec le nom d'origine et de
      servir un store privé.
    """
    if not reference:
        raise FileNotFoundError("Référence de stockage vide")

    if not is_remote(reference):
        path = Path(reference)
        if not path.is_file():
            raise FileNotFoundError(f"Fichier introuvable : {path}")
        return FileResponse(
            str(path),
            media_type=media_type or guess_content_type(path),
            filename=None if inline else (filename or path.name),
        )

    # Validation avant d'ouvrir le flux : sans ce contrôle, un objet supprimé
    # produirait une réponse 200 dont le corps s'interrompt, au lieu d'un 404
    # exploitable par le client.
    try:
        metadata = blob_storage.head_object(reference)
    except blob_storage.BlobNotFound as exc:
        raise FileNotFoundError(f"Objet distant introuvable : {reference}") from exc
    except BlobStorageError as exc:
        logger.error("Vercel Blob : métadonnées de « %s » illisibles — %s", reference, exc)
        raise FileNotFoundError(f"Objet distant illisible : {reference}") from exc

    resolved_media = media_type or metadata.get("contentType") or guess_content_type(reference)
    wants_named_download = bool(filename) and not inline
    if settings.BLOB_ACCESS == "public" and not wants_named_download:
        # Store public : le CDN Vercel sert l'objet directement. Ni bande
        # passante Function, ni limite de corps de réponse.
        return RedirectResponse(reference, status_code=302)

    try:
        content_stream = blob_storage.stream_object(reference)
    except BlobStorageError as exc:
        logger.error("Vercel Blob : lecture de « %s » en échec — %s", reference, exc)
        raise FileNotFoundError(f"Objet distant illisible : {reference}") from exc

    headers = {}
    if filename:
        # RFC 6266 : ASCII dans filename, UTF-8 dans filename* pour les accents.
        ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "document"
        headers["Content-Disposition"] = (
            f'{"inline" if inline else "attachment"}; filename="{ascii_name}"'
        )
        if ascii_name != filename:
            from urllib.parse import quote

            headers["Content-Disposition"] += f"; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(content_stream, media_type=resolved_media, headers=headers)


# ---------------------------------------------------------------------------
# Suppressions
# ---------------------------------------------------------------------------
def delete(reference: str | None) -> None:
    """Supprime une référence, locale ou distante, sans lever si elle est absente."""
    if not reference:
        return
    if is_remote(reference):
        try:
            blob_storage.delete_objects([reference])
        except BlobStorageError as exc:
            logger.warning("Vercel Blob : suppression de « %s » en échec — %s", reference, exc)
        return
    path = Path(reference)
    try:
        if path.is_file():
            path.unlink()
    except OSError as exc:
        logger.warning("Suppression locale de « %s » en échec — %s", path, exc)
