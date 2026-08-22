"""Schémas Pydantic du module 9 : tableau de bord et reporting."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Widgets du dashboard (drag & drop)
# ---------------------------------------------------------------------------
class DashboardWidgetCreate(BaseModel):
    widget_type: str
    title: Optional[str] = None
    column_index: int = 0
    position: int = 0
    size: str = "medium"
    config: Dict[str, Any] = Field(default_factory=dict)


class DashboardWidgetUpdate(BaseModel):
    title: Optional[str] = None
    column_index: Optional[int] = None
    position: Optional[int] = None
    size: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None


class WidgetPosition(BaseModel):
    widget_id: int
    column_index: int
    position: int


class DashboardWidgetReorder(BaseModel):
    """Résultat d'un drag & drop : nouvelle disposition complète."""
    positions: List[WidgetPosition]


# ---------------------------------------------------------------------------
# Rapports personnalisés
# ---------------------------------------------------------------------------
class ReportFilter(BaseModel):
    field: str
    operator: str = "eq"  # eq | ne | gt | gte | lt | lte | like | in | between
    value: Optional[Any] = None
    second_value: Optional[Any] = None  # pour between


class CustomReportCreate(BaseModel):
    name: str
    description: Optional[str] = None
    dataset: str
    fields: List[str] = Field(default_factory=list)  # vide = toutes les colonnes
    filters: List[ReportFilter] = Field(default_factory=list)
    group_by: List[str] = Field(default_factory=list)
    sort_by: List[Dict[str, str]] = Field(default_factory=list)  # [{"field": "x", "dir": "asc"}]
    limit: Optional[int] = None


class CustomReportUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    dataset: Optional[str] = None
    fields: Optional[List[str]] = None
    filters: Optional[List[ReportFilter]] = None
    group_by: Optional[List[str]] = None
    sort_by: Optional[List[Dict[str, str]]] = None
    limit: Optional[int] = None
    is_active: Optional[bool] = None


class CustomReportRun(BaseModel):
    format: str = "json"  # json | pdf | excel | csv | word


class CustomReportSchedule(BaseModel):
    frequency: str = Field(..., pattern="^(aucune|quotidien|hebdomadaire|mensuel|trimestriel)$")
    recipients: List[str] = Field(default_factory=list)
    format: str = "pdf"


# ---------------------------------------------------------------------------
# Alertes
# ---------------------------------------------------------------------------
class AlertRuleCreate(BaseModel):
    name: str
    metric: str
    operator: str = Field("<", pattern="^(<|<=|>|>=|==)$")
    threshold: float
    severity: str = Field("warning", pattern="^(info|warning|critical)$")
    channels: List[str] = Field(default_factory=lambda: ["dashboard"])
    cooldown_hours: int = 24
    is_enabled: bool = True


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    metric: Optional[str] = None
    operator: Optional[str] = Field(None, pattern="^(<|<=|>|>=|==)$")
    threshold: Optional[float] = None
    severity: Optional[str] = Field(None, pattern="^(info|warning|critical)$")
    channels: Optional[List[str]] = None
    cooldown_hours: Optional[int] = None
    is_enabled: Optional[bool] = None


class AlertEventAck(BaseModel):
    acknowledged: bool = True
