"""Extraction OCR et contrôles automatiques des justificatifs.

Les PDF texte sont lus avec pypdf. Les PDF scannés sont rendus avec PyMuPDF,
puis reconnus comme les images avec Tesseract. Une extraction impossible ne
valide jamais un document : il est envoyé en contrôle manuel.
"""

import io
import re
import unicodedata
from pathlib import Path
from typing import Dict, Optional

from app.models.tenant import DocumentType, VerificationStatus


KEYWORDS = {
    DocumentType.IDENTITY: ("republique francaise", "carte nationale", "passeport", "identity card"),
    DocumentType.PAY_SLIP: ("bulletin de paie", "bulletin de salaire", "net a payer", "payslip"),
    DocumentType.TAX_NOTICE: ("avis d'impot", "avis d'imposition", "revenu fiscal", "impot sur les revenus"),
    DocumentType.PROOF_OF_ADDRESS: ("facture", "electricite", "gaz", "echeance", "domicile", "abonnement"),
    DocumentType.EMPLOYMENT_CONTRACT: ("contrat de travail", "contrat a duree", "employeur", "salarie"),
    DocumentType.EMPLOYER_CERTIFICATE: ("attestation employeur", "attestation de l'employeur", "certifie employer"),
    DocumentType.GUARANTEE_DEED: ("acte de cautionnement", "caution solidaire", "caution simple"),
    DocumentType.VISALE_CERTIFICATE: ("visale", "visa certifie"),
    DocumentType.GLI_CERTIFICATE: ("garantie loyers impayes", "gli"),
    DocumentType.LEASE: ("contrat de location", "bail", "locataire", "bailleur"),
    DocumentType.OTHER: (),
}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:10])
    except Exception:
        return ""


def _tesseract_image(image) -> tuple[str, float]:
    import pytesseract

    data = pytesseract.image_to_data(image, lang="fra+eng", output_type=pytesseract.Output.DICT)
    words = []
    confidences = []
    for word, confidence in zip(data.get("text", []), data.get("conf", [])):
        if word and word.strip():
            words.append(word.strip())
            try:
                value = float(confidence)
                if value >= 0:
                    confidences.append(value)
            except (TypeError, ValueError):
                pass
    return " ".join(words), (sum(confidences) / len(confidences) if confidences else 0)


def _extract_image(path: Path) -> tuple[str, float]:
    try:
        from PIL import Image

        return _tesseract_image(Image.open(path))
    except Exception:
        return "", 0


def _extract_scanned_pdf(path: Path) -> tuple[str, float]:
    """OCR des cinq premières pages d'un PDF image pour borner le coût CPU."""
    try:
        import fitz
        from PIL import Image

        texts = []
        confidences = []
        document = fitz.open(str(path))
        try:
            for page_index in range(min(5, document.page_count)):
                page = document.load_page(page_index)
                # 150 dpi offre un bon compromis pour les justificatifs usuels.
                pixmap = page.get_pixmap(dpi=150, alpha=False)
                image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                text, confidence = _tesseract_image(image)
                if text:
                    texts.append(text)
                    confidences.append(confidence)
        finally:
            document.close()
        return "\n".join(texts), (sum(confidences) / len(confidences) if confidences else 0)
    except Exception:
        return "", 0


def analyse_document(
    path: str,
    document_type: DocumentType,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> Dict:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    confidence = 0.0

    if suffix == ".pdf":
        text = _extract_pdf(file_path)
        engine = "pypdf"
        # Un PDF peut être un simple conteneur d'images. Dans ce cas on le rend
        # et on déclenche la véritable reconnaissance optique.
        if len(text.strip()) >= 20:
            confidence = 95.0
        else:
            text, confidence = _extract_scanned_pdf(file_path)
            engine = "tesseract_pdf"
    else:
        text, confidence = _extract_image(file_path)
        engine = "tesseract"

    normalized = _normalize(text)
    expected_keywords = KEYWORDS.get(document_type, ())
    keyword_match = not expected_keywords or any(keyword in normalized for keyword in expected_keywords)
    identity_terms = [_normalize(value) for value in (first_name, last_name) if value]
    identity_match = not identity_terms or all(term in normalized for term in identity_terms)
    sufficient_text = len(normalized) >= 20

    checks = {
        "text_extracted": sufficient_text,
        "document_type_consistent": keyword_match if sufficient_text else False,
        "candidate_identity_found": identity_match if sufficient_text else False,
        "matched_keywords": [keyword for keyword in expected_keywords if keyword in normalized],
    }

    if not sufficient_text:
        status = VerificationStatus.MANUAL_REVIEW
        reason = "Aucun texte exploitable extrait automatiquement"
    elif keyword_match and identity_match:
        status = VerificationStatus.VERIFIED
        reason = None
    else:
        status = VerificationStatus.MANUAL_REVIEW
        reason = "Le type du document ou l'identité doit être contrôlé manuellement"

    return {
        "text": text[:100_000],
        "confidence": round(float(confidence), 2),
        "checks": checks,
        "status": status,
        "reason": reason,
        "engine": engine,
    }
