"""Client Vercel Blob minimal, sans dépendance supplémentaire.

Le SDK Python officiel ``vercel-blob`` exige ``pydantic>=2.7`` et ``httpx2``,
incompatibles avec les versions épinglées du projet (``pydantic==2.5.2``,
``httpx==0.25.2``). Ce module reproduit donc directement le contrat REST du SDK
TypeScript ``@vercel/blob`` 2.8.2 :

===========================  ==================================================
Opération                    Requête
===========================  ==================================================
Téléverser                   ``PUT  {base}/?pathname=<encodé>``
Métadonnées (équivalent head) ``GET  {base}/?url=<encodé>``
Lister                       ``GET  {base}/?prefix=&limit=&cursor=``
Supprimer                    ``POST {base}/delete`` avec ``{"urls": [...]}``
Lire le contenu              ``GET`` sur l'URL de l'objet
===========================  ==================================================

avec ``base = https://vercel.com/api/blob`` (``BLOB_API_URL``) et les entêtes
``x-api-version: 13``, ``authorization: Bearer $BLOB_READ_WRITE_TOKEN``,
``x-vercel-blob-access``, ``x-content-type``, ``x-cache-control-max-age`` et
``x-add-random-suffix``.

Les objets de plus de ``BLOB_MULTIPART_THRESHOLD`` (100 Mo par défaut) sont
refusés avec un message explicite : Vercel recommande alors l'upload multipart
ou un téléversement direct du navigateur vers le store.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterator
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Codes renvoyés par la plateforme quand l'objet est absent ou le jeton invalide.
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class BlobStorageError(RuntimeError):
    """Échec d'un appel à Vercel Blob (réseau, quota, jeton, objet absent)."""


class BlobNotFound(BlobStorageError):
    """L'objet demandé n'existe pas dans le store."""


def is_blob_url(reference: str | None) -> bool:
    """Vrai quand la référence stockée en base est une URL Vercel Blob."""
    if not reference:
        return False
    lowered = reference.strip().lower()
    return lowered.startswith(("http://", "https://")) and "blob.vercel-storage.com" in lowered


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    token = settings.BLOB_READ_WRITE_TOKEN
    if not token:
        raise BlobStorageError(
            "BLOB_READ_WRITE_TOKEN est absent : créez un store Blob dans le "
            "tableau de bord Vercel (Storage → Create → Blob) puis recopiez le "
            "jeton dans les variables d'environnement du projet."
        )
    headers = {
        "authorization": f"Bearer {token}",
        "x-api-version": str(settings.BLOB_API_VERSION),
    }
    if settings.BLOB_STORE_ID:
        headers["x-vercel-blob-store-id"] = settings.BLOB_STORE_ID
    if extra:
        headers.update(extra)
    return headers


def _client(timeout: float | None = None) -> httpx.Client:
    return httpx.Client(timeout=timeout or settings.BLOB_TIMEOUT_SECONDS)


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    content: bytes | None = None,
    json_body: Any | None = None,
    timeout: float | None = None,
) -> httpx.Response:
    """Exécute un appel avec relances bornées sur les erreurs transitoires."""
    last_error: str = ""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with _client(timeout) as client:
                response = client.request(
                    method,
                    url,
                    headers=headers,
                    content=content,
                    json=json_body,
                )
        except httpx.HTTPError as exc:  # réseau, DNS, TLS, délai dépassé
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Vercel Blob : échec réseau (tentative %d/%d) — %s", attempt, _MAX_ATTEMPTS, last_error)
            if attempt < _MAX_ATTEMPTS:
                time.sleep(0.5 * attempt)
                continue
            raise BlobStorageError(f"Vercel Blob injoignable : {last_error}") from exc

        if response.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
            retry_after = response.headers.get("retry-after")
            try:
                delay = float(retry_after) if retry_after else 0.5 * attempt
            except ValueError:
                delay = 0.5 * attempt
            logger.warning(
                "Vercel Blob : statut %d (tentative %d/%d), nouvelle tentative dans %.1fs",
                response.status_code, attempt, _MAX_ATTEMPTS, delay,
            )
            time.sleep(min(delay, 10.0))
            continue

        if response.status_code == 404:
            raise BlobNotFound(f"Objet Vercel Blob introuvable : {url}")
        if response.status_code >= 400:
            detail = response.text[:500]
            raise BlobStorageError(f"Vercel Blob a refusé la requête ({response.status_code}) : {detail}")
        return response

    raise BlobStorageError(f"Vercel Blob : échec après {_MAX_ATTEMPTS} tentatives ({last_error})")


def put_object(
    pathname: str,
    content: bytes,
    *,
    content_type: str | None = None,
    access: str | None = None,
    add_random_suffix: bool | None = None,
    cache_control_max_age: int | None = None,
) -> dict[str, Any]:
    """Téléverse ``content`` sous ``pathname`` et renvoie le descripteur Blob.

    Le descripteur contient ``url`` (lecture), ``downloadUrl`` (avec en-tête de
    téléchargement), ``pathname`` (avec suffixe aléatoire éventuel) et
    ``contentType``.
    """
    clean = (pathname or "").strip().lstrip("/")
    if not clean:
        raise BlobStorageError("Le pathname Vercel Blob ne peut pas être vide")
    if "//" in clean:
        # Le SDK officiel rejette les doubles barres obliques : elles cassent la
        # résolution du pathname côté store.
        raise BlobStorageError(f"Le pathname Vercel Blob ne peut pas contenir « // » : {clean}")

    size = len(content)
    if size > settings.BLOB_MULTIPART_THRESHOLD:
        raise BlobStorageError(
            f"Objet de {size} octets supérieur au seuil multipart "
            f"({settings.BLOB_MULTIPART_THRESHOLD} octets). Utilisez l'upload "
            "multipart de Vercel Blob ou un téléversement direct du navigateur."
        )

    resolved_access = (access or settings.BLOB_ACCESS or "public").lower()
    if resolved_access not in {"public", "private"}:
        raise BlobStorageError(
            f"BLOB_ACCESS doit valoir « public » ou « private » (reçu : {resolved_access})"
        )
    suffix = settings.BLOB_ADD_RANDOM_SUFFIX if add_random_suffix is None else add_random_suffix

    headers = _headers({
        "x-vercel-blob-access": resolved_access,
        "x-content-type": content_type or "application/octet-stream",
        "x-cache-control-max-age": str(
            settings.BLOB_CACHE_CONTROL_MAX_AGE if cache_control_max_age is None
            else cache_control_max_age
        ),
        "x-add-random-suffix": "1" if suffix else "0",
    })
    url = f"{settings.BLOB_API_URL}/?pathname={quote(clean, safe='')}"
    response = _request("PUT", url, headers=headers, content=content, timeout=settings.BLOB_TIMEOUT_SECONDS)
    try:
        payload = response.json()
    except ValueError as exc:
        raise BlobStorageError(f"Réponse Vercel Blob illisible : {response.text[:300]}") from exc
    if not payload.get("url"):
        raise BlobStorageError(f"Réponse Vercel Blob sans URL : {payload}")
    return payload


def head_object(url: str) -> dict[str, Any]:
    """Renvoie les métadonnées d'un objet (taille, type, date, etag)."""
    headers = _headers()
    response = _request("GET", f"{settings.BLOB_API_URL}/?url={quote(url, safe='')}", headers=headers)
    try:
        return response.json()
    except ValueError as exc:
        raise BlobStorageError(f"Réponse Vercel Blob illisible : {response.text[:300]}") from exc


def get_object(url: str, *, access: str | None = None) -> bytes:
    """Télécharge intégralement un objet. Préférer :func:`stream_object` en lecture serveur."""
    resolved = (access or settings.BLOB_ACCESS or "public").lower()
    headers = _headers() if resolved == "private" else {}
    response = _request("GET", url, headers=headers, timeout=settings.BLOB_TIMEOUT_SECONDS)
    return response.content


def stream_object(url: str, *, access: str | None = None, chunk_size: int = 65_536) -> Iterator[bytes]:
    """Lit un objet par morceaux, sans le charger entièrement en mémoire.

    Le générateur ouvre sa propre connexion : il est consommable dans un
    ``StreamingResponse`` synchrone (Starlette le déroule dans un threadpool).
    """
    resolved = (access or settings.BLOB_ACCESS or "public").lower()
    headers = _headers() if resolved == "private" else {}
    with httpx.Client(timeout=settings.BLOB_TIMEOUT_SECONDS) as client:
        with client.stream("GET", url, headers=headers) as response:
            if response.status_code == 404:
                raise BlobNotFound(f"Objet Vercel Blob introuvable : {url}")
            if response.status_code >= 400:
                response.read()
                raise BlobStorageError(
                    f"Vercel Blob a refusé la lecture ({response.status_code}) : {response.text[:300]}"
                )
            for chunk in response.iter_bytes(chunk_size):
                if chunk:
                    yield chunk


def delete_objects(urls: list[str]) -> None:
    """Supprime un ou plusieurs objets. Les URL inconnues sont ignorées."""
    targets = [url for url in urls if url]
    if not targets:
        return
    _request(
        "POST",
        f"{settings.BLOB_API_URL}/delete",
        headers=_headers({"content-type": "application/json"}),
        json_body={"urls": targets},
    )


def list_objects(prefix: str = "", *, limit: int = 1000, cursor: str | None = None) -> dict[str, Any]:
    """Liste les objets du store, éventuellement filtrés par préfixe."""
    params = [f"limit={limit}"]
    if prefix:
        params.append(f"prefix={quote(prefix, safe='')}")
    if cursor:
        params.append(f"cursor={quote(cursor, safe='')}")
    response = _request("GET", f"{settings.BLOB_API_URL}/?{'&'.join(params)}", headers=_headers())
    try:
        return response.json()
    except ValueError as exc:
        raise BlobStorageError(f"Réponse Vercel Blob illisible : {response.text[:300]}") from exc
