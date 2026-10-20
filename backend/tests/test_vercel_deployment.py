"""Tests du déploiement serverless : Vercel Blob, façade de stockage, IP proxy, cron.

Ces tests n'appellent jamais le vrai service Vercel Blob : la couche HTTP est
remplacée par un client factice qui enregistre les requêtes. On vérifie ainsi le
*contrat* (URL, méthode, entêtes) reproduit du SDK officiel, et le comportement
de la façade dans les deux moteurs (local et blob), sans réseau ni jeton.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-vercel-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DIR}/tests.db")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("PRIVATE_UPLOAD_DIR", f"{TEST_DIR}/private")
os.environ.setdefault("UPLOAD_DIR", f"{TEST_DIR}/public")
os.environ.setdefault("BACKUP_DIR", f"{TEST_DIR}/backups")

from app.config import is_vercel_environment, settings  # noqa: E402
from app.middleware.rate_limit import client_ip  # noqa: E402
from app.services import blob_storage, file_storage  # noqa: E402

FAKE_TOKEN = "vercel_blob_rw_test_token"
FAKE_URL = "https://store_test.public.blob.vercel-storage.com/private/ged/1/fichier.pdf"


# ---------------------------------------------------------------------------
# Couche HTTP factice
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b"", text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.text = text or (str(payload) if payload else "")
        self.headers = {}

    def json(self):
        if not self._payload:
            raise ValueError("pas de JSON")
        return self._payload

    def read(self):
        return self.content

    def iter_bytes(self, chunk_size=65_536):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start:start + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeClient:
    """Remplace ``httpx.Client`` : enregistre les appels, renvoie des réponses fixes."""

    calls: list[dict] = []
    # Rempli par chaque test : {(method, kind) -> FakeResponse}
    plan: dict = {}

    def __init__(self, timeout=None):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def _record(self, method, url, headers=None, content=None, json=None):
        FakeClient.calls.append({
            "method": method, "url": url, "headers": headers or {},
            "content": content, "json": json,
        })

    def _planned(self, method, url):
        for (planned_method, needle), response in FakeClient.plan.items():
            if planned_method == method and needle in url:
                return response
        return FakeResponse(200, payload={"url": FAKE_URL, "pathname": "private/ged/1/fichier.pdf"})

    def request(self, method, url, headers=None, content=None, json=None):
        self._record(method, url, headers, content, json)
        return self._planned(method, url)

    def stream(self, method, url, headers=None):
        self._record(method, url, headers)
        return self._planned(method, url)


class BlobHttpTestCase(unittest.TestCase):
    """Base qui installe le client factice et un jeton de test."""

    def setUp(self):
        FakeClient.calls = []
        FakeClient.plan = {}
        self._client_patch = patch.object(blob_storage.httpx, "Client", FakeClient)
        self._client_patch.start()
        self._token_patch = patch.object(settings, "BLOB_READ_WRITE_TOKEN", FAKE_TOKEN)
        self._token_patch.start()
        self.addCleanup(self._client_patch.stop)
        self.addCleanup(self._token_patch.stop)

    def last_call(self):
        self.assertTrue(FakeClient.calls, "aucun appel HTTP enregistré")
        return FakeClient.calls[-1]


# ---------------------------------------------------------------------------
# Contrat REST de Vercel Blob
# ---------------------------------------------------------------------------
class BlobClientContractTest(BlobHttpTestCase):
    def test_put_object_utilise_le_contrat_du_sdk_officiel(self):
        result = blob_storage.put_object(
            "private/ged/1/fichier.pdf", b"contenu", content_type="application/pdf"
        )
        call = self.last_call()
        self.assertEqual(call["method"], "PUT")
        # Base officielle + pathname en paramètre de requête encodé.
        self.assertTrue(call["url"].startswith("https://vercel.com/api/blob/?pathname="))
        self.assertIn("private%2Fged%2F1%2Ffichier.pdf", call["url"])
        self.assertEqual(call["content"], b"contenu")
        headers = call["headers"]
        self.assertEqual(headers["authorization"], f"Bearer {FAKE_TOKEN}")
        self.assertEqual(headers["x-api-version"], "13")
        self.assertEqual(headers["x-vercel-blob-access"], "public")
        self.assertEqual(headers["x-content-type"], "application/pdf")
        self.assertEqual(headers["x-add-random-suffix"], "1")
        self.assertIn("x-cache-control-max-age", headers)
        self.assertEqual(result["url"], FAKE_URL)

    def test_put_object_refuse_le_double_slash(self):
        with self.assertRaises(blob_storage.BlobStorageError):
            blob_storage.put_object("ged//fichier.pdf", b"x")

    def test_put_object_refuse_au_dela_du_seuil_multipart(self):
        with patch.object(settings, "BLOB_MULTIPART_THRESHOLD", 10):
            with self.assertRaises(blob_storage.BlobStorageError) as ctx:
                blob_storage.put_object("gros.bin", b"0123456789ABCDEF")
        self.assertIn("multipart", str(ctx.exception))

    def test_put_object_exige_un_jeton(self):
        with patch.object(settings, "BLOB_READ_WRITE_TOKEN", ""):
            with self.assertRaises(blob_storage.BlobStorageError) as ctx:
                blob_storage.put_object("a/b.pdf", b"x")
        self.assertIn("BLOB_READ_WRITE_TOKEN", str(ctx.exception))

    def test_delete_utilise_le_point_d_entree_json(self):
        blob_storage.delete_objects([FAKE_URL])
        call = self.last_call()
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith("/delete"))
        self.assertEqual(call["json"], {"urls": [FAKE_URL]})

    def test_delete_ignoré_sans_url(self):
        blob_storage.delete_objects([])
        self.assertEqual(FakeClient.calls, [])

    def test_head_et_list_ciblent_la_base_officielle(self):
        FakeClient.plan = {("GET", "?url="): FakeResponse(200, payload={"size": 12, "contentType": "application/pdf"})}
        metadata = blob_storage.head_object(FAKE_URL)
        self.assertEqual(metadata["size"], 12)
        self.assertIn("?url=", self.last_call()["url"])

        FakeClient.plan = {("GET", "prefix="): FakeResponse(200, payload={"blobs": []})}
        blob_storage.list_objects("ged/", limit=5)
        call = self.last_call()
        self.assertIn("limit=5", call["url"])
        self.assertIn("prefix=ged%2F", call["url"])

    def test_erreur_4xx_remonte_avec_le_detail(self):
        FakeClient.plan = {("PUT", "pathname="): FakeResponse(403, text="invalid token")}
        with self.assertRaises(blob_storage.BlobStorageError) as ctx:
            blob_storage.put_object("a/b.pdf", b"x")
        self.assertIn("403", str(ctx.exception))

    def test_404_est_typé(self):
        FakeClient.plan = {("GET", "?url="): FakeResponse(404, text="not found")}
        with self.assertRaises(blob_storage.BlobNotFound):
            blob_storage.head_object(FAKE_URL)

    def test_is_blob_url_reconnait_les_deux_stores(self):
        self.assertTrue(blob_storage.is_blob_url(FAKE_URL))
        self.assertTrue(blob_storage.is_blob_url(
            "https://store_test.private.blob.vercel-storage.com/x.pdf"
        ))
        self.assertFalse(blob_storage.is_blob_url("/tmp/uploads/1/photo.jpg"))
        self.assertFalse(blob_storage.is_blob_url(None))
        self.assertFalse(blob_storage.is_blob_url("https://exemple.com/photo.jpg"))


# ---------------------------------------------------------------------------
# Façade de stockage — moteur local (comportement historique inchangé)
# ---------------------------------------------------------------------------
class FileStorageLocalTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="gestimmo-local-")
        self._backend = patch.object(settings, "STORAGE_BACKEND", "local")
        self._backend.start()
        self.addCleanup(self._backend.stop)

    def test_mirror_ne_fait_rien_en_moteur_local(self):
        path = os.path.join(self.dir, "doc.pdf")
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.4")
        self.assertFalse(file_storage.remote_enabled())
        self.assertIsNone(file_storage.mirror(path))
        self.assertEqual(file_storage.reference_for(path, None), path)

    def test_read_exists_delete_en_local(self):
        path = os.path.join(self.dir, "doc.txt")
        with open(path, "wb") as handle:
            handle.write(b"bonjour")
        self.assertTrue(file_storage.exists(path))
        self.assertEqual(file_storage.read_bytes(path), b"bonjour")
        self.assertEqual(b"".join(file_storage.stream(path)), b"bonjour")
        file_storage.delete(path)
        self.assertFalse(file_storage.exists(path))

    def test_read_bytes_lève_sur_fichier_absent(self):
        with self.assertRaises(FileNotFoundError):
            file_storage.read_bytes(os.path.join(self.dir, "absent.txt"))

    def test_response_renvoie_un_fileresponse_local(self):
        path = os.path.join(self.dir, "doc.txt")
        with open(path, "wb") as handle:
            handle.write(b"bonjour")
        response = file_storage.response(path, media_type="text/plain", filename="doc.txt")
        self.assertEqual(type(response).__name__, "FileResponse")

    def test_object_key_conserve_l_arborescence(self):
        with patch.object(settings, "PRIVATE_UPLOAD_DIR", "private_uploads"):
            key = file_storage.object_key(
                os.path.join(str(settings.private_upload_dir_path), "ged", "12", "f.pdf")
            )
        self.assertEqual(key, "private/ged/12/f.pdf")

    def test_object_key_classe_les_sauvegardes(self):
        key = file_storage.object_key(
            os.path.join(str(settings.backup_dir_path), "gestimmo-daily-2026.dump")
        )
        self.assertTrue(key.startswith("backups/"))

    def test_materialize_renvoie_le_chemin_local_sans_copie(self):
        path = os.path.join(self.dir, "doc.txt")
        with open(path, "wb") as handle:
            handle.write(b"x")
        self.assertEqual(file_storage.materialize(path).name, "doc.txt")

    def test_describe_backend_signale_le_disque(self):
        state = file_storage.describe_backend()
        self.assertEqual(state["backend"], "local")
        self.assertIn("detail", state)

    def test_durabilité_déclarée_selon_la_racine_de_stockage(self):
        # Les racines sont lues depuis `settings`, construit une fois par
        # processus : on les fixe explicitement pour ne pas dépendre du module de
        # test importé en premier.
        persistant = {
            "UPLOAD_DIR": "/var/data/gestimmo/public",
            "PRIVATE_UPLOAD_DIR": "/var/data/gestimmo/private",
            "BACKUP_DIR": "/var/data/gestimmo/backups",
        }
        ephemere = {
            "UPLOAD_DIR": "/tmp/uploads",
            "PRIVATE_UPLOAD_DIR": "/tmp/private_uploads",
            "BACKUP_DIR": "/tmp/backups",
        }
        with patch.multiple(settings, **persistant):
            state = file_storage.describe_backend()
        self.assertTrue(state["durable"], state)

        with patch.multiple(settings, **ephemere):
            state = file_storage.describe_backend()
        # /tmp est la seule zone inscriptible sur Vercel, et elle est effacée à
        # la mise à l'échelle à zéro : le diagnostic doit le signaler.
        self.assertFalse(state["durable"], state)


# ---------------------------------------------------------------------------
# Façade de stockage — moteur Vercel Blob
# ---------------------------------------------------------------------------
class FileStorageBlobTest(BlobHttpTestCase):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp(prefix="gestimmo-blob-")
        patches = [
            patch.object(settings, "STORAGE_BACKEND", "blob"),
            patch.object(settings, "BLOB_ACCESS", "public"),
            patch.object(settings, "PRIVATE_UPLOAD_DIR", f"{self.dir}/private"),
            patch.object(settings, "UPLOAD_DIR", f"{self.dir}/public"),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.assertTrue(file_storage.remote_enabled())

    def _local_file(self, name="doc.pdf", content=b"%PDF-1.4"):
        directory = os.path.join(self.dir, "private", "ged", "12")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def test_mirror_replique_et_renvoie_l_url(self):
        path = self._local_file()
        url = file_storage.mirror(path, content_type="application/pdf")
        self.assertEqual(url, FAKE_URL)
        call = FakeClient.calls[-1]
        # La clé conserve le classement par module et par entité.
        self.assertIn("private%2Fged%2F12%2Fdoc.pdf", call["url"])
        # Le fichier local subsiste : l'OCR et les empreintes le relisent.
        self.assertTrue(os.path.isfile(path))

    def test_reference_for_privilégie_l_url(self):
        path = self._local_file()
        self.assertEqual(file_storage.reference_for(path, FAKE_URL), FAKE_URL)
        self.assertEqual(file_storage.reference_for(path, None), path)

    def test_échec_du_miroir_ne_casse_pas_l_appel_metier(self):
        path = self._local_file()
        FakeClient.plan = {("PUT", "pathname="): FakeResponse(500, text="boom")}
        with patch.object(settings, "BLOB_FAIL_OPEN", True):
            self.assertIsNone(file_storage.mirror(path))
        with patch.object(settings, "BLOB_FAIL_OPEN", False):
            with self.assertRaises(blob_storage.BlobStorageError):
                file_storage.mirror(path)

    def test_read_bytes_interroge_le_store(self):
        FakeClient.plan = {("GET", FAKE_URL): FakeResponse(200, content=b"contenu distant")}
        self.assertEqual(file_storage.read_bytes(FAKE_URL), b"contenu distant")

    def test_exists_valide_par_les_metadonnees(self):
        FakeClient.plan = {("GET", "?url="): FakeResponse(200, payload={"size": 8})}
        self.assertTrue(file_storage.exists(FAKE_URL))
        FakeClient.plan = {("GET", "?url="): FakeResponse(404, text="absent")}
        self.assertFalse(file_storage.exists(FAKE_URL))

    def test_response_redirige_vers_le_cdn_pour_une_lecture_en_ligne(self):
        FakeClient.plan = {("GET", "?url="): FakeResponse(200, payload={"contentType": "image/jpeg"})}
        response = file_storage.response(FAKE_URL, inline=True)
        self.assertEqual(type(response).__name__, "RedirectResponse")
        self.assertEqual(response.status_code, 302)

    def test_response_relaie_une_piece_jointe_nominee(self):
        # Store public mais téléchargement nommé : le relais par l'API est le seul
        # moyen de poser Content-Disposition avec le nom d'origine.
        FakeClient.plan = {
            ("GET", "?url="): FakeResponse(200, payload={"contentType": "application/pdf"}),
            ("GET", FAKE_URL): FakeResponse(200, content=b"%PDF-1.4 distant"),
        }
        response = file_storage.response(FAKE_URL, filename="bail-2026.pdf")
        self.assertEqual(type(response).__name__, "StreamingResponse")
        self.assertIn('filename="bail-2026.pdf"', response.headers["Content-Disposition"])

    def test_response_relaie_depuis_un_store_prive(self):
        FakeClient.plan = {
            ("GET", "?url="): FakeResponse(200, payload={"contentType": "application/pdf"}),
            ("GET", FAKE_URL): FakeResponse(200, content=b"%PDF-1.4"),
        }
        with patch.object(settings, "BLOB_ACCESS", "private"):
            response = file_storage.response(FAKE_URL, inline=True)
            # Un store privé n'est jamais exposé en redirection : l'API relaie le
            # contenu après authentification. Le corps d'un StreamingResponse est
            # paresseux, on le consomme pour déclencher l'appel.
            self.assertEqual(type(response).__name__, "StreamingResponse")
            relayed = b"".join(blob_storage.stream_object(FAKE_URL))

        self.assertEqual(relayed, b"%PDF-1.4")
        stream_calls = [call for call in FakeClient.calls if call["url"] == FAKE_URL]
        self.assertTrue(stream_calls)
        self.assertEqual(
            stream_calls[-1]["headers"]["authorization"], f"Bearer {FAKE_TOKEN}"
        )

    def test_response_accentue_le_nom_de_fichier_en_utf8(self):
        FakeClient.plan = {
            ("GET", "?url="): FakeResponse(200, payload={"contentType": "application/pdf"}),
            ("GET", FAKE_URL): FakeResponse(200, content=b"x"),
        }
        response = file_storage.response(FAKE_URL, filename="état des lieux.pdf")
        disposition = response.headers["Content-Disposition"]
        self.assertIn("filename*=", disposition)
        self.assertIn("UTF-8''", disposition)

    def test_objet_distant_absent_produit_une_erreur_404_propre(self):
        FakeClient.plan = {("GET", "?url="): FakeResponse(404, text="absent")}
        with self.assertRaises(FileNotFoundError):
            file_storage.response(FAKE_URL, filename="doc.pdf")

    def test_delete_supprime_l_objet_distant(self):
        file_storage.delete(FAKE_URL)
        self.assertTrue(FakeClient.calls[-1]["url"].endswith("/delete"))

    def test_materialize_rapatrie_un_objet_distant(self):
        FakeClient.plan = {("GET", FAKE_URL): FakeResponse(200, content=b"%PDF-1.4")}
        local = file_storage.materialize(FAKE_URL)
        try:
            self.assertTrue(local.is_file())
            self.assertEqual(local.read_bytes(), b"%PDF-1.4")
            self.assertEqual(local.suffix, ".pdf")
        finally:
            file_storage.discard_temporary(local)
        self.assertFalse(local.exists())

    def test_describe_backend_signale_le_store(self):
        state = file_storage.describe_backend()
        self.assertEqual(state["backend"], "blob")
        self.assertTrue(state["durable"])
        self.assertEqual(state["access"], "public")


# ---------------------------------------------------------------------------
# IP cliente derrière le proxy de la plateforme
# ---------------------------------------------------------------------------
class _FakeRequest:
    def __init__(self, headers=None, host="10.0.0.1"):
        self.headers = headers or {}
        self.client = type("Client", (), {"host": host})()


class ProxyClientIpTest(unittest.TestCase):
    def test_xff_prioritaire_quand_le_proxy_est_de_confiance(self):
        request = _FakeRequest({"x-forwarded-for": "41.204.87.12, 10.0.0.1"}, host="10.0.0.1")
        with patch.object(settings, "TRUST_PROXY_HEADERS", True):
            self.assertEqual(client_ip(request), "41.204.87.12")

    def test_deux_visiteurs_ne_partagent_plus_le_meme_seau(self):
        with patch.object(settings, "TRUST_PROXY_HEADERS", True):
            premier = client_ip(_FakeRequest({"x-forwarded-for": "1.2.3.4"}, host="10.0.0.1"))
            second = client_ip(_FakeRequest({"x-forwarded-for": "5.6.7.8"}, host="10.0.0.1"))
        self.assertNotEqual(premier, second)

    def test_sans_proxy_de_confiance_l_en_tete_est_ignoré(self):
        # En exposition directe, un client pourrait forger l'en-tête pour
        # contourner la limitation : il n'est alors pas cru.
        request = _FakeRequest({"x-forwarded-for": "8.8.8.8"}, host="192.168.1.5")
        with patch.object(settings, "TRUST_PROXY_HEADERS", False):
            self.assertEqual(client_ip(request), "192.168.1.5")

    def test_repli_sur_x_real_ip_puis_sur_le_client(self):
        with patch.object(settings, "TRUST_PROXY_HEADERS", True):
            self.assertEqual(client_ip(_FakeRequest({"x-real-ip": "9.9.9.9"})), "9.9.9.9")
            self.assertEqual(client_ip(_FakeRequest()), "10.0.0.1")


# ---------------------------------------------------------------------------
# Détection de la plateforme et limites qui en découlent
# ---------------------------------------------------------------------------
class VercelEnvironmentTest(unittest.TestCase):
    def test_detection_de_vercel(self):
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=False):
            self.assertTrue(is_vercel_environment())
        with patch.dict(os.environ, {"VERCEL_ENV": "production"}, clear=False):
            self.assertTrue(is_vercel_environment())

    def test_limite_d_upload_alignee_sur_vercel(self):
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=False):
            with patch.object(settings, "MAX_UPLOAD_SIZE", 5_242_880):
                # Vercel refuse tout corps de requête au-delà de 4,5 Mo.
                self.assertEqual(settings.effective_upload_limit, 4_500_000)
        for marker in ("VERCEL", "VERCEL_ENV", "VERCEL_DEPLOYMENT_ID", "VERCEL_URL"):
            os.environ.pop(marker, None)
        with patch.object(settings, "MAX_UPLOAD_SIZE", 5_242_880):
            self.assertEqual(settings.effective_upload_limit, 5_242_880)

    def test_blob_inactif_sans_jeton_meme_si_demande(self):
        with patch.object(settings, "STORAGE_BACKEND", "blob"):
            with patch.object(settings, "BLOB_READ_WRITE_TOKEN", ""):
                self.assertFalse(settings.blob_enabled)
                state = file_storage.describe_backend()
                self.assertEqual(state["backend"], "local")
                self.assertIn("BLOB_READ_WRITE_TOKEN", state["detail"])


# ---------------------------------------------------------------------------
# Route de tâche périodique
# ---------------------------------------------------------------------------
class CronRouteTest(unittest.TestCase):
    """Vercel appelle GET /api/cron/daily avec Authorization: Bearer $CRON_SECRET."""

    def setUp(self):
        from fastapi.testclient import TestClient

        from app.database import Base, engine
        from app.main import app

        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        from app.services.admin_security_service import bootstrap_security

        bootstrap_security()
        self.context = TestClient(app)
        self.client = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)

    def test_sans_secret_la_route_est_fermee(self):
        with patch.object(settings, "CRON_SECRET", ""):
            response = self.client.get("/api/cron/daily")
        self.assertEqual(response.status_code, 503)
        self.assertIn("CRON_SECRET", response.json()["detail"])

    def test_jeton_invalide_refuse(self):
        with patch.object(settings, "CRON_SECRET", "secret-attendu"):
            response = self.client.get(
                "/api/cron/daily", headers={"Authorization": "Bearer mauvais"}
            )
        self.assertEqual(response.status_code, 401)

    def test_appel_anonyme_refuse(self):
        with patch.object(settings, "CRON_SECRET", "secret-attendu"):
            self.assertEqual(self.client.get("/api/cron/daily").status_code, 401)

    def test_jeton_valide_execute_les_taches(self):
        with patch.object(settings, "CRON_SECRET", "secret-attendu"):
            response = self.client.get(
                "/api/cron/daily", headers={"Authorization": "Bearer secret-attendu"}
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "ok", body)
        self.assertEqual(
            set(body["tasks"]),
            {"daily_backup", "report_schedules", "rent_revisions", "automatic_renewals"},
        )
        for name, outcome in body["tasks"].items():
            self.assertTrue(outcome["ok"], f"{name} : {outcome}")

    def test_une_tache_en_echec_n_arrete_pas_les_autres(self):
        from app.routes import cron as cron_module

        def boom(_db):
            raise RuntimeError("panne simulée")

        tasks = tuple(
            ("cassée", boom) if name == "daily_backup" else (name, fn)
            for name, fn in cron_module.DAILY_TASKS
        )
        with patch.object(settings, "CRON_SECRET", "secret-attendu"):
            with patch.object(cron_module, "DAILY_TASKS", tasks):
                response = self.client.get(
                    "/api/cron/daily", headers={"Authorization": "Bearer secret-attendu"}
                )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "partial")
        self.assertEqual(body["failed"], ["cassée"])
        self.assertFalse(body["tasks"]["cassée"]["ok"])
        self.assertIn("panne simulée", body["tasks"]["cassée"]["error"])
        self.assertTrue(body["tasks"]["report_schedules"]["ok"])

    def test_statut_sans_effet_de_bord(self):
        with patch.object(settings, "CRON_SECRET", "secret-attendu"):
            response = self.client.get(
                "/api/cron/status", headers={"Authorization": "Bearer secret-attendu"}
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["secret_configured"])
        self.assertIn("daily_backup", body["tasks"])


if __name__ == "__main__":
    unittest.main()
