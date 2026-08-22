"""API du module 9 : tableau de bord et reporting."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import require_read, require_write
from app.database import get_db
from app.models.reporting import AlertRule, CustomReport, ReportExecution
from app.schemas.reporting import (
    AlertEventAck,
    AlertRuleCreate,
    AlertRuleUpdate,
    CustomReportCreate,
    CustomReportRun,
    CustomReportSchedule,
    CustomReportUpdate,
    DashboardWidgetCreate,
    DashboardWidgetReorder,
    DashboardWidgetUpdate,
)
from app.services import reporting_service

router = APIRouter(prefix="/api/reporting", tags=["Tableau de bord et reporting"])

EXPORT_FORMATS = {"json", "pdf", "excel", "csv", "word"}


def _file_response(content: bytes, mime: str, extension: str, name: str) -> Response:
    return Response(
        content=content,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{name}.{extension}"'},
    )


# ---------------------------------------------------------------------------
# Dashboard principal
# ---------------------------------------------------------------------------
@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), current_user=Depends(require_read)):
    """KPIs temps réel + graphiques dynamiques du dashboard principal."""
    return {
        "kpis": reporting_service.dashboard_kpis(db),
        "charts": reporting_service.dashboard_charts(db),
    }


@router.get("/dashboard/kpis")
def dashboard_kpis(db: Session = Depends(get_db), current_user=Depends(require_read)):
    return reporting_service.dashboard_kpis(db)


@router.get("/dashboard/charts")
def dashboard_charts(
    months: int = Query(12, ge=1, le=36),
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    return reporting_service.dashboard_charts(db, months)


# ---------------------------------------------------------------------------
# Widgets personnalisables (drag & drop)
# ---------------------------------------------------------------------------
@router.get("/dashboard/widgets/catalog")
def widget_catalog(current_user=Depends(require_read)):
    return {"data": reporting_service.WIDGET_CATALOG}


@router.get("/dashboard/widgets")
def list_widgets(db: Session = Depends(get_db), current_user=Depends(require_read)):
    widgets = reporting_service.list_widgets(db, current_user.email)
    return {
        "data": [
            {
                "id": w.id,
                "widget_type": w.widget_type,
                "title": w.title,
                "column_index": w.column_index,
                "position": w.position,
                "size": w.size,
                "config": w.config or {},
                "is_enabled": w.is_enabled,
            }
            for w in widgets
        ],
        "count": len(widgets),
    }


@router.post("/dashboard/widgets", status_code=201)
def create_widget(data: DashboardWidgetCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    widget = reporting_service.create_widget(db, current_user.email, data)
    return {"id": widget.id, "widget_type": widget.widget_type, "position": widget.position}


@router.put("/dashboard/widgets/reorder")
def reorder_widgets(data: DashboardWidgetReorder, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        widgets = reporting_service.reorder_widgets(db, current_user.email, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "reordered": len(widgets),
        "data": [
            {"id": w.id, "column_index": w.column_index, "position": w.position} for w in widgets
        ],
    }


@router.put("/dashboard/widgets/{widget_id}")
def update_widget(widget_id: int, data: DashboardWidgetUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        widget = reporting_service.update_widget(db, widget_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"id": widget.id, "updated": True}


@router.delete("/dashboard/widgets/{widget_id}")
def delete_widget(widget_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        reporting_service.delete_widget(db, widget_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": True}


@router.get("/dashboard/widgets/{widget_type}/data")
def widget_data(widget_type: str, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return {"widget_type": widget_type, "data": reporting_service.widget_data(db, widget_type)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Rapports prédéfinis
# ---------------------------------------------------------------------------
@router.get("/reports/predefined")
def list_predefined_reports(current_user=Depends(require_read)):
    return {
        "data": [
            {"key": key, "name": name} for key, name in reporting_service.PREDEFINED_REPORTS.items()
        ]
    }


@router.get("/reports/predefined/{report_key}")
def run_predefined_report(
    report_key: str,
    format: str = Query("json", pattern="^(json|pdf|excel|csv|word)$"),
    year: Optional[int] = None,
    month: Optional[int] = Query(None, ge=1, le=12),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    params = {"year": year, "month": month, "date_from": date_from, "date_to": date_to}
    params = {k: v for k, v in params.items() if v is not None}
    try:
        report = reporting_service.build_predefined_report(db, report_key, params)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    report.setdefault("row_count", len(report.get("rows", [])))
    reporting_service.record_execution(
        db, "predefined", report_key, report.get("title", report_key), params, format,
        len(report.get("rows", [])), None, current_user.email,
    )
    if format == "json":
        return report
    try:
        content, mime, extension = reporting_service.build_export(report, format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _file_response(content, mime, extension, f"rapport_{report_key}")


# ---------------------------------------------------------------------------
# Rapports personnalisés
# ---------------------------------------------------------------------------
@router.get("/custom-reports/datasets")
def datasets(current_user=Depends(require_read)):
    return {"data": reporting_service.dataset_catalog()}


@router.post("/custom-reports", status_code=201)
def create_custom_report(data: CustomReportCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        report = reporting_service.create_custom_report(db, data, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _report_view(report)


@router.get("/custom-reports")
def list_custom_reports(db: Session = Depends(get_db), current_user=Depends(require_read)):
    reports = db.query(CustomReport).order_by(CustomReport.created_at.desc()).all()
    return {"data": [_report_view(r) for r in reports], "count": len(reports)}


@router.get("/custom-reports/{report_id}")
def get_custom_report(report_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    report = db.query(CustomReport).filter(CustomReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Rapport non trouvé")
    return _report_view(report)


@router.put("/custom-reports/{report_id}")
def update_custom_report(report_id: int, data: CustomReportUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        report = reporting_service.update_custom_report(db, report_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _report_view(report)


@router.delete("/custom-reports/{report_id}")
def delete_custom_report(report_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        reporting_service.delete_custom_report(db, report_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": True}


@router.post("/custom-reports/{report_id}/run")
def run_custom_report(
    report_id: int,
    data: CustomReportRun,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    report = db.query(CustomReport).filter(CustomReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Rapport non trouvé")
    try:
        result = reporting_service.run_custom_report(db, report)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    reporting_service.record_execution(
        db, "custom", report.id, report.name, {}, data.format, result["row_count"], None, current_user.email
    )
    if data.format == "json":
        return result
    try:
        content, mime, extension = reporting_service.build_export(result, data.format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _file_response(content, mime, extension, f"rapport_{report.id}_{report.name}"[:80])


@router.post("/custom-reports/{report_id}/schedule")
def schedule_custom_report(report_id: int, data: CustomReportSchedule, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        report = reporting_service.schedule_custom_report(db, report_id, data.frequency, data.recipients, data.format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _report_view(report)


@router.post("/reports/schedules/run")
def run_schedules(db: Session = Depends(get_db), current_user=Depends(require_write)):
    """Traite les envois planifiés échus (à déclencher par un cron)."""
    return reporting_service.run_due_schedules(db)


@router.get("/reports/shared/{token}")
def shared_report(token: str, db: Session = Depends(get_db)):
    """Accès à un rapport partagé via son jeton (sans authentification)."""
    try:
        return reporting_service.get_shared_report(db, token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/executions")
def list_executions(
    report_kind: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    query = db.query(ReportExecution)
    if report_kind:
        query = query.filter(ReportExecution.report_kind == report_kind)
    executions = query.order_by(ReportExecution.generated_at.desc()).limit(limit).all()
    return {
        "data": [
            {
                "id": e.id,
                "report_kind": e.report_kind,
                "report_key": e.report_key,
                "report_name": e.report_name,
                "output_format": e.output_format,
                "row_count": e.row_count,
                "generated_by": e.generated_by,
                "generated_at": e.generated_at.isoformat() if e.generated_at else None,
            }
            for e in executions
        ],
        "count": len(executions),
    }


def _report_view(report) -> dict:
    return {
        "id": report.id,
        "name": report.name,
        "description": report.description,
        "dataset": report.dataset,
        "fields": report.fields or [],
        "filters": report.filters or [],
        "group_by": report.group_by or [],
        "sort_by": report.sort_by or [],
        "limit": report.limit,
        "schedule": {
            "frequency": report.schedule_frequency,
            "recipients": report.schedule_recipients or [],
            "format": report.schedule_format,
            "last_run_at": report.last_run_at.isoformat() if report.last_run_at else None,
            "next_run_at": report.next_run_at.isoformat() if report.next_run_at else None,
            "last_run_status": report.last_run_status,
        },
        "share_token": report.share_token,
        "share_url": f"/api/reporting/reports/shared/{report.share_token}",
        "is_active": report.is_active,
        "created_by": report.created_by,
    }


# ---------------------------------------------------------------------------
# Exports génériques (pour BI externe : format json)
# ---------------------------------------------------------------------------
@router.get("/exports")
def generic_export(
    dataset: str,
    format: str = Query("json", pattern="^(json|pdf|excel|csv|word)$"),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    """Export brut d'un dataset — points d'entrée API pour un BI externe
    (format json) ou téléchargement de fichier."""
    from app.models.reporting import CustomReport

    if dataset not in reporting_service.DATASETS:
        raise HTTPException(status_code=400, detail=f"Dataset inconnu : {dataset}")
    spec = reporting_service.DATASETS[dataset]
    report = CustomReport(
        name=spec["label"], dataset=dataset, fields=list(spec["fields"].keys()), limit=limit
    )
    try:
        result = reporting_service.run_custom_report(db, report)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    reporting_service.record_execution(
        db, "custom", f"export_{dataset}", spec["label"], {"limit": limit}, format,
        result["row_count"], None, current_user.email,
    )
    if format == "json":
        return result
    content, mime, extension = reporting_service.build_export(result, format)
    return _file_response(content, mime, extension, f"export_{dataset}")


# ---------------------------------------------------------------------------
# Alertes et notifications dashboard
# ---------------------------------------------------------------------------
@router.get("/alerts/metrics")
def alert_metrics(current_user=Depends(require_read)):
    return {"data": [{"metric": k, "label": v} for k, v in reporting_service.ALERT_METRICS.items()]}


@router.post("/alert-rules", status_code=201)
def create_alert_rule(data: AlertRuleCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        rule = reporting_service.create_alert_rule(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _rule_view(rule)


@router.get("/alert-rules")
def list_alert_rules(db: Session = Depends(get_db), current_user=Depends(require_read)):
    rules = db.query(AlertRule).order_by(AlertRule.created_at.desc()).all()
    return {"data": [_rule_view(r) for r in rules], "count": len(rules)}


@router.put("/alert-rules/{rule_id}")
def update_alert_rule(rule_id: int, data: AlertRuleUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        rule = reporting_service.update_alert_rule(db, rule_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _rule_view(rule)


@router.delete("/alert-rules/{rule_id}")
def delete_alert_rule(rule_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        reporting_service.delete_alert_rule(db, rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": True}


@router.post("/alerts/evaluate")
def evaluate_alerts(db: Session = Depends(get_db), current_user=Depends(require_read)):
    """Évalue les règles actives : déclenche les alertes temps réel."""
    return reporting_service.evaluate_alerts(db)


@router.get("/alert-events")
def list_alert_events(
    acknowledged: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    events = reporting_service.list_alert_events(db, acknowledged)
    return {
        "data": [
            {
                "id": e.id,
                "rule_id": e.rule_id,
                "metric": e.metric,
                "value": e.value,
                "threshold": e.threshold,
                "severity": e.severity,
                "message": e.message,
                "channels": e.channels,
                "triggered_at": e.triggered_at.isoformat() if e.triggered_at else None,
                "acknowledged_at": e.acknowledged_at.isoformat() if e.acknowledged_at else None,
            }
            for e in events
        ],
        "count": len(events),
    }


@router.post("/alert-events/{event_id}/ack")
def acknowledge_event(event_id: int, data: AlertEventAck, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        event = reporting_service.acknowledge_alert_event(db, event_id, data.acknowledged)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"id": event.id, "acknowledged": event.acknowledged_at is not None}


def _rule_view(rule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "metric": rule.metric,
        "metric_label": reporting_service.ALERT_METRICS.get(rule.metric, rule.metric),
        "operator": rule.operator,
        "threshold": rule.threshold,
        "severity": rule.severity,
        "channels": rule.channels or [],
        "cooldown_hours": rule.cooldown_hours,
        "is_enabled": rule.is_enabled,
        "last_triggered_at": rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
    }
