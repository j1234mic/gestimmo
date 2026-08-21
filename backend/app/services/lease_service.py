"""Règles métier et génération documentaire des baux."""

import base64
import binascii
import calendar
import hashlib
import html
import io
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from string import Template
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image as PDFImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.lease_contract import (
    ArchiveStatus,
    ContractDocument,
    ContractDocumentType,
    ContractEvent,
    InspectionDeduction,
    InspectionType,
    ItemCondition,
    LeaseAmendment,
    LeaseClause,
    LeaseClauseAssignment,
    LeaseContractSettings,
    LeaseContractType,
    LeaseNotice,
    LeaseRenewal,
    LeaseTemplate,
    NoticeGivenBy,
    NoticeReason,
    PropertyInspection,
    RenewalMode,
    RenewalStatus,
    RentCapRule,
    RentIndexType,
    RentIndexValue,
    RentRevision,
    RevisionStatus,
    SignatureEnvelope,
    SignatureEnvelopeStatus,
    SignatureParty,
    SignaturePartyStatus,
)
from app.models.property import Property, PropertyStatus
from app.models.tenant import Lease, LeaseStatus, Tenant, TenantNotification
from app.schemas.lease_contract import LeaseContractCreate, NoticeCreate, RentRevisionCreate


DEFAULT_DURATIONS = {
    LeaseContractType.RESIDENTIAL_UNFURNISHED: 36,
    LeaseContractType.RESIDENTIAL_FURNISHED: 12,
    LeaseContractType.COMMERCIAL_369: 108,
    LeaseContractType.PROFESSIONAL: 72,
    LeaseContractType.SHORT_TERM_DEROGATORY: 36,
    LeaseContractType.SEASONAL: 3,
    LeaseContractType.PRECARIOUS_OCCUPANCY: 12,
    LeaseContractType.MIXED_USE: 36,
}

# Valeurs de base usuelles. Le gestionnaire peut toujours fournir une durée
# différente avec sa référence juridique lorsque la situation l'exige.
DEFAULT_NOTICE_MONTHS = {
    (LeaseContractType.RESIDENTIAL_UNFURNISHED, NoticeGivenBy.TENANT): 3,
    (LeaseContractType.RESIDENTIAL_UNFURNISHED, NoticeGivenBy.OWNER): 6,
    (LeaseContractType.RESIDENTIAL_FURNISHED, NoticeGivenBy.TENANT): 1,
    (LeaseContractType.RESIDENTIAL_FURNISHED, NoticeGivenBy.OWNER): 3,
    (LeaseContractType.MIXED_USE, NoticeGivenBy.TENANT): 3,
    (LeaseContractType.MIXED_USE, NoticeGivenBy.OWNER): 6,
    (LeaseContractType.COMMERCIAL_369, NoticeGivenBy.TENANT): 6,
    (LeaseContractType.COMMERCIAL_369, NoticeGivenBy.OWNER): 6,
    (LeaseContractType.PROFESSIONAL, NoticeGivenBy.TENANT): 6,
    (LeaseContractType.PROFESSIONAL, NoticeGivenBy.OWNER): 6,
}

CONDITION_RANK = {
    ItemCondition.NEW: 0,
    ItemCondition.GOOD: 1,
    ItemCondition.FAIR: 2,
    ItemCondition.POOR: 3,
    ItemCondition.DAMAGED: 4,
    ItemCondition.MISSING: 5,
    ItemCondition.NOT_APPLICABLE: 0,
}


def generate_reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def datetime_is_past(value: datetime) -> bool:
    now = datetime.now(timezone.utc)
    if value.tzinfo is None:
        now = now.replace(tzinfo=None)
    return value <= now


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def log_event(db: Session, lease_id: int, event_type: str, title: str, actor: str, description=None, details=None):
    event = ContractEvent(
        lease_id=lease_id,
        event_type=event_type,
        title=title,
        description=description,
        details=details or {},
        actor=actor,
    )
    db.add(event)
    return event


def notify_tenant(db: Session, tenant_id: int, notification_type: str, title: str, content: str):
    notification = TenantNotification(
        tenant_id=tenant_id,
        channel="in_app",
        notification_type=notification_type,
        title=title,
        content=content,
        delivery_status="delivered",
    )
    db.add(notification)
    return notification


def _settings_or_404(db: Session, lease_id: int) -> LeaseContractSettings:
    settings_row = db.query(LeaseContractSettings).filter(LeaseContractSettings.lease_id == lease_id).first()
    if not settings_row:
        raise ValueError("Paramètres contractuels du bail non trouvés")
    return settings_row


def create_contract_lease(db: Session, data: LeaseContractCreate, actor: str) -> Lease:
    tenant = db.query(Tenant).filter(Tenant.id == data.tenant_id, Tenant.is_active.is_(True)).first()
    if not tenant:
        raise ValueError("Locataire non trouvé")
    property_obj = db.query(Property).filter(Property.id == data.property_id, Property.is_active.is_(True)).first()
    if not property_obj:
        raise ValueError("Bien non trouvé")
    template = None
    if data.template_id:
        template = db.query(LeaseTemplate).filter(
            LeaseTemplate.id == data.template_id,
            LeaseTemplate.lease_type == data.lease_type,
            LeaseTemplate.is_active.is_(True),
        ).first()
        if not template:
            raise ValueError("Modèle incompatible ou inactif")
    else:
        template = db.query(LeaseTemplate).filter(
            LeaseTemplate.lease_type == data.lease_type,
            LeaseTemplate.is_default.is_(True),
            LeaseTemplate.is_active.is_(True),
        ).order_by(LeaseTemplate.version.desc()).first()

    if data.end_date and data.duration_months is None:
        duration = max(1, (data.end_date.year - data.start_date.year) * 12 + data.end_date.month - data.start_date.month)
        if add_months(data.start_date, duration) - timedelta(days=1) < data.end_date:
            duration += 1
    else:
        duration = data.duration_months or DEFAULT_DURATIONS[data.lease_type]
    end_date = data.end_date or (add_months(data.start_date, duration) - timedelta(days=1))
    if data.lease_type == LeaseContractType.SHORT_TERM_DEROGATORY and end_date >= add_months(data.start_date, 36):
        raise ValueError("Un bail dérogatoire ne peut pas dépasser 36 mois")
    lease = Lease(
        reference=generate_reference("LEA"),
        tenant_id=tenant.id,
        property_id=property_obj.id,
        status=data.status,
        start_date=data.start_date,
        end_date=end_date,
        monthly_rent=data.rent_excluding_charges,
        monthly_charges=data.charges,
        deposit=data.deposit,
        payment_day=data.payment_day,
        lease_type=data.lease_type.value,
        signed_at=data.signed_at,
        notes=data.notes,
    )
    db.add(lease)
    db.flush()
    if data.status == LeaseStatus.ACTIVE:
        property_obj.status = PropertyStatus.RENTED
    contract_settings = LeaseContractSettings(
        lease_id=lease.id,
        lease_type=data.lease_type,
        template_id=template.id if template else None,
        duration_months=duration,
        tacit_renewal=data.tacit_renewal,
        renewal_notice_months=data.renewal_notice_months,
        charge_method=data.charge_method,
        rent_frequency=data.rent_frequency,
        payment_method=data.payment_method,
        rent_index_type=data.rent_index_type,
        base_index_value=data.base_index_value,
        base_index_date=data.base_index_date,
        next_revision_date=data.next_revision_date,
        resolutory_clause=data.resolutory_clause,
        resolutory_clause_text=data.resolutory_clause_text,
        special_conditions=data.special_conditions,
        custom_variables=data.custom_variables,
    )
    db.add(contract_settings)
    db.flush()

    assigned_clause_ids = set()
    if template:
        for link in sorted(template.clauses, key=lambda item: item.display_order):
            clause = link.clause
            db.add(LeaseClauseAssignment(
                settings_id=contract_settings.id,
                clause_id=clause.id,
                title=clause.title,
                content=clause.content_template,
                display_order=link.display_order,
                is_required=link.is_required or clause.is_mandatory,
                source="template",
            ))
            assigned_clause_ids.add(clause.id)
    if data.clause_ids:
        clauses = db.query(LeaseClause).filter(LeaseClause.id.in_(data.clause_ids), LeaseClause.is_active.is_(True)).all()
        if len(clauses) != len(set(data.clause_ids)):
            raise ValueError("Une ou plusieurs clauses sont invalides")
        for clause in clauses:
            if clause.id in assigned_clause_ids:
                continue
            compatible = clause.compatible_lease_types or []
            if compatible and data.lease_type.value not in compatible:
                raise ValueError(f"Clause {clause.code} incompatible avec le type de bail")
            db.add(LeaseClauseAssignment(
                settings_id=contract_settings.id,
                clause_id=clause.id,
                title=clause.title,
                content=clause.content_template,
                display_order=100 + len(assigned_clause_ids),
                is_required=clause.is_mandatory,
                source="library",
            ))
            assigned_clause_ids.add(clause.id)
    for clause in data.custom_clauses:
        db.add(LeaseClauseAssignment(settings_id=contract_settings.id, source="custom", **clause.model_dump()))

    log_event(
        db,
        lease.id,
        "lease_created",
        "Bail créé",
        actor,
        details={"lease_type": data.lease_type.value, "tenant_id": tenant.id, "property_id": property_obj.id},
    )
    db.commit()
    db.refresh(lease)
    return lease


def template_context(lease: Lease, contract_settings: LeaseContractSettings) -> dict:
    prop = lease.property
    tenant = lease.tenant
    owners = prop.owners if prop else []
    owner_names = ", ".join(
        owner.company_name or f"{owner.first_name or ''} {owner.last_name or ''}".strip() for owner in owners
    ) or "Bailleur"
    context = {
        "lease_reference": lease.reference,
        "lease_type": contract_settings.lease_type.value,
        "tenant_name": f"{tenant.first_name} {tenant.last_name}",
        "tenant_address": tenant.address or "",
        "owner_names": owner_names,
        "property_address": f"{prop.address}, {prop.postal_code} {prop.city}",
        "start_date": lease.start_date.strftime("%d/%m/%Y"),
        "end_date": lease.end_date.strftime("%d/%m/%Y") if lease.end_date else "indéterminée",
        "rent": f"{lease.monthly_rent:.2f}",
        "charges": f"{lease.monthly_charges:.2f}",
        "deposit": f"{lease.deposit:.2f}",
        "payment_day": str(lease.payment_day),
        "index_type": contract_settings.rent_index_type.value.upper(),
    }
    context.update({str(key): str(value) for key, value in (contract_settings.custom_variables or {}).items()})
    return context


def _safe_substitute(value: Optional[str], context: dict) -> str:
    return Template(value or "").safe_substitute(context)


def _pdf_buffer(title: str):
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.7 * cm,
        bottomMargin=1.7 * cm,
        title=title,
    )
    return output, document, getSampleStyleSheet()


def generate_lease_pdf_bytes(lease: Lease, contract_settings: LeaseContractSettings) -> bytes:
    context = template_context(lease, contract_settings)
    template = contract_settings.template
    title = _safe_substitute(template.title_template if template else "Contrat de location — ${property_address}", context)
    output, document, styles = _pdf_buffer(title)
    story = [Paragraph(html.escape(title), styles["Title"]), Spacer(1, 0.5 * cm)]
    if template and template.introduction_template:
        story.extend([Paragraph(html.escape(_safe_substitute(template.introduction_template, context)), styles["BodyText"]), Spacer(1, 0.5 * cm)])
    story.extend([
        Paragraph("Parties", styles["Heading2"]),
        Paragraph(f"Bailleur : {html.escape(context['owner_names'])}", styles["BodyText"]),
        Paragraph(f"Locataire : {html.escape(context['tenant_name'])}", styles["BodyText"]),
        Spacer(1, 0.3 * cm),
        Paragraph("Bien loué", styles["Heading2"]),
        Paragraph(html.escape(context["property_address"]), styles["BodyText"]),
        Spacer(1, 0.3 * cm),
        Paragraph("Conditions principales", styles["Heading2"]),
    ])
    details = [
        ["Référence", lease.reference],
        ["Type", contract_settings.lease_type.value],
        ["Durée", f"{contract_settings.duration_months} mois"],
        ["Dates", f"{context['start_date']} au {context['end_date']}"],
        ["Loyer hors charges", f"{context['rent']} €"],
        ["Charges", f"{context['charges']} € ({contract_settings.charge_method.value})"],
        ["Dépôt de garantie", f"{context['deposit']} €"],
        ["Paiement", f"{contract_settings.rent_frequency.value}, échéance le {lease.payment_day}"],
        ["Indice", contract_settings.rent_index_type.value.upper()],
        ["Tacite reconduction", "Oui" if contract_settings.tacit_renewal else "Non"],
    ]
    table = Table(details, colWidths=[5.2 * cm, 10.2 * cm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E8F0F4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
    ]))
    story.extend([table, Spacer(1, 0.5 * cm)])
    if contract_settings.resolutory_clause:
        text = contract_settings.resolutory_clause_text or "Le présent bail comporte une clause résolutoire dans les limites prévues par les textes applicables."
        story.extend([Paragraph("Clause résolutoire", styles["Heading2"]), Paragraph(html.escape(text), styles["BodyText"])])
    for index, clause in enumerate(sorted(contract_settings.clause_assignments, key=lambda item: item.display_order), start=1):
        story.extend([
            Spacer(1, 0.25 * cm),
            Paragraph(f"Article {index} — {html.escape(clause.title)}", styles["Heading3"]),
            Paragraph(html.escape(_safe_substitute(clause.content, context)), styles["BodyText"]),
        ])
    if contract_settings.special_conditions:
        story.extend([Paragraph("Conditions particulières", styles["Heading2"]), Paragraph(html.escape(contract_settings.special_conditions), styles["BodyText"])])
    if template and template.footer_template:
        story.extend([Spacer(1, 0.5 * cm), Paragraph(html.escape(_safe_substitute(template.footer_template, context)), styles["Italic"])])
    story.extend([
        Spacer(1, 1 * cm),
        Paragraph("Signatures des parties", styles["Heading2"]),
        Paragraph("Le bailleur : ____________________        Le locataire : ____________________", styles["BodyText"]),
    ])
    document.build(story)
    return output.getvalue()


def store_contract_document(
    db: Session,
    lease_id: int,
    document_type: ContractDocumentType,
    title: str,
    content: bytes,
    actor: str,
    *,
    original_filename: Optional[str] = None,
    is_required: bool = False,
) -> ContractDocument:
    directory = Path(settings.private_upload_dir_path) / "contracts" / str(lease_id)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.pdf"
    path = directory / filename
    path.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    version = db.query(ContractDocument).filter(
        ContractDocument.lease_id == lease_id,
        ContractDocument.document_type == document_type,
    ).count() + 1
    document = ContractDocument(
        reference=generate_reference("DOC"),
        lease_id=lease_id,
        document_type=document_type,
        title=title,
        original_filename=original_filename or filename,
        storage_path=str(path),
        mime_type="application/pdf",
        file_size=len(content),
        checksum_sha256=checksum,
        version=version,
        is_required=is_required,
        uploaded_by=actor,
    )
    db.add(document)
    db.flush()
    return document


def generate_and_store_lease(db: Session, lease: Lease, actor: str) -> ContractDocument:
    contract_settings = _settings_or_404(db, lease.id)
    content = generate_lease_pdf_bytes(lease, contract_settings)
    document = store_contract_document(
        db,
        lease.id,
        ContractDocumentType.LEASE,
        f"Bail {lease.reference} — version {contract_settings.contract_version}",
        content,
        actor,
        is_required=True,
    )
    contract_settings.pdf_document_id = document.id
    lease.document_storage_path = document.storage_path
    lease.document_url = f"/api/leases/{lease.id}/documents/{document.id}/download"
    log_event(db, lease.id, "lease_pdf_generated", "PDF du bail généré", actor, details={"document_id": document.id, "checksum": document.checksum_sha256})
    db.commit()
    db.refresh(document)
    return document


def mandatory_annexes(lease: Lease, contract_settings: LeaseContractSettings) -> list[ContractDocumentType]:
    lease_type = contract_settings.lease_type
    required = {ContractDocumentType.DPE, ContractDocumentType.ERNMT}
    if lease_type in {
        LeaseContractType.RESIDENTIAL_UNFURNISHED,
        LeaseContractType.RESIDENTIAL_FURNISHED,
        LeaseContractType.MIXED_USE,
    }:
        required.add(ContractDocumentType.INFORMATION_NOTICE)
    year = lease.property.construction_year
    if year and year < 1949:
        required.add(ContractDocumentType.LEAD_DIAGNOSIS)
    if year and year < 1997:
        required.add(ContractDocumentType.ASBESTOS_DIAGNOSIS)
    if (lease.property.equipment or {}).get("condominium"):
        required.add(ContractDocumentType.CONDO_RULES_EXTRACT)
    return sorted(required, key=lambda item: item.value)


def annex_completeness(db: Session, lease: Lease) -> dict:
    contract_settings = _settings_or_404(db, lease.id)
    required = mandatory_annexes(lease, contract_settings)
    active_types = {
        item.document_type for item in db.query(ContractDocument).filter(
            ContractDocument.lease_id == lease.id,
            ContractDocument.archive_status != ArchiveStatus.DESTROYED,
        ).all()
    }
    missing = [item.value for item in required if item not in active_types]
    return {
        "complete": not missing,
        "required": [item.value for item in required],
        "present": sorted(item.value for item in active_types),
        "missing": missing,
    }


def calculate_rent_revision(db: Session, lease: Lease, data: RentRevisionCreate, actor: str) -> RentRevision:
    contract_settings = _settings_or_404(db, lease.id)
    if contract_settings.rent_index_type == RentIndexType.NONE:
        raise ValueError("Aucun indice de révision n'est configuré pour ce bail")
    index_record = None
    if data.index_value_id:
        index_record = db.query(RentIndexValue).filter(RentIndexValue.id == data.index_value_id).first()
        if not index_record or index_record.index_type != contract_settings.rent_index_type:
            raise ValueError("Valeur d'indice incompatible")
    new_index = data.new_index_value or index_record.value
    old_index = data.old_index_value or contract_settings.base_index_value
    if not old_index:
        raise ValueError("Valeur d'indice de base manquante")
    old_rent = float(lease.monthly_rent)
    calculated = round(old_rent * float(new_index) / float(old_index), 2)

    cap_rule = None
    applicable_geographies = {lease.property.country or "France", lease.property.city, lease.property.postal_code}
    if data.cap_rule_id:
        cap_rule = db.query(RentCapRule).filter(RentCapRule.id == data.cap_rule_id, RentCapRule.is_active.is_(True)).first()
        if not cap_rule:
            raise ValueError("Règle de plafonnement inconnue")
        if cap_rule.valid_from > data.effective_date or (cap_rule.valid_to and cap_rule.valid_to < data.effective_date):
            raise ValueError("La règle de plafonnement n'est pas valide à la date d'effet")
        if cap_rule.lease_type and cap_rule.lease_type != contract_settings.lease_type:
            raise ValueError("La règle de plafonnement ne s'applique pas à ce type de bail")
        if cap_rule.geography not in applicable_geographies:
            raise ValueError("La règle de plafonnement ne s'applique pas à la zone du bien")
    elif data.manual_cap_percent is None:
        cap_rule = db.query(RentCapRule).filter(
            RentCapRule.is_active.is_(True),
            RentCapRule.valid_from <= data.effective_date,
            or_(RentCapRule.valid_to.is_(None), RentCapRule.valid_to >= data.effective_date),
            or_(RentCapRule.lease_type.is_(None), RentCapRule.lease_type == contract_settings.lease_type),
            RentCapRule.geography.in_(applicable_geographies),
        ).order_by(RentCapRule.valid_from.desc()).first()
    cap_percent = data.manual_cap_percent if data.manual_cap_percent is not None else (cap_rule.maximum_increase_percent if cap_rule else None)
    maximum_rent = round(old_rent * (1 + cap_percent / 100), 2) if cap_percent is not None else None
    capped = min(calculated, maximum_rent) if maximum_rent is not None and calculated > old_rent else calculated
    revision = RentRevision(
        reference=generate_reference("REV"),
        lease_id=lease.id,
        status=RevisionStatus.SCHEDULED,
        effective_date=data.effective_date,
        old_rent=old_rent,
        index_type=contract_settings.rent_index_type,
        old_index_value=old_index,
        new_index_value=new_index,
        calculated_rent=calculated,
        cap_rule_id=cap_rule.id if cap_rule else None,
        cap_percent=cap_percent,
        capped_rent=round(capped, 2),
        calculation_details={
            "formula": "old_rent × new_index / old_index",
            "cap_applied": maximum_rent is not None and calculated > maximum_rent,
            "maximum_rent": maximum_rent,
            "index_record_id": index_record.id if index_record else None,
            "legal_reference": cap_rule.legal_reference if cap_rule else None,
        },
        created_by=actor,
    )
    db.add(revision)
    if data.notify_tenant:
        notify_tenant(
            db,
            lease.tenant_id,
            "rent_revision_planned",
            "Révision de votre loyer",
            f"Une révision du loyer à {revision.capped_rent:.2f} € est prévue à compter du {data.effective_date.strftime('%d/%m/%Y')}.",
        )
        revision.tenant_notified_at = datetime.now(timezone.utc)
    log_event(db, lease.id, "rent_revision_calculated", "Révision de loyer calculée", actor, details={"revision_reference": revision.reference, "new_rent": revision.capped_rent})
    db.commit()
    db.refresh(revision)
    return revision


def apply_rent_revision(db: Session, revision: RentRevision, actor: str) -> RentRevision:
    if revision.status != RevisionStatus.SCHEDULED:
        raise ValueError("Seule une révision planifiée peut être appliquée")
    lease = revision.lease
    contract_settings = _settings_or_404(db, lease.id)
    lease.monthly_rent = revision.capped_rent
    revision.applied_rent = revision.capped_rent
    revision.status = RevisionStatus.APPLIED
    revision.applied_at = datetime.now(timezone.utc)
    contract_settings.base_index_value = revision.new_index_value
    contract_settings.base_index_date = revision.effective_date
    contract_settings.next_revision_date = add_months(revision.effective_date, 12)
    notify_tenant(db, lease.tenant_id, "rent_revision_applied", "Nouveau montant du loyer", f"Le loyer hors charges est désormais de {revision.capped_rent:.2f} €.")
    log_event(db, lease.id, "rent_revision_applied", "Révision de loyer appliquée", actor, details={"revision_id": revision.id, "rent": revision.capped_rent})
    db.commit()
    db.refresh(revision)
    return revision


def renewal_alerts(db: Session, horizon_months: Optional[int] = None) -> list[dict]:
    today = date.today()
    leases = db.query(Lease).join(LeaseContractSettings, LeaseContractSettings.lease_id == Lease.id).filter(
        Lease.status == LeaseStatus.ACTIVE,
        Lease.end_date.isnot(None),
    ).all()
    alerts = []
    for lease in leases:
        contract_settings = _settings_or_404(db, lease.id)
        months = horizon_months or contract_settings.renewal_notice_months
        threshold = add_months(today, months)
        if today <= lease.end_date <= threshold:
            alerts.append({
                "lease_id": lease.id,
                "reference": lease.reference,
                "tenant_id": lease.tenant_id,
                "tenant_name": f"{lease.tenant.first_name} {lease.tenant.last_name}",
                "end_date": lease.end_date,
                "days_remaining": (lease.end_date - today).days,
                "alert_months": months,
                "tacit_renewal": contract_settings.tacit_renewal,
            })
    return sorted(alerts, key=lambda item: item["end_date"])


def create_notice(db: Session, lease: Lease, data: NoticeCreate, actor: str) -> LeaseNotice:
    contract_settings = _settings_or_404(db, lease.id)
    months = data.notice_period_months
    if months is None:
        months = DEFAULT_NOTICE_MONTHS.get((contract_settings.lease_type, data.given_by), 1)
    effective_date = data.effective_end_date or add_months(data.notice_date, months)
    notice = LeaseNotice(
        reference=generate_reference("NOT"),
        lease_id=lease.id,
        given_by=data.given_by,
        reason=data.reason,
        reason_details=data.reason_details,
        notice_date=data.notice_date,
        notice_period_months=months,
        effective_end_date=effective_date,
        legal_basis=data.legal_basis,
        delivery_method=data.delivery_method,
        created_by=actor,
    )
    db.add(notice)
    notify_tenant(
        db,
        lease.tenant_id,
        "lease_notice",
        "Congé / résiliation du bail",
        f"Une procédure de congé est enregistrée avec une date d'effet au {effective_date.strftime('%d/%m/%Y')}.",
    )
    log_event(db, lease.id, "notice_created", "Congé enregistré", actor, details={"given_by": data.given_by.value, "reason": data.reason.value, "effective_end_date": effective_date.isoformat()})
    db.commit()
    db.refresh(notice)
    return notice


def generate_notice_pdf_bytes(notice: LeaseNotice) -> bytes:
    lease = notice.lease
    output, document, styles = _pdf_buffer(f"Congé {notice.reference}")
    giver = "le locataire" if notice.given_by == NoticeGivenBy.TENANT else "le bailleur"
    reason_labels = {
        NoticeReason.SALE: "vente du logement",
        NoticeReason.REPOSSESSION: "reprise du logement",
        NoticeReason.LEGITIMATE_REASON: "motif légitime et sérieux",
        NoticeReason.TENANT_DEPARTURE: "départ du locataire",
        NoticeReason.LEASE_EXPIRY: "échéance du bail",
        NoticeReason.OTHER: "autre motif",
    }
    story = [
        Paragraph("LETTRE DE CONGÉ", styles["Title"]),
        Spacer(1, 0.7 * cm),
        Paragraph(f"Référence : {html.escape(notice.reference)}", styles["BodyText"]),
        Paragraph(f"Bail : {html.escape(lease.reference)}", styles["BodyText"]),
        Paragraph(f"Bien : {html.escape(lease.property.address)}, {html.escape(lease.property.city)}", styles["BodyText"]),
        Spacer(1, 0.5 * cm),
        Paragraph(
            f"Par la présente, {giver} notifie le congé pour le motif suivant : {reason_labels[notice.reason]}. "
            f"Le préavis enregistré est de {notice.notice_period_months} mois et prendra effet le "
            f"{notice.effective_end_date.strftime('%d/%m/%Y')}.",
            styles["BodyText"],
        ),
    ]
    if notice.reason_details:
        story.extend([Spacer(1, 0.3 * cm), Paragraph(html.escape(notice.reason_details), styles["BodyText"])])
    if notice.legal_basis:
        story.extend([Spacer(1, 0.3 * cm), Paragraph(f"Fondement déclaré : {html.escape(notice.legal_basis)}", styles["BodyText"])])
    story.extend([Spacer(1, 1 * cm), Paragraph("Signature : ____________________", styles["BodyText"])])
    document.build(story)
    return output.getvalue()


def generate_amendment_pdf_bytes(amendment: LeaseAmendment) -> bytes:
    lease = amendment.lease
    output, document, styles = _pdf_buffer(f"Avenant {amendment.reference}")
    story = [
        Paragraph("AVENANT AU BAIL", styles["Title"]),
        Spacer(1, 0.5 * cm),
        Paragraph(f"Avenant n° {amendment.amendment_number} — {html.escape(amendment.title)}", styles["Heading2"]),
        Paragraph(f"Bail de référence : {html.escape(lease.reference)}", styles["BodyText"]),
        Paragraph(f"Prise d'effet : {amendment.effective_date.strftime('%d/%m/%Y')}", styles["BodyText"]),
        Paragraph(f"Locataire : {html.escape(lease.tenant.first_name)} {html.escape(lease.tenant.last_name)}", styles["BodyText"]),
        Paragraph(f"Bien : {html.escape(lease.property.address)}, {html.escape(lease.property.city)}", styles["BodyText"]),
        Spacer(1, 0.4 * cm),
    ]
    if amendment.reason:
        story.extend([Paragraph("Motif", styles["Heading3"]), Paragraph(html.escape(amendment.reason), styles["BodyText"])])
    story.append(Paragraph("Modifications", styles["Heading3"]))
    for key, value in (amendment.changes or {}).items():
        story.append(Paragraph(f"• {html.escape(str(key))} : {html.escape(str(value))}", styles["BodyText"]))
    for clause in amendment.clauses or []:
        story.extend([Paragraph(html.escape(clause.get("title", "Clause")), styles["Heading3"]), Paragraph(html.escape(clause.get("content", "")), styles["BodyText"])])
    story.extend([Spacer(1, 1 * cm), Paragraph("Signatures des parties : ______________________________", styles["BodyText"])])
    document.build(story)
    return output.getvalue()


def create_amendment(db: Session, lease: Lease, data, actor: str) -> LeaseAmendment:
    number = db.query(LeaseAmendment).filter(LeaseAmendment.lease_id == lease.id).count() + 1
    amendment = LeaseAmendment(
        reference=generate_reference("AMD"),
        lease_id=lease.id,
        amendment_number=number,
        title=data.title,
        effective_date=data.effective_date,
        reason=data.reason,
        changes=data.changes,
        clauses=[item.model_dump() for item in data.clauses],
        created_by=actor,
    )
    db.add(amendment)
    db.flush()
    document = store_contract_document(
        db,
        lease.id,
        ContractDocumentType.AMENDMENT,
        f"Avenant n° {number} — {data.title}",
        generate_amendment_pdf_bytes(amendment),
        actor,
    )
    amendment.document_id = document.id
    notify_tenant(db, lease.tenant_id, "lease_amendment", "Nouvel avenant au bail", f"L'avenant n° {number} prendra effet le {data.effective_date.strftime('%d/%m/%Y')}.")
    log_event(db, lease.id, "amendment_created", "Avenant créé", actor, details={"amendment_id": amendment.id, "document_id": document.id})
    db.commit()
    db.refresh(amendment)
    return amendment


def process_renewal(db: Session, renewal: LeaseRenewal, actor: str) -> LeaseRenewal:
    if renewal.status not in {RenewalStatus.PLANNED, RenewalStatus.NOTIFIED}:
        raise ValueError("Ce renouvellement ne peut plus être traité")
    if renewal.mode == RenewalMode.AMENDMENT and renewal.amendment_id:
        raise ValueError("L'avenant de renouvellement est en attente de signature et d'application")
    lease = renewal.lease
    contract_settings = _settings_or_404(db, lease.id)
    new_end_date = renewal.new_end_date or add_months(lease.end_date or renewal.planned_date, contract_settings.duration_months)
    awaiting_amendment_signature = False
    if renewal.mode == RenewalMode.AUTOMATIC:
        lease.end_date = new_end_date
        if renewal.new_rent:
            lease.monthly_rent = renewal.new_rent
    elif renewal.mode == RenewalMode.AMENDMENT:
        class RenewalAmendmentData:
            title = "Renouvellement du bail"
            effective_date = renewal.planned_date
            reason = "Renouvellement contractuel"
            changes = {"end_date": new_end_date.isoformat(), **({"rent_excluding_charges": renewal.new_rent} if renewal.new_rent else {})}
            clauses = []

        amendment = create_amendment(db, lease, RenewalAmendmentData(), actor)
        renewal.amendment_id = amendment.id
        awaiting_amendment_signature = True
    else:
        new_lease = Lease(
            reference=generate_reference("LEA"),
            tenant_id=lease.tenant_id,
            property_id=lease.property_id,
            status=LeaseStatus.DRAFT,
            start_date=renewal.planned_date,
            end_date=new_end_date,
            monthly_rent=renewal.new_rent or lease.monthly_rent,
            monthly_charges=lease.monthly_charges,
            deposit=lease.deposit,
            payment_day=lease.payment_day,
            lease_type=lease.lease_type,
            notes=f"Renouvellement du bail {lease.reference}",
        )
        db.add(new_lease)
        db.flush()
        new_settings = LeaseContractSettings(
            lease_id=new_lease.id,
            lease_type=contract_settings.lease_type,
            template_id=contract_settings.template_id,
            duration_months=contract_settings.duration_months,
            tacit_renewal=contract_settings.tacit_renewal,
            renewal_notice_months=contract_settings.renewal_notice_months,
            charge_method=contract_settings.charge_method,
            rent_frequency=contract_settings.rent_frequency,
            payment_method=contract_settings.payment_method,
            rent_index_type=contract_settings.rent_index_type,
            base_index_value=contract_settings.base_index_value,
            base_index_date=contract_settings.base_index_date,
            next_revision_date=contract_settings.next_revision_date,
            resolutory_clause=contract_settings.resolutory_clause,
            resolutory_clause_text=contract_settings.resolutory_clause_text,
            special_conditions=contract_settings.special_conditions,
            custom_variables=contract_settings.custom_variables,
        )
        db.add(new_settings)
        db.flush()
        for clause in contract_settings.clause_assignments:
            db.add(LeaseClauseAssignment(
                settings_id=new_settings.id,
                clause_id=clause.clause_id,
                title=clause.title,
                content=clause.content,
                display_order=clause.display_order,
                is_required=clause.is_required,
                source=clause.source,
            ))
        renewal.new_lease_id = new_lease.id
    renewal.new_end_date = new_end_date
    if awaiting_amendment_signature:
        renewal.status = RenewalStatus.NOTIFIED
        renewal.notified_at = datetime.now(timezone.utc)
        notify_tenant(db, lease.tenant_id, "lease_renewal_amendment", "Avenant de renouvellement à signer", f"Un avenant de renouvellement du bail {lease.reference} est disponible pour signature.")
        event_title = "Avenant de renouvellement généré"
    else:
        renewal.status = RenewalStatus.COMPLETED
        renewal.completed_at = datetime.now(timezone.utc)
        notify_tenant(db, lease.tenant_id, "lease_renewed", "Renouvellement du bail", f"Le renouvellement du bail {lease.reference} a été enregistré.")
        event_title = "Bail renouvelé"
    log_event(db, lease.id, "lease_renewed", event_title, actor, details={"renewal_id": renewal.id, "mode": renewal.mode.value, "new_end_date": new_end_date.isoformat(), "awaiting_signature": awaiting_amendment_signature})
    db.commit()
    db.refresh(renewal)
    return renewal


def compare_inspections(db: Session, exit_inspection: PropertyInspection) -> dict:
    if exit_inspection.inspection_type != InspectionType.EXIT:
        raise ValueError("La comparaison et les retenues s'appliquent à un état des lieux de sortie")
    entry = exit_inspection.comparison_inspection
    if not entry:
        entry = db.query(PropertyInspection).filter(
            PropertyInspection.lease_id == exit_inspection.lease_id,
            PropertyInspection.inspection_type == InspectionType.ENTRY,
            PropertyInspection.id != exit_inspection.id,
        ).order_by(PropertyInspection.inspection_date.desc()).first()
    if not entry:
        raise ValueError("Aucun état des lieux d'entrée disponible")
    exit_inspection.comparison_inspection_id = entry.id
    db.query(InspectionDeduction).filter(InspectionDeduction.inspection_id == exit_inspection.id).delete()

    entry_items = {}
    for room in entry.rooms:
        for item in room.items:
            entry_items[(room.name.strip().lower(), item.category, item.name.strip().lower())] = item
    comparisons = []
    total = 0.0
    for room in exit_inspection.rooms:
        for item in room.items:
            key = (room.name.strip().lower(), item.category, item.name.strip().lower())
            old = entry_items.get(key)
            old_rank = CONDITION_RANK.get(old.condition, 0) if old else 0
            new_rank = CONDITION_RANK.get(item.condition, 0)
            deteriorated = old is not None and new_rank > old_rank
            suggested = 0.0
            deduction = None
            if deteriorated and item.estimated_repair_cost > 0:
                suggested = round(
                    item.estimated_repair_cost
                    * (1 - item.depreciation_percent / 100)
                    * (item.tenant_responsibility_percent / 100),
                    2,
                )
                deduction = InspectionDeduction(
                    inspection_id=exit_inspection.id,
                    item_id=item.id,
                    label=f"{room.name} — {item.name}",
                    deterioration=f"{old.condition.value} → {item.condition.value}",
                    estimated_cost=item.estimated_repair_cost,
                    depreciation_percent=item.depreciation_percent,
                    responsibility_percent=item.tenant_responsibility_percent,
                    suggested_amount=suggested,
                )
                db.add(deduction)
                total += suggested
            comparisons.append({
                "room": room.name,
                "category": item.category,
                "item": item.name,
                "entry_condition": old.condition.value if old else None,
                "exit_condition": item.condition.value,
                "deteriorated": deteriorated,
                "suggested_deduction": suggested,
            })
    exit_inspection.total_suggested_deductions = round(total, 2)
    db.flush()
    log_event(db, exit_inspection.lease_id, "inspection_compared", "États des lieux comparés", "system", details={"entry_id": entry.id, "exit_id": exit_inspection.id, "suggested_deductions": total})
    db.commit()
    return {
        "entry_inspection_id": entry.id,
        "exit_inspection_id": exit_inspection.id,
        "comparisons": comparisons,
        "total_suggested_deductions": round(total, 2),
        "warning": "Les retenues proposées doivent être justifiées et approuvées avant imputation.",
    }


def decode_signature_image(encoded: str, directory: Path) -> tuple[str, str]:
    value = encoded.split(",", 1)[-1] if encoded.startswith("data:") else encoded
    try:
        content = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Signature encodée invalide")
    if not content or len(content) > 2 * 1024 * 1024:
        raise ValueError("La signature doit être une image PNG/JPEG de moins de 2 Mo")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        extension = "png"
    elif content.startswith(b"\xff\xd8\xff"):
        extension = "jpg"
    else:
        raise ValueError("La signature doit être une image PNG ou JPEG")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}.{extension}"
    path.write_bytes(content)
    return str(path), hashlib.sha256(content).hexdigest()


def create_signature_envelope(db: Session, lease: Lease, document: ContractDocument, data, actor: str) -> tuple[SignatureEnvelope, list[dict]]:
    if document.lease_id != lease.id or document.archive_status == ArchiveStatus.DESTROYED:
        raise ValueError("Document invalide pour ce bail")
    if document.signed_at:
        raise ValueError("Ce document est déjà entièrement signé")
    active_envelope = db.query(SignatureEnvelope).filter(
        SignatureEnvelope.document_id == document.id,
        SignatureEnvelope.status.in_([SignatureEnvelopeStatus.PENDING, SignatureEnvelopeStatus.PARTIALLY_SIGNED]),
    ).first()
    if active_envelope:
        raise ValueError("Une procédure de signature est déjà active pour ce document")
    if not Path(document.storage_path).is_file() or hashlib.sha256(Path(document.storage_path).read_bytes()).hexdigest() != document.checksum_sha256:
        raise ValueError("L'intégrité du document à signer ne peut pas être vérifiée")
    contract_settings = _settings_or_404(db, lease.id)
    if document.document_type == ContractDocumentType.LEASE and contract_settings.pdf_document_id != document.id:
        raise ValueError("Seule la dernière version générée du bail peut être envoyée en signature")
    if data.expires_at and datetime_is_past(data.expires_at):
        raise ValueError("La date d'expiration doit être future")
    envelope = SignatureEnvelope(
        reference=generate_reference("SIG"),
        lease_id=lease.id,
        document_id=document.id,
        subject=data.subject,
        message=data.message,
        expires_at=data.expires_at,
        status=SignatureEnvelopeStatus.PENDING,
        created_by=actor,
    )
    db.add(envelope)
    db.flush()
    invitations = []
    for party_data in data.parties:
        token = secrets.token_urlsafe(32)
        party = SignatureParty(
            envelope_id=envelope.id,
            access_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            **party_data.model_dump(),
        )
        db.add(party)
        db.flush()
        signing_url = f"/api/lease-signatures/{token}"
        invitations.append({
            "party_id": party.id,
            "email": party.email,
            "signing_url": signing_url,
        })
        if party.party_type == "tenant" and (party.party_id in {None, lease.tenant_id} or party.email.lower() == lease.tenant.email.lower()):
            notify_tenant(
                db,
                lease.tenant_id,
                "lease_signature_requested",
                data.subject,
                "Un document contractuel attend votre signature dans le portail locataire.",
            )
    if document.document_type == ContractDocumentType.LEASE:
        contract_settings.signature_status = "pending"
    elif document.document_type == ContractDocumentType.AMENDMENT:
        amendment = db.query(LeaseAmendment).filter(LeaseAmendment.document_id == document.id).first()
        if amendment:
            amendment.signature_status = "pending"
    log_event(db, lease.id, "signature_requested", "Signature électronique demandée", actor, details={"envelope_id": envelope.id, "parties": len(invitations)})
    db.commit()
    db.refresh(envelope)
    return envelope, invitations


def find_signature_party(db: Session, token: str) -> SignatureParty:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    party = db.query(SignatureParty).filter(SignatureParty.access_token_hash == token_hash).first()
    if not party:
        raise ValueError("Invitation de signature invalide")
    envelope = party.envelope
    if envelope.expires_at and datetime_is_past(envelope.expires_at):
        envelope.status = SignatureEnvelopeStatus.EXPIRED
        db.commit()
        raise ValueError("Invitation de signature expirée")
    if envelope.status in {SignatureEnvelopeStatus.CANCELLED, SignatureEnvelopeStatus.DECLINED, SignatureEnvelopeStatus.EXPIRED}:
        raise ValueError("Cette procédure de signature n'est plus active")
    return party


def generate_signature_evidence_bytes(envelope: SignatureEnvelope) -> bytes:
    output, document, styles = _pdf_buffer(f"Preuve de signature {envelope.reference}")
    story = [
        Paragraph("DOSSIER DE PREUVE DE SIGNATURE", styles["Title"]),
        Spacer(1, 0.5 * cm),
        Paragraph(f"Enveloppe : {envelope.reference}", styles["BodyText"]),
        Paragraph(f"Document : {envelope.document.reference}", styles["BodyText"]),
        Paragraph(f"Empreinte SHA-256 : {envelope.document.checksum_sha256}", styles["BodyText"]),
        Paragraph(f"Prestataire : {envelope.provider}", styles["BodyText"]),
        Spacer(1, 0.5 * cm),
        Paragraph("Signataires", styles["Heading2"]),
    ]
    rows = [["Nom", "Email", "Date", "Adresse IP", "Empreinte signée"]]
    for signer in sorted(envelope.parties, key=lambda item: item.signing_order):
        rows.append([
            signer.full_name,
            signer.email,
            signer.signed_at.strftime("%d/%m/%Y %H:%M UTC") if signer.signed_at else "",
            signer.ip_address or "",
            signer.signed_document_checksum or "",
        ])
    table = Table(rows, colWidths=[3.3 * cm, 4.2 * cm, 3.4 * cm, 2.6 * cm, 3 * cm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#244C66")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.extend([table, Spacer(1, 0.5 * cm), Paragraph(
        "Ce dossier atteste d'une signature électronique simple avec consentement explicite, horodatage, empreinte du document et éléments d'audit. Il ne constitue pas automatiquement une signature qualifiée au sens eIDAS.",
        styles["BodyText"],
    )])
    document.build(story)
    return output.getvalue()


def complete_signature(db: Session, party: SignatureParty, typed_signature: str, signature_image_base64: Optional[str], ip: str, user_agent: str):
    if party.status == SignaturePartyStatus.SIGNED:
        return party
    prior_pending = any(
        item.signing_order < party.signing_order and item.status != SignaturePartyStatus.SIGNED
        for item in party.envelope.parties
    )
    if prior_pending:
        raise ValueError("Le signataire précédent doit signer avant vous")
    signed_document = Path(party.envelope.document.storage_path)
    if not signed_document.is_file() or hashlib.sha256(signed_document.read_bytes()).hexdigest() != party.envelope.document.checksum_sha256:
        raise ValueError("L'intégrité du document à signer ne peut pas être vérifiée")
    path = None
    if signature_image_base64:
        path, _ = decode_signature_image(
            signature_image_base64,
            Path(settings.private_upload_dir_path) / "contracts" / str(party.envelope.lease_id) / "signatures",
        )
    party.status = SignaturePartyStatus.SIGNED
    party.typed_signature = typed_signature
    party.signature_image_path = path
    party.consent_text = "Je reconnais avoir lu le document et consens à le signer électroniquement."
    party.ip_address = ip
    party.user_agent = user_agent[:1000]
    party.signed_at = datetime.now(timezone.utc)
    party.signed_document_checksum = party.envelope.document.checksum_sha256
    db.flush()
    envelope = party.envelope
    if all(item.status == SignaturePartyStatus.SIGNED for item in envelope.parties):
        envelope.status = SignatureEnvelopeStatus.COMPLETED
        envelope.completed_at = datetime.now(timezone.utc)
        envelope.document.signed_at = envelope.completed_at
        if envelope.document.document_type == ContractDocumentType.LEASE:
            contract_settings = _settings_or_404(db, envelope.lease_id)
            contract_settings.signature_status = "completed"
            envelope.lease.signed_at = envelope.completed_at
            if envelope.lease.status == LeaseStatus.DRAFT:
                envelope.lease.status = LeaseStatus.ACTIVE
            envelope.lease.property.status = PropertyStatus.RENTED
        elif envelope.document.document_type == ContractDocumentType.AMENDMENT:
            amendment = db.query(LeaseAmendment).filter(LeaseAmendment.document_id == envelope.document_id).first()
            if amendment:
                amendment.signature_status = "completed"
                amendment.status = "signed"
        evidence = store_contract_document(
            db,
            envelope.lease_id,
            ContractDocumentType.SIGNATURE_CERTIFICATE,
            f"Dossier de preuve {envelope.reference}",
            generate_signature_evidence_bytes(envelope),
            "signature_service",
        )
        envelope.evidence_document_id = evidence.id
        log_event(db, envelope.lease_id, "signature_completed", "Signature électronique terminée", "signature_service", details={"envelope_id": envelope.id, "document_checksum": envelope.document.checksum_sha256, "evidence_document_id": evidence.id})
    else:
        envelope.status = SignatureEnvelopeStatus.PARTIALLY_SIGNED
    db.commit()
    db.refresh(party)
    return party


def generate_inspection_pdf_bytes(inspection: PropertyInspection) -> bytes:
    lease = inspection.lease
    title = "État des lieux d'entrée" if inspection.inspection_type == InspectionType.ENTRY else "État des lieux de sortie"
    output, document, styles = _pdf_buffer(f"{title} {inspection.reference}")
    story = [
        Paragraph(title.upper(), styles["Title"]),
        Paragraph(f"Référence : {inspection.reference}", styles["BodyText"]),
        Paragraph(f"Date : {inspection.inspection_date.strftime('%d/%m/%Y %H:%M')}", styles["BodyText"]),
        Paragraph(f"Bien : {html.escape(lease.property.address)}, {html.escape(lease.property.city)}", styles["BodyText"]),
        Paragraph(f"Locataire : {html.escape(lease.tenant.first_name)} {html.escape(lease.tenant.last_name)}", styles["BodyText"]),
        Spacer(1, 0.5 * cm),
    ]
    for room in sorted(inspection.rooms, key=lambda item: item.display_order):
        story.append(Paragraph(html.escape(room.name), styles["Heading2"]))
        rows = [["Élément", "Catégorie", "État", "Observations"]]
        for item in room.items:
            rows.append([item.name, item.category, item.condition.value, item.description or ""])
        table = Table(rows, colWidths=[4.5 * cm, 3 * cm, 2.5 * cm, 6 * cm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#244C66")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.extend([table, Spacer(1, 0.2 * cm)])
        for photo in [item for item in inspection.photos if item.room_id == room.id]:
            if Path(photo.storage_path).is_file():
                image = PDFImage(photo.storage_path)
                image._restrictSize(7 * cm, 5 * cm)
                caption = f"Photo horodatée : {photo.captured_at.strftime('%d/%m/%Y %H:%M')}"
                if photo.caption:
                    caption += f" — {photo.caption}"
                story.extend([image, Paragraph(html.escape(caption), styles["Caption"]), Spacer(1, 0.2 * cm)])
        story.append(Spacer(1, 0.2 * cm))
    unassigned_photos = [item for item in inspection.photos if item.room_id is None]
    if unassigned_photos:
        story.append(Paragraph("Photos générales horodatées", styles["Heading2"]))
        for photo in unassigned_photos:
            if Path(photo.storage_path).is_file():
                image = PDFImage(photo.storage_path)
                image._restrictSize(7 * cm, 5 * cm)
                story.extend([
                    image,
                    Paragraph(html.escape(f"{photo.captured_at.strftime('%d/%m/%Y %H:%M')} — {photo.caption or ''}"), styles["Caption"]),
                    Spacer(1, 0.2 * cm),
                ])
    if inspection.meters:
        story.append(Paragraph("Compteurs", styles["Heading2"]))
        story.append(Table([["Type", "N°", "Relevé", "Unité"]] + [[m.meter_type, m.serial_number or "", m.reading, m.unit or ""] for m in inspection.meters], colWidths=[4 * cm] * 4))
    if inspection.keys:
        story.append(Paragraph("Clés remises", styles["Heading2"]))
        story.append(Table([["Type", "Quantité", "Observations"]] + [[k.key_type, str(k.quantity), k.comments or ""] for k in inspection.keys], colWidths=[5 * cm, 3 * cm, 8 * cm]))
    if inspection.deductions:
        story.extend([PageBreak(), Paragraph("Retenues proposées / approuvées", styles["Heading2"])])
        story.append(Table(
            [["Élément", "Coût", "Vétusté", "Proposé", "Approuvé"]]
            + [[d.label, f"{d.estimated_cost:.2f} €", f"{d.depreciation_percent:.0f} %", f"{d.suggested_amount:.2f} €", f"{(d.approved_amount or 0):.2f} €"] for d in inspection.deductions],
            colWidths=[6 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm],
        ))
    story.extend([Spacer(1, 0.8 * cm), Paragraph("Signatures", styles["Heading2"])])
    for signature in inspection.signatures:
        story.append(Paragraph(f"{html.escape(signature.signer_type)} — {html.escape(signature.signer_name)} — {signature.signed_at.strftime('%d/%m/%Y %H:%M')}", styles["BodyText"]))
    document.build(story)
    return output.getvalue()
