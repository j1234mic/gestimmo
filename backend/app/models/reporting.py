"""Modèles du module 9 : tableau de bord et reporting.

Couvre la persistance de la personnalisation du dashboard (widgets
repositionnables en drag & drop), les rapports personnalisés (générateur,
filtres avancés, planification d'envoi, partage par jeton), l'historique des
exécutions de rapports et les règles d'alerte paramétrables avec seuils
personnalisables et journal des déclenchements.
"""

import enum
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from app.database import Base


class ScheduleFrequency(str, enum.Enum):
    NONE = "aucune"
    DAILY = "quotidien"
    WEEKLY = "hebdomadaire"
    MONTHLY = "mensuel"
    QUARTERLY = "trimestriel"


def _generate_share_token() -> str:
    return uuid.uuid4().hex


class DashboardWidget(Base):
    """Widget du tableau de bord principal, positionnable en drag & drop."""
    __tablename__ = "reporting_dashboard_widgets"

    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String(255), index=True, nullable=False)
    widget_type = Column(String(50), nullable=False)   # kpi_occupancy, revenue_chart…
    title = Column(String(255))
    column_index = Column(Integer, default=0, nullable=False)  # Colonne du dashboard
    position = Column(Integer, default=0, nullable=False)      # Ordre dans la colonne
    size = Column(String(20), default="medium")                # small | medium | large | xlarge
    config = Column(JSON, default=dict)
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CustomReport(Base):
    """Rapport personnalisé : dataset, champs, filtres, groupement,
    planification et partage."""
    __tablename__ = "reporting_custom_reports"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    dataset = Column(String(50), nullable=False)     # biens, baux, loyers, impayés…
    fields = Column(JSON, default=list)              # Colonnes sélectionnées
    filters = Column(JSON, default=list)             # Filtres avancés
    group_by = Column(JSON, default=list)
    sort_by = Column(JSON, default=list)
    limit = Column(Integer)

    schedule_frequency = Column(
        String(20), default=ScheduleFrequency.NONE, nullable=False
    )
    schedule_recipients = Column(JSON, default=list)  # Emails destinataires
    schedule_format = Column(String(20), default="pdf")
    last_run_at = Column(DateTime(timezone=True))
    next_run_at = Column(DateTime(timezone=True))
    last_run_status = Column(String(30))

    share_token = Column(String(64), unique=True, index=True, default=_generate_share_token)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ReportExecution(Base):
    """Historique des générations de rapports (prédéfinis et personnalisés)."""
    __tablename__ = "reporting_executions"

    id = Column(Integer, primary_key=True, index=True)
    report_kind = Column(String(20), nullable=False)   # predefined | custom
    report_key = Column(String(80), nullable=False, index=True)
    report_name = Column(String(255))
    params = Column(JSON, default=dict)
    output_format = Column(String(20), default="json")
    file_path = Column(String(500))
    row_count = Column(Integer, default=0)
    generated_by = Column(String(255))
    generated_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class AlertRule(Base):
    """Règle d'alerte dashboard : métrique surveillée, comparateur, seuil,
    sévérité, canaux et anti-spam (délai de repos)."""
    __tablename__ = "reporting_alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    metric = Column(String(80), nullable=False, index=True)  # occupancy_rate, unpaid_total…
    operator = Column(String(3), default="<", nullable=False)  # < <= > >= ==
    threshold = Column(Float, nullable=False)
    severity = Column(String(20), default="warning")          # info | warning | critical
    channels = Column(JSON, default=list)                     # dashboard | email | sms
    cooldown_hours = Column(Integer, default=24)
    is_enabled = Column(Boolean, default=True, nullable=False)
    last_triggered_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AlertEvent(Base):
    """Déclenchement d'une règle d'alerte (notification temps réel)."""
    __tablename__ = "reporting_alert_events"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, nullable=False, index=True)
    metric = Column(String(80), nullable=False)
    value = Column(Float, nullable=False)
    threshold = Column(Float, nullable=False)
    severity = Column(String(20), default="warning")
    message = Column(Text)
    channels = Column(JSON, default=list)
    triggered_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    acknowledged_at = Column(DateTime(timezone=True))
