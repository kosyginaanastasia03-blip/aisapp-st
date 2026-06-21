from __future__ import annotations

from django import forms
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from .models import (
    DocumentRecord,
    ConstructionObject,
    DocumentStatus,
    DocumentType,
    Material,
    MaterialNorm,
    ProcurementRequest,
    RoleChoices,
    SiteMaterialRequest,
    SMRContract,
    SMRContractWorkLine,  
    PrimaryDocument,
    PPEIssuance,
    StockIssue,
    StockReceipt,
    Supplier,
    SupplierDocument,
    SupplyContract,
    WorkSchedule,
    WorkScheduleLine,
    User,
    Worker,
    WorkStage,
    WorkAcceptanceAct,
    WorkLog,
    WriteOffAct,
    WriteOffTemplateVariant,
    OrganizationProfile,
)
from .reporting import REPORT_CHOICES
from .services import parse_line_items, parse_ppe_lines


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%d")
        super().__init__(*args, **kwargs)


EMPTY_CHOICE_LABEL = "Не выбрано"


def _text_choices(values, *, empty_label: str | None = EMPTY_CHOICE_LABEL) -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = []
    if empty_label is not None:
        choices.append(("", empty_label))
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        choices.append((text, text))
    return choices


class BaseStyledForm:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            css_class = widget.attrs.get("class", "")
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = f"{css_class} checkbox-input".strip()
            else:
                widget.attrs["class"] = f"{css_class} form-input".strip()

            if getattr(field, "empty_label", None) == "---------":
                field.empty_label = EMPTY_CHOICE_LABEL
            if hasattr(field, "choices"):
                choices = list(field.choices)
                if choices and choices[0][1] == "---------":
                    field.choices = [(choices[0][0], EMPTY_CHOICE_LABEL), *choices[1:]]

        items_field = self.fields.get("items")
        if items_field and isinstance(items_field.widget, forms.HiddenInput):
            items_mode = items_field.widget.attrs.get("data-items-mode")
            if items_mode == "ppe-lines":
                items_field.help_text = "Заполните строки в таблице ниже: табельный номер, код материала, количество и срок службы."
            elif items_mode == "material-lines":
                if items_field.required:
                    items_field.help_text = "Заполните строки в таблице ниже. Наименование, единица и цена подставляются по коду материала."
                else:
                    items_field.help_text = (
                        "Заполните строки в таблице ниже. Если оставить поле пустым, позиции будут взяты из связанного документа."
                    )


class DateRangeValidationMixin:
    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")
        if date_from and date_to and date_to < date_from:
            self.add_error("date_to", "Дата окончания не может быть раньше даты начала.")
        return cleaned_data


WORKFLOW_ENTRY_STATUS_CHOICES = [
    (DocumentStatus.DRAFT, dict(DocumentStatus.choices)[DocumentStatus.DRAFT]),
    (DocumentStatus.APPROVAL, dict(DocumentStatus.choices)[DocumentStatus.APPROVAL]),
]

SUPPLIER_DOCUMENT_TYPE_FALLBACK = [
    ("Счет", "Счет"),
    ("Счет-фактура", "Счет-фактура"),
    ("Товарная накладная", "Товарная накладная"),
    ("Приходная накладная", "Приходная накладная"),
]


def _upload_document_type_choices() -> list[tuple[str, str]]:
    try:
        rows = list(
            DocumentType.objects.filter(is_active=True, available_for_upload=True)
            .order_by("name")
            .values_list("name", "name")
        )
    except Exception:
        rows = []
    return rows or SUPPLIER_DOCUMENT_TYPE_FALLBACK


class ProcurementRequestCreateForm(BaseStyledForm, forms.Form):
    number = forms.CharField(
        max_length=128, required=False, label="Номер",
        help_text="Если оставить пустым, номер будет сформирован автоматически (по участку).",
    )
    request_date = forms.DateField(widget=DateInput(), initial=timezone.localdate, label="Дата заявки")
    site_request = forms.ModelChoiceField(
        queryset=SiteMaterialRequest.objects.none(),
        required=False,
        label="Заявка участка",
        help_text="В списке только утверждённые заявки начальников участков.",
    )
    site_name = forms.CharField(max_length=255, required=False, label="Участок")
    contract = forms.ModelChoiceField(queryset=SMRContract.objects.order_by("-contract_date"), required=False, label="Договор СМР")
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.order_by("name"), required=False, label="Поставщик")
    items = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"data-items-mode": "procurement-lines"}),
        label="Позиции",
        help_text="Заполните позиции или выберите заявку участка. Цены подставит поставщик.",
    )

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)

        busy_site_request_ids = ProcurementRequest.objects.filter(
            status__in=[
                DocumentStatus.APPROVAL,
                DocumentStatus.APPROVED,
                DocumentStatus.SENT_ACCOUNTING,
                DocumentStatus.ACCEPTED,
            ]
        ).exclude(site_request=None)

        if instance and instance.pk:
            busy_site_request_ids = busy_site_request_ids.exclude(pk=instance.pk)

        busy_site_request_ids = busy_site_request_ids.values_list("site_request_id", flat=True)

        self.fields["site_request"].queryset = SiteMaterialRequest.objects.filter(
            status__in=[DocumentStatus.APPROVED, DocumentStatus.ACCEPTED, DocumentStatus.SENT_ACCOUNTING]
        ).exclude(id__in=busy_site_request_ids).order_by("-request_date")

    def clean_items(self):
        items = self.cleaned_data.get("items", "")
        if items:
            parse_line_items(items)
        return items
    def clean_number(self):
        number = (self.cleaned_data.get("number") or "").strip()
        if number and ProcurementRequest.objects.filter(number__iexact=number).exists():
            raise forms.ValidationError("Заявка с таким номером уже существует.")
        return number

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("items") and not cleaned_data.get("site_request"):
            raise forms.ValidationError("Заполните позиции или выберите заявку участка.")
        return cleaned_data


class SiteMaterialRequestCreateForm(BaseStyledForm, forms.Form):
    number = forms.CharField(
        max_length=128, required=False, label="Номер",
        help_text="Если оставить пустым, номер будет сформирован автоматически (по участку).",
    )
    request_date = forms.DateField(widget=DateInput(), initial=timezone.localdate, label="Дата заявки")
    site_name = forms.CharField(max_length=255, label="Участок")
    contract = forms.ModelChoiceField(
        queryset=SMRContract.objects.exclude(
            id__in=SiteMaterialRequest.objects.filter(
                status__in=[DocumentStatus.APPROVAL, DocumentStatus.APPROVED,
                            DocumentStatus.SENT_ACCOUNTING, DocumentStatus.ACCEPTED]
            ).exclude(contract=None).values_list("contract_id", flat=True)
        ).order_by("-contract_date"),
        required=False,
        label="Договор СМР"
    )
   
    items = forms.CharField(
        widget=forms.HiddenInput(attrs={"data-items-mode": "material-lines-no-price"}),
        label="Позиции",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and getattr(user, "role", None) == RoleChoices.SITE_MANAGER:
            site_name = getattr(user, "site_name", "") or ""
            self.fields["site_name"].initial = site_name

    def clean_items(self):
        items = self.cleaned_data["items"]
        parse_line_items(items)
        return items
    def clean_number(self):
        number = (self.cleaned_data.get("number") or "").strip()
        if number and SiteMaterialRequest.objects.filter(number__iexact=number).exists():
            raise forms.ValidationError("Заявка с таким номером уже существует.")
        return number


class SupplierDocumentUploadForm(BaseStyledForm, forms.Form):
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.order_by("name"), required=False, label="Поставщик")
    doc_type = forms.ChoiceField(choices=SUPPLIER_DOCUMENT_TYPE_FALLBACK, label="Тип документа")
    doc_number = forms.CharField(max_length=128, required=False, label="Номер")
    doc_date = forms.DateField(widget=DateInput(), initial=timezone.localdate, label="Дата")
    amount = forms.DecimalField(max_digits=14, decimal_places=2, required=False, label="Сумма")
    vat_rate = forms.DecimalField(max_digits=5, decimal_places=2, required=False, label="Ставка НДС, %", initial=20)
    request = forms.ModelChoiceField(queryset=ProcurementRequest.objects.none(), required=False, label="Заявка")
    supply_contract = forms.ModelChoiceField(queryset=SupplyContract.objects.order_by("-contract_date"), required=False, label="Договор поставки")
    items = forms.CharField(
        widget=forms.HiddenInput(attrs={"data-items-mode": "supplier-lines"}),
        label="Материалы",
        required=False,
    )
    attachment = forms.FileField(required=False, label="Файл")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["doc_type"].choices = _upload_document_type_choices()

        # Заявки на закупку которые уже использованы в документах поставщика
        busy_request_ids = SupplierDocument.objects.filter(
            status__in=[
                DocumentStatus.UPLOADED, DocumentStatus.APPROVAL,
                DocumentStatus.APPROVED, DocumentStatus.SENT_ACCOUNTING,
                DocumentStatus.ACCEPTED,
            ]
        ).exclude(request=None).values_list("request_id", flat=True)

        self.fields["request"].queryset = ProcurementRequest.objects.filter(
            status__in=[DocumentStatus.APPROVED, DocumentStatus.ACCEPTED, DocumentStatus.SENT_ACCOUNTING]
        ).exclude(id__in=busy_request_ids).order_by("-request_date")

    def clean(self):
        cleaned_data = super().clean()
        supplier = cleaned_data.get("supplier")
        related_suppliers = [
            item.supplier
            for item in [cleaned_data.get("request"), cleaned_data.get("supply_contract")]
            if item is not None and getattr(item, "supplier_id", None)
        ]
        if supplier and any(item.pk != supplier.pk for item in related_suppliers):
            raise forms.ValidationError("Поставщик документа должен совпадать с поставщиком в заявке или договоре.")
        return cleaned_data


class PrimaryDocumentCreateForm(BaseStyledForm, forms.Form):
    document_type = forms.ModelChoiceField(queryset=DocumentType.objects.none(), label="Тип документа")
    number = forms.CharField(
        max_length=128, required=False, label="Номер",
        help_text="Если оставить пустым, номер будет сформирован автоматически.",
    )
    doc_date = forms.DateField(widget=DateInput(), initial=timezone.localdate, label="Дата")
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.order_by("name"), required=False, label="Поставщик")
    request = forms.ModelChoiceField(queryset=ProcurementRequest.objects.order_by("-request_date"), required=False, label="Заявка")
    supply_contract = forms.ModelChoiceField(queryset=SupplyContract.objects.order_by("-contract_date"), required=False, label="Договор поставки")
    stock_receipt = forms.ModelChoiceField(queryset=StockReceipt.objects.order_by("-receipt_date"), required=False, label="Приход на склад")
    status = forms.ChoiceField(choices=WORKFLOW_ENTRY_STATUS_CHOICES, initial=DocumentStatus.DRAFT, label="Статус")
    amount = forms.DecimalField(max_digits=14, decimal_places=2, required=False, label="Сумма")
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Комментарий")
    items = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"data-items-mode": "material-lines"}),
        label="Позиции",
        help_text="Если оставить поле пустым, позиции будут взяты из заявки или приходного документа.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document_type"].queryset = DocumentType.objects.filter(is_active=True, available_for_generation=True).order_by("name")

    def clean_items(self):
        items = self.cleaned_data.get("items", "")
        if items:
            parse_line_items(items)
        return items
    def clean_number(self):
        number = (self.cleaned_data.get("number") or "").strip()
        if number and PrimaryDocument.objects.filter(number__iexact=number).exists():
            raise forms.ValidationError("Документ с таким номером уже существует.")
        return number

class StockReceiptCreateForm(BaseStyledForm, forms.Form):
    number = forms.CharField(
        max_length=128, required=False, label="Номер",
        help_text="Если оставить пустым, номер будет сформирован автоматически.",
    )
    receipt_date = forms.DateField(widget=DateInput(), initial=timezone.localdate, label="Дата прихода")
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.order_by("name"), required=False, label="Поставщик")
    supplier_document = forms.ModelChoiceField(queryset=SupplierDocument.objects.none(), required=False, label="Документ поставщика")
    items = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"data-items-mode": "material-lines"}),
        label="Позиции",
        help_text="Заполните позиции или выберите товарную накладную.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        approved_statuses = [DocumentStatus.APPROVED, DocumentStatus.ACCEPTED, DocumentStatus.SENT_ACCOUNTING]

        # Документы поставщика которые уже использованы в приходе на утверждении или выше
        busy_supplier_doc_ids = StockReceipt.objects.filter(
            status__in=[
                DocumentStatus.APPROVAL, DocumentStatus.APPROVED,
                DocumentStatus.SENT_ACCOUNTING, DocumentStatus.ACCEPTED,
            ]
        ).exclude(supplier_document=None).values_list("supplier_document_id", flat=True)

        self.fields["supplier_document"].queryset = SupplierDocument.objects.filter(
            status__in=approved_statuses,
            doc_type="Товарная накладная",
        ).exclude(id__in=busy_supplier_doc_ids).order_by("-doc_date")

    def clean_items(self):
        items = self.cleaned_data.get("items", "")
        if items:
            parse_line_items(items)
        return items

    def clean(self):
        cleaned_data = super().clean()
        supplier = cleaned_data.get("supplier")
        supplier_document = cleaned_data.get("supplier_document")
        if not supplier:
            raise forms.ValidationError("Укажите поставщика.")
        if supplier and supplier_document and supplier_document.supplier_id != supplier.id:
            raise forms.ValidationError("Документ поставщика должен принадлежать выбранному поставщику.")
        if not cleaned_data.get("items") and not supplier_document:
            raise forms.ValidationError("Заполните позиции или выберите документ поставщика.")
        return cleaned_data
    
    def clean_number(self):
        number = (self.cleaned_data.get("number") or "").strip()
        if number and StockReceipt.objects.filter(number__iexact=number).exists():
            raise forms.ValidationError("Приходный ордер с таким номером уже существует.")
        return number


class StockIssueCreateForm(BaseStyledForm, forms.Form):
    number = forms.CharField(
        max_length=128, required=False, label="Номер",
        help_text="Если оставить пустым, номер будет сформирован автоматически.",
    )
    issue_date = forms.DateField(widget=DateInput(), initial=timezone.localdate, label="Дата отпуска")
    site_name = forms.ChoiceField(choices=[], required=True, label="Участок")
    site_request = forms.IntegerField(
        required=False,
        label="Заявка участка",
        help_text="В списке только утверждённые заявки участков.",
        widget=forms.Select(choices=[]),
    )
    contract = forms.ModelChoiceField(queryset=SMRContract.objects.order_by("-contract_date"), required=False, label="Договор СМР")

    received_by_user = forms.ModelChoiceField(
        queryset=User.objects.filter(role='site_manager').order_by('last_name', 'first_name'),
        required=True,
        label="Получатель",
        empty_label="Не выбрано"
    )
    items = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"data-items-mode": "material-lines"}),
        label="Позиции",
        help_text="Заполните позиции или выберите заявку участка.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        values: list[str] = []
        values.extend(User.objects.filter(role=RoleChoices.SITE_MANAGER).exclude(site_name="").values_list("site_name", flat=True))
        values.extend(Worker.objects.exclude(site_name="").values_list("site_name", flat=True))
        values.extend(SiteMaterialRequest.objects.exclude(site_name="").values_list("site_name", flat=True))
        values.extend(StockIssue.objects.exclude(site_name="").values_list("site_name", flat=True))
        seen: set[str] = set()
        choices: list[tuple[str, str]] = [("", "Выберите участок")]
        for value in values:
            text = str(value or "").strip()
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            choices.append((text, text))
        self.fields["site_name"].choices = choices
        self.fields["received_by_user"].label_from_instance = lambda obj: obj.full_name_or_username

        approved_requests = SiteMaterialRequest.objects.filter(
            status__in=[DocumentStatus.APPROVED, DocumentStatus.ACCEPTED, DocumentStatus.SENT_ACCOUNTING]
        ).order_by("-request_date")
        self.fields["site_request"].widget.choices = [("", "Не выбрано")] + [
            (r.pk, str(r)) for r in approved_requests
        ]

    def clean_items(self):
        items = self.cleaned_data.get("items", "")
        if items:
            parse_line_items(items)
        return items

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("items") and not cleaned_data.get("site_request"):
            raise forms.ValidationError("Заполните позиции или выберите заявку участка.")
        return cleaned_data

    def clean_site_request(self):
        request_id = self.cleaned_data.get("site_request")
        if not request_id:
            return None
        try:
            return SiteMaterialRequest.objects.get(pk=request_id)
        except SiteMaterialRequest.DoesNotExist:
            return None
    def clean_number(self):
        number = (self.cleaned_data.get("number") or "").strip()
        if number and StockIssue.objects.filter(number__iexact=number).exists():
            raise forms.ValidationError("Требование-накладная с таким номером уже существует.")
        return number
class WriteOffCreateForm(BaseStyledForm, forms.Form):
    number = forms.CharField(
        max_length=128, required=False, label="Номер",
        help_text="Если оставить пустым, номер будет сформирован автоматически.",
    )
    act_date = forms.DateField(widget=DateInput(), initial=timezone.localdate, label="Дата акта")
    contract = forms.ModelChoiceField(queryset=SMRContract.objects.order_by("-contract_date"), label="Договор СМР", required=False, empty_label="Не выбрано (для хознужд)")
    template_variant = forms.ChoiceField(
        choices=WriteOffTemplateVariant.choices,
        initial=WriteOffTemplateVariant.CONTRACT,
        label="Форма акта",
    )
    site_name = forms.ChoiceField(choices=[], label="Участок")
    work_type = forms.ChoiceField(choices=[], required=False, label="Вид работ")
    work_volume = forms.DecimalField(max_digits=14, decimal_places=3, required=False, label="Объем работ")
    volume_unit = forms.CharField(max_length=64, required=False, label="Единица объема")
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Комментарий",
        help_text="Если вид работ или объем не заполнены, система возьмет их из договора СМР.",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site_name"].choices = self._site_choices(user=user)
        self.fields["work_type"].choices = self._work_type_choices()

        template_variant = self.data.get("template_variant") or (self.initial.get("template_variant") or WriteOffTemplateVariant.CONTRACT)
        # Договоры которые уже на утверждении в акте списания
        busy_contract_ids = WriteOffAct.objects.filter(
            status__in=[
                DocumentStatus.APPROVAL, DocumentStatus.APPROVED,
                DocumentStatus.SENT_ACCOUNTING, DocumentStatus.ACCEPTED,
            ]
        ).exclude(contract=None).values_list("contract_id", flat=True)

        if template_variant == WriteOffTemplateVariant.PRODUCTION_ECONOMIC:
            self.fields["contract"].queryset = SMRContract.objects.filter(
                status=DocumentStatus.ACCEPTED
            ).exclude(id__in=busy_contract_ids).order_by("-contract_date")
            self.fields["contract"].required = True
            self.fields["contract"].empty_label = "Выберите закрытый договор"
        else:
            self.fields["contract"].queryset = SMRContract.objects.filter(
                status__in=[DocumentStatus.APPROVED, DocumentStatus.ACCEPTED, DocumentStatus.SENT_ACCOUNTING]
            ).exclude(id__in=busy_contract_ids).order_by("-contract_date")

    def _initial_text(self, field_name: str) -> str:
        return str(self.initial.get(field_name) or "").strip()

    def _site_choices(self, *, user=None) -> list[tuple[str, str]]:
        initial_site = self._initial_text("site_name")
        if getattr(user, "role", None) == RoleChoices.SITE_MANAGER:
            return _text_choices(
                [getattr(user, "site_name", ""), initial_site],
                empty_label=None,
            )

        values: list[str] = [initial_site]
        values.extend(User.objects.exclude(site_name="").values_list("site_name", flat=True))
        values.extend(Worker.objects.exclude(site_name="").values_list("site_name", flat=True))
        values.extend(ConstructionObject.objects.exclude(name="").values_list("name", flat=True))
        values.extend(SiteMaterialRequest.objects.exclude(site_name="").values_list("site_name", flat=True))
        values.extend(StockIssue.objects.exclude(site_name="").values_list("site_name", flat=True))
        values.extend(WriteOffAct.objects.exclude(site_name="").values_list("site_name", flat=True))
        values.extend(PPEIssuance.objects.exclude(site_name="").values_list("site_name", flat=True))
        values.extend(WorkAcceptanceAct.objects.exclude(site_name="").values_list("site_name", flat=True))
        values.extend(WorkLog.objects.exclude(site_name="").values_list("site_name", flat=True))
        return _text_choices(values)

    def _work_type_choices(self) -> list[tuple[str, str]]:
        values: list[str] = [self._initial_text("work_type")]
        values.extend(MaterialNorm.objects.exclude(work_type="").order_by("work_type").values_list("work_type", flat=True))
        values.extend(SMRContract.objects.exclude(work_type="").order_by("work_type").values_list("work_type", flat=True))
        return _text_choices(values, empty_label="По договору СМР")
    def clean_number(self):
        number = (self.cleaned_data.get("number") or "").strip()
        if number and WriteOffAct.objects.filter(number__iexact=number).exists():
            raise forms.ValidationError("Акт списания с таким номером уже существует.")
        return number

class PPEIssuanceCreateForm(BaseStyledForm, forms.Form):
    number = forms.CharField(
        max_length=128, required=False, label="Номер",
        help_text="Если оставить пустым, номер будет сформирован автоматически.",
    )
    issue_date = forms.DateField(widget=DateInput(), initial=timezone.localdate, label="Дата выдачи")
    site_name = forms.CharField(max_length=255, label="Участок")
    season = forms.ChoiceField(choices=[("летняя", "летняя"), ("зимняя", "зимняя"), ("перчатки", "перчатки")], required=False, label="Сезон")
    items = forms.CharField(
        widget=forms.HiddenInput(attrs={"data-items-mode": "ppe-lines"}),
        label="Позиции",
        help_text="Выберите ФИО работника и наименование спецодежды, табельный номер и код подставятся автоматически.",
    )

    def clean_items(self):
        items = self.cleaned_data["items"]
        parse_ppe_lines(items)
        return items
    def clean_number(self):
        number = (self.cleaned_data.get("number") or "").strip()
        if number and PPEIssuance.objects.filter(number__iexact=number).exists():
            raise forms.ValidationError("Ведомость с таким номером уже существует.")
        return number


class WorkLogCreateForm(BaseStyledForm, forms.Form):
    site_name = forms.CharField(max_length=255, label="Участок")
    contract = forms.ModelChoiceField(queryset=SMRContract.objects.order_by("-contract_date"), required=False, label="Договор СМР")
    work_type = forms.ChoiceField(choices=[("", "Сначала выберите договор")], required=True, label="Вид работ")

    planned_volume = forms.DecimalField(max_digits=14, decimal_places=3, required=False, label="Плановый объем")
    actual_volume = forms.DecimalField(max_digits=14, decimal_places=3, required=False, label="Фактический объем")
    volume_unit = forms.CharField(max_length=64, required=False, label="Единица измерения")
    plan_date = forms.DateField(widget=DateInput(), required=False, label="Плановая дата")
    actual_date = forms.DateField(widget=DateInput(), required=False, label="Фактическая дата")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import WorkStage
        self.fields["contract"].widget.attrs["data-worklog-contract"] = "1"
        self.fields["work_type"].widget.attrs["data-worklog-worktype"] = "1"
        self.fields["volume_unit"].widget.attrs["data-worklog-unit"] = "1"
        

        # Собираем choices: все виды работ из всех договоров
        # (валидация чтобы любой существующий вид работ прошёл)
        all_work_types = SMRContractWorkLine.objects.values_list("work_type", flat=True).distinct()
        choices = [("", "Сначала выберите договор")]
        for wt in all_work_types:
            if wt:
                choices.append((wt, wt))

        # Если форма привязана к данным — оставляем выбранное значение валидным
        if self.is_bound:
            current = self.data.get("work_type", "")
            if current and (current, current) not in choices:
                choices.append((current, current))

        # Если есть initial — тоже добавим
        initial_wt = self.initial.get("work_type", "")
        if initial_wt and (initial_wt, initial_wt) not in choices:
            choices.append((initial_wt, initial_wt))

        self.fields["work_type"].choices = choices

class WorkAcceptanceCreateForm(BaseStyledForm, forms.Form):
    number = forms.CharField(
        max_length=128, required=False, label="Номер",
        help_text="Если оставить пустым, номер будет сформирован автоматически.",
    )
    act_date = forms.DateField(widget=DateInput(), initial=timezone.localdate, label="Дата акта")
    contract = forms.ModelChoiceField(
        queryset=SMRContract.objects.exclude(
            id__in=WorkAcceptanceAct.objects.filter(
                status__in=[DocumentStatus.APPROVAL, DocumentStatus.APPROVED,
                            DocumentStatus.SENT_ACCOUNTING, DocumentStatus.ACCEPTED]
            ).values_list("contract_id", flat=True)
        ).order_by("-contract_date"),
        label="Договор СМР"
    )
    site_name = forms.CharField(max_length=255, label="Участок")
    work_description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), label="Описание выполненных работ")
    amount = forms.DecimalField(max_digits=14, decimal_places=2, required=False, label="Сумма по акту")
    def clean_number(self):
        number = (self.cleaned_data.get("number") or "").strip()
        if number and WorkAcceptanceAct.objects.filter(number__iexact=number).exists():
            raise forms.ValidationError("Акт с таким номером уже существует.")
        return number

class ArchiveFilterForm(DateRangeValidationMixin, BaseStyledForm, forms.Form):
    doc_type = forms.ChoiceField(required=False, choices=[], label="Тип документа")
    doc_number = forms.CharField(required=False, label="Номер")
    status = forms.ChoiceField(required=False, choices=[("", "Все")] + list(DocumentStatus.choices), label="Статус")
    date_from = forms.DateField(required=False, widget=DateInput(), label="С")
    date_to = forms.DateField(required=False, widget=DateInput(), label="По")
    counterparty = forms.ModelChoiceField(
        queryset=Supplier.objects.order_by("name"),
        required=False,
        label="Поставщик / контрагент",
        empty_label="Все контрагенты",
    )
    object_name = forms.ModelChoiceField(
        queryset=ConstructionObject.objects.order_by("name"),
        required=False,
        label="Объект",
        empty_label="Все объекты",
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.is_archive = kwargs.pop("is_archive", False)
        super().__init__(*args, **kwargs)
        if getattr(self.user, 'role', None) == RoleChoices.SUPPLIER:
            self.fields.pop("counterparty", None)
            self.fields.pop("object_name", None)
        # В архиве все документы со статусом «Принят» — фильтр статуса не нужен
        if self.is_archive:
            self.fields.pop("status", None)

        #  Список типов документов — только те что пользователь имеет право видеть
        from .services import filter_queryset_for_user
        visible_records = filter_queryset_for_user(
            self.user, DocumentRecord.objects.exclude(doc_type="")
        ) if self.user else DocumentRecord.objects.exclude(doc_type="")
        doc_types = (
            visible_records
            .values_list("doc_type", flat=True)
            .distinct()
            .order_by("doc_type")
        )
        self.fields["doc_type"].choices = [("", "Все типы")] + [(t, t) for t in doc_types]


class ReportFilterForm(DateRangeValidationMixin, BaseStyledForm, forms.Form):
    report = forms.ChoiceField(choices=REPORT_CHOICES, label="Отчет")
    date_from = forms.DateField(required=False, widget=DateInput(), label="С")
    date_to = forms.DateField(required=False, widget=DateInput(), label="По")
    material_code = forms.ModelChoiceField(
        queryset=Material.objects.order_by("code"),
        required=False,
        label="Код материала",
        empty_label="Все материалы",
    )
    location_name = forms.ChoiceField(choices=[], required=False, label="Участок / склад")
    object_name = forms.ModelChoiceField(
        queryset=ConstructionObject.objects.order_by("name"),
        required=False,
        label="Объект",
        empty_label="Все объекты",
    )
    supplier_name = forms.ModelChoiceField(
        queryset=Supplier.objects.order_by("name"),
        required=False,
        label="Поставщик",
        empty_label="Все поставщики",
    )
    contract_number = forms.ModelChoiceField(
        queryset=SMRContract.objects.order_by("-contract_date"),
        required=False,
        label="Номер договора",
        empty_label="Все договоры",
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        role = getattr(self.user, "role", None)

        # Ограничение отчётов
        if role == RoleChoices.SITE_MANAGER:
            allowed = ["site_material_report", "writeoffs", "work", "work_stats", "ppe"]
        elif role == RoleChoices.WAREHOUSE:
            allowed = ["stock", "movements", "site_material_report"]
        elif role == RoleChoices.PROCUREMENT:
            allowed = ["purchases", "consumption", "site_material_report"]
        else:
            allowed = [choice[0] for choice in REPORT_CHOICES]

        self.fields["report"].choices = [
            choice for choice in REPORT_CHOICES if choice[0] in allowed
        ]

        # Ограничение для начальника участка
        if role == RoleChoices.SITE_MANAGER:
            site_name = getattr(self.user, "site_name", "") or ""
            self.fields["location_name"].choices = [(site_name, site_name)]
            self.fields["location_name"].initial = site_name
            # Начальнику участка поставщики не нужны
            self.fields.pop("supplier_name", None)

            # Только договоры (работает)
            self.fields["contract_number"].queryset = SMRContract.objects.filter(
                stock_issues__site_name=site_name
            ).distinct().order_by("-contract_date")

            # Временно отключаем ограничение объектов (самая частая причина падения)
            # self.fields["object_name"].queryset = ...

        else:
            locations = ["Центральный склад"]
            locations.extend(
                StockIssue.objects.exclude(site_name="")
                .values_list("site_name", flat=True)
                .distinct()
            )
            self.fields["location_name"].choices = [("", "Все участки")] + [
                (l, l) for l in sorted(set(locations))
            ]
            
        # Снабженцу и кладовщику договоры СМР в фильтрах не нужны
        if role in (RoleChoices.PROCUREMENT, RoleChoices.WAREHOUSE):
            self.fields.pop("contract_number", None)
            self.fields.pop("object_name", None)

class AuditLogFilterForm(DateRangeValidationMixin, BaseStyledForm, forms.Form):
    username = forms.ChoiceField(required=False, choices=[], label="Пользователь")
    action = forms.ChoiceField(required=False, choices=[], label="Действие")
    entity_type = forms.ChoiceField(required=False, choices=[], label="Сущность")
    date_from = forms.DateField(required=False, widget=DateInput(), label="С")
    date_to = forms.DateField(required=False, widget=DateInput(), label="По")
    query = forms.CharField(required=False, label="Поиск")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import AuditLog

        usernames = (
            AuditLog.objects.exclude(user=None)
            .values_list("user__username", flat=True)
            .distinct()
            .order_by("user__username")
        )
        self.fields["username"].choices = [("", "Все пользователи")] + [
            (u, u) for u in usernames if u
        ]

        actions = (
            AuditLog.objects.exclude(action="")
            .values_list("action", flat=True)
            .distinct()
            .order_by("action")
        )
        from .views import AUDIT_ACTION_LABELS
        self.fields["action"].choices = [("", "Все действия")] + [
            (a, AUDIT_ACTION_LABELS.get(a, a)) for a in actions if a
        ]

        entity_types = (
            AuditLog.objects.exclude(entity_type="")
            .values_list("entity_type", flat=True)
            .distinct()
            .order_by("entity_type")
        )
        from .views import AUDIT_ENTITY_LABELS
        self.fields["entity_type"].choices = [("", "Все сущности")] + [
            (e, AUDIT_ENTITY_LABELS.get(e, e)) for e in entity_types if e
        ]


class MaterialForm(BaseStyledForm, forms.ModelForm):
    class Meta:
        model = Material
        fields = ["code", "name", "unit", "stock_reserve_qty", "category", "is_ppe"]
        labels = {
            "code": "Код",
            "name": "Наименование",
            "unit": "Ед. изм.",
            "stock_reserve_qty": "Норма остатка",
            "category": "Категория",
            "is_ppe": "СИЗ / спецодежда",
        }
    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip()
        if not code:
            return code
        existing = Material.objects.filter(code__iexact=code)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("Материал с таким кодом уже существует.")
        return code

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            return name
        existing = Material.objects.filter(name__iexact=name)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("Материал с таким наименованием уже существует.")
        return name

class SupplierForm(BaseStyledForm, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "tax_id", "ogrnip", "contact_person", "phone", "email", "address", "requisites"]
        labels = {
            "name": "Поставщик",
            "tax_id": "ИНН",
            "ogrnip": "ОГРНИП",
            "contact_person": "Контактное лицо",
            "phone": "Телефон",
            "email": "Эл. почта",
            "address": "Адрес",
            "requisites": "Реквизиты",
        }
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "requisites": forms.Textarea(attrs={"rows": 4}),
        }

    def clean(self):
        cleaned_data = super().clean()
        tax_id = (cleaned_data.get("tax_id") or "").strip()
        ogrnip = (cleaned_data.get("ogrnip") or "").strip()

        if ogrnip and tax_id and len(tax_id) == 10:
            self.add_error(
                "ogrnip",
                "ОГРНИП заполняется только для ИП. У организаций (ИНН из 10 цифр) "
                "этого реквизита не должно быть — уберите значение или проверьте ИНН.",
            )
        if ogrnip and not tax_id:
            self.add_error(
                "ogrnip",
                "Чтобы заполнить ОГРНИП, сначала укажите ИНН поставщика (12 цифр для ИП).",
            )
        return cleaned_data


class ConstructionObjectForm(BaseStyledForm, forms.ModelForm):
    class Meta:
        model = ConstructionObject
        fields = [
            "name", "address", "customer_name", "customer_name_short",
            "customer_legal_address", "customer_tax_id", "customer_kpp",
            "customer_ogrn", "customer_bank", "customer_bik",
            "customer_account", "customer_corr_account", "customer_okpo",
            "customer_requisites", "description", "start_date", "end_date",
        ]
        labels = {
            "name": "Наименование объекта",
            "address": "Адрес объекта",
            "customer_name": "Заказчик (полное наименование)",
            "customer_name_short": "Заказчик (краткое наименование)",
            "customer_legal_address": "Юридический адрес",
            "customer_tax_id": "ИНН",
            "customer_kpp": "КПП",
            "customer_ogrn": "ОГРН",
            "customer_bank": "Банк",
            "customer_bik": "БИК",
            "customer_account": "Расчётный счёт",
            "customer_corr_account": "Корреспондентский счёт",
            "customer_okpo": "ОКПО",
            "customer_requisites": "Реквизиты (текстом, если нужно)",
            "description": "Описание",
            "start_date": "Дата начала",
            "end_date": "Дата окончания",
        }
        widgets = {
            "customer_requisites": forms.Textarea(attrs={"rows": 3}),
            "description": forms.Textarea(attrs={"rows": 3}),
            "start_date": DateInput(),
            "end_date": DateInput(),
        }


class WorkerForm(BaseStyledForm, forms.ModelForm):
    class Meta:
        model = Worker
        fields = ["full_name", "employee_number", "site_name", "position", "hire_date"]
        labels = {
            "full_name": "ФИО",
            "employee_number": "Табельный номер",
            "site_name": "Участок",
            "position": "Должность",
            "hire_date": "Дата приема",
        }
        widgets = {"hire_date": DateInput()}
    def clean_employee_number(self):
        employee_number = (self.cleaned_data.get("employee_number") or "").strip()
        if not employee_number:
            return employee_number
        existing = Worker.objects.filter(employee_number__iexact=employee_number)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("Работник с таким табельным номером уже существует.")
        return employee_number

class MaterialNormForm(BaseStyledForm, forms.ModelForm):
    class Meta:
        model = MaterialNorm
        fields = ["work_type", "material", "norm_per_unit", "unit", "notes"]
        labels = {
            "work_type": "Вид работ",
            "material": "Материал",
            "norm_per_unit": "Норма на единицу",
            "unit": "Ед. изм.",
            "notes": "Примечание",
        }
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class DocumentTypeForm(BaseStyledForm, forms.ModelForm):
    class Meta:
        model = DocumentType
        fields = ["code", "name", "prefix", "is_active", "available_for_upload", "available_for_generation", "requires_items", "description"]
        labels = {
            "code": "Код",
            "name": "Наименование",
            "prefix": "Префикс",
            "is_active": "Активен",
            "available_for_upload": "Доступен для загрузки",
            "available_for_generation": "Доступен для генерации",
            "requires_items": "Требует позиции",
            "description": "Описание",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class SMRContractForm(BaseStyledForm, forms.ModelForm):
    work_lines = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"data-items-mode": "work-lines"}),
        label="Виды работ (смета)",
    )
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "customer_name" in self.fields:
            self.fields["customer_name"].required = False

        profile = getattr(settings, "ORGANIZATION_PROFILE", {}) or {}
        if not self.is_bound:
            if "contractor_name" in self.fields and not self.initial.get("contractor_name"):
                self.fields["contractor_name"].initial = str(profile.get("name", "")).strip()
            if "contractor_requisites" in self.fields and not self.initial.get("contractor_requisites"):
                self.fields["contractor_requisites"].initial = str(profile.get("requisites", "")).strip()
        if "site_manager" in self.fields:
            self.fields["site_manager"].queryset = User.objects.filter(
                role=RoleChoices.SITE_MANAGER, is_active=True
            ).order_by("last_name", "first_name", "username")
            self.fields["site_manager"].empty_label = "Не назначен"

    def clean(self):
        cleaned_data = super().clean()
        construction_object = cleaned_data.get("object")

        if not cleaned_data.get("object"):
            self.add_error("object", "Выберите объект строительства.")
        
        profile = getattr(settings, "ORGANIZATION_PROFILE", {}) or {}
        contractor_name = (cleaned_data.get("contractor_name") or "").strip()
        if not contractor_name:
            cleaned_data["contractor_name"] = str(profile.get("name", "")).strip()

        contractor_requisites = (cleaned_data.get("contractor_requisites") or "").strip()
        if not contractor_requisites:
            cleaned_data["contractor_requisites"] = str(profile.get("requisites", "")).strip()

        return cleaned_data

    class Meta:
        model = SMRContract
        fields = [
            "number",
            "contract_date",
            "object",
            "subject",
            "amount",
            "vat_rate",
            "start_date",
            "end_date",
            "status",
            "site_manager",
            "customer_signer_name",
            "customer_signer_position", 
            "customer_signer_name_genitive",
            "customer_signer_position_genitive",
            "customer_auth_doc",
            "work_object_description",
            "work_basis_text",
            "work_basis_number",
            "work_basis_date",
            "work_goal",
            "work_conditions",
            "attachment",
        ]
        labels = {
            "number": "Номер",
            "contract_date": "Дата договора",
            "object": "Объект строительства",
            "customer_signer_name": "ФИО подписанта заказчика",
            "customer_signer_position": "Должность подписанта заказчика",
            "customer_signer_name_genitive": "ФИО подписанта заказчика (родительный падеж)",
            "customer_signer_position_genitive": "Должность подписанта заказчика (родительный падеж)",
            "customer_auth_doc": "Документ полномочий (доверенность/устав)",
            "subject": "Предмет договора",
            "work_type": "Вид работ",
            "planned_volume": "Плановый объем",
            "amount": "Сумма",
            "vat_rate": "Ставка НДС",
            "start_date": "Дата начала",
            "end_date": "Дата окончания",
            "status": "Статус",
            "site_manager": "Ответственный начальник участка",
            "work_object_description": "Описание объекта (ТЗ)",
            "work_basis_text": "Основание (тип документа)",
            "work_basis_number": "Номер основания",
            "work_basis_date": "Дата основания",
            "work_goal": "Цель работ",
            "work_conditions": "Условия проведения работ",
            "attachment": "Локальная смета (Excel/PDF)",
        }
        widgets = {
            "contract_date": DateInput(),
            "start_date": DateInput(),
            "end_date": DateInput(),
            "work_basis_date": DateInput(),
            "work_object_description": forms.Textarea(attrs={"rows": 4}),
            "work_conditions": forms.Textarea(attrs={"rows": 3}),
            "attachment": forms.FileInput(),
        }


class SupplyContractForm(BaseStyledForm, forms.ModelForm):
    class Meta:
        model = SupplyContract
        fields = ["number", "contract_date", "supplier", "amount", "status", "terms"]
        labels = {
            "number": "Номер",
            "contract_date": "Дата договора",
            "supplier": "Поставщик",
            "amount": "Сумма",
            "status": "Статус",
            "terms": "Условия",
        }
        widgets = {
            "contract_date": DateInput(),
            "terms": forms.Textarea(attrs={"rows": 3}),
        }


class UserForm(BaseStyledForm, forms.ModelForm):
    role = forms.ChoiceField(choices=RoleChoices.choices, label="Роль")
    password1 = forms.CharField(required=False, widget=forms.PasswordInput(), label="Пароль")
    password2 = forms.CharField(required=False, widget=forms.PasswordInput(), label="Подтверждение пароля")

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "role", "site_name", "supplier", "is_active"]
        labels = {
            "username": "Логин",
            "first_name": "Имя и Отчество",
            "last_name": "Фамилия",
            "email": "Адрес электронной почты",
            "site_name": "Участок / подразделение",
            "supplier": "Поставщик",
            "is_active": "Активный",
        }
        help_texts = {
            "username": "Используйте буквы, цифры и символы @/./+/-/_",
            "first_name": "Укажите имя и отчество через пробел, например: Олег Александрович",
        }


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].required = False
        if self.instance.pk:
            self.fields["password1"].help_text = "Оставьте пустым, чтобы не менять пароль."
            self.fields["password2"].help_text = "Заполните только если меняете пароль."
        else:
            self.fields["password1"].help_text = "Укажите пароль для новой учетной записи."
            self.fields["password2"].help_text = "Повторите пароль."

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            return username
        existing = User.objects.filter(username__iexact=username)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("Пользователь с таким логином уже существует. Выберите другой логин.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        supplier = cleaned_data.get("supplier")
        site_name = (cleaned_data.get("site_name") or "").strip()
        password1 = cleaned_data.get("password1") or ""
        password2 = cleaned_data.get("password2") or ""

        if role == RoleChoices.SUPPLIER:
            if supplier is None:
                self.add_error("supplier", "Для роли поставщика нужно выбрать связанного поставщика.")
            else:
                existing_supplier_user = User.objects.filter(role=RoleChoices.SUPPLIER, supplier=supplier)
                if self.instance.pk:
                    existing_supplier_user = existing_supplier_user.exclude(pk=self.instance.pk)
                if existing_supplier_user.exists():
                    self.add_error(
                        "supplier",
                        "Для этого поставщика уже создан пользователь. Используйте существующую учетную запись.",
                    )
        else:
            cleaned_data["supplier"] = None

        if role == RoleChoices.SITE_MANAGER and site_name:
            existing_site_manager = User.objects.filter(
                role=RoleChoices.SITE_MANAGER, site_name__iexact=site_name, is_active=True,
            )
            if self.instance.pk:
                existing_site_manager = existing_site_manager.exclude(pk=self.instance.pk)
            if existing_site_manager.exists():
                self.add_error(
                    "site_name",
                    "На этом участке уже есть активный начальник участка.",
                )

        if not self.instance.pk and not password1:
            self.add_error("password1", "Укажите пароль для новой учетной записи.")

        if password1 or password2:
            if password1 != password2:
                self.add_error("password2", "Пароли должны совпадать.")
            else:
                validate_password(password1, self.instance if self.instance.pk else None)

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("role") != RoleChoices.SUPPLIER:
            user.supplier = None

        password = self.cleaned_data.get("password1")
        if password:
            user.set_password(password)

        if commit:
            user.save()
        return user


class BackupRestoreUploadForm(BaseStyledForm, forms.Form):
    backup_file = forms.FileField(label="JSON-файл резервной копии")
    confirm_restore = forms.BooleanField(label="Подтверждаю замену текущих данных при восстановлении")


class WorkScheduleCreateForm(BaseStyledForm, forms.Form):
    number = forms.CharField(
        max_length=128, required=False, label="Номер",
        help_text="Если оставить пустым, номер будет сформирован автоматически.",
    )
    contract = forms.ModelChoiceField(
        queryset=SMRContract.objects.order_by("-contract_date"),
        label="Договор СМР"
    )
    site_name = forms.CharField(max_length=255, label="Участок")
    period_start = forms.DateField(widget=DateInput(), label="Начало периода")
    period_end = forms.DateField(widget=DateInput(), label="Окончание периода")
    items = forms.CharField(
        widget=forms.HiddenInput(attrs={"data-items-mode": "schedule-lines"}),
        label="Строки графика",
    )

    def clean_items(self):
        items = self.cleaned_data.get("items", "")
        if not items:
            raise forms.ValidationError("Заполните строки графика.")
        try:
            import json
            parsed = json.loads(items)
            if not isinstance(parsed, list) or len(parsed) == 0:
                raise forms.ValidationError("Добавьте хотя бы одну строку.")
        except (ValueError, TypeError):
            raise forms.ValidationError("Ошибка формата строк.")
        return items    
    def clean_number(self):
        number = (self.cleaned_data.get("number") or "").strip()
        if number and WorkSchedule.objects.filter(number__iexact=number).exists():
            raise forms.ValidationError("График с таким номером уже существует.")
        return number
class WorkStageForm(BaseStyledForm, forms.Form):
    work_type = forms.ChoiceField(choices=[], label="Вид работ")
    stages = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": "Введите каждый этап с новой строки:\nРазметка трасс\nПрокладка кабеля\nПодключение"}),
        label="Этапы (каждый с новой строки)",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)
        work_types = list(
            MaterialNorm.objects.values_list("work_type", flat=True)
            .distinct().order_by("work_type")
        )
        self.fields["work_type"].choices = [("", "Выберите вид работ")] + [(wt, wt) for wt in work_types]

class WorkStageControlForm(BaseStyledForm, forms.Form):
    contract = forms.ModelChoiceField(
        queryset=SMRContract.objects.order_by("-contract_date"),
        label="Договор СМР",
        empty_label="Выберите договор",
    )
    work_type = forms.ChoiceField(choices=[("", "Сначала выберите договор")], label="Вид работ")
    stage = forms.ChoiceField(choices=[("", "Сначала выберите вид работ")], label="Этап", required=False)
    plan_start = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "readonly": "readonly"}),
        label="План начало",
        required=False,
    )
    plan_end = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "readonly": "readonly"}),
        label="План конец",
        required=False,
    )
    actual_start = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Факт начало",
        required=False,
    )
    actual_end = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Факт конец",
        required=False,
    )
    actual_notes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Примечание",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)
        from .models import WorkStage, SMRContractWorkLine
        work_types = list(SMRContractWorkLine.objects.values_list("work_type", flat=True).distinct().order_by("work_type"))
        self.fields["work_type"].choices = [("", "Сначала выберите договор")] + [(wt, wt) for wt in work_types]
        stages = list(WorkStage.objects.values_list("stage_name", flat=True).distinct().order_by("stage_name"))
        self.fields["stage"].choices = [("", "Выберите этап")] + [(s, s) for s in stages]
        self.fields["contract"].widget.attrs["data-worklog-contract"] = "1"
        self.fields["work_type"].widget.attrs["data-worklog-worktype"] = "1"
        self.fields["stage"].widget.attrs["data-worklog-stage"] = "1"


    def clean(self):
        cleaned_data = super().clean()
        actual_start = cleaned_data.get("actual_start")
        actual_end = cleaned_data.get("actual_end")
        if actual_start and actual_end and actual_start > actual_end:
            raise forms.ValidationError("Дата фактического начала не может быть позже даты фактического окончания.")
        return cleaned_data
class OrganizationProfileForm(BaseStyledForm, forms.ModelForm):
    class Meta:
        model = OrganizationProfile
        fields = [
            "name", "tax_id", "kpp", "ogrn", "address",
            "bank_name", "bik", "account", "corr_account", "okpo",
            "bank_details", "requisites",
            "contractor_signer_name", "contractor_signer_position",
            "contractor_signer_name_genitive", "contractor_signer_position_genitive",
            "contractor_auth_doc",
        ]
        labels = {
            "name": "Наименование организации",
            "tax_id": "ИНН",
            "kpp": "КПП",
            "ogrn": "ОГРН",
            "address": "Адрес",
            "bank_name": "Банк",
            "bik": "БИК",
            "account": "Расчётный счёт",
            "corr_account": "Корреспондентский счёт",
            "okpo": "ОКПО",
            "bank_details": "Банковские реквизиты (текстом)",
            "requisites": "Реквизиты (текстом)",
            "contractor_signer_name": "ФИО подписанта",
            "contractor_signer_position": "Должность подписанта",
            "contractor_signer_name_genitive": "ФИО подписанта (родительный падеж)",
            "contractor_signer_position_genitive": "Должность подписанта (родительный падеж)",
            "contractor_auth_doc": "Документ полномочий",
        }
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
            "bank_details": forms.Textarea(attrs={"rows": 3}),
            "requisites": forms.Textarea(attrs={"rows": 3}),
        }