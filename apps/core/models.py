from __future__ import annotations

import calendar
from datetime import date

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from decimal import Decimal


def _add_months(base_date: date, months: int) -> date:
    if months <= 0:
        return base_date
    month_offset = base_date.month - 1 + months
    year = base_date.year + month_offset // 12
    month = month_offset % 12 + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class RoleChoices(models.TextChoices):
    DIRECTOR = "director", "Начальник монтажного объекта"
    PROCUREMENT = "procurement", "Снабженец"
    WAREHOUSE = "warehouse", "Кладовщик"
    SITE_MANAGER = "site_manager", "Начальник участка"
    ACCOUNTING = "accounting", "Бухгалтерия"
    SUPPLIER = "supplier", "Поставщик"
    ADMIN = "admin", "Администратор"


class DocumentStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    APPROVAL = "approval", "На утверждении"
    APPROVED = "approved", "Утвержден"
    SENT_ACCOUNTING = "sent_accounting", "Отправлен в бухгалтерию"
    ACCEPTED = "accepted", "Принят"
    REWORK = "rework", "Возвращен на доработку"
    UPLOADED = "uploaded", "Загружен поставщиком"
    SUPPLY_CONFIRMED = "supply_confirmed", "Подтверждение поставки"


class NotificationType(models.TextChoices):
    DOCUMENT_CREATED = "document_created", "Создан документ"
    STATUS_CHANGED = "status_changed", "Изменен статус"
    ACTION_REQUIRED = "action_required", "Требуется действие"
    LOW_STOCK = "low_stock", "Низкий остаток"


class WriteOffTemplateVariant(models.TextChoices):
    CONTRACT = "contract", "По договору СМР"
    PRODUCTION_ECONOMIC = "production_economic", "На производственно-хозяйственные нужды"


class DocumentType(TimeStampedModel):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128, unique=True)
    prefix = models.CharField(max_length=16, unique=True)
    is_active = models.BooleanField(default=True)
    available_for_upload = models.BooleanField(default=False)
    available_for_generation = models.BooleanField(default=False)
    requires_items = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Supplier(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    tax_id = models.CharField(max_length=32, blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=64, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    requisites = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def requisites_text(self) -> str:
        explicit = (self.requisites or "").strip()
        if explicit:
            return explicit

        parts: list[str] = []
        if self.tax_id:
            parts.append(f"ИНН {self.tax_id}")
        if self.address:
            parts.append(self.address.strip())
        if self.phone:
            parts.append(f"Тел.: {self.phone}")
        if self.email:
            parts.append(f"Эл. почта: {self.email}")
        return "; ".join(part for part in parts if part)


class User(AbstractUser):
    role = models.CharField(max_length=32, choices=RoleChoices.choices, default=RoleChoices.SITE_MANAGER)
    site_name = models.CharField(max_length=255, blank=True)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="users")

    class Meta:
        ordering = ["last_name", "first_name", "username"]

    @property
    def full_name_or_username(self) -> str:
        # Ожидаем: first_name = "Имя Отчество", last_name = "Фамилия"
        # Возвращаем: "Фамилия Имя Отчество" для правильного сокращения
        first = (self.first_name or "").strip()
        last = (self.last_name or "").strip()
        if last and first:
            return f"{last} {first}"
        return last or first or self.username

    @property
    def role_label(self) -> str:
        return dict(RoleChoices.choices).get(self.role, self.role)


class Material(TimeStampedModel):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    unit = models.CharField(max_length=32)
    price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    stock_reserve_qty = models.DecimalField(
        max_digits=14, decimal_places=3, default=0,
        verbose_name="Норма остатка (в ед. измерения)"
    )
    category = models.CharField(max_length=128, blank=True)
    is_ppe = models.BooleanField(default=False)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class ConstructionObject(TimeStampedModel):
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    customer_name = models.CharField(max_length=255, blank=True)
    customer_name_short = models.CharField(max_length=255, blank=True, verbose_name="Краткое наименование заказчика")
    customer_requisites = models.TextField(blank=True)
    customer_legal_address = models.CharField(max_length=512, blank=True, verbose_name="Юридический адрес заказчика")
    customer_tax_id = models.CharField(max_length=32, blank=True, verbose_name="ИНН заказчика")
    customer_kpp = models.CharField(max_length=32, blank=True, verbose_name="КПП заказчика")
    customer_ogrn = models.CharField(max_length=32, blank=True, verbose_name="ОГРН заказчика")
    customer_bank = models.CharField(max_length=255, blank=True, verbose_name="Банк заказчика")
    customer_bik = models.CharField(max_length=32, blank=True, verbose_name="БИК заказчика")
    customer_account = models.CharField(max_length=64, blank=True, verbose_name="Расчётный счёт заказчика")
    customer_corr_account = models.CharField(max_length=64, blank=True, verbose_name="Корреспондентский счёт")
    customer_okpo = models.CharField(max_length=32, blank=True, verbose_name="ОКПО заказчика")
    description = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Worker(TimeStampedModel):
    full_name = models.CharField(max_length=255)
    employee_number = models.CharField(max_length=64, unique=True)
    site_name = models.CharField(max_length=255, blank=True)
    position = models.CharField(max_length=255, blank=True)
    hire_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.employee_number})"


class MaterialNorm(TimeStampedModel):
    work_type = models.CharField(max_length=255)
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="norms")
    norm_per_unit = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=32, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["work_type", "material__code"]
        constraints = [models.UniqueConstraint(fields=["work_type", "material"], name="uq_material_norm_work_type")]

    def __str__(self) -> str:
        return f"{self.work_type}: {self.material.code}"


class SMRContract(TimeStampedModel):
    number = models.CharField(max_length=128, unique=True)
    contract_date = models.DateField()
    object = models.ForeignKey(ConstructionObject, null=True, blank=True, on_delete=models.SET_NULL, related_name="contracts")
    customer_name = models.CharField(max_length=255)
    customer_requisites = models.TextField(blank=True)
    contractor_name = models.CharField(max_length=255, blank=True)
    contractor_requisites = models.TextField(blank=True)
    subject = models.CharField(max_length=255)
    work_type = models.CharField(max_length=255, blank=True)
    planned_volume = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    volume_unit = models.CharField(max_length=64, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=20)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    work_object_description = models.TextField(blank=True, verbose_name="Описание объекта")
    work_basis_text = models.CharField(max_length=255, blank=True, verbose_name="Основание (тип документа)")
    work_basis_number = models.CharField(max_length=128, blank=True, verbose_name="Номер основания")
    work_basis_date = models.DateField(null=True, blank=True, verbose_name="Дата основания")
    work_goal = models.CharField(max_length=255, blank=True, verbose_name="Цель работ")
    work_conditions = models.TextField(blank=True, verbose_name="Условия проведения работ")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_contracts")
    customer_signer_name = models.CharField(max_length=255, blank=True, verbose_name="ФИО подписанта заказчика")
    customer_signer_position = models.CharField(max_length=255, blank=True, verbose_name="Должность подписанта заказчика")
    customer_auth_doc = models.CharField(max_length=255, blank=True, default="доверенности", verbose_name="Документ полномочий заказчика")
    customer_signer_name_genitive = models.CharField(max_length=255, blank=True, verbose_name="ФИО подписанта заказчика (родительный падеж)")
    customer_signer_position_genitive = models.CharField(max_length=255, blank=True, verbose_name="Должность подписанта заказчика (родительный падеж)")
    site_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="responsible_contracts",
        verbose_name="Ответственный начальник участка",
    )
    attachment = models.FileField(upload_to="smr_contracts/", null=True, blank=True, verbose_name="Локальная смета (Excel/PDF)")
    scan_file = models.FileField(upload_to="smr_contract_scans/", null=True, blank=True, verbose_name="Скан подписанного договора")
    class Meta:
        ordering = ["-contract_date", "-id"]

    def __str__(self) -> str:
        object_name = self.object.name if self.object else ""
        return f"{self.number} — {self.subject} ({object_name})"

    def resolved_customer_name(self) -> str:
        value = (self.customer_name or "").strip()
        if value:
            return value
        if self.object:
            return (self.object.customer_name or "").strip()
        return ""

    def resolved_customer_requisites(self) -> str:
        value = (self.customer_requisites or "").strip()
        if value:
            return value
        if self.object:
            return (self.object.customer_requisites or "").strip()
        return ""

    def resolved_contractor_name(self) -> str:
        value = (self.contractor_name or "").strip()
        if value:
            return value
        profile = getattr(settings, "ORGANIZATION_PROFILE", {}) or {}
        return str(profile.get("name", "")).strip()

    def resolved_contractor_requisites(self) -> str:
        value = (self.contractor_requisites or "").strip()
        if value:
            return value

        profile = getattr(settings, "ORGANIZATION_PROFILE", {}) or {}
        explicit = str(profile.get("requisites", "")).strip()
        if explicit:
            return explicit

        parts: list[str] = []
        if profile.get("tax_id"):
            parts.append(f"ИНН {profile['tax_id']}")
        if profile.get("kpp"):
            parts.append(f"КПП {profile['kpp']}")
        if profile.get("ogrn"):
            parts.append(f"ОГРН {profile['ogrn']}")
        if profile.get("address"):
            parts.append(str(profile["address"]).strip())
        if profile.get("bank_details"):
            parts.append(str(profile["bank_details"]).strip())
        return "; ".join(part for part in parts if part)

class SMRContractWorkLine(models.Model):
    contract = models.ForeignKey(SMRContract, on_delete=models.CASCADE, related_name="work_lines")
    work_type = models.CharField(max_length=255, verbose_name="Вид работ")
    unit = models.CharField(max_length=64, verbose_name="Ед. изм.")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, verbose_name="Количество")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    @property
    def total(self):
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))

class SupplyContract(TimeStampedModel):
    number = models.CharField(max_length=128, unique=True)
    contract_date = models.DateField()
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="supply_contracts")
    related_smr_contract = models.ForeignKey(SMRContract, null=True, blank=True, on_delete=models.SET_NULL, related_name="supply_contracts")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    terms = models.TextField(blank=True)
    attachment = models.FileField(upload_to="supply_contracts/", null=True, blank=True, verbose_name="Скан договора")
    class Meta:
        ordering = ["-contract_date", "-id"]

    def __str__(self) -> str:
        return self.number


class ProcurementRequest(TimeStampedModel):
    number = models.CharField(max_length=128, unique=True)
    request_date = models.DateField()
    site_name = models.CharField(max_length=255)
    contract = models.ForeignKey(SMRContract, null=True, blank=True, on_delete=models.SET_NULL, related_name="procurement_requests")
    site_request = models.ForeignKey(
        "SiteMaterialRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="procurement_requests",
    )
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="procurement_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="procurement_requests")
    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to="procurement_requests/", null=True, blank=True, verbose_name="Скан документа")

    class Meta:
        ordering = ["-request_date", "-id"]

    def __str__(self) -> str:
        return self.number


class ProcurementRequestLine(models.Model):
    request = models.ForeignKey(ProcurementRequest, on_delete=models.CASCADE, related_name="lines")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="procurement_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["material__code"]


class SiteMaterialRequest(TimeStampedModel):
    number = models.CharField(max_length=128, unique=True)
    request_date = models.DateField()
    site_name = models.CharField(max_length=255)
    contract = models.ForeignKey(SMRContract, null=True, blank=True, on_delete=models.SET_NULL, related_name="site_material_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="site_material_requests")
    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to="site_requests/", null=True, blank=True, verbose_name="Скан документа")

    class Meta:
        ordering = ["-request_date", "-id"]

    def __str__(self) -> str:
        return self.number


class SiteMaterialRequestLine(models.Model):
    request = models.ForeignKey(SiteMaterialRequest, on_delete=models.CASCADE, related_name="lines")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="site_request_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.CharField(max_length=255, blank=True)
    reserve_qty = models.DecimalField(max_digits=14, decimal_places=3, default=0, verbose_name="Запас")

    class Meta:
        ordering = ["material__code"]


class SupplierDocument(TimeStampedModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="documents")
    request = models.ForeignKey(ProcurementRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="supplier_documents")
    supply_contract = models.ForeignKey(SupplyContract, null=True, blank=True, on_delete=models.SET_NULL, related_name="supplier_documents")
    doc_type = models.CharField(max_length=64)
    doc_number = models.CharField(max_length=128)
    doc_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_supplier_documents")
    attachment = models.FileField(upload_to="supplier_docs/", blank=True, null=True)
    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.UPLOADED)
    notes = models.TextField(blank=True)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=20, verbose_name="Ставка НДС, %")
    payment_order = models.FileField(
    upload_to="payment_orders/",
    null=True, blank=True,
    verbose_name="Платёжное поручение",
    )
    class Meta:
        ordering = ["-doc_date", "-id"]

    def __str__(self) -> str:
        return f"{self.doc_type} {self.doc_number} от {self.doc_date} ({self.supplier.name})"


class PrimaryDocument(TimeStampedModel):
    document_type = models.ForeignKey(DocumentType, on_delete=models.PROTECT, related_name="primary_documents")
    number = models.CharField(max_length=128, unique=True)
    doc_date = models.DateField()
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="primary_documents")
    procurement_request = models.ForeignKey(ProcurementRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="primary_documents")
    supply_contract = models.ForeignKey(SupplyContract, null=True, blank=True, on_delete=models.SET_NULL, related_name="primary_documents")
    stock_receipt = models.ForeignKey("StockReceipt", null=True, blank=True, on_delete=models.SET_NULL, related_name="primary_documents")
    site_name = models.CharField(max_length=255, blank=True)
    basis_reference = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="primary_documents")
    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to="primary_documents/", null=True, blank=True, verbose_name="Скан документа")

    class Meta:
        ordering = ["-doc_date", "-id"]

    def __str__(self) -> str:
        return f"{self.document_type.name} {self.number}"


class PrimaryDocumentLine(models.Model):
    document = models.ForeignKey(PrimaryDocument, on_delete=models.CASCADE, related_name="lines")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="primary_document_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["material__code"]


class StockReceipt(TimeStampedModel):
    number = models.CharField(max_length=128, unique=True)
    receipt_date = models.DateField()
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="stock_receipts")
    supplier_document = models.ForeignKey(SupplierDocument, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_receipts")
    primary_document = models.ForeignKey(PrimaryDocument, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_receipts")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stock_receipts")
    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to="stock_receipts/", null=True, blank=True, verbose_name="Скан документа")
    
    class Meta:
        ordering = ["-receipt_date", "-id"]

    def __str__(self):
        return f"Приходный ордер {self.number} от {self.receipt_date} ({self.supplier.name})"


class StockReceiptLine(models.Model):
    receipt = models.ForeignKey(StockReceipt, on_delete=models.CASCADE, related_name="lines")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="receipt_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["material__code"]


class StockIssue(TimeStampedModel):
    number = models.CharField(max_length=128, unique=True)
    issue_date = models.DateField()
    site_name = models.CharField(max_length=255)
    contract = models.ForeignKey(SMRContract, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_issues")
    site_request = models.ForeignKey(SiteMaterialRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_issues")
    stock_receipt = models.ForeignKey(StockReceipt, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_issues")
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stock_issues")
    received_by_name = models.CharField(max_length=255)
    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to="stock_issues/", null=True, blank=True, verbose_name="Скан документа")
   
    class Meta:
        ordering = ["-issue_date", "-id"]

    def __str__(self) -> str:
        return self.number


class StockIssueLine(models.Model):
    issue = models.ForeignKey(StockIssue, on_delete=models.CASCADE, related_name="lines")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="issue_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["material__code"]


class WorkLog(TimeStampedModel):
    site_name = models.CharField(max_length=255)
    contract = models.ForeignKey(SMRContract, null=True, blank=True, on_delete=models.SET_NULL, related_name="work_logs")
    work_type = models.CharField(max_length=255, verbose_name="Вид работ", default="")
    stage = models.CharField(max_length=255, blank=True, verbose_name="Этап", default="")
    planned_volume = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    actual_volume = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    volume_unit = models.CharField(max_length=64, blank=True)
    plan_date = models.DateField(null=True, blank=True)
    actual_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=64, default="Запланировано")
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="work_logs")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    class Meta:
        ordering = ["-actual_date", "-plan_date", "-id"]

    @property
    def status_label(self) -> str:
        status_map = {
            "planned": "Запланировано",
            "delayed": "С задержкой",
        }
        return status_map.get(self.status, self.status)


class WorkAcceptanceAct(TimeStampedModel):
    number = models.CharField(max_length=128, unique=True)
    act_date = models.DateField()
    contract = models.ForeignKey(SMRContract, on_delete=models.PROTECT, related_name="acceptance_acts")
    site_name = models.CharField(max_length=255)
    work_description = models.TextField(blank=True)
    accepted_volume = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    volume_unit = models.CharField(max_length=64, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="work_acceptance_acts")
    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to="work_acceptances/", null=True, blank=True, verbose_name="Скан документа")

    class Meta:
        ordering = ["-act_date", "-id"]

    def __str__(self) -> str:
        return self.number


class WriteOffAct(TimeStampedModel):
    number = models.CharField(max_length=128, unique=True)
    act_date = models.DateField()
    contract = models.ForeignKey(SMRContract, null=True, blank=True, on_delete=models.PROTECT, related_name="write_off_acts")
    template_variant = models.CharField(
        max_length=32,
        choices=WriteOffTemplateVariant.choices,
        default=WriteOffTemplateVariant.CONTRACT,
    )
    site_name = models.CharField(max_length=255)
    work_type = models.CharField(max_length=255)
    work_volume = models.DecimalField(max_digits=14, decimal_places=3)
    volume_unit = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="write_off_acts")
    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to="writeoffs/", null=True, blank=True, verbose_name="Скан документа")

    class Meta:
        ordering = ["-act_date", "-id"]

    def __str__(self) -> str:
        return self.number


class WriteOffLine(models.Model):
    act = models.ForeignKey(WriteOffAct, on_delete=models.CASCADE, related_name="lines")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="writeoff_lines")
    norm_per_unit = models.DecimalField(max_digits=14, decimal_places=4)
    calculated_quantity = models.DecimalField(max_digits=14, decimal_places=3)
    actual_quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["material__code"]


class PPEIssuance(TimeStampedModel):
    number = models.CharField(max_length=128, unique=True)
    issue_date = models.DateField()
    site_name = models.CharField(max_length=255)
    season = models.CharField(max_length=64, blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ppe_issuances")
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="confirmed_ppe_issuances",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to="ppe_issuances/", null=True, blank=True, verbose_name="Скан документа")

    class Meta:
        ordering = ["-issue_date", "-id"]

    def __str__(self) -> str:
        return self.number


class PPEIssuanceLine(models.Model):
    REPLACEMENT_WARNING_DAYS = 30
    REPLACEMENT_STATUS_OK = "ok"
    REPLACEMENT_STATUS_EXPIRING = "expiring_soon"
    REPLACEMENT_STATUS_EXPIRED = "expired"

    issuance = models.ForeignKey(PPEIssuance, on_delete=models.CASCADE, related_name="lines")
    worker = models.ForeignKey(Worker, on_delete=models.PROTECT, related_name="ppe_lines")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="ppe_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    service_life_months = models.PositiveIntegerField(default=0)
    issue_start_date = models.DateField(null=True, blank=True)
    clothing_size = models.CharField(max_length=64, blank=True)
    shoe_size = models.CharField(max_length=64, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["worker__full_name", "material__code"]

    @property
    def replacement_start_date(self) -> date | None:
        return self.issue_start_date or getattr(self.issuance, "issue_date", None)

    @property
    def replacement_due_date(self) -> date | None:
        start_date = self.replacement_start_date
        if not start_date or self.service_life_months <= 0:
            return None
        return _add_months(start_date, self.service_life_months)

    @property
    def days_until_replacement(self) -> int | None:
        due_date = self.replacement_due_date
        if not due_date:
            return None
        return (due_date - timezone.localdate()).days

    @property
    def replacement_status(self) -> str:
        days_left = self.days_until_replacement
        if days_left is None:
            return self.REPLACEMENT_STATUS_OK
        if days_left < 0:
            return self.REPLACEMENT_STATUS_EXPIRED
        if days_left <= self.REPLACEMENT_WARNING_DAYS:
            return self.REPLACEMENT_STATUS_EXPIRING
        return self.REPLACEMENT_STATUS_OK

    @property
    def replacement_status_label(self) -> str:
        label_map = {
            self.REPLACEMENT_STATUS_OK: "В норме",
            self.REPLACEMENT_STATUS_EXPIRING: "Истекает срок",
            self.REPLACEMENT_STATUS_EXPIRED: "Срок истек",
        }
        return label_map.get(self.replacement_status, self.replacement_status)

    @property
    def needs_replacement(self) -> bool:
        return self.replacement_status in {self.REPLACEMENT_STATUS_EXPIRING, self.REPLACEMENT_STATUS_EXPIRED}

    @property
    def replacement_warning(self) -> str:
        days_left = self.days_until_replacement
        if days_left is None:
            return ""
        if days_left < 0:
            return f"Просрочено на {abs(days_left)} дн."
        if days_left <= self.REPLACEMENT_WARNING_DAYS:
            return f"Истекает через {days_left} дн."
        return ""


class StockMovement(TimeStampedModel):
    movement_date = models.DateField()
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="movements")
    quantity_delta = models.DecimalField(max_digits=14, decimal_places=3)
    location_name = models.CharField(max_length=255)
    source_type = models.CharField(max_length=64)
    source_id = models.PositiveBigIntegerField()
    contract = models.ForeignKey(
        "SMRContract",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_movements",
        verbose_name="Договор СМР",
    )
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stock_movements")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-movement_date", "-id"]
        indexes = [
            models.Index(fields=["location_name", "movement_date"]),
            models.Index(fields=["source_type", "source_id"]),
        ]


class DocumentRecord(TimeStampedModel):
    entity_type = models.CharField(max_length=64)
    entity_id = models.PositiveBigIntegerField()
    doc_type = models.CharField(max_length=128)
    doc_number = models.CharField(max_length=128)
    doc_date = models.DateField()
    status = models.CharField(max_length=32, choices=DocumentStatus.choices)
    title = models.CharField(max_length=255)
    counterparty = models.CharField(max_length=255, blank=True)
    object_name = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="document_records")
    file_path = models.CharField(max_length=512, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    search_text = models.TextField(blank=True)

    class Meta:
        ordering = ["-doc_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["entity_type", "entity_id"], name="uq_document_record_entity")]
        indexes = [
            models.Index(fields=["doc_type", "doc_date"]),
            models.Index(fields=["status", "doc_date"]),
        ]


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=64, choices=NotificationType.choices)
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    entity_type = models.CharField(max_length=64, blank=True)
    entity_id = models.PositiveBigIntegerField(null=True, blank=True)
    document_record = models.ForeignKey(
        DocumentRecord,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "is_read", "created_at"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    def mark_read(self) -> None:
        if self.is_read:
            return
        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=["is_read", "read_at"])


class FormDraft(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="form_drafts")
    operation_slug = models.CharField(max_length=64)
    payload_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["user", "operation_slug"], name="uq_form_draft_user_slug")]


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries")
    action = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=64)
    entity_id = models.PositiveBigIntegerField(null=True, blank=True)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

class WorkSchedule(TimeStampedModel):
    number = models.CharField(max_length=128, unique=True)
    contract = models.ForeignKey(SMRContract, on_delete=models.PROTECT, related_name="work_schedules")
    site_name = models.CharField(max_length=255)
    period_start = models.DateField(verbose_name="Начало периода")
    period_end = models.DateField(verbose_name="Окончание периода")
    status = models.CharField(max_length=32, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="work_schedules")
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to="work_schedules/", null=True, blank=True, verbose_name="Скан графика")

    class Meta:
        ordering = ["-period_start", "-id"]

    def __str__(self) -> str:
        return self.number


class WorkScheduleLine(models.Model):
    schedule = models.ForeignKey(WorkSchedule, on_delete=models.CASCADE, related_name="lines")
    order = models.PositiveIntegerField(default=0)
    work_type = models.CharField(max_length=255, verbose_name="Вид работ")
    stage = models.CharField(max_length=255, blank=True, verbose_name="Этап")
    executor = models.CharField(max_length=255, blank=True, verbose_name="Исполнитель")
    start_date = models.DateField(verbose_name="Дата начала")
    end_date = models.DateField(verbose_name="Дата окончания")
    notes = models.CharField(max_length=255, blank=True)
    actual_date = models.DateField(null=True, blank=True, verbose_name="Фактическая дата выполнения")
    actual_start = models.DateField(null=True, blank=True, verbose_name="Фактическая дата начала")
    actual_date = models.DateField(null=True, blank=True, verbose_name="Фактическая дата окончания")
    actual_notes = models.CharField(max_length=500, blank=True, default="", verbose_name="Примечание по факту")

    class Meta:
        ordering = ["order", "id"]

class WorkStage(models.Model):
    work_type = models.CharField(max_length=255, verbose_name="Вид работ")
    stage_name = models.CharField(max_length=255, verbose_name="Наименование этапа")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        ordering = ["work_type", "order", "id"]
        verbose_name = "Этап работ"
        verbose_name_plural = "Этапы работ"

    def __str__(self) -> str:
        return f"{self.work_type} — {self.stage_name}"
    
class SupplierDocumentLine(models.Model):
    document = models.ForeignKey(SupplierDocument, on_delete=models.CASCADE, related_name="lines")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="supplier_document_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["material__code"]

class OrganizationProfile(models.Model):
    name = models.CharField(max_length=255, blank=True, verbose_name="Наименование организации")
    tax_id = models.CharField(max_length=32, blank=True, verbose_name="ИНН")
    kpp = models.CharField(max_length=32, blank=True, verbose_name="КПП")
    ogrn = models.CharField(max_length=32, blank=True, verbose_name="ОГРН")
    address = models.CharField(max_length=512, blank=True, verbose_name="Адрес")
    bank_name = models.CharField(max_length=255, blank=True, verbose_name="Банк")
    bik = models.CharField(max_length=32, blank=True, verbose_name="БИК")
    account = models.CharField(max_length=64, blank=True, verbose_name="Расчётный счёт")
    corr_account = models.CharField(max_length=64, blank=True, verbose_name="Корреспондентский счёт")
    okpo = models.CharField(max_length=32, blank=True, verbose_name="ОКПО")
    bank_details = models.TextField(blank=True, verbose_name="Банковские реквизиты (текстом)")
    requisites = models.TextField(blank=True, verbose_name="Реквизиты (текстом)")
    contractor_signer_name = models.CharField(max_length=255, blank=True, verbose_name="ФИО подписанта")
    contractor_signer_position = models.CharField(max_length=255, blank=True, verbose_name="Должность подписанта")
    contractor_signer_name_genitive = models.CharField(max_length=255, blank=True, verbose_name="ФИО подписанта (родительный падеж)")
    contractor_signer_position_genitive = models.CharField(max_length=255, blank=True, verbose_name="Должность подписанта (родительный падеж)")
    contractor_auth_doc = models.CharField(max_length=255, blank=True, verbose_name="Документ полномочий")

    class Meta:
        verbose_name = "Профиль организации"

    def __str__(self) -> str:
        return self.name or "Профиль организации"

    @classmethod
    def get(cls) -> "OrganizationProfile":
        instance = cls.objects.first()
        if not instance:
            # Создаём из settings.py если ещё нет в БД
            profile = getattr(settings, "ORGANIZATION_PROFILE", {}) or {}
            instance = cls.objects.create(
                name=profile.get("name", ""),
                tax_id=profile.get("tax_id", ""),
                kpp=profile.get("kpp", ""),
                ogrn=profile.get("ogrn", ""),
                address=profile.get("address", ""),
                bank_name=profile.get("bank_name", ""),
                bik=profile.get("bik", ""),
                account=profile.get("account", ""),
                corr_account=profile.get("corr_account", ""),
                okpo=profile.get("okpo", ""),
                bank_details=profile.get("bank_details", ""),
                requisites=profile.get("requisites", ""),
                contractor_signer_name=profile.get("contractor_signer_name", ""),
                contractor_signer_position=profile.get("contractor_signer_position", ""),
                contractor_signer_name_genitive=profile.get("contractor_signer_name_genitive", ""),
                contractor_signer_position_genitive=profile.get("contractor_signer_position_genitive", ""),
                contractor_auth_doc=profile.get("contractor_auth_doc", ""),
            )
        return instance