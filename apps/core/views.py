from __future__ import annotations
import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any, Callable

from django import forms as django_forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .access import (
    ROLE_SET_ARCHIVE,
    ROLE_SET_AUDIT_LOG,
    ROLE_SET_BACKUP,
    ROLE_SET_DOCUMENTS,
    ROLE_SET_REPORTS,
    can_access_archive,
    can_access_audit_log,
    can_access_backups,
    can_access_documents,
    can_access_reports,
    can_update_archive_status,
)
from .exports import Exporter
from .forms import (
    ArchiveFilterForm,
    AuditLogFilterForm,
    BackupRestoreUploadForm,
    ConstructionObjectForm,
    DocumentTypeForm,
    MaterialForm,
    MaterialNormForm,
    PPEIssuanceCreateForm,
    PrimaryDocumentCreateForm,
    ProcurementRequestCreateForm,
    ReportFilterForm,
    SiteMaterialRequestCreateForm,
    SMRContractForm,
    StockIssueCreateForm,
    StockReceiptCreateForm,
    SupplierDocumentUploadForm,
    SupplierForm,
    SupplyContractForm,
    UserForm,
    WorkerForm,
    WorkStageForm,
    WorkAcceptanceCreateForm,
    WorkLogCreateForm,
    WorkScheduleCreateForm,
    WriteOffCreateForm,
    WorkStageControlForm,
)
from .models import (
    AuditLog,
    ConstructionObject,
    DocumentRecord,
    DocumentStatus,
    DocumentType,
    Material,
    MaterialNorm,
    PPEIssuance,
    PrimaryDocument,
    ProcurementRequest,
    RoleChoices,
    SiteMaterialRequest,
    SMRContract,
    StockIssue,
    StockReceipt,
    Supplier,
    WorkStage,
    SupplierDocument,
    SupplyContract,
    User,
    Worker,
    WorkAcceptanceAct,
    WorkLog,
    WorkSchedule,
    WorkScheduleLine,
    WriteOffAct,
)

from .reporting import REPORT_PROVIDERS, REPORT_TITLES
from .services import (
    backup_files,
    can_rework_document,
    clear_operation_draft,
    create_ppe_issuance,
    create_primary_document,
    create_procurement_request,
    create_site_material_request,
    create_supplier_document,
    create_stock_issue,
    create_stock_receipt,
    create_work_acceptance,
    create_stage_control,
    create_work_log,
    create_work_schedule,
    create_writeoff,
    dashboard_metrics,
    document_records,
    filter_queryset_for_user,
    load_operation_draft,
    low_stock_alerts,
    mark_all_notifications_read,
    mark_notification_read,
    notification_summary,
    notify_initial_document_status,
    restore_backup_payload,
    restore_backup_file,
    save_operation_draft,
    site_balances,
    transition_document,
    rework_target_status,
    update_rework_document,
    warehouse_balances,
    workflow_allowed_statuses,
    workflow_status_label,
    write_backup_file,
)

def _supply_contract_spent(contract) -> str:
    from .services import INVOICE_DOC_TYPES
    from django.db.models import Sum
    from decimal import Decimal
    spent = SupplierDocument.objects.filter(
        supply_contract=contract,
        doc_type__in=INVOICE_DOC_TYPES,
        status__in=[
            DocumentStatus.APPROVED,
            DocumentStatus.ACCEPTED,
            DocumentStatus.SENT_ACCOUNTING,
        ],
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return f"{spent:,.2f}".replace(",", " ")


def _supply_contract_remaining(contract) -> str:
    from .services import INVOICE_DOC_TYPES
    from django.db.models import Sum
    from decimal import Decimal
    if not contract.amount:
        return "—"
    spent = SupplierDocument.objects.filter(
        supply_contract=contract,
        doc_type__in=INVOICE_DOC_TYPES,
        status__in=[
            DocumentStatus.APPROVED,
            DocumentStatus.ACCEPTED,
            DocumentStatus.SENT_ACCOUNTING,
        ],
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    remaining = Decimal(contract.amount) - spent
    sign = "⚠️ -" if remaining < 0 else ""
    return f"{sign}{abs(remaining):,.2f}".replace(",", " ")

CATALOG_CONFIG: dict[str, dict[str, Any]] = {
    "materials": {
        "title": "Справочник материалов",
        "description": "Материалы, цены, минимальные остатки и признак СИЗ.",
        "form_class": MaterialForm,
        "queryset": lambda: Material.objects.order_by("code"),
        "columns": [
            ("Код", lambda obj: obj.code),
            ("Наименование", lambda obj: obj.name),
            ("Ед.", lambda obj: obj.unit),
            ("Норма остатка", lambda obj: obj.stock_reserve_qty),
            ("Категория", lambda obj: obj.category),
            ("СИЗ", lambda obj: obj.is_ppe),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.WAREHOUSE},
        "read_only_roles": {RoleChoices.DIRECTOR, RoleChoices.WAREHOUSE},
    },
    "suppliers": {
        "title": "Справочник поставщиков",
        "description": "Контрагенты, контактные лица и реквизиты для закупок.",
        "form_class": SupplierForm,
        "queryset": lambda: Supplier.objects.order_by("name"),
        "columns": [
            ("Поставщик", lambda obj: obj.name),
            ("ИНН", lambda obj: obj.tax_id),
            ("Контакт", lambda obj: obj.contact_person),
            ("Телефон", lambda obj: obj.phone),
            ("Эл. почта", lambda obj: obj.email),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.PROCUREMENT},
    },
    "objects": {
        "title": "Строительные объекты",
        "description": "Объекты строительства и связанная информация по заказчику.",
        "form_class": ConstructionObjectForm,
        "queryset": lambda: ConstructionObject.objects.order_by("name"),
        "columns": [
            ("Объект", lambda obj: obj.name),
            ("Заказчик", lambda obj: obj.customer_name),
            ("Адрес", lambda obj: obj.address),
            ("Начало", lambda obj: obj.start_date),
            ("Окончание", lambda obj: obj.end_date),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.PROCUREMENT, RoleChoices.SITE_MANAGER},
        "read_only_roles": {RoleChoices.PROCUREMENT, RoleChoices.SITE_MANAGER},
    },
    "workers": {
        "title": "Работники",
        "description": "Табельные номера и принадлежность к участкам.",
        "form_class": WorkerForm,
        "queryset": lambda: Worker.objects.order_by("full_name"),
        "columns": [
            ("ФИО", lambda obj: obj.full_name),
            ("Табельный номер", lambda obj: obj.employee_number),
            ("Участок", lambda obj: obj.site_name),
            ("Должность", lambda obj: obj.position),
            ("Дата приема", lambda obj: obj.hire_date),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.SITE_MANAGER},
        "scoped_roles": {RoleChoices.SITE_MANAGER},
        "read_only_roles": {RoleChoices.DIRECTOR, RoleChoices.SITE_MANAGER},
    },
    "norms": {
        "title": "Нормы расхода",
        "description": "Нормативы списания материалов по видам работ.",
        "form_class": MaterialNormForm,
        "queryset": lambda: MaterialNorm.objects.select_related("material").order_by("work_type", "material__code"),
        "columns": [
            ("Вид работ", lambda obj: obj.work_type),
            ("Материал", lambda obj: obj.material.code),
            ("Наименование", lambda obj: obj.material.name),
            ("Норма", lambda obj: obj.norm_per_unit),
            ("Ед.", lambda obj: obj.unit or obj.material.unit),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.DIRECTOR},
        "read_only_roles": {RoleChoices.DIRECTOR},
    },

    "work-stages": {
        "title": "Этапы работ",
        "description": "Этапы выполнения работ по видам для автоматического заполнения графика.",
        "form_class": WorkStageForm,
        "queryset": lambda: WorkStage.objects.order_by("work_type", "order"),
        "columns": [
            ("Вид работ", lambda obj: obj.work_type),
            ("Этап", lambda obj: obj.stage_name),
            ("Порядок", lambda obj: obj.order),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.DIRECTOR},
        "read_only_roles": set(),
        "save_callback": "save_work_stages",
    },

    "contracts": {
        "title": "Договоры СМР",
        "description": "Основные договоры с заказчиками по строительно-монтажным работам.",
        "form_class": SMRContractForm,
        "queryset": lambda: SMRContract.objects.select_related("object", "created_by").order_by("-contract_date", "-id"),
        "columns": [
            ("Номер", lambda obj: obj.number),
            ("Дата", lambda obj: obj.contract_date),
            ("Заказчик", lambda obj: obj.customer_name),
            ("Объект", lambda obj: obj.object.name if obj.object else ""),
            ("Сумма", lambda obj: obj.amount),
            ("Статус", lambda obj: obj.get_status_display()),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.SITE_MANAGER},
        "scoped_roles": {RoleChoices.SITE_MANAGER},
        "read_only_roles": {RoleChoices.SITE_MANAGER},
        "save_callback": "save_contract",
        "entity_type": "smr_contract",
    },
    "supply-contracts": {
        "title": "Договоры поставки",
        "description": "Договоры на закупку и поставку материалов от контрагентов.",
        "form_class": SupplyContractForm,
        "queryset": lambda: SupplyContract.objects.select_related("supplier").order_by("-contract_date", "-id"),
        "columns": [
            ("Номер", lambda obj: obj.number),
            ("Дата", lambda obj: obj.contract_date),
            ("Поставщик", lambda obj: obj.supplier.name),
            ("Сумма договора", lambda obj: obj.amount),
            ("Израсходовано", lambda obj: _supply_contract_spent(obj)),
            ("Остаток", lambda obj: _supply_contract_remaining(obj)),
            ("Статус", lambda obj: obj.get_status_display()),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.PROCUREMENT, RoleChoices.SUPPLIER},
        "scoped_roles": {RoleChoices.SUPPLIER},
        "read_only_roles": {RoleChoices.SUPPLIER},
        "entity_type": "supply_contract",
    },
    "document-types": {
        "title": "Типы документов",
        "description": "Справочник системных типов документов для загрузки и генерации.",
        "form_class": DocumentTypeForm,
        "queryset": lambda: DocumentType.objects.order_by("name"),
        "columns": [
            ("Код", lambda obj: obj.code),
            ("Наименование", lambda obj: obj.name),
            ("Префикс", lambda obj: obj.prefix),
            ("Загрузка", lambda obj: obj.available_for_upload),
            ("Генерация", lambda obj: obj.available_for_generation),
            ("Активен", lambda obj: obj.is_active),
        ],
        "allowed_roles": {RoleChoices.ADMIN},
    },
    "users": {
        "title": "Пользователи",
        "description": "Учетные записи ролей АИС и привязка к участкам/поставщикам.",
        "form_class": UserForm,
        "queryset": lambda: User.objects.select_related("supplier").order_by("username"),
        "columns": [
            ("Логин", lambda obj: obj.username),
            ("ФИО", lambda obj: obj.full_name_or_username),
            ("Роль", lambda obj: obj.role_label),
            ("Участок", lambda obj: obj.site_name),
            ("Поставщик", lambda obj: obj.supplier.name if obj.supplier else ""),
            ("Активен", lambda obj: obj.is_active),
        ],
        "allowed_roles": {RoleChoices.ADMIN},
        "save_callback": "save_user",
    },
}


OPERATION_CONFIG: dict[str, dict[str, Any]] = {
    "site-requests": {
        "title": "Заявки кладовщику",
        "description": "Заявки начальника участка на материалы со склада.",
        "form_class": SiteMaterialRequestCreateForm,
        "handler": create_site_material_request,
        "queryset": lambda: SiteMaterialRequest.objects.select_related("contract", "requested_by").order_by("-request_date", "-id"),
        "columns": [
            ("Номер", lambda obj: obj.number),
            ("Дата", lambda obj: obj.request_date),
            ("Участок", lambda obj: obj.site_name),
            ("Договор", lambda obj: obj.contract.number if obj.contract else ""),
            ("Статус", lambda obj: obj.get_status_display()),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.SITE_MANAGER, RoleChoices.WAREHOUSE},
        "read_only_roles": {RoleChoices.WAREHOUSE},
        "initial": lambda request: {"request_date": date.today(), "site_name": request.user.site_name or ""},
        "entity_type": "site_material_request",
    },
    "procurement": {
        "title": "Заявки на закупку",
        "description": "Заявки снабженцу и поставщику на основании заявки участка.",
        "form_class": ProcurementRequestCreateForm,
        "handler": create_procurement_request,
        "queryset": lambda: ProcurementRequest.objects.select_related("supplier", "contract", "site_request", "requested_by").order_by("-request_date", "-id"),
        "columns": [
            ("Номер", lambda obj: obj.number),
            ("Дата", lambda obj: obj.request_date),
            ("Участок", lambda obj: obj.site_name),
            ("Заявка участка", lambda obj: obj.site_request.number if obj.site_request else ""),
            ("Поставщик", lambda obj: obj.supplier.name if obj.supplier else ""),
            ("Статус", lambda obj: obj.get_status_display()),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.PROCUREMENT, RoleChoices.SUPPLIER},
        "read_only_roles": {RoleChoices.SUPPLIER},
        "initial": lambda request: {"request_date": date.today(), "site_name": request.user.site_name or ""},
        "entity_type": "procurement_request",
    },
    "supplier-documents": {
        "title": "Документы поставщиков",
        "description": "Загрузка счетов, счетов-фактур и накладных с привязкой к заявке или договору.",
        "form_class": SupplierDocumentUploadForm,
        "handler": create_supplier_document,
        "queryset": lambda: SupplierDocument.objects.select_related("supplier", "request", "supply_contract").order_by("-doc_date", "-id"),
        "columns": [
            ("Тип", lambda obj: obj.doc_type),
            ("Номер", lambda obj: obj.doc_number),
            ("Дата", lambda obj: obj.doc_date),
            ("Поставщик", lambda obj: obj.supplier.name),
            ("Сумма", lambda obj: obj.amount),
            ("Статус", lambda obj: obj.get_status_display()),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.PROCUREMENT, RoleChoices.SUPPLIER},
        "read_only_roles": {RoleChoices.PROCUREMENT},
        "scope_form_for_supplier": True,
        "initial": lambda request: {"doc_date": date.today(), "supplier": request.user.supplier if request.user.supplier_id else None},
        "entity_type": "supplier_document",
    },
    "primary-documents": {
        "title": "Первичные документы",
        "description": "Генерация счетов, счетов-фактур, товарных и приходных накладных на основе заявки, договора или прихода.",
        "form_class": PrimaryDocumentCreateForm,
        "handler": create_primary_document,
        "queryset": lambda: PrimaryDocument.objects.select_related(
            "document_type",
            "supplier",
            "procurement_request",
            "supply_contract",
            "stock_receipt",
            "created_by",
        ).order_by("-doc_date", "-id"),
        "columns": [
            ("Тип", lambda obj: obj.document_type.name),
            ("Номер", lambda obj: obj.number),
            ("Дата", lambda obj: obj.doc_date),
            ("Поставщик", lambda obj: obj.supplier.name),
            ("Основание", lambda obj: obj.basis_reference),
            ("Сумма", lambda obj: obj.amount),
            ("Статус", lambda obj: obj.get_status_display()),
        ],
        "allowed_roles": {RoleChoices.ADMIN},
        "initial": lambda request: {"doc_date": date.today(), "status": DocumentStatus.DRAFT},
        "entity_type": "primary_document",
    },
    "receipts": {
        "title": "Приход на склад",
        "description": "Оформление приходных ордеров и пополнение остатков центрального склада.",
        "form_class": StockReceiptCreateForm,
        "handler": create_stock_receipt,
        "queryset": lambda: StockReceipt.objects.select_related("supplier", "supplier_document", "primary_document", "created_by").order_by("-receipt_date", "-id"),
        "columns": [
            ("Номер", lambda obj: obj.number),
            ("Дата", lambda obj: obj.receipt_date),
            ("Поставщик", lambda obj: obj.supplier.name),
            ("Документ", lambda obj: obj.supplier_document.doc_number if obj.supplier_document else ""),
            ("Статус", lambda obj: obj.get_status_display()),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.WAREHOUSE},
        "initial": lambda request: {"receipt_date": date.today()},
        "entity_type": "stock_receipt",
    },
    "issues": {
        "title": "Отпуск материалов",
        "description": "Требования-накладные на передачу материалов с центрального склада на участок.",
        "form_class": StockIssueCreateForm,
        "handler": create_stock_issue,
        "queryset": lambda: StockIssue.objects.select_related("contract", "site_request", "stock_receipt", "issued_by").order_by("-issue_date", "-id"),
        "columns": [
            ("Номер", lambda obj: obj.number),
            ("Дата", lambda obj: obj.issue_date),
            ("Участок", lambda obj: obj.site_name),
            ("Получатель", lambda obj: obj.received_by_name),
            ("Статус", lambda obj: obj.get_status_display()),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.WAREHOUSE},
        "initial": lambda request: {"issue_date": date.today(), "site_name": request.user.site_name or ""},
        "entity_type": "stock_issue",
    },
    "writeoffs": {
        "title": "Акты списания",
        "description": "Списание материалов по нормативам на основании объема выполненных работ.",
        "form_class": WriteOffCreateForm,
        "handler": create_writeoff,
        "queryset": lambda: WriteOffAct.objects.select_related("contract", "created_by").order_by("-act_date", "-id"),
        "columns": [
            ("Номер", lambda obj: obj.number),
            ("Дата", lambda obj: obj.act_date),
            ("Участок", lambda obj: obj.site_name),
            ("Вид работ", lambda obj: obj.work_type),
            ("Статус", lambda obj: obj.get_status_display()),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.SITE_MANAGER},
        "initial": lambda request: {"act_date": date.today(), "site_name": request.user.site_name or ""},
        "entity_type": "write_off",
    },
    "ppe": {
        "title": "Выдача спецодежды",
        "description": "Учет СИЗ и спецодежды по работникам и срокам службы.",
        "form_class": PPEIssuanceCreateForm,
        "handler": create_ppe_issuance,
        "queryset": lambda: PPEIssuance.objects.select_related("issued_by").order_by("-issue_date", "-id"),
        "columns": [
            ("Номер", lambda obj: obj.number),
            ("Дата", lambda obj: obj.issue_date),
            ("Участок", lambda obj: obj.site_name),
            ("Сезон", lambda obj: obj.season),
            ("Статус", lambda obj: obj.get_status_display()),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.SITE_MANAGER},
        "initial": lambda request: {"issue_date": date.today(), "site_name": request.user.site_name or ""},
        "entity_type": "ppe_issuance",
    },
    "acceptance": {
        "title": "Акты сдачи-приемки",
        "description": "Закрывающий акт по выполненным работам СМР.",
        "form_class": WorkAcceptanceCreateForm,
        "handler": create_work_acceptance,
        "queryset": lambda: WorkAcceptanceAct.objects.select_related("contract", "contract__object", "created_by").order_by("-act_date", "-id"),
        "columns": [
            ("Номер", lambda obj: obj.number),
            ("Дата", lambda obj: obj.act_date),
            ("Участок", lambda obj: obj.site_name),
            ("Договор", lambda obj: obj.contract.number),
            ("Сумма", lambda obj: obj.amount),
            ("Статус", lambda obj: obj.get_status_display()),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.SITE_MANAGER},
        "initial": lambda request: {"act_date": date.today(), "site_name": request.user.site_name or ""},
        "entity_type": "work_acceptance",
    },
    "worklogs": {
        "title": "Журнал работ",
        "description": "Фиксация плановых и фактических объемов работ по участкам.",
        "form_class": WorkLogCreateForm,
        "handler": create_work_log,
        "queryset": lambda: WorkLog.objects.select_related("contract", "created_by").order_by("-actual_date", "-plan_date", "-id"),
        "columns": [
            ("Дата", lambda obj: obj.created_at),
            ("Участок", lambda obj: obj.site_name),
            ("Договор", lambda obj: obj.contract.number if obj.contract else ""),
            ("Вид работ", lambda obj: obj.work_type),
            ("План", lambda obj: obj.planned_volume),
            ("Факт", lambda obj: obj.actual_volume),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.SITE_MANAGER},
        "initial": lambda request: {"site_name": request.user.site_name or "", "plan_date": date.today()},
    },
    "stage-control": {
        "title": "Контроль этапов",
        "description": "Фиксация фактических дат выполнения этапов по графику работ.",
        "form_class": WorkStageControlForm,
        "handler": create_stage_control,
        "queryset": lambda: WorkScheduleLine.objects.select_related("schedule__contract").filter(
            schedule__contract__isnull=False,
        ).order_by("schedule__contract__number", "work_type", "order"),
        "columns": [
            ("Договор", lambda obj: obj.schedule.contract.number),
            ("Вид работ", lambda obj: obj.work_type),
            ("Этап", lambda obj: obj.stage),
            ("План начало", lambda obj: obj.start_date or ""),
            ("План конец", lambda obj: obj.end_date or ""),
            ("Факт начало", lambda obj: obj.actual_start or ""),
            ("Факт конец", lambda obj: obj.actual_date or ""),
            ("Статус", lambda obj: _stage_status(obj)),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.SITE_MANAGER},
        "initial": lambda request: {},
    },
    "work-schedules": {
        "title": "График работ",
        "description": "Календарный график производства работ по договору СМР.",
        "form_class": WorkScheduleCreateForm,
        "handler": create_work_schedule,
        "queryset": lambda: WorkSchedule.objects.select_related("contract", "created_by").order_by("-period_start", "-id"),
        "columns": [
            ("Номер", lambda obj: obj.number),
            ("Договор", lambda obj: obj.contract.number),
            ("Участок", lambda obj: obj.site_name),
            ("Начало", lambda obj: obj.period_start),
            ("Окончание", lambda obj: obj.period_end),
            ("Статус", lambda obj: obj.get_status_display()),
        ],
        "allowed_roles": {RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.SITE_MANAGER},
        "read_only_roles": set(),
        "initial": lambda request: {
            "site_name": request.user.site_name or "",
        },
        "entity_type": "work_schedule",
    },
}


def _require_roles(request: HttpRequest, allowed_roles: set[str]) -> None:
    if request.user.is_superuser:
        return
    if getattr(request.user, "role", None) not in allowed_roles:
        raise PermissionDenied("Недостаточно прав для выполнения операции.")

def _stage_status(line) -> str:
    from datetime import date as date_type
    today = date_type.today()
    if line.actual_date and line.end_date:
        diff = (line.actual_date - line.end_date).days
        if diff > 0:
            return f"Задержка {diff} дн."
        elif diff < 0:
            return f"Опережение {abs(diff)} дн."
        else:
            return "В срок"
    elif line.actual_start:
        return "В работе"
    elif line.end_date and line.end_date < today:
        return "Просрочен"
    elif line.start_date and line.start_date <= today:
        return "Ожидается начало"
    return "Не начат"

def _client_ip(request: HttpRequest) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _material_catalog(*, ppe_only: bool = False) -> list[dict[str, str]]:
    queryset = Material.objects.order_by("code")
    if ppe_only:
        queryset = queryset.filter(is_ppe=True)
    return [
        {
            "code": row["code"],
            "name": row["name"],
            "unit": row["unit"],
            "price": str(row["price"]),
        }
        for row in queryset.values("code", "name", "unit", "price")
    ]


def _worker_catalog(user=None) -> list[dict[str, str]]:
    queryset = Worker.objects.order_by("full_name")
    if getattr(user, "role", None) == RoleChoices.SITE_MANAGER:
        site_name = (getattr(user, "site_name", "") or "").strip()
        queryset = queryset.filter(site_name__iexact=site_name) if site_name else queryset.none()
    return [
        {
            "employee_number": row["employee_number"],
            "full_name": row["full_name"],
            "site_name": row["site_name"],
        }
        for row in queryset.values("employee_number", "full_name", "site_name")
    ]


def _format_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, Decimal):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _table_rows(queryset, columns: list[tuple[str, Callable[[Any], Any]]], *, limit: int = 20) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in queryset[:limit]:
        rows.append([_format_value(getter(item)) for _header, getter in columns])
    return rows


def _export_url(entity_type: str | None, item: Any) -> str:
    if not entity_type or not getattr(item, "pk", None):
        return ""
    return reverse("export-document", kwargs={"entity_type": entity_type, "entity_id": item.pk})


def _operation_slug_for_entity(entity_type: str) -> str:
    for slug, config in OPERATION_CONFIG.items():
        if config.get("entity_type") == entity_type:
            return slug
    return ""


def _rework_edit_url(record: DocumentRecord, user) -> str:
    slug = _operation_slug_for_entity(record.entity_type)
    if not slug or not can_rework_document(user, record):
        return ""
    config = OPERATION_CONFIG[slug]
    if not getattr(user, "is_superuser", False) and getattr(user, "role", None) in set(config.get("read_only_roles", set())):
        return ""
    return f"{reverse('operation-page', kwargs={'slug': slug})}?rework={record.pk}"


def _created_export_url(request: HttpRequest, config: dict[str, Any], queryset) -> str:
    entity_type = config.get("entity_type")
    raw_created_id = request.GET.get("created")
    if not entity_type or not raw_created_id:
        return ""
    try:
        created_id = int(raw_created_id)
    except (TypeError, ValueError):
        return ""
    if not queryset.filter(pk=created_id).exists():
        return ""
    return reverse("export-document", kwargs={"entity_type": entity_type, "entity_id": created_id})


def _material_lines_json(lines) -> str:
    return json.dumps(
        [
            {
                "material_code": line.material.code,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "notes": getattr(line, "notes", "") or "",
            }
            for line in lines.select_related("material").all()
        ],
        ensure_ascii=False,
    )


def _ppe_lines_json(lines) -> str:
    return json.dumps(
        [
            {
                "employee_number": line.worker.employee_number,
                "worker_name": line.worker.full_name,
                "material_code": line.material.code,
                "material_name": line.material.name,
                "quantity": str(line.quantity),
                "service_life_months": str(line.service_life_months),
                "clothing_size": line.clothing_size,
                "shoe_size": line.shoe_size,
            }
            for line in lines.select_related("worker", "material").all()
        ],
        ensure_ascii=False,
    )


def _operation_initial_from_instance(entity_type: str, instance: Any, user) -> dict[str, Any]:
    if entity_type == "site_material_request":
        return {
            "request_date": instance.request_date,
            "site_name": instance.site_name,
            "contract": instance.contract,
            "status": DocumentStatus.APPROVAL,
            "notes": instance.notes,
            "items": _material_lines_json(instance.lines),
        }
    if entity_type == "procurement_request":
        return {
            "request_date": instance.request_date,
            "site_request": instance.site_request,
            "site_name": instance.site_name,
            "contract": instance.contract,
            "supplier": instance.supplier,
            "status": DocumentStatus.APPROVAL,
            "notes": instance.notes,
            "items": _material_lines_json(instance.lines),
        }
    if entity_type == "supplier_document":
        return {
            "supplier": instance.supplier,
            "request": instance.request,
            "supply_contract": instance.supply_contract,
            "doc_type": instance.doc_type,
            "doc_number": instance.doc_number,
            "doc_date": instance.doc_date,
            "amount": instance.amount,
            "vat_amount": instance.vat_amount,
            "notes": instance.notes,
        }
    if entity_type == "primary_document":
        return {
            "document_type": instance.document_type,
            "doc_date": instance.doc_date,
            "supplier": instance.supplier,
            "request": instance.procurement_request,
            "supply_contract": instance.supply_contract,
            "stock_receipt": instance.stock_receipt,
            "status": DocumentStatus.APPROVAL,
            "amount": instance.amount,
            "vat_amount": instance.vat_amount,
            "notes": instance.notes,
            "items": _material_lines_json(instance.lines),
        }
    if entity_type == "stock_receipt":
        return {
            "receipt_date": instance.receipt_date,
            "supplier": instance.supplier,
            "supplier_document": instance.supplier_document,
            "primary_document": instance.primary_document,
            "status": DocumentStatus.APPROVAL,
            "notes": instance.notes,
            "items": _material_lines_json(instance.lines),
        }
    if entity_type == "stock_issue":
        return {
            "issue_date": instance.issue_date,
            "site_name": instance.site_name,
            "site_request": instance.site_request,
            "contract": instance.contract,
            "stock_receipt": instance.stock_receipt,
            "received_by_name": instance.received_by_name,
            "status": DocumentStatus.APPROVAL,
            "notes": instance.notes,
            "items": _material_lines_json(instance.lines),
        }
    if entity_type == "write_off":
        return {
            "act_date": instance.act_date,
            "contract": instance.contract,
            "template_variant": instance.template_variant,
            "site_name": instance.site_name,
            "work_type": instance.work_type,
            "work_volume": instance.work_volume,
            "volume_unit": instance.volume_unit,
            "status": DocumentStatus.APPROVAL,
            "notes": instance.notes,
        }
    if entity_type == "ppe_issuance":
        return {
            "issue_date": instance.issue_date,
            "site_name": instance.site_name,
            "season": instance.season,
            "status": DocumentStatus.APPROVAL,
            "notes": instance.notes,
            "items": _ppe_lines_json(instance.lines),
        }
    if entity_type == "work_acceptance":
        return {
            "act_date": instance.act_date,
            "contract": instance.contract,
            "site_name": instance.site_name,
            "work_description": instance.work_description,
            "accepted_volume": instance.accepted_volume,
            "volume_unit": instance.volume_unit,
            "amount": instance.amount,
            "status": DocumentStatus.APPROVAL,
            "notes": instance.notes,
        }
    return {}


def _rework_record_and_instance(request: HttpRequest, config: dict[str, Any]) -> tuple[DocumentRecord | None, Any | None]:
    raw_rework_id = request.POST.get("rework_record_id") or request.GET.get("rework")
    entity_type = config.get("entity_type")
    if not raw_rework_id or not entity_type:
        return None, None
    try:
        rework_id = int(raw_rework_id)
    except (TypeError, ValueError):
        raise Http404("Документ на доработку не найден.")

    record = get_object_or_404(
        filter_queryset_for_user(request.user, DocumentRecord.objects.select_related("created_by")),
        pk=rework_id,
        entity_type=entity_type,
    )
    if not can_rework_document(request.user, record):
        raise PermissionDenied("Для этого документа доработка недоступна.")
    queryset = filter_queryset_for_user(request.user, config["queryset"]())
    instance = get_object_or_404(queryset, pk=record.entity_id)
    return record, instance


def _prepare_rework_form(form, *, user, record: DocumentRecord | None) -> None:
    if record is None or "status" not in form.fields:
        return
    target_status = rework_target_status(user, record)
    form.fields["status"].choices = [(target_status, dict(DocumentStatus.choices)[target_status])]
    form.fields["status"].initial = target_status
    form.initial["status"] = target_status


def _catalog_rows(
    queryset,
    columns: list[tuple[str, Callable[[Any], Any]]],
    *,
    slug: str,
    can_manage: bool,
    entity_type: str | None = None,
    editing_id: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in queryset[:limit]:
        item_status = getattr(item, "status", None)
        can_edit = can_manage and item_status not in {"accepted", "archived", "approved", "sent_accounting"}
        can_upload_scan = can_manage and item_status not in {"accepted", "archived"}
        schedule = WorkSchedule.objects.filter(contract_id=item.pk).first() if slug == "contracts" else None
        has_schedule = bool(schedule)
        schedule_export_url = (
            reverse("export-document", kwargs={"entity_type": "work_schedule", "entity_id": schedule.pk})
            if schedule else ""
        )
        schedule_scan_url = schedule.attachment.url if schedule and schedule.attachment else ""
        schedule_id = schedule.pk if schedule else None
        rows.append(
            {
                "id": item.pk,
                "cells": [_format_value(getter(item)) for _header, getter in columns],
                "can_manage": can_manage,
                "can_edit": can_edit,
                "edit_url": f"{reverse('catalog-page', kwargs={'slug': slug})}?edit={item.pk}",
                "export_url": _export_url(entity_type, item),
                "estimate_url": item.attachment.url if getattr(item, "attachment", None) and item.attachment else "",
                "scan_url": item.scan_file.url if getattr(item, "scan_file", None) and item.scan_file else "",
                "is_editing": editing_id == item.pk,
                "has_schedule": has_schedule,
                "schedule_export_url": schedule_export_url,
                "schedule_scan_url": schedule_scan_url,
                "schedule_id": schedule_id,
                "can_upload_scan": can_upload_scan,
            }
        )
    return rows


def _operation_rows(
    queryset,
    columns: list[tuple[str, Callable[[Any], Any]]],
    *,
    entity_type: str | None = None,
    user=None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in queryset[:limit]:
        record = DocumentRecord.objects.filter(entity_type=entity_type, entity_id=item.pk).first() if entity_type else None
        status_choices = []
        if record and user:
            allowed = workflow_allowed_statuses(user, record)
            status_choices = [(v, l) for v, l in allowed if v != record.status]
        payment_order_url = ""
        if entity_type == "supplier_document" and hasattr(item, "payment_order") and item.payment_order:
            payment_order_url = item.payment_order.url

        rows.append(
            {
                "id": item.pk,
                "cells": [_format_value(getter(item)) for _header, getter in columns],
                "export_url": _export_url(entity_type, item),
                "scan_url": item.attachment.url if getattr(item, "attachment", None) and item.attachment else "",
                "record_id": record.pk if record else "",
                "current_status": record.status if record else "",
                "status_choices": status_choices,
                "payment_order_url": payment_order_url,
            }
        )
    return rows


def _dict_rows(items: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    if not items:
        return [], []
    headers = list(items[0].keys())
    rows = [[_format_value(item.get(header)) for header in headers] for item in items]
    return headers, rows


def _catalog_queryset_for_request(request: HttpRequest, config: dict[str, Any]):
    queryset = config["queryset"]()
    scoped_roles = set(config.get("scoped_roles", set()))
    if getattr(request.user, "role", None) in scoped_roles:
        queryset = filter_queryset_for_user(request.user, queryset)
    return queryset


def _navigation(request: HttpRequest) -> dict[str, Any]:
    role = getattr(getattr(request, "user", None), "role", None)
    catalog_links = []
    operation_links = []
    notifications = {"notification_count": 0, "notification_items": []}
    if role:
        catalog_links = [
            {"slug": slug, "title": config["title"], "url": reverse("catalog-page", kwargs={"slug": slug})}
            for slug, config in CATALOG_CONFIG.items()
            if role in config["allowed_roles"]
        ]
        operation_links = [
            {"slug": slug, "title": config["title"], "url": reverse("operation-page", kwargs={"slug": slug})}
            for slug, config in OPERATION_CONFIG.items()
            if role in config["allowed_roles"]
        ]
    if getattr(getattr(request, "user", None), "is_authenticated", False):
        notifications = notification_summary(request.user)
    return {
        "catalog_links": catalog_links,
        "operation_links": operation_links,
        **notifications,
        "documents_url": reverse("documents"),
        "archive_url": reverse("archive"),
        "reports_url": reverse("reports"),
        "backups_url": reverse("backups"),
        "audit_log_url": reverse("audit-log"),
        "dashboard_url": reverse("dashboard"),
        "analytics_url": reverse("analytics"),
        "can_access_documents": can_access_documents(role),
        "can_access_archive": can_access_archive(role),
        "can_access_reports": can_access_reports(role),
        "can_access_backups": can_access_backups(role),
        "can_access_audit_log": can_access_audit_log(role),
    }


def _render(request: HttpRequest, template_name: str, context: dict[str, Any]) -> HttpResponse:
    base_context = _navigation(request)
    base_context.update(context)
    return render(request, template_name, base_context)


def _save_contract(form, request: HttpRequest):
    from .models import SMRContractWorkLine
    
    contract = form.save(commit=False)
    if not contract.created_by_id:
        contract.created_by = request.user
    contract.save()
    
    # Сохраняем строки таблицы 3.2 (виды работ)
    work_lines_raw = (form.cleaned_data.get("work_lines") or "").strip()
    if work_lines_raw:
        try:
            work_lines_data = json.loads(work_lines_raw)
        except (json.JSONDecodeError, ValueError):
            work_lines_data = []
        
        if isinstance(work_lines_data, list):
            # Удаляем старые строки и создаём заново
            contract.work_lines.all().delete()
            for index, row in enumerate(work_lines_data, start=1):
                if not isinstance(row, dict):
                    continue
                work_type = str(row.get("work_type") or row.get("section") or "").strip()
                if not work_type:
                    continue
                unit = str(row.get("unit") or "").strip()
                quantity_raw = str(row.get("quantity") or "").strip().replace(",", ".")
                try:
                    quantity = Decimal(quantity_raw) if quantity_raw else Decimal("0")
                except (InvalidOperation, ValueError):
                    quantity = Decimal("0")
                SMRContractWorkLine.objects.create(
                    contract=contract,
                    work_type=work_type,
                    unit=unit,
                    quantity=quantity,
                    order=index,
                )
    
    return contract


def _save_user(form, request: HttpRequest):
    user = form.save(commit=False)
    user.is_staff = user.role in {RoleChoices.ADMIN, RoleChoices.ACCOUNTING, RoleChoices.PROCUREMENT, RoleChoices.WAREHOUSE, RoleChoices.DIRECTOR}
    user.is_superuser = user.role == RoleChoices.ADMIN
    user.save()
    return user

def _save_work_stages(form, request):
    work_type = form.cleaned_data["work_type"]
    stages_raw = (form.cleaned_data.get("stages") or "").strip()
    
    WorkStage.objects.filter(work_type=work_type).delete()
    
    for index, line in enumerate(stages_raw.splitlines(), start=1):
        stage_name = line.strip()
        if not stage_name:
            continue
        WorkStage.objects.create(
            work_type=work_type,
            stage_name=stage_name,
            order=index,
        )
    
    result = WorkStage.objects.filter(work_type=work_type).first()
    if not result:
        result = WorkStage.objects.create(work_type=work_type, stage_name="(пусто)", order=0)
    return result

SAVE_CALLBACKS = {
    "save_contract": _save_contract,
    "save_user": _save_user,
    "save_work_stages": _save_work_stages,
}


def _safe_file_response(path: Path) -> FileResponse:
    if not path.exists():
        raise Http404("Файл не найден.")
    return FileResponse(path.open("rb"), as_attachment=True, filename=path.name)


def _draft_payload_from_form(form) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for name, field in form.fields.items():
        if isinstance(field.widget, django_forms.FileInput):
            continue
        if isinstance(field, (django_forms.MultipleChoiceField, django_forms.ModelMultipleChoiceField)):
            payload[name] = form.data.getlist(name)
        else:
            payload[name] = form.data.get(name, "")
    return payload


def _can_create_in_config(*, request: HttpRequest, config: dict[str, Any]) -> bool:
    if request.user.is_superuser:
        return True
    read_only_roles = set(config.get("read_only_roles", set()))
    return getattr(request.user, "role", None) not in read_only_roles


def _scope_operation_form_for_supplier(*, request: HttpRequest, config: dict[str, Any], form) -> None:
    role = getattr(request.user, "role", None)
    if "contract" in form.fields:
        contracts_qs = SMRContract.objects.select_related("object", "created_by").order_by("-contract_date", "-id")
        if role == RoleChoices.SITE_MANAGER:
            contracts_qs = filter_queryset_for_user(request.user, contracts_qs)
        form.fields["contract"].queryset = contracts_qs
    if "site_request" in form.fields:
        busy_site_request_ids = ProcurementRequest.objects.filter(
            status__in=[
                DocumentStatus.APPROVAL,
                DocumentStatus.APPROVED,
                DocumentStatus.SENT_ACCOUNTING,
                DocumentStatus.ACCEPTED,
            ]
        ).exclude(site_request=None).values_list("site_request_id", flat=True)
        site_requests_qs = SiteMaterialRequest.objects.select_related("contract", "requested_by").filter(
            status__in=[DocumentStatus.APPROVED, DocumentStatus.ACCEPTED, DocumentStatus.SENT_ACCOUNTING]
        ).exclude(id__in=busy_site_request_ids).order_by("-request_date", "-id")
        if role == RoleChoices.SITE_MANAGER:
            site_requests_qs = filter_queryset_for_user(request.user, site_requests_qs)
        form.fields["site_request"].queryset = site_requests_qs

    if role != RoleChoices.SUPPLIER:
        return
    if not config.get("scope_form_for_supplier"):
        return

    supplier_id = getattr(request.user, "supplier_id", None)
    if "supplier" in form.fields:
        form.fields["supplier"].queryset = Supplier.objects.filter(pk=supplier_id) if supplier_id else Supplier.objects.none()
    if "request" in form.fields:
        requests_qs = ProcurementRequest.objects.select_related("supplier", "contract").order_by("-request_date", "-id")
        form.fields["request"].queryset = filter_queryset_for_user(request.user, requests_qs)
    if "supply_contract" in form.fields:
        contracts_qs = SupplyContract.objects.select_related("supplier", "related_smr_contract").order_by("-contract_date", "-id")
        form.fields["supply_contract"].queryset = filter_queryset_for_user(request.user, contracts_qs)


def _operation_form_kwargs(*, request: HttpRequest, config: dict[str, Any], initial: dict[str, Any] | None = None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"initial": initial or {}}
    if config.get("entity_type") == "write_off":
        kwargs["user"] = request.user
    return kwargs


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    recent_documents = filter_queryset_for_user(request.user, DocumentRecord.objects.select_related("created_by").order_by("-doc_date", "-id"))
    if request.user.role == RoleChoices.SUPPLIER:
        metrics = {
            "contracts": 0,
            "pending": recent_documents.count(),
            "supplier_docs": recent_documents.filter(entity_type__in=["supplier_document", "primary_document"]).count(),
            "site_tasks": 0,
            "alerts": 0,
        }
        alerts = []
        warehouse_rows = []
        site_rows = []
    elif request.user.role == RoleChoices.ACCOUNTING:
        metrics = dashboard_metrics(user=request.user)
        alerts = []
        warehouse_rows = []
        site_rows = []
    elif request.user.role == RoleChoices.SITE_MANAGER:
        site_name = (request.user.site_name or "").strip()
        metrics = dashboard_metrics(user=request.user)
        alerts = []
        warehouse_rows = []
        site_rows = site_balances(site_name=site_name)[:50] if site_name else []
    else:
        metrics = dashboard_metrics(user=request.user)
        alerts = low_stock_alerts()[:50]
        warehouse_rows = warehouse_balances()[:50]
        site_rows = site_balances()[:50]

    alert_label = "Заявки участков" if request.user.role == RoleChoices.PROCUREMENT else "Низкие остатки"

    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth
    from .models import StockIssueLine
    from .services import site_stock_alerts
    if request.user.role == RoleChoices.SITE_MANAGER:
        site_name = (request.user.site_name or "").strip()
        stock_alerts = [a for a in site_stock_alerts() if a["location_name"] == site_name] if site_name else []
    else:
        stock_alerts = site_stock_alerts()

    status_data = list(
        filter_queryset_for_user(request.user, DocumentRecord.objects.all())
        .values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )
    status_labels = [dict(DocumentStatus.choices).get(s["status"], s["status"]) for s in status_data]

    receipt_by_month = list(
        StockReceipt.objects
        .annotate(month=TruncMonth("receipt_date"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
        .filter(month__isnull=False)[:6]
    )

    top_materials = list(
        StockIssueLine.objects
        .values("material__name")
        .annotate(total=Sum("quantity"))
        .order_by("-total")[:5]
    )

    context = {
        "title": "Панель управления",
        "metrics": metrics,
        "alerts": alerts,
        "alert_label": alert_label,
        "warehouse_rows": warehouse_rows,
        "site_rows": site_rows,
        "recent_documents": recent_documents[:50],
        "stock_alerts": stock_alerts[:50],        
        "stock_alerts_count": len(stock_alerts),
        "chart_status_labels": json.dumps(status_labels, ensure_ascii=False),
        "chart_status_data": json.dumps([s["count"] for s in status_data]),
        "chart_receipt_labels": json.dumps([r["month"].strftime("%b %Y") if r["month"] else "" for r in receipt_by_month], ensure_ascii=False),
        "chart_receipt_data": json.dumps([r["count"] for r in receipt_by_month]),
        "chart_material_labels": json.dumps([m["material__name"] for m in top_materials], ensure_ascii=False),
        "chart_material_data": json.dumps([float(m["total"]) for m in top_materials]),
    }
    return _render(request, "core/dashboard.html", context)

@login_required
def upload_contract_scan(request: HttpRequest, contract_id: int) -> HttpResponse:
    """Загрузка скана подписанного договора СМР прямо из списка."""
    if request.method != "POST":
        raise Http404("Метод не поддерживается.")
    _require_roles(request, {RoleChoices.ADMIN, RoleChoices.DIRECTOR})
    contract = get_object_or_404(SMRContract, pk=contract_id)
    scan = request.FILES.get("scan_file")
    if scan:
        contract.scan_file = scan
        contract.save(update_fields=["scan_file"])
        messages.success(request, f"Скан договора {contract.number} загружен.")
    else:
        messages.error(request, "Файл не выбран.")
    return redirect("catalog-page", slug="contracts")

SCAN_UPLOAD_MODELS = {
    "site_material_request": SiteMaterialRequest,
    "procurement_request": ProcurementRequest,
    "supplier_document": SupplierDocument,
    "primary_document": PrimaryDocument,
    "stock_receipt": StockReceipt,
    "stock_issue": StockIssue,
    "write_off": WriteOffAct,
    "ppe_issuance": PPEIssuance,
    "work_acceptance": WorkAcceptanceAct,
    "work_schedule": WorkSchedule,
}


@login_required
def upload_operation_scan(request: HttpRequest, entity_type: str, entity_id: int) -> HttpResponse:
    if request.method != "POST":
        raise Http404("Метод не поддерживается.")
    model_class = SCAN_UPLOAD_MODELS.get(entity_type)
    if not model_class:
        raise Http404("Тип документа не поддерживается.")
    instance = get_object_or_404(model_class, pk=entity_id)
    scan = request.FILES.get("scan_file")
    slug = _operation_slug_for_entity(entity_type)
    if scan:
        instance.attachment = scan
        instance.save(update_fields=["attachment"])
        messages.success(request, "Скан документа загружен.")
    else:
        messages.error(request, "Файл не выбран.")
    
    # Для графика работ — возвращаем в договора
    if entity_type == "work_schedule":
        return redirect("catalog-page", slug="contracts")
    
    return redirect("operation-page", slug=slug)

@login_required
def catalog_page(request: HttpRequest, slug: str) -> HttpResponse:
    config = CATALOG_CONFIG.get(slug)
    if not config:
        raise Http404("Справочник не найден.")
    _require_roles(request, set(config["allowed_roles"]))

    can_create = _can_create_in_config(request=request, config=config)
    queryset = filter_queryset_for_user(request.user, config["queryset"]())
    # Черновики видит только создатель
    from django.db.models import Q
    model = queryset.model
    field_names = {f.name for f in model._meta.get_fields() if hasattr(f, 'name')}
    if 'status' in field_names:
        creator_field = next((f for f in ('created_by', 'requested_by', 'issued_by', 'uploaded_by') if f in field_names), None)
        if creator_field:
            queryset = queryset.exclude(
                Q(status=DocumentStatus.DRAFT) & ~Q(**{creator_field: request.user})
            )
    object_id = request.POST.get("object_id") if request.method == "POST" else request.GET.get("edit")
    instance = get_object_or_404(queryset, pk=object_id) if object_id else None
    form = config["form_class"](request.POST or None, request.FILES or None, instance=instance)
    # Загружаем сохранённые work_lines в форму при редактировании договора СМР
    if instance and slug == "contracts" and request.method != "POST":
        work_lines_qs = instance.work_lines.all().order_by("order", "id")
        if work_lines_qs.exists():
            form.fields["work_lines"].initial = json.dumps(
                [
                    {
                        "section": "",
                        "work_type": line.work_type,
                        "unit": line.unit,
                        "quantity": str(line.quantity),
                    }
                    for line in work_lines_qs
                ],
                ensure_ascii=False,
            )

    if request.method == "POST":
        if not can_create:
            raise PermissionDenied("Для вашей роли доступен только просмотр справочника.")
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "delete":
            if instance is None:
                raise Http404("Запись не найдена.")
            if slug == "users" and instance.pk == request.user.pk:
                messages.error(request, "Нельзя удалить текущую учетную запись.")
                return redirect("catalog-page", slug=slug)
            try:
                instance.delete()
                messages.success(request, "Запись удалена.")
            except ProtectedError:
                messages.error(
                    request,
                    "Запись нельзя удалить, потому что она связана с другими данными. Используйте редактирование и деактивацию.",
                )
            return redirect("catalog-page", slug=slug)
    if request.method == "POST" and form.is_valid():
        try:
            callback_name = config.get("save_callback")
            if callback_name:
                saved_object = SAVE_CALLBACKS[callback_name](form, request)
            else:
                saved_object = form.save()
            entity_type = config.get("entity_type")
            if entity_type and getattr(saved_object, "pk", None):
                notify_initial_document_status(actor=request.user, entity_type=entity_type, entity_id=saved_object.pk)
                message = (
                    "Запись обновлена. Файл доступен для скачивания."
                    if instance
                    else "Запись успешно сохранена. Файл доступен для скачивания."
                )
                messages.success(request, message)
                return redirect(f"{reverse('catalog-page', kwargs={'slug': slug})}?created={saved_object.pk}")
            else:
                messages.success(request, "Запись обновлена." if instance else "Запись успешно сохранена.")
            return redirect("catalog-page", slug=slug)
        except Exception as exc:
            form.add_error(None, str(exc))

    from .models import MaterialNorm
    work_type_choices = list(
        MaterialNorm.objects.values_list("work_type", flat=True)
        .distinct().order_by("work_type")
    )
    context = {
        "title": config["title"],
        "description": config["description"],
        "form": form,
        "can_create": can_create,
        "headers": [header for header, _getter in config["columns"]],
        "rows": _catalog_rows(
            queryset,
            config["columns"],
            slug=slug,
            can_manage=can_create,
            entity_type=config.get("entity_type"),
            editing_id=instance.pk if instance else None,
        ),
        "catalog_has_manage_actions": can_create,
        "catalog_has_export_actions": bool(config.get("entity_type")),
        "catalog_has_actions": can_create or bool(config.get("entity_type")),
        "is_editing": instance is not None,
        "current_catalog": slug,
        "created_export_url": _created_export_url(request, config, queryset),
        "work_type_choices": work_type_choices,  # ← ДОБАВЬ ЭТУ СТРОКУ
    }
    return _render(request, "core/catalogs.html", context)


@login_required
def operation_page(request: HttpRequest, slug: str) -> HttpResponse:
    config = OPERATION_CONFIG.get(slug)
    if not config:
        raise Http404("Операция не найдена.")
    _require_roles(request, set(config["allowed_roles"]))

    can_create = _can_create_in_config(request=request, config=config)
    # Очищаем старый черновик при открытии формы
    if request.method == "GET":
        clear_operation_draft(user=request.user, operation_slug=slug)
    initial = config.get("initial", lambda _request: {})(request)
    draft_payload = {}
    rework_record, rework_instance = _rework_record_and_instance(request, config)
    is_rework_edit = rework_record is not None
    if is_rework_edit and not can_create:
        raise PermissionDenied("Для вашей роли доработка этого документа через форму недоступна.")
    if is_rework_edit:
        initial = {**initial, **_operation_initial_from_instance(config["entity_type"], rework_instance, request.user)}
      # Черновики не подгружаются — форма всегда открывается чистой
    draft_payload = {}
    form = config["form_class"](
        request.POST or None,
        request.FILES or None,
        **_operation_form_kwargs(request=request, config=config, initial=initial),
    )
    _scope_operation_form_for_supplier(request=request, config=config, form=form)
    _prepare_rework_form(form, user=request.user, record=rework_record)
    if request.method == "POST" and not can_create:
        raise PermissionDenied("Для вашей роли доступен только просмотр операции.")
    if request.method == "POST" and form.is_valid():
        try:
            if is_rework_edit:
                update_rework_document(user=request.user, record=rework_record, cleaned_data=form.cleaned_data, ip_address=_client_ip(request))
                messages.success(request, "Документ доработан и отправлен повторно по маршруту согласования.")
                return redirect("documents")
            created_document = config["handler"](user=request.user, cleaned_data=form.cleaned_data, ip_address=_client_ip(request))
            clear_operation_draft(user=request.user, operation_slug=slug)
            entity_type = config.get("entity_type")
            if entity_type and getattr(created_document, "pk", None):
                messages.success(request, "Документ успешно создан. Файл доступен для скачивания.")
                return redirect(f"{reverse('operation-page', kwargs={'slug': slug})}?created={created_document.pk}")
            else:
                messages.success(request, "Документ успешно создан.")
            return redirect("operation-page", slug=slug)
        except Exception as exc:
            form.add_error(None, str(exc))

    items_field = form.fields.get("items")
    items_mode = ""
    if items_field is not None:
        items_mode = items_field.widget.attrs.get("data-items-mode", "")
    material_catalog = _material_catalog(ppe_only=items_mode == "ppe-lines") if items_mode else []
    worker_catalog = _worker_catalog(request.user) if items_mode == "ppe-lines" else []

    queryset = filter_queryset_for_user(request.user, config["queryset"]())
    # Черновики видит только создатель
    from django.db.models import Q
    model = queryset.model
    field_names = {f.name for f in model._meta.get_fields() if hasattr(f, 'name')}
    if 'status' in field_names:
        creator_field = next((f for f in ('created_by', 'requested_by', 'issued_by', 'uploaded_by') if f in field_names), None)
        if creator_field:
            queryset = queryset.exclude(
                Q(status=DocumentStatus.DRAFT) & ~Q(**{creator_field: request.user})
            )
    context = {
        "title": config["title"],
        "description": config["description"],
        "form": form,
        "headers": [header for header, _getter in config["columns"]],
        "rows": _operation_rows(queryset, config["columns"], entity_type=config.get("entity_type"), user=request.user),
        "operation_has_export_actions": bool(config.get("entity_type")),
        "current_operation": slug,
        "autosave_url": "",
        "draft_loaded": bool(draft_payload),
        "entity_type": config.get("entity_type", ""),
        "can_create": can_create,
        "is_rework_edit": is_rework_edit,
        "rework_record": rework_record,
        "rework_reason": (rework_record.metadata_json or {}).get("last_rework_reason", "") if rework_record else "",
        "rework_reason_by": (rework_record.metadata_json or {}).get("last_rework_by", "") if rework_record else "",
        "has_items_field": items_field is not None,
        "items_mode": items_mode,
        "material_catalog": material_catalog,
        "worker_catalog": worker_catalog,
        "created_export_url": _created_export_url(request, config, queryset),
        "current_user_fullname": request.user.full_name_or_username,
        "current_user_site": request.user.site_name or "",
    }
    return _render(request, "core/operation.html", context)


@login_required
def operation_draft(request: HttpRequest, slug: str) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"ok": False, "detail": "Метод не поддерживается."}, status=405)

    config = OPERATION_CONFIG.get(slug)
    if not config:
        raise Http404("Операция не найдена.")
    _require_roles(request, set(config["allowed_roles"]))
    if not _can_create_in_config(request=request, config=config):
        return JsonResponse({"ok": False, "detail": "Для вашей роли автосохранение недоступно."}, status=403)

    form = config["form_class"](
        request.POST or None,
        request.FILES or None,
        **_operation_form_kwargs(request=request, config=config),
    )
    _scope_operation_form_for_supplier(request=request, config=config, form=form)
    payload = _draft_payload_from_form(form)
    draft = save_operation_draft(user=request.user, operation_slug=slug, payload=payload)
    return JsonResponse(
        {
            "ok": True,
            "saved": draft is not None,
            "saved_at": timezone.localtime().strftime("%H:%M:%S"),
        }
    )


def _redirect_after_notification_action(request: HttpRequest) -> HttpResponse:
    target = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("dashboard")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = reverse("dashboard")
    return redirect(target)


@login_required
def notification_read(request: HttpRequest, notification_id: int) -> HttpResponse:
    if request.method != "POST":
        raise Http404("Метод не поддерживается.")
    mark_notification_read(user=request.user, notification_id=notification_id)
    return _redirect_after_notification_action(request)


@login_required
def notifications_read_all(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        raise Http404("Метод не поддерживается.")
    mark_all_notifications_read(user=request.user)
    return _redirect_after_notification_action(request)


def _notification_payload(item: Any, *, documents_url: str) -> dict[str, Any]:
    created_at = timezone.localtime(item.created_at)
    return {
        "id": item.id,
        "kind": item.kind,
        "title": item.title,
        "message": item.message,
        "entity_type": item.entity_type,
        "entity_id": item.entity_id,
        "document_record_id": item.document_record_id,
        "created_at": created_at.isoformat(),
        "created_label": created_at.strftime("%d.%m.%Y %H:%M"),
        "read_url": reverse("notification-read", kwargs={"notification_id": item.id}),
        "documents_url": documents_url,
    }


@login_required
def notifications_feed(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        raise Http404("Метод не поддерживается.")
    role = getattr(request.user, "role", None)
    documents_url = reverse("documents") if can_access_documents(role) else ""
    summary = notification_summary(request.user)
    return JsonResponse(
        {
            "count": summary["notification_count"],
            "items": [
                _notification_payload(item, documents_url=documents_url)
                for item in summary["notification_items"]
            ],
        }
    )


def _selected_record_ids(request: HttpRequest) -> list[int]:
    record_ids: list[int] = []
    seen: set[int] = set()
    for raw_id in request.POST.getlist("record_ids"):
        try:
            record_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if record_id <= 0 or record_id in seen:
            continue
        seen.add(record_id)
        record_ids.append(record_id)
    return record_ids


def _bulk_send_to_accounting(request: HttpRequest) -> None:
    record_ids = _selected_record_ids(request)
    if not record_ids:
        messages.error(request, "Выберите документы для отправки в бухгалтерию.")
        return

    scoped_records = filter_queryset_for_user(
        request.user,
        DocumentRecord.objects.select_related("created_by").exclude(status=DocumentStatus.ACCEPTED),
    )
    records_by_id = {record.id: record for record in scoped_records.filter(pk__in=record_ids)}
    sent_count = 0
    skipped: list[str] = []

    for record_id in record_ids:
        record = records_by_id.get(record_id)
        if record is None:
            skipped.append(f"ID {record_id}: документ недоступен")
            continue
        allowed_statuses = {value for value, _label in workflow_allowed_statuses(request.user, record)}
        if DocumentStatus.SENT_ACCOUNTING not in allowed_statuses:
            skipped.append(f"{record.doc_number}: нет доступного перехода в бухгалтерию")
            continue
        try:
            transition_document(
                user=request.user,
                record=record,
                new_status=DocumentStatus.SENT_ACCOUNTING,
                ip_address=_client_ip(request),
            )
            sent_count += 1
        except Exception as exc:
            skipped.append(f"{record.doc_number}: {exc}")

    if sent_count:
        messages.success(request, f"В бухгалтерию отправлено документов: {sent_count}.")
    if skipped:
        details = "; ".join(skipped[:4])
        if len(skipped) > 4:
            details = f"{details}; еще {len(skipped) - 4}"
        messages.warning(request, f"Не отправлены: {len(skipped)}. {details}")
    elif not sent_count:
        messages.error(request, "Не удалось отправить выбранные документы.")


def _rework_reason_from_post(request: HttpRequest, new_status: str) -> str:
    if new_status != DocumentStatus.REWORK:
        return ""
    return (request.POST.get("rework_reason") or "").strip()

SCAN_LOOKUP_MODELS = {
    "smr_contract": (SMRContract, "scan_file"),
    "supply_contract": (SupplyContract, "attachment"),
    "site_material_request": (SiteMaterialRequest, "attachment"),
    "procurement_request": (ProcurementRequest, "attachment"),
    "supplier_document": (SupplierDocument, "attachment"),
    "primary_document": (PrimaryDocument, "attachment"),
    "stock_receipt": (StockReceipt, "attachment"),
    "stock_issue": (StockIssue, "attachment"),
    "write_off": (WriteOffAct, "attachment"),
    "ppe_issuance": (PPEIssuance, "attachment"),
    "work_acceptance": (WorkAcceptanceAct, "attachment"),
}

def _record_estimate_url(record) -> str:
    """Ссылка на локальную смету — только для договоров СМР."""
    if record.entity_type != "smr_contract":
        return ""
    instance = SMRContract.objects.filter(pk=record.entity_id).first()
    if not instance or not instance.attachment:
        return ""
    return instance.attachment.url

def _record_scan_url(record) -> str:
    entry = SCAN_LOOKUP_MODELS.get(record.entity_type)
    if not entry:
        return ""
    model_class, field_name = entry
    instance = model_class.objects.filter(pk=record.entity_id).first()
    if not instance:
        return ""
    file_field = getattr(instance, field_name, None)
    return file_field.url if file_field else ""

@login_required
def documents(request: HttpRequest) -> HttpResponse:
    _require_roles(request, ROLE_SET_DOCUMENTS)
    can_manage_status = can_update_archive_status(getattr(request.user, "role", None))

    if request.method == "POST":
        if not can_manage_status:
            raise PermissionDenied("Недостаточно прав для изменения статуса.")
        if request.POST.get("action") == "bulk_send_accounting":
            _bulk_send_to_accounting(request)
            return redirect("documents")
        record = get_object_or_404(filter_queryset_for_user(request.user, DocumentRecord.objects.all()), pk=request.POST.get("record_id"))
        new_status = request.POST.get("new_status")
        if new_status not in dict(DocumentStatus.choices):
            raise Http404("Недопустимый статус.")
        rework_reason = _rework_reason_from_post(request, new_status)
        if new_status == DocumentStatus.REWORK and not rework_reason:
            messages.error(request, "Укажите причину возврата документа на доработку.")
            return redirect("documents")
        try:
            payment_order_file = request.FILES.get("payment_order") if new_status == DocumentStatus.APPROVED else None
            transition_document(
                user=request.user,
                record=record,
                new_status=new_status,
                ip_address=_client_ip(request),
                rework_reason=rework_reason,
                payment_order=payment_order_file,
            )
            messages.success(request, f"Статус документа {record.doc_number} обновлен.")
        except Exception as exc:
            messages.error(request, str(exc))
        return redirect("documents")

    form = ArchiveFilterForm(request.GET or None, user=request.user)
    filters = _archive_filters(form.cleaned_data) if form.is_valid() else {}
    records = document_records(filters, user=request.user, active_only=True)
     # Черновики видит только создатель
    from django.db.models import Q
    records = [
        r for r in records
        if r.status != DocumentStatus.DRAFT or r.created_by == request.user
    ]

    for record in records:
        record.display_status = workflow_status_label(record.entity_type, record.status)
        record.available_status_choices = [(record.status, record.display_status)]
        record.can_update_status = False
        record.scan_url = _record_scan_url(record)
        # Платёжное поручение (только для документов поставщика типа "счёт")
        record.payment_order_url = ""
        if record.entity_type == "supplier_document":
            _sd = SupplierDocument.objects.filter(pk=record.entity_id).first()
            if _sd and getattr(_sd, "payment_order", None) and _sd.payment_order:
                record.payment_order_url = _sd.payment_order.url
        record.estimate_url = _record_estimate_url(record)
        record.schedule_scan_url = ""
        record.schedule_scan_url = ""
        if record.entity_type == "smr_contract":
            schedule = WorkSchedule.objects.filter(contract_id=record.entity_id).first()
            if schedule and schedule.attachment:
                record.schedule_scan_url = schedule.attachment.url
        #if record.entity_type == "smr_contract":
            #print(f"DEBUG: договор {record.doc_number}, entity_id={record.entity_id}, estimate={record.estimate_url}, scan={record.scan_url}")

        if can_manage_status:
            allowed_statuses = workflow_allowed_statuses(request.user, record)
            for value, label in allowed_statuses:
                if value != record.status:
                    record.available_status_choices.append((value, label))
        record.can_update_status = can_manage_status and len(record.available_status_choices) > 1
        record.can_send_to_accounting = can_manage_status and any(
            value == DocumentStatus.SENT_ACCOUNTING
            for value, _label in record.available_status_choices
        )
        record.rework_edit_url = _rework_edit_url(record, request.user)
        record.can_edit_draft = (
            record.status in {DocumentStatus.DRAFT, DocumentStatus.REWORK}
            and record.created_by_id == request.user.pk
        )      
    can_bulk_send_to_accounting = any(getattr(record, "can_send_to_accounting", False) for record in records)
    context = {
        "title": "Документы в работе",
        "form": form,
        "records": records,
        "can_manage_status": can_manage_status,
        "can_bulk_send_to_accounting": can_bulk_send_to_accounting,
        "rework_status": DocumentStatus.REWORK,
        "is_archive": False,
    }
    return _render(request, "core/archive.html", context)


@login_required
def archive(request: HttpRequest) -> HttpResponse:
    _require_roles(request, ROLE_SET_ARCHIVE)
    if request.method == "POST":
        raise PermissionDenied("Архив закрытых документов доступен только для просмотра.")

    form = ArchiveFilterForm(request.GET or None, user=request.user, is_archive=True)
    filters = _archive_filters(form.cleaned_data) if form.is_valid() else {}
    records = document_records(filters, user=request.user, archived_only=True)
    for record in records:
        record.display_status = workflow_status_label(record.entity_type, record.status)
        record.available_status_choices = [(record.status, record.display_status)]
        record.can_update_status = False
        record.scan_url = _record_scan_url(record)
        record.estimate_url = _record_estimate_url(record)
        record.schedule_scan_url = ""
        if record.entity_type == "smr_contract":
            schedule = WorkSchedule.objects.filter(contract_id=record.entity_id).first()
            if schedule and schedule.attachment:
                record.schedule_scan_url = schedule.attachment.url
    context = {
        "title": "Архив закрытых документов",
        "form": form,
        "records": records,
        "can_manage_status": False,
        "rework_status": DocumentStatus.REWORK,
        "is_archive": True,
    }
    return _render(request, "core/archive.html", context)

def _report_filters(cleaned_data):
    material = cleaned_data.get("material_code")
    object_obj = cleaned_data.get("object_name")
    supplier = cleaned_data.get("supplier_name")
    contract = cleaned_data.get("contract_number")

    return {
        **cleaned_data,
        "material_code": material.code if material else "",
        "object_name": object_obj.name if object_obj else "",
        "supplier_name": supplier.name if supplier else "",
        "contract_number": contract.number if contract else "",
        "location_name": cleaned_data.get("location_name") or "",
    }

def _archive_filters(cleaned_data):
    counterparty = cleaned_data.get("counterparty")
    object_obj = cleaned_data.get("object_name")
    return {
        **cleaned_data,
        "counterparty": counterparty.name if counterparty else "",
        "object_name": object_obj.name if object_obj else "",
    }

    return {
        **cleaned_data,
        "material_code": material.code if material else "",
        "object_name": object_obj.name if object_obj else "",
        "supplier_name": supplier.name if supplier else "",
        "contract_number": contract.number if contract else "",
    }

@login_required
def reports(request: HttpRequest) -> HttpResponse:
    _require_roles(request, ROLE_SET_REPORTS)
    form = ReportFilterForm(request.GET or None, user=request.user)
    rows: list[dict[str, Any]] = []
    report_name = "summary"
    if form.is_valid():
        report_name = form.cleaned_data["report"]
        rows = REPORT_PROVIDERS[report_name](_report_filters(form.cleaned_data), user=request.user)
    

    headers, table_rows = _dict_rows(rows)
    context = {
        "title": "Отчеты",
        "form": form,
        "report_name": report_name,
        "report_title": REPORT_TITLES[report_name] if rows else "",
        "headers": headers,
        "rows": table_rows,
    }
    return _render(request, "core/reports.html", context)


@login_required
def backups(request: HttpRequest) -> HttpResponse:
    _require_roles(request, ROLE_SET_BACKUP)
    restore_form = BackupRestoreUploadForm()
    if request.method == "POST":
        action = request.POST.get("action", "create")
        try:
            if action == "create":
                path = write_backup_file(user=request.user)
                messages.success(request, f"Резервная копия создана: {path.name}")
                return redirect("backups")
            if action == "restore-existing":
                backup_name = request.POST.get("backup_name", "")
                backup_path = (settings.BACKUPS_DIR / backup_name).resolve()
                if backup_path.parent != settings.BACKUPS_DIR.resolve() or not backup_path.exists():
                    raise Http404("Файл не найден.")
                restored_counts = restore_backup_file(backup_path, user=request.user, ip_address=_client_ip(request))
                messages.success(request, f"Данные восстановлены из {backup_name}. Записей: {sum(restored_counts.values())}.")
                return redirect("backups")
            if action == "restore-upload":
                restore_form = BackupRestoreUploadForm(request.POST, request.FILES)
                if restore_form.is_valid():
                    uploaded = restore_form.cleaned_data["backup_file"]
                    payload = json.loads(uploaded.read().decode("utf-8"))
                    restored_counts = restore_backup_payload(
                        payload=payload,
                        user=request.user,
                        ip_address=_client_ip(request),
                        source_name=uploaded.name,
                    )
                    messages.success(request, f"Данные восстановлены из загруженного файла {uploaded.name}. Записей: {sum(restored_counts.values())}.")
                    return redirect("backups")
            else:
                raise Http404("Неизвестное действие.")
        except Exception as exc:
            if action == "restore-upload":
                restore_form.add_error(None, str(exc))
            else:
                messages.error(request, str(exc))
    context = {
        "title": "Резервные копии",
        "items": backup_files(),
        "restore_form": restore_form,
    }
    return _render(request, "core/backups.html", context)

AUDIT_ACTION_LABELS = {
    "create": "Создание",
    "update": "Изменение",
    "delete": "Удаление",
    "upload": "Загрузка",
    "status_change": "Смена статуса",
    "backup": "Резервная копия",
    "restore": "Восстановление",
    "login": "Вход",
    "logout": "Выход",
}

AUDIT_ENTITY_LABELS = {
    "site_material_request": "Заявка кладовщику",
    "procurement_request": "Заявка на закупку",
    "supplier_document": "Документ поставщика",
    "primary_document": "Первичный документ",
    "stock_receipt": "Приход на склад",
    "stock_issue": "Отпуск материалов",
    "write_off": "Акт списания",
    "ppe_issuance": "Выдача спецодежды",
    "work_acceptance": "Акт сдачи-приёмки",
    "work_schedule": "График работ",
    "smr_contract": "Договор СМР",
    "supply_contract": "Договор поставки",
    "material": "Материал",
    "worker": "Работник",
    "user": "Пользователь",
    "database": "База данных",
    "work_log": "Журнал работ",
    "work_schedule_line": "Строка графика работ",
}

@login_required
def audit_log(request: HttpRequest) -> HttpResponse:
    _require_roles(request, ROLE_SET_AUDIT_LOG)
    form = AuditLogFilterForm(request.GET or None)
    entries = AuditLog.objects.select_related("user").order_by("-created_at", "-id")

    if form.is_valid():
        filters = form.cleaned_data
        if filters.get("username"):
            entries = entries.filter(user__username__icontains=filters["username"])
        if filters.get("action"):
            entries = entries.filter(action__icontains=filters["action"])
        if filters.get("entity_type"):
            entries = entries.filter(entity_type__icontains=filters["entity_type"])
        if filters.get("date_from"):
            entries = entries.filter(created_at__date__gte=filters["date_from"])
        if filters.get("date_to"):
            entries = entries.filter(created_at__date__lte=filters["date_to"])
        if filters.get("query"):
            query = filters["query"]
            entries = entries.filter(
                Q(details__icontains=query)
                | Q(action__icontains=query)
                | Q(entity_type__icontains=query)
                | Q(user__username__icontains=query)
            )
    entries_list = list(entries[:100])
    for entry in entries_list:
        entry.action_label = AUDIT_ACTION_LABELS.get(entry.action, entry.action)
        entry.entity_label = AUDIT_ENTITY_LABELS.get(entry.entity_type, entry.entity_type)

    context = {
        "title": "Журнал действий",
        "form": form,
        "entries": entries_list,  
    }
    return _render(request, "core/audit_log.html", context)


@login_required
def export_document(request: HttpRequest, entity_type: str, entity_id: int) -> FileResponse:
    record = DocumentRecord.objects.filter(entity_type=entity_type, entity_id=entity_id).first()
    if not record:
        # Создаём DocumentRecord для старых документов у которых его нет
        from .services import sync_document_record
        model_map = {
            "smr_contract": (SMRContract, lambda obj: {
                "doc_type": "Договор СМР",
                "doc_number": obj.number,
                "doc_date": obj.contract_date,
                "status": obj.status,
                "title": str(obj),
                "created_by": obj.created_by,
            }),
            "supply_contract": (SupplyContract, lambda obj: {
                "doc_type": "Договор поставки",
                "doc_number": obj.number,
                "doc_date": obj.contract_date,
                "status": obj.status,
                "title": str(obj),
            }),
            "work_schedule": (WorkSchedule, lambda obj: {
                "doc_type": "График работ",
                "doc_number": obj.number,
                "doc_date": obj.period_start,
                "status": obj.status,
                "title": f"График работ {obj.number}",
                "created_by": obj.created_by,
            }),
        }
        if entity_type in model_map:
            model_class, get_data = model_map[entity_type]
            instance = model_class.objects.filter(pk=entity_id).first()
            if instance:
                data = get_data(instance)
                sync_document_record(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    **data,
                )
        record = DocumentRecord.objects.filter(entity_type=entity_type, entity_id=entity_id).first()
    if not record:
        raise Http404("Документ не найден.")
    if not request.user.is_superuser:
        if not filter_queryset_for_user(request.user, DocumentRecord.objects.filter(pk=record.pk)).exists():
            raise Http404("Документ не найден.")
    exporter = Exporter()
    path = exporter.export_document(entity_type, entity_id)
    return _safe_file_response(path)


@login_required
def export_report(request: HttpRequest) -> FileResponse:
    _require_roles(request, ROLE_SET_REPORTS)
    form = ReportFilterForm(request.GET or None, user=request.user)
    if not form.is_valid():
        raise Http404("Некорректные параметры отчета.")
    exporter = Exporter()
    path = exporter.export_report(
        form.cleaned_data["report"],
        _report_filters(form.cleaned_data),
        user=request.user
    )
    return _safe_file_response(path)


@login_required
def download_backup(request: HttpRequest, backup_name: str) -> FileResponse:
    _require_roles(request, ROLE_SET_BACKUP)
    backup_path = (settings.BACKUPS_DIR / backup_name).resolve()
    if backup_path.parent != settings.BACKUPS_DIR.resolve():
        raise Http404("Файл не найден.")
    return _safe_file_response(backup_path)

@login_required
def supplier_documents_json(request: HttpRequest) -> JsonResponse:
    supplier_id = request.GET.get("supplier_id")
    if not supplier_id:
        return JsonResponse({"documents": []})
    try:
        supplier_id = int(supplier_id)
    except (TypeError, ValueError):
        return JsonResponse({"documents": []})
    docs = SupplierDocument.objects.filter(
        supplier_id=supplier_id,
        doc_type="Товарная накладная",
    ).order_by("-doc_date")
    data = [
        {"id": doc.pk, "label": str(doc)}
        for doc in docs
    ]
    return JsonResponse({"documents": data})

@login_required
def contract_work_lines_json(request: HttpRequest) -> JsonResponse:
    contract_id = request.GET.get("contract_id")
    if not contract_id:
        return JsonResponse({"work_lines": []})
    try:
        contract_id = int(contract_id)
    except (TypeError, ValueError):
        return JsonResponse({"work_lines": []})
    from .models import SMRContractWorkLine
    lines = SMRContractWorkLine.objects.filter(contract_id=contract_id).order_by("order", "id")
    data = [
        {
            "work_type": line.work_type,
            "unit": line.unit,
            "quantity": str(line.quantity),
        }
        for line in lines
    ]
    return JsonResponse({"work_lines": data})

@login_required
def contract_materials_json(request: HttpRequest) -> JsonResponse:
    """Подтягивает материалы по нормам расхода для видов работ из договора СМР."""
    contract_id = request.GET.get("contract_id")
    if not contract_id:
        return JsonResponse({"materials": []})
    try:
        contract_id = int(contract_id)
    except (TypeError, ValueError):
        return JsonResponse({"materials": []})
    
    from .models import SMRContractWorkLine, MaterialNorm
    
    work_lines = SMRContractWorkLine.objects.filter(contract_id=contract_id).order_by("order", "id")
    
    materials_needed = {}
    for work_line in work_lines:
        if not work_line.work_type or not work_line.quantity:
            continue
        norms = MaterialNorm.objects.select_related("material").filter(work_type=work_line.work_type)
        for norm in norms:
            material = norm.material
            # Количество по договору (норма × объём)
            qty_by_contract = Decimal(work_line.quantity) * Decimal(norm.norm_per_unit)
            # Запас из справочника материала (в единицах измерения)
            reserve = Decimal(material.stock_reserve_qty or 0)
            
            if material.id in materials_needed:
                materials_needed[material.id]["qty_by_contract"] += qty_by_contract
            else:
                materials_needed[material.id] = {
                    "material_code": material.code,
                    "material_name": material.name,
                    "unit": material.unit,
                    "unit_price": str(material.price),
                    "qty_by_contract": qty_by_contract,
                    "reserve": reserve,
                    "notes": f"По норме для: {work_line.work_type}",
                }
    
    data = [
        {
            "material_code": m["material_code"],
            "material_name": m["material_name"],
            "unit": m["unit"],
            "unit_price": m["unit_price"],
            # Итого = по договору + запас
            "quantity": str(math.ceil(float(m["qty_by_contract"] + m["reserve"]))),
            "qty_by_contract": str(math.ceil(float(m["qty_by_contract"]))),
            "reserve": str(math.ceil(float(m["reserve"]))),
            "notes": m["notes"],
        }
        for m in materials_needed.values()
    ]
    return JsonResponse({"materials": data})

@login_required
def supplier_document_materials_json(request: HttpRequest) -> JsonResponse:
    doc_id = request.GET.get("doc_id")
    if not doc_id:
        return JsonResponse({"materials": []})
    try:
        doc_id = int(doc_id)
    except (TypeError, ValueError):
        return JsonResponse({"materials": []})

    from .models import SupplierDocumentLine
    from .services import INVOICE_DOC_TYPES

    doc = SupplierDocument.objects.select_related("request", "supplier").filter(pk=doc_id).first()
    if not doc or not doc.request:
        return JsonResponse({"materials": []})

    # Индекс цен из счёта по той же заявке
    price_index: dict[str, str] = {}
    invoice = SupplierDocument.objects.filter(
        request=doc.request,
        supplier=doc.supplier,
        doc_type__in=INVOICE_DOC_TYPES,
    ).order_by("-doc_date", "-id").first()
    if invoice:
        for sdl in SupplierDocumentLine.objects.select_related("material").filter(document=invoice):
            if sdl.unit_price:
                price_index[sdl.material.code] = str(sdl.unit_price)

    # Индекс примечаний из строк заявки
    notes_index: dict[str, str] = {}
    if doc.request:
        for req_line in doc.request.lines.select_related("material").all():
            if req_line.notes:
                notes_index[req_line.material.code] = req_line.notes

    # Берём строки из накладной если есть, иначе из заявки
    supplier_lines = list(SupplierDocumentLine.objects.select_related("material").filter(document=doc))
    if supplier_lines:
        data = [
            {
                "material_code": line.material.code,
                "material_name": line.material.name,
                "unit": line.material.unit,
                "quantity": str(line.quantity),
                "unit_price": price_index.get(line.material.code) or str(line.unit_price or "0"),
                "notes": line.notes or notes_index.get(line.material.code, ""),
            }
            for line in supplier_lines
        ]
    else:
        data = [
            {
                "material_code": line.material.code,
                "material_name": line.material.name,
                "unit": line.material.unit,
                "quantity": str(line.quantity),
                "unit_price": price_index.get(line.material.code) or str(line.unit_price or "0"),
                "notes": line.notes or notes_index.get(line.material.code, ""),
            }
            for line in doc.request.lines.select_related("material").all()
        ]

    return JsonResponse({"materials": data})

@login_required
def analytics(request: HttpRequest) -> HttpResponse:
    from datetime import date as date_type
    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth
    from .models import StockIssueLine, WorkScheduleLine

    from .services import work_volume_forecast
    forecast_date_from = request.GET.get("forecast_from")
    forecast_date_to = request.GET.get("forecast_to")
    forecasts = work_volume_forecast(
        date_from=forecast_date_from,
        date_to=forecast_date_to,
    )

    schedule_control = []
    lines = WorkScheduleLine.objects.select_related("schedule__contract").filter(
        schedule__contract__isnull=False,
        start_date__isnull=False,
        end_date__isnull=False,
    ).order_by("schedule__contract__number", "work_type", "order")

    for line in lines:
        actual_start = line.actual_start
        actual_end = line.actual_date

        deviation = None
        status = "Не начат"
        status_class = "neutral"

        if actual_end and line.end_date:
            deviation = (actual_end - line.end_date).days
            if deviation > 0:
                status = f"Задержка {deviation} дн."
                status_class = "danger"
            elif deviation < 0:
                status = f"Опережение {abs(deviation)} дн."
                status_class = "success"
            else:
                status = "В срок"
                status_class = "success"
        elif actual_start:
            status = "В работе"
            status_class = "warning"
        elif line.end_date and line.end_date < date_type.today():
            status = "Просрочен"
            status_class = "danger"

        schedule_control.append({
            "contract": line.schedule.contract.number,
            "work_type": line.work_type,
            "stage": line.stage,
            "plan_start": line.start_date.strftime("%d.%m.%Y") if line.start_date else "",
            "plan_end": line.end_date.strftime("%d.%m.%Y") if line.end_date else "",
            "actual_start": actual_start.strftime("%d.%m.%Y") if actual_start else "",
            "actual_end": actual_end.strftime("%d.%m.%Y") if actual_end else "",
            "deviation": deviation,
            "status": status,
            "status_class": status_class,
        })

    status_data = list(
        filter_queryset_for_user(request.user, DocumentRecord.objects.all())
        .values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )
    status_labels = [dict(DocumentStatus.choices).get(s["status"], s["status"]) for s in status_data]

    receipt_by_month = list(
        StockReceipt.objects
        .annotate(month=TruncMonth("receipt_date"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
        .filter(month__isnull=False)[:6]
    )

    top_materials = list(
        StockIssueLine.objects
        .values("material__name")
        .annotate(total=Sum("quantity"))
        .order_by("-total")[:5]
    )

    context = {
        "title": "Аналитика",
        "chart_status_labels": json.dumps(status_labels, ensure_ascii=False),
        "chart_status_data": json.dumps([s["count"] for s in status_data]),
        "chart_receipt_labels": json.dumps([r["month"].strftime("%b %Y") if r["month"] else "" for r in receipt_by_month], ensure_ascii=False),
        "chart_receipt_data": json.dumps([r["count"] for r in receipt_by_month]),
        "chart_material_labels": json.dumps([m["material__name"] for m in top_materials], ensure_ascii=False),
        "chart_material_data": json.dumps([float(m["total"]) for m in top_materials]),
        "forecasts": forecasts,
        "forecast_labels": json.dumps([f["work_type"] for f in forecasts], ensure_ascii=False),
        "forecast_avg": json.dumps([f["avg_actual"] for f in forecasts]),
        "forecast_next": json.dumps([f["forecast"] for f in forecasts]),
        "schedule_control": schedule_control,
        "user_role": getattr(request.user, "role", ""),
    }
    return _render(request, "core/analytics.html", context)

@login_required
def contract_dates_json(request: HttpRequest) -> JsonResponse:
    contract_id = request.GET.get("contract_id")
    if not contract_id:
        return JsonResponse({"start_date": "", "end_date": ""})
    try:
        contract_id = int(contract_id)
    except (TypeError, ValueError):
        return JsonResponse({"start_date": "", "end_date": ""})
    contract = SMRContract.objects.filter(pk=contract_id).first()
    if not contract:
        return JsonResponse({"start_date": "", "end_date": ""})
    return JsonResponse({
        "start_date": contract.start_date.strftime("%Y-%m-%d") if contract.start_date else "",
        "end_date": contract.end_date.strftime("%Y-%m-%d") if contract.end_date else "",
    })

@login_required
def work_stages_json(request: HttpRequest) -> JsonResponse:
    from .models import WorkStage
    work_type = request.GET.get("work_type", "").strip()
    if not work_type:
        return JsonResponse({"stages": []})
    stages = WorkStage.objects.filter(work_type__iexact=work_type).order_by("order", "id")
    return JsonResponse({
        "stages": [{"stage_name": s.stage_name, "order": s.order} for s in stages]
    })

@login_required
def schedule_stage_dates_json(request: HttpRequest) -> JsonResponse:
    contract_id = request.GET.get("contract_id")
    work_type = request.GET.get("work_type", "").strip()
    stage = request.GET.get("stage", "").strip()
    if not contract_id or not work_type or not stage:
        return JsonResponse({"start_date": "", "end_date": ""})
    try:
        contract_id = int(contract_id)
    except (TypeError, ValueError):
        return JsonResponse({"start_date": "", "end_date": ""})
    
    line = WorkScheduleLine.objects.filter(
        schedule__contract_id=contract_id,
        work_type__iexact=work_type,
        stage__iexact=stage,
        #schedule__status=DocumentStatus.ACCEPTED,
    ).first()
    
    if not line:
        return JsonResponse({"start_date": "", "end_date": ""})
    
    return JsonResponse({
        "start_date": line.start_date.strftime("%Y-%m-%d") if line.start_date else "",
        "end_date": line.end_date.strftime("%Y-%m-%d") if line.end_date else "",
    })
@login_required
def procurement_request_materials_json(request: HttpRequest) -> JsonResponse:
    request_id = request.GET.get("request_id")
    if not request_id:
        return JsonResponse({"materials": []})
    try:
        request_id = int(request_id)
    except (TypeError, ValueError):
        return JsonResponse({"materials": []})
    
    req = ProcurementRequest.objects.filter(pk=request_id).first()
    if not req:
        return JsonResponse({"materials": []})
    
    lines = req.lines.select_related("material").all()
    data = [
        {
            "material_code": line.material.code,
            "material_name": line.material.name,
            "unit": line.material.unit,
            "quantity": str(line.quantity),
            "unit_price": str(line.unit_price),
        }
        for line in lines
    ]
    return JsonResponse({"materials": data})

@login_required
def site_request_materials_json(request: HttpRequest) -> JsonResponse:
    request_id = request.GET.get("request_id")
    if not request_id:
        return JsonResponse({"materials": []})
    req = SiteMaterialRequest.objects.filter(pk=request_id).first()
    if not req:
        return JsonResponse({"materials": []})

    from .models import SupplierDocumentLine
    from .services import INVOICE_DOC_TYPES

    # Ищем счёт по заявке на закупку, которая связана с этой заявкой участка
    price_index: dict[str, str] = {}
    procurement_req = ProcurementRequest.objects.filter(
        site_request=req
    ).order_by("-request_date", "-id").first()
    if procurement_req:
        invoice = SupplierDocument.objects.filter(
            request=procurement_req,
            doc_type__in=INVOICE_DOC_TYPES,
        ).order_by("-doc_date", "-id").first()
        if invoice:
            for sdl in SupplierDocumentLine.objects.select_related("material").filter(document=invoice):
                if sdl.unit_price:
                    price_index[sdl.material.code] = str(sdl.unit_price)

    lines = req.lines.select_related("material").all()
    data = [
        {
            "material_code": line.material.code,
            "material_name": line.material.name,
            "unit": line.material.unit,
            "qty_by_contract": str(line.quantity - line.reserve_qty),
            "reserve": str(line.reserve_qty),
            "quantity": str(line.quantity),
            "unit_price": price_index.get(line.material.code) or str(line.unit_price or "0"),
            "notes": line.notes or "",
        }
        for line in lines
    ]
    return JsonResponse({"materials": data})

@login_required
def site_requests_by_site_json(request: HttpRequest) -> JsonResponse:
    site_name = request.GET.get("site_name", "").strip()
    if not site_name:
        return JsonResponse({"requests": []})

    # Заявки участка которые уже использованы в отпусках на утверждении или выше
    busy_request_ids = StockIssue.objects.filter(
        status__in=[
            DocumentStatus.APPROVAL,
            DocumentStatus.APPROVED,
            DocumentStatus.SENT_ACCOUNTING,
            DocumentStatus.ACCEPTED,
        ]
    ).exclude(site_request=None).values_list("site_request_id", flat=True)

    qs = SiteMaterialRequest.objects.filter(
        status__in=[DocumentStatus.ACCEPTED],
        site_name__iexact=site_name,
    ).exclude(id__in=busy_request_ids).order_by("-request_date")

    return JsonResponse({
        "requests": [{"id": r.pk, "label": str(r)} for r in qs]
    })
@login_required
def invoice_prices_by_request_json(request: HttpRequest) -> JsonResponse:
    request_id = request.GET.get("request_id")
    if not request_id:
        return JsonResponse({"prices": {}, "vat_rate": ""})
    try:
        request_id = int(request_id)
    except (TypeError, ValueError):
        return JsonResponse({"prices": {}, "vat_rate": ""})

    from .models import SupplierDocumentLine
    from .services import INVOICE_DOC_TYPES

    invoice = SupplierDocument.objects.filter(
        request_id=request_id,
        doc_type__in=INVOICE_DOC_TYPES,
    ).order_by("-doc_date", "-id").first()

    if not invoice:
        return JsonResponse({"prices": {}, "vat_rate": ""})

    prices = {}
    for line in SupplierDocumentLine.objects.select_related("material").filter(document=invoice):
        if line.unit_price:
            prices[line.material.code] = str(line.unit_price)

    return JsonResponse({
        "prices": prices,
        "vat_rate": str(invoice.vat_rate) if invoice.vat_rate else "",
    })
@login_required
def site_manager_by_site_json(request: HttpRequest) -> JsonResponse:
    site_name = request.GET.get("site_name", "").strip()
    if not site_name:
        return JsonResponse({"user_id": "", "user_name": ""})
    manager = User.objects.filter(
        role=RoleChoices.SITE_MANAGER,
        site_name__iexact=site_name,
        is_active=True,
    ).first()
    if not manager:
        return JsonResponse({"user_id": "", "user_name": ""})
    return JsonResponse({
        "user_id": manager.pk,
        "user_name": manager.full_name_or_username,
    })
@login_required
def invoice_prices_by_site_request_json(request: HttpRequest) -> JsonResponse:
    request_id = request.GET.get("request_id")
    if not request_id:
        return JsonResponse({"prices": {}})
    try:
        request_id = int(request_id)
    except (TypeError, ValueError):
        return JsonResponse({"prices": {}})

    from .models import SupplierDocumentLine
    from .services import INVOICE_DOC_TYPES

    site_req = SiteMaterialRequest.objects.filter(pk=request_id).first()
    if not site_req:
        return JsonResponse({"prices": {}})

    procurement_req = ProcurementRequest.objects.filter(
        site_request=site_req
    ).order_by("-request_date", "-id").first()
    if not procurement_req:
        return JsonResponse({"prices": {}})

    invoice = SupplierDocument.objects.filter(
        request=procurement_req,
        doc_type__in=INVOICE_DOC_TYPES,
        status__in=[
            DocumentStatus.APPROVED,
            DocumentStatus.ACCEPTED,
            DocumentStatus.SENT_ACCOUNTING,
        ],
    ).order_by("-doc_date", "-id").first()
    if not invoice:
        return JsonResponse({"prices": {}})

    prices = {}
    for line in SupplierDocumentLine.objects.select_related("material").filter(document=invoice):
        if line.unit_price:
            prices[line.material.code] = str(line.unit_price)

    return JsonResponse({"prices": prices})
@login_required
def contract_details_json(request: HttpRequest) -> JsonResponse:
    contract_id = request.GET.get("contract_id")
    if not contract_id:
        return JsonResponse({})
    try:
        contract_id = int(contract_id)
    except (TypeError, ValueError):
        return JsonResponse({})
    contract = SMRContract.objects.select_related("object").filter(pk=contract_id).first()
    if not contract:
        return JsonResponse({})
    return JsonResponse({
        "subject": contract.subject or "",
        "planned_volume": str(contract.planned_volume) if contract.planned_volume else "",
        "volume_unit": contract.volume_unit or "",
        "amount": str(contract.amount) if contract.amount else "",
        "object_name": contract.object.name if contract.object else "",
        "customer_name": contract.resolved_customer_name() or "",
        "work_type": contract.work_type or "",
    })

@login_required
def site_request_contract_json(request: HttpRequest) -> JsonResponse:
    request_id = request.GET.get("request_id")
    if not request_id:
        return JsonResponse({"contract_id": ""})
    req = SiteMaterialRequest.objects.filter(pk=request_id).first()
    if not req or not req.contract_id:
        return JsonResponse({"contract_id": ""})
    return JsonResponse({"contract_id": req.contract_id})