from decimal import Decimal
from datetime import date, timedelta, datetime
 
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
 
from apps.core.models import (
    Material, Supplier, ConstructionObject, Worker, MaterialNorm,
    SMRContract, SMRContractWorkLine, SupplyContract, WorkStage,
    DocumentStatus, RoleChoices, User,
    AuditLog, DocumentRecord, FormDraft, Notification,
    PPEIssuanceLine, PPEIssuance,
    PrimaryDocumentLine, PrimaryDocument,
    ProcurementRequestLine, ProcurementRequest,
    SiteMaterialRequestLine, SiteMaterialRequest,
    StockIssueLine, StockIssue,
    StockMovement,
    StockReceiptLine, StockReceipt,
    SupplierDocumentLine, SupplierDocument,
    WorkAcceptanceAct,
    WorkLog,
    WorkScheduleLine, WorkSchedule,
    WriteOffLine, WriteOffAct,
    NotificationType,
)
 
TODAY = date(2026, 6, 8)
 
 
class Command(BaseCommand):
    help = "Заполняет базу полным набором демонстрационных данных для скриншотов"
 
    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true",
                            help="Удалить существующие данные перед заполнением")
 
    def handle(self, *args, **options):
        if options["clear"]:
            self.stdout.write("Очищаем все данные...")
            self._clear_all()
            self.stdout.write(self.style.WARNING("Данные очищены."))
 
        self.stdout.write("=== СОЗДАНИЕ СПРАВОЧНИКОВ ===")
        self._create_users()
        self._create_suppliers()
        self._create_objects()
        self._create_materials()
        self._create_workers()
        self._create_norms()
        self._create_work_stages()
 
        self.stdout.write("=== СОЗДАНИЕ ДОГОВОРОВ ===")
        self._create_contracts()
 
        self.stdout.write("=== СОЗДАНИЕ ОПЕРАЦИОННЫХ ДОКУМЕНТОВ ===")
        self._create_site_requests()
        self._create_procurement_requests()
        self._create_supplier_documents()
        self._create_stock_receipts()
        self._create_stock_issues()
        self._create_writeoff_acts()
        self._create_acceptance_acts()
        self._create_ppe_issuances()
        self._create_work_schedules()
        self._create_work_logs()
        self._create_notifications()
 
        self.stdout.write(self.style.SUCCESS(
            "\n✅ База заполнена!\n"
            "Логины: admin/director/procurement/warehouse/site_manager_1/site_manager_2/accounting/supplier_1/supplier_2/supplier_3\n"
            "Пароль для всех: demo1234"
        ))
 
    def _clear_all(self):
        order = [
            FormDraft, AuditLog, Notification, DocumentRecord,
            PPEIssuanceLine, WriteOffLine, StockMovement, StockIssueLine,
            StockReceiptLine, PrimaryDocumentLine, ProcurementRequestLine,
            SiteMaterialRequestLine, WorkScheduleLine, SupplierDocumentLine,
            PPEIssuance, WriteOffAct, StockIssue, StockReceipt,
            PrimaryDocument, SupplierDocument, ProcurementRequest,
            SiteMaterialRequest, WorkSchedule, WorkLog, WorkAcceptanceAct,
            WorkStage, MaterialNorm, SMRContractWorkLine, SMRContract,
            SupplyContract, Worker, Material, ConstructionObject, Supplier,
        ]
        for model in order:
            count, _ = model.objects.all().delete()
            self.stdout.write(f"  {model.__name__}: удалено {count}")
        User.objects.filter(role=RoleChoices.SUPPLIER).delete()
 
    def _create_users(self):
        self.stdout.write("Пользователи...")
        users_data = [
            {"username": "admin",          "first_name": "Сергей",  "last_name": "Петров",    "role": RoleChoices.ADMIN,        "site_name": "",                  "is_staff": True,  "is_superuser": True},
            {"username": "director",       "first_name": "Алексей", "last_name": "Родионов",  "role": RoleChoices.DIRECTOR,     "site_name": "",                  "is_staff": True},
            {"username": "procurement",    "first_name": "Марина",  "last_name": "Соколова",  "role": RoleChoices.PROCUREMENT,  "site_name": "Отдел снабжения",   "is_staff": True},
            {"username": "warehouse",      "first_name": "Игорь",   "last_name": "Пахомов",   "role": RoleChoices.WAREHOUSE,    "site_name": "Центральный склад", "is_staff": True},
            {"username": "site_manager_1", "first_name": "Дмитрий", "last_name": "Волков",    "role": RoleChoices.SITE_MANAGER, "site_name": "Участок Север-1"},
            {"username": "site_manager_2", "first_name": "Андрей",  "last_name": "Козлов",    "role": RoleChoices.SITE_MANAGER, "site_name": "Участок Юг-2"},
            {"username": "accounting",     "first_name": "Елена",   "last_name": "Михайлова", "role": RoleChoices.ACCOUNTING,   "site_name": "",                  "is_staff": True},
        ]
        for d in users_data:
            user, created = User.objects.update_or_create(
                username=d["username"],
                defaults={k: v for k, v in d.items() if k != "username"} | {"is_active": True},
            )
            if created:
                user.set_password("demo1234")
                user.save()
        self.stdout.write(f"  {len(users_data)} пользователей")
 
    def _create_suppliers(self):
        self.stdout.write("Поставщики...")
        data = [
            {"name": 'ООО "ЭлектроКомплект"',  "tax_id": "7701234567", "contact_person": "Новиков Павел Андреевич",   "phone": "+7 (495) 123-45-67", "email": "info@electrokomplekt.ru",   "address": "г. Москва, ул. Электрозаводская, д. 21, стр. 3",   "requisites": "ИНН 7701234567; КПП 770101001; ОГРН 1177700001234; р/с 40702810500000012345 в ПАО Сбербанк; БИК 044525225; к/с 30101810400000000225"},
            {"name": 'ООО "СтройСнаб Групп"',  "tax_id": "7705678901", "contact_person": "Кириллова Анна Сергеевна",  "phone": "+7 (495) 987-65-43", "email": "zakaz@stroysnab.ru",        "address": "г. Москва, Варшавское шоссе, д. 46, офис 301",      "requisites": "ИНН 7705678901; КПП 770501001; ОГРН 1187700005678; р/с 40702810700000056789 в АО Альфа-Банк; БИК 044525593; к/с 30101810200000000593"},
            {"name": 'ООО "ТехПромСервис"',     "tax_id": "7709012345", "contact_person": "Громов Виктор Иванович",   "phone": "+7 (495) 555-12-34", "email": "sales@techpromservice.ru",  "address": "г. Москва, ул. Промышленная, д. 8",                  "requisites": "ИНН 7709012345; КПП 770901001; ОГРН 1197700009012; р/с 40702810300000098765 в ПАО ВТБ; БИК 044525187; к/с 30101810700000000187"},
        ]
        for d in data:
            Supplier.objects.update_or_create(name=d["name"], defaults=d)
        suppliers = list(Supplier.objects.all())
        for username, fn, ln, idx in [("supplier_1","Павел","Новиков",0),("supplier_2","Анна","Кириллова",1),("supplier_3","Виктор","Громов",2)]:
            user, created = User.objects.update_or_create(
                username=username,
                defaults={"first_name": fn, "last_name": ln, "role": RoleChoices.SUPPLIER, "supplier": suppliers[idx], "is_active": True},
            )
            if created:
                user.set_password("demo1234"); user.save()
        self.stdout.write(f"  {len(data)} поставщиков")
 
    def _create_objects(self):
        self.stdout.write("Строительные объекты...")
        objs = [
            {"name": "БЦ «Горизонт» Восточный",      "address": "г. Москва, ул. Профсоюзная, д. 84, корп. 2",           "customer_name": 'ООО "Горизонт Девелопмент"', "customer_name_short": "Горизонт Девелопмент", "customer_tax_id": "7719025777", "customer_kpp": "771901001", "customer_ogrn": "1027739128823", "customer_legal_address": "107023, г. Москва, Мажоров пер., д. 7", "customer_bank": "ПАО Сбербанк",  "customer_bik": "044525225", "customer_account": "40702810538000012345",  "customer_corr_account": "30101810400000000225", "customer_okpo": "12345678", "description": "СМР по электроснабжению бизнес-центра", "start_date": date(2026, 1, 15), "end_date": date(2026, 12, 31)},
            {"name": "ЖК «Северный квартал»",         "address": "г. Москва, Дмитровское шоссе, д. 100",                  "customer_name": 'ООО "Север Девелопмент"',    "customer_name_short": "Север Девелопмент",    "customer_tax_id": "7713098765", "customer_kpp": "771301001", "customer_ogrn": "1187700098765", "customer_legal_address": "125047, г. Москва, ул. Бутырская, д. 12",  "customer_bank": "АО Альфа-Банк", "customer_bik": "044525593", "customer_account": "40702810102000054321",  "customer_corr_account": "30101810200000000593", "customer_okpo": "87654321", "description": "Электромонтажные работы жилого комплекса",      "start_date": date(2026, 3, 1),  "end_date": date(2027, 6, 30)},
            {"name": "Логистический парк «Южный»",    "address": "Московская обл., г. Подольск, ул. Складская, д. 15",    "customer_name": 'АО "ТрансПортИнвест"',       "customer_name_short": "ТрансПортИнвест",      "customer_tax_id": "5036012345", "customer_kpp": "503601001", "customer_ogrn": "1205000012345", "customer_legal_address": "142100, МО, г. Подольск, ул. Кирова, д. 3",                                                                                                                                                                              "description": "Монтаж электрических сетей складского комплекса", "start_date": date(2026, 2, 1),  "end_date": date(2026, 10, 31)},
        ]
        for d in objs:
            ConstructionObject.objects.update_or_create(name=d["name"], defaults=d)
        self.stdout.write(f"  {len(objs)} объектов")
 
    def _create_materials(self):
        self.stdout.write("Материалы...")
        mats = [
            {"code": "MAT-001", "name": "Кабель ВВГнг-LS 3х2.5",             "unit": "м",     "price": Decimal("85.00"),    "stock_reserve_qty": Decimal("50"),  "category": "Кабельная продукция"},
            {"code": "MAT-002", "name": "Кабель ВВГнг-LS 5х4",               "unit": "м",     "price": Decimal("210.00"),   "stock_reserve_qty": Decimal("30"),  "category": "Кабельная продукция"},
            {"code": "MAT-003", "name": "Кабель ВВГнг-LS 5х10",              "unit": "м",     "price": Decimal("480.00"),   "stock_reserve_qty": Decimal("20"),  "category": "Кабельная продукция"},
            {"code": "MAT-004", "name": "Провод ПВС 3х1.5",                  "unit": "м",     "price": Decimal("42.00"),    "stock_reserve_qty": Decimal("20"),  "category": "Кабельная продукция"},
            {"code": "MAT-005", "name": "Кабель-канал 40х25",                "unit": "м",     "price": Decimal("65.00"),    "stock_reserve_qty": Decimal("30"),  "category": "Кабельная продукция"},
            {"code": "MAT-006", "name": "Гофротруба ПНД 25 мм",             "unit": "м",     "price": Decimal("18.50"),    "stock_reserve_qty": Decimal("100"), "category": "Трубы и лотки"},
            {"code": "MAT-007", "name": "Гофротруба ПНД 32 мм",             "unit": "м",     "price": Decimal("24.00"),    "stock_reserve_qty": Decimal("50"),  "category": "Трубы и лотки"},
            {"code": "MAT-008", "name": "Лоток перфорированный 200х50",      "unit": "м",     "price": Decimal("320.00"),   "stock_reserve_qty": Decimal("10"),  "category": "Трубы и лотки"},
            {"code": "MAT-009", "name": "Труба ПВХ гладкая 20 мм",          "unit": "м",     "price": Decimal("15.00"),    "stock_reserve_qty": Decimal("50"),  "category": "Трубы и лотки"},
            {"code": "MAT-010", "name": "Анкер-клин 6х40",                  "unit": "шт",    "price": Decimal("8.50"),     "stock_reserve_qty": Decimal("200"), "category": "Крепёж"},
            {"code": "MAT-011", "name": "Дюбель-гвоздь 6х60",               "unit": "шт",    "price": Decimal("4.20"),     "stock_reserve_qty": Decimal("300"), "category": "Крепёж"},
            {"code": "MAT-012", "name": "Скоба крепёжная 25 мм",            "unit": "шт",    "price": Decimal("3.50"),     "stock_reserve_qty": Decimal("500"), "category": "Крепёж"},
            {"code": "MAT-013", "name": "Хомут стяжка 200 мм",              "unit": "шт",    "price": Decimal("2.10"),     "stock_reserve_qty": Decimal("500"), "category": "Крепёж"},
            {"code": "MAT-014", "name": "Автоматический выключатель 16А",   "unit": "шт",    "price": Decimal("280.00"),   "stock_reserve_qty": Decimal("5"),   "category": "Электроустановочные"},
            {"code": "MAT-015", "name": "Автоматический выключатель 25А",   "unit": "шт",    "price": Decimal("350.00"),   "stock_reserve_qty": Decimal("3"),   "category": "Электроустановочные"},
            {"code": "MAT-016", "name": "УЗО 40А 30мА",                     "unit": "шт",    "price": Decimal("1250.00"),  "stock_reserve_qty": Decimal("2"),   "category": "Электроустановочные"},
            {"code": "MAT-017", "name": "Щит распределительный ЩРН-24",     "unit": "шт",    "price": Decimal("2800.00"),  "stock_reserve_qty": Decimal("1"),   "category": "Электроустановочные"},
            {"code": "MAT-018", "name": "Розетка двойная с заземлением",    "unit": "шт",    "price": Decimal("185.00"),   "stock_reserve_qty": Decimal("10"),  "category": "Электроустановочные"},
            {"code": "MAT-019", "name": "Выключатель одноклавишный",        "unit": "шт",    "price": Decimal("120.00"),   "stock_reserve_qty": Decimal("10"),  "category": "Электроустановочные"},
            {"code": "MAT-020", "name": "Распаячная коробка IP54",          "unit": "шт",    "price": Decimal("65.00"),    "stock_reserve_qty": Decimal("20"),  "category": "Электроустановочные"},
            {"code": "MAT-021", "name": "Светильник LED 36W офисный",       "unit": "шт",    "price": Decimal("1450.00"),  "stock_reserve_qty": Decimal("0"),   "category": "Освещение"},
            {"code": "MAT-022", "name": "Светильник аварийного освещения",  "unit": "шт",    "price": Decimal("980.00"),   "stock_reserve_qty": Decimal("0"),   "category": "Освещение"},
            {"code": "MAT-023", "name": "Светильник LED 18W накладной",     "unit": "шт",    "price": Decimal("650.00"),   "stock_reserve_qty": Decimal("0"),   "category": "Освещение"},
            {"code": "MAT-024", "name": "Коммутатор PoE 8 портов",         "unit": "шт",    "price": Decimal("4500.00"),  "stock_reserve_qty": Decimal("0"),   "category": "Слаботочные системы"},
            {"code": "MAT-025", "name": "Кабель UTP Cat.6",                 "unit": "м",     "price": Decimal("28.00"),    "stock_reserve_qty": Decimal("50"),  "category": "Слаботочные системы"},
            # СИЗ
            {"code": "PPE-001",    "name": "Каска защитная",                           "unit": "шт",    "price": Decimal("450.00"),  "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-002-8",  "name": "Перчатки диэлектрические р.8",            "unit": "пар",   "price": Decimal("380.00"),  "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-002-9",  "name": "Перчатки диэлектрические р.9",            "unit": "пар",   "price": Decimal("380.00"),  "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-002-10", "name": "Перчатки диэлектрические р.10",           "unit": "пар",   "price": Decimal("380.00"),  "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-003-39", "name": "Ботинки рабочие с защитным носком р.39",  "unit": "пар",   "price": Decimal("2800.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-003-40", "name": "Ботинки рабочие с защитным носком р.40",  "unit": "пар",   "price": Decimal("2800.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-003-41", "name": "Ботинки рабочие с защитным носком р.41",  "unit": "пар",   "price": Decimal("2800.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-003-42", "name": "Ботинки рабочие с защитным носком р.42",  "unit": "пар",   "price": Decimal("2800.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-003-43", "name": "Ботинки рабочие с защитным носком р.43",  "unit": "пар",   "price": Decimal("2800.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-003-44", "name": "Ботинки рабочие с защитным носком р.44",  "unit": "пар",   "price": Decimal("2800.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-003-45", "name": "Ботинки рабочие с защитным носком р.45",  "unit": "пар",   "price": Decimal("2800.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-004-48", "name": "Костюм рабочий летний р.48-50/170-176",   "unit": "компл", "price": Decimal("1950.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-004-52", "name": "Костюм рабочий летний р.52-54/170-176",   "unit": "компл", "price": Decimal("1950.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-004-56", "name": "Костюм рабочий летний р.56-58/182-188",   "unit": "компл", "price": Decimal("1950.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-004-96", "name": "Костюм рабочий летний р.96-100/158-164",  "unit": "компл", "price": Decimal("1950.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-005-48", "name": "Костюм рабочий зимний р.48-50/170-176",   "unit": "компл", "price": Decimal("4200.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-005-52", "name": "Костюм рабочий зимний р.52-54/170-176",   "unit": "компл", "price": Decimal("4200.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-005-56", "name": "Костюм рабочий зимний р.56-58/182-188",   "unit": "компл", "price": Decimal("4200.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-005-96", "name": "Костюм рабочий зимний р.96-100/158-164",  "unit": "компл", "price": Decimal("4200.00"), "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
            {"code": "PPE-006",    "name": "Жилет сигнальный",                         "unit": "шт",    "price": Decimal("250.00"),  "stock_reserve_qty": Decimal("0"), "category": "СИЗ", "is_ppe": True},
        ]
        for d in mats:
            Material.objects.update_or_create(code=d["code"], defaults=d)
        self.stdout.write(f"  {len(mats)} материалов")
 
    def _create_workers(self):
        self.stdout.write("Работники...")
        workers = [
            {"full_name": "Сидоров Иван Петрович",       "employee_number": "ТН-001", "site_name": "Участок Север-1", "position": "Электромонтажник 5 разряда", "hire_date": date(2024, 3, 1)},
            {"full_name": "Кузнецов Михаил Андреевич",   "employee_number": "ТН-002", "site_name": "Участок Север-1", "position": "Электромонтажник 4 разряда", "hire_date": date(2024, 5, 15)},
            {"full_name": "Лебедев Олег Сергеевич",      "employee_number": "ТН-003", "site_name": "Участок Север-1", "position": "Электромонтажник 4 разряда", "hire_date": date(2025, 1, 10)},
            {"full_name": "Морозов Артём Николаевич",    "employee_number": "ТН-004", "site_name": "Участок Север-1", "position": "Электромонтажник 3 разряда", "hire_date": date(2025, 4, 20)},
            {"full_name": "Попов Денис Владимирович",    "employee_number": "ТН-005", "site_name": "Участок Север-1", "position": "Подсобный рабочий",          "hire_date": date(2025, 6, 1)},
            {"full_name": "Соловьёв Роман Игоревич",     "employee_number": "ТН-006", "site_name": "Участок Юг-2",    "position": "Электромонтажник 5 разряда", "hire_date": date(2023, 9, 1)},
            {"full_name": "Васильев Николай Дмитриевич", "employee_number": "ТН-007", "site_name": "Участок Юг-2",    "position": "Электромонтажник 4 разряда", "hire_date": date(2024, 2, 1)},
            {"full_name": "Зайцев Владислав Алексеевич", "employee_number": "ТН-008", "site_name": "Участок Юг-2",    "position": "Электромонтажник 3 разряда", "hire_date": date(2024, 8, 15)},
            {"full_name": "Павлов Егор Максимович",      "employee_number": "ТН-009", "site_name": "Участок Юг-2",    "position": "Электромонтажник 3 разряда", "hire_date": date(2025, 3, 1)},
            {"full_name": "Семёнов Антон Викторович",    "employee_number": "ТН-010", "site_name": "Участок Юг-2",    "position": "Подсобный рабочий",          "hire_date": date(2025, 7, 1)},
        ]
        for d in workers:
            Worker.objects.update_or_create(employee_number=d["employee_number"], defaults=d)
        self.stdout.write(f"  {len(workers)} работников")
 
    def _create_norms(self):
        self.stdout.write("Нормы расхода...")
        def mat(code): return Material.objects.get(code=code)
        norms = [
            # Монтаж кабельной трассы (на 1 м трассы)
            {"work_type": "Монтаж кабельной трассы", "material": mat("MAT-001"), "norm_per_unit": Decimal("1.05"),  "unit": "м трассы", "notes": "Кабель ВВГнг 3х2.5 с запасом 5%"},
            {"work_type": "Монтаж кабельной трассы", "material": mat("MAT-006"), "norm_per_unit": Decimal("1.10"),  "unit": "м трассы", "notes": "Гофротруба 25 мм"},
            {"work_type": "Монтаж кабельной трассы", "material": mat("MAT-010"), "norm_per_unit": Decimal("0.25"),  "unit": "м трассы", "notes": "Анкер-клин через каждые 4 м"},
            {"work_type": "Монтаж кабельной трассы", "material": mat("MAT-012"), "norm_per_unit": Decimal("0.30"),  "unit": "м трассы", "notes": "Скобы крепёжные"},
            {"work_type": "Монтаж кабельной трассы", "material": mat("MAT-013"), "norm_per_unit": Decimal("0.50"),  "unit": "м трассы", "notes": "Хомуты стяжки"},
            {"work_type": "Монтаж кабельной трассы", "material": mat("MAT-020"), "norm_per_unit": Decimal("0.03"),  "unit": "м трассы", "notes": "Распаячные коробки"},
            # Монтаж электрощита (на 1 щит)
            {"work_type": "Монтаж электрощита", "material": mat("MAT-017"), "norm_per_unit": Decimal("1.00"),  "unit": "щит", "notes": "Щит ЩРН-24"},
            {"work_type": "Монтаж электрощита", "material": mat("MAT-014"), "norm_per_unit": Decimal("8.00"),  "unit": "щит", "notes": "Автоматы 16А"},
            {"work_type": "Монтаж электрощита", "material": mat("MAT-015"), "norm_per_unit": Decimal("4.00"),  "unit": "щит", "notes": "Автоматы 25А"},
            {"work_type": "Монтаж электрощита", "material": mat("MAT-016"), "norm_per_unit": Decimal("2.00"),  "unit": "щит", "notes": "УЗО"},
            {"work_type": "Монтаж электрощита", "material": mat("MAT-002"), "norm_per_unit": Decimal("15.00"), "unit": "щит", "notes": "Кабель 5х4 для ввода"},
            # Монтаж освещения (на 1 точку)
            {"work_type": "Монтаж освещения", "material": mat("MAT-021"), "norm_per_unit": Decimal("1.00"), "unit": "точка", "notes": "Светильник LED 36W"},
            {"work_type": "Монтаж освещения", "material": mat("MAT-022"), "norm_per_unit": Decimal("0.20"), "unit": "точка", "notes": "Аварийное освещение"},
            {"work_type": "Монтаж освещения", "material": mat("MAT-001"), "norm_per_unit": Decimal("8.00"), "unit": "точка", "notes": "Кабель ВВГнг 3х2.5"},
            {"work_type": "Монтаж освещения", "material": mat("MAT-006"), "norm_per_unit": Decimal("8.50"), "unit": "точка", "notes": "Гофротруба 25 мм"},
            {"work_type": "Монтаж освещения", "material": mat("MAT-019"), "norm_per_unit": Decimal("0.50"), "unit": "точка", "notes": "Выключатели"},
            # Монтаж розеточной сети (на 1 точку)
            {"work_type": "Монтаж розеточной сети", "material": mat("MAT-018"), "norm_per_unit": Decimal("1.00"), "unit": "точка", "notes": "Розетки двойные"},
            {"work_type": "Монтаж розеточной сети", "material": mat("MAT-001"), "norm_per_unit": Decimal("6.00"), "unit": "точка", "notes": "Кабель ВВГнг 3х2.5"},
            {"work_type": "Монтаж розеточной сети", "material": mat("MAT-006"), "norm_per_unit": Decimal("6.25"), "unit": "точка", "notes": "Гофротруба 25 мм"},
            {"work_type": "Монтаж розеточной сети", "material": mat("MAT-020"), "norm_per_unit": Decimal("0.50"), "unit": "точка", "notes": "Распаячные коробки"},
            {"work_type": "Монтаж розеточной сети", "material": mat("MAT-011"), "norm_per_unit": Decimal("3.00"), "unit": "точка", "notes": "Дюбель-гвозди"},
            # Монтаж СКС (на 1 рабочее место)
            {"work_type": "Монтаж СКС", "material": mat("MAT-025"), "norm_per_unit": Decimal("30.00"),  "unit": "раб. место", "notes": "Кабель UTP Cat.6"},
            {"work_type": "Монтаж СКС", "material": mat("MAT-007"), "norm_per_unit": Decimal("30.00"),  "unit": "раб. место", "notes": "Гофротруба 32 мм"},
            {"work_type": "Монтаж СКС", "material": mat("MAT-024"), "norm_per_unit": Decimal("0.125"), "unit": "раб. место", "notes": "Коммутатор на 8 рабочих мест"},
        ]
        for d in norms:
            MaterialNorm.objects.update_or_create(
                work_type=d["work_type"], material=d["material"],
                defaults={"norm_per_unit": d["norm_per_unit"], "unit": d["unit"], "notes": d.get("notes", "")},
            )
        self.stdout.write(f"  {len(norms)} норм расхода")
 
    def _create_work_stages(self):
        self.stdout.write("Этапы работ...")
        stages = {
            "Монтаж кабельной трассы": ["Разметка трасс", "Установка крепежа", "Прокладка кабеля", "Монтаж муфт", "Маркировка и проверка"],
            "Монтаж электрощита":       ["Монтаж корпуса", "Установка автоматов", "Подключение ввода", "Подключение линий", "Наладка"],
            "Монтаж освещения":         ["Разметка светильников", "Прокладка кабелей", "Установка светильников", "Подключение и проверка"],
            "Монтаж розеточной сети":   ["Разметка розеток", "Штробление каналов", "Прокладка кабелей", "Установка розеток", "Проверка"],
            "Монтаж СКС":              ["Прокладка каналов", "Протяжка UTP", "Разделка и обжим", "Монтаж коммутаторов", "Тестирование"],
        }
        for wt, stage_list in stages.items():
            WorkStage.objects.filter(work_type=wt).delete()
            for i, name in enumerate(stage_list, 1):
                WorkStage.objects.create(work_type=wt, stage_name=name, order=i)
        self.stdout.write(f"  {sum(len(v) for v in stages.values())} этапов")
 
    def _create_contracts(self):
        self.stdout.write("Договоры СМР...")
        objects = {o.name: o for o in ConstructionObject.objects.all()}
        admin = User.objects.get(username="admin")
        sm1   = User.objects.get(username="site_manager_1")
        sm2   = User.objects.get(username="site_manager_2")
        sup1, sup2, sup3 = list(Supplier.objects.all())[:3]
 
        contracts_cfg = [
            {"number": "СМР-2026/001", "contract_date": date(2026, 1, 17), "object_name": "БЦ «Горизонт» Восточный",   "subject": "Электромонтажные работы бизнес-центра «Горизонт»",          "amount": Decimal("4250000.00"), "start_date": date(2026, 2, 1),  "end_date": date(2026, 8, 31),  "status": DocumentStatus.APPROVED, "site_manager": sm1, "work_lines": [("Монтаж кабельной трассы","м трассы",Decimal("2500")),("Монтаж электрощита","щит",Decimal("12")),("Монтаж освещения","точка",Decimal("450")),("Монтаж розеточной сети","точка",Decimal("600")),("Монтаж СКС","раб. место",Decimal("120"))]},
            {"number": "СМР-2026/002", "contract_date": date(2026, 3, 5),  "object_name": "ЖК «Северный квартал»",      "subject": "Электромонтажные работы жилого комплекса",                    "amount": Decimal("3900000.00"), "start_date": date(2026, 4, 1),  "end_date": date(2026, 12, 31), "status": DocumentStatus.APPROVED, "site_manager": sm2, "work_lines": [("Монтаж кабельной трассы","м трассы",Decimal("3200")),("Монтаж электрощита","щит",Decimal("18")),("Монтаж освещения","точка",Decimal("600")),("Монтаж розеточной сети","точка",Decimal("800"))]},
            {"number": "СМР-2026/003", "contract_date": date(2026, 2, 20), "object_name": "Логистический парк «Южный»", "subject": "Монтаж электрических сетей складского комплекса",              "amount": Decimal("1850000.00"), "start_date": date(2026, 3, 15), "end_date": date(2026, 9, 30),  "status": DocumentStatus.APPROVED, "site_manager": sm1, "work_lines": [("Монтаж кабельной трассы","м трассы",Decimal("1800")),("Монтаж электрощита","щит",Decimal("6")),("Монтаж освещения","точка",Decimal("350"))]},
            {"number": "СМР-2026/004", "contract_date": date(2026, 5, 10), "object_name": "БЦ «Горизонт» Восточный",   "subject": "Дополнительные электромонтажные работы — серверная комната", "amount": Decimal("850000.00"),  "start_date": date(2026, 6, 1),  "end_date": date(2026, 9, 30),  "status": DocumentStatus.DRAFT,    "site_manager": sm1, "work_lines": [("Монтаж СКС","раб. место",Decimal("40")),("Монтаж электрощита","щит",Decimal("2"))]},
        ]
        self.contracts = {}
        for cfg in contracts_cfg:
            obj = objects[cfg["object_name"]]
            wlines = cfg.pop("work_lines")
            contract, _ = SMRContract.objects.update_or_create(
                number=cfg["number"],
                defaults={"contract_date": cfg["contract_date"], "object": obj, "customer_name": obj.customer_name, "subject": cfg["subject"], "amount": cfg["amount"], "vat_rate": Decimal("20"), "start_date": cfg["start_date"], "end_date": cfg["end_date"], "status": cfg["status"], "site_manager": cfg["site_manager"], "created_by": admin},
            )
            contract.work_lines.all().delete()
            for i, (wt, unit, qty) in enumerate(wlines, 1):
                SMRContractWorkLine.objects.create(contract=contract, work_type=wt, unit=unit, quantity=qty, order=i)
            self.contracts[cfg["number"]] = contract
        self.stdout.write(f"  {len(contracts_cfg)} договоров СМР")
 
        self.stdout.write("Договоры поставки...")
        c001, c002 = self.contracts["СМР-2026/001"], self.contracts["СМР-2026/002"]
        supply_cfgs = [
            {"number": "ДП-2026/001", "date": date(2026, 1, 25), "supplier": sup1, "smr": c001, "amount": Decimal("1200000"), "status": DocumentStatus.APPROVED, "terms": "Поставка в течение 5 рабочих дней по заявке."},
            {"number": "ДП-2026/002", "date": date(2026, 2, 10), "supplier": sup2, "smr": c001, "amount": Decimal("950000"),  "status": DocumentStatus.APPROVED, "terms": "Поставка партиями согласно графику."},
            {"number": "ДП-2026/003", "date": date(2026, 3, 15), "supplier": sup3, "smr": c002, "amount": Decimal("780000"),  "status": DocumentStatus.APPROVED, "terms": "Поставка в течение 7 рабочих дней."},
            {"number": "ДП-2026/004", "date": date(2026, 4, 1),  "supplier": sup1, "smr": c002, "amount": Decimal("500000"),  "status": DocumentStatus.DRAFT,    "terms": "Условия согласовываются."},
        ]
        self.supply_contracts = {}
        for d in supply_cfgs:
            sc, _ = SupplyContract.objects.update_or_create(number=d["number"], defaults={"contract_date": d["date"], "supplier": d["supplier"], "related_smr_contract": d["smr"], "amount": d["amount"], "status": d["status"], "terms": d["terms"]})
            self.supply_contracts[d["number"]] = sc
        self.stdout.write(f"  {len(supply_cfgs)} договоров поставки")
 
    def _create_site_requests(self):
        self.stdout.write("Заявки участков...")
        sm1 = User.objects.get(username="site_manager_1")
        sm2 = User.objects.get(username="site_manager_2")
        c001, c002, c003 = self.contracts["СМР-2026/001"], self.contracts["СМР-2026/002"], self.contracts["СМР-2026/003"]
        def mat(c): return Material.objects.get(code=c)
        self.site_requests = {}
 
        sr1 = SiteMaterialRequest.objects.create(number="ЗУ-2026/001", request_date=date(2026, 2, 3), site_name="Участок Север-1", contract=c001, requested_by=sm1, status=DocumentStatus.APPROVED, notes="Первая заявка. Кабельная трасса, 1-й этап.")
        SiteMaterialRequestLine.objects.bulk_create([
            SiteMaterialRequestLine(request=sr1, material=mat("MAT-001"), quantity=Decimal("2675"), reserve_qty=Decimal("50"),  unit_price=Decimal("85.00")),
            SiteMaterialRequestLine(request=sr1, material=mat("MAT-006"), quantity=Decimal("2850"), reserve_qty=Decimal("100"), unit_price=Decimal("18.50")),
            SiteMaterialRequestLine(request=sr1, material=mat("MAT-010"), quantity=Decimal("825"),  reserve_qty=Decimal("200"), unit_price=Decimal("8.50")),
            SiteMaterialRequestLine(request=sr1, material=mat("MAT-012"), quantity=Decimal("1250"), reserve_qty=Decimal("500"), unit_price=Decimal("3.50")),
            SiteMaterialRequestLine(request=sr1, material=mat("MAT-013"), quantity=Decimal("1750"), reserve_qty=Decimal("500"), unit_price=Decimal("2.10")),
            SiteMaterialRequestLine(request=sr1, material=mat("MAT-020"), quantity=Decimal("95"),   reserve_qty=Decimal("20"),  unit_price=Decimal("65.00")),
        ])
        self.site_requests["ЗУ-2026/001"] = sr1
 
        sr2 = SiteMaterialRequest.objects.create(number="ЗУ-2026/002", request_date=date(2026, 2, 20), site_name="Участок Север-1", contract=c001, requested_by=sm1, status=DocumentStatus.APPROVED, notes="Щиты и освещение.")
        SiteMaterialRequestLine.objects.bulk_create([
            SiteMaterialRequestLine(request=sr2, material=mat("MAT-017"), quantity=Decimal("13"),   reserve_qty=Decimal("1"),  unit_price=Decimal("2800.00")),
            SiteMaterialRequestLine(request=sr2, material=mat("MAT-014"), quantity=Decimal("101"),  reserve_qty=Decimal("5"),  unit_price=Decimal("280.00")),
            SiteMaterialRequestLine(request=sr2, material=mat("MAT-015"), quantity=Decimal("51"),   reserve_qty=Decimal("3"),  unit_price=Decimal("350.00")),
            SiteMaterialRequestLine(request=sr2, material=mat("MAT-016"), quantity=Decimal("26"),   reserve_qty=Decimal("2"),  unit_price=Decimal("1250.00")),
            SiteMaterialRequestLine(request=sr2, material=mat("MAT-021"), quantity=Decimal("450"),  reserve_qty=Decimal("0"),  unit_price=Decimal("1450.00")),
            SiteMaterialRequestLine(request=sr2, material=mat("MAT-022"), quantity=Decimal("90"),   reserve_qty=Decimal("0"),  unit_price=Decimal("980.00")),
        ])
        self.site_requests["ЗУ-2026/002"] = sr2
 
        sr3 = SiteMaterialRequest.objects.create(number="ЗУ-2026/003", request_date=TODAY-timedelta(days=2), site_name="Участок Юг-2", contract=c002, requested_by=sm2, status=DocumentStatus.APPROVAL, notes="Розеточная сеть 1-й этаж.")
        SiteMaterialRequestLine.objects.bulk_create([
            SiteMaterialRequestLine(request=sr3, material=mat("MAT-018"), quantity=Decimal("810"),  reserve_qty=Decimal("10"),  unit_price=Decimal("185.00")),
            SiteMaterialRequestLine(request=sr3, material=mat("MAT-001"), quantity=Decimal("4850"), reserve_qty=Decimal("50"),  unit_price=Decimal("85.00")),
            SiteMaterialRequestLine(request=sr3, material=mat("MAT-006"), quantity=Decimal("5100"), reserve_qty=Decimal("100"), unit_price=Decimal("18.50")),
            SiteMaterialRequestLine(request=sr3, material=mat("MAT-020"), quantity=Decimal("420"),  reserve_qty=Decimal("20"),  unit_price=Decimal("65.00")),
            SiteMaterialRequestLine(request=sr3, material=mat("MAT-011"), quantity=Decimal("2700"), reserve_qty=Decimal("300"), unit_price=Decimal("4.20")),
        ])
        self.site_requests["ЗУ-2026/003"] = sr3
 
        sr4 = SiteMaterialRequest.objects.create(number="ЗУ-2026/004", request_date=date(2026, 3, 18), site_name="Участок Север-1", contract=c003, requested_by=sm1, status=DocumentStatus.REWORK, notes='Возврат: уточните количество кабеля и добавьте позицию по лоткам. — Родионов А.В.')
        SiteMaterialRequestLine.objects.bulk_create([
            SiteMaterialRequestLine(request=sr4, material=mat("MAT-001"), quantity=Decimal("1940"), reserve_qty=Decimal("50"),  unit_price=Decimal("85.00")),
            SiteMaterialRequestLine(request=sr4, material=mat("MAT-006"), quantity=Decimal("2080"), reserve_qty=Decimal("100"), unit_price=Decimal("18.50")),
        ])
        self.site_requests["ЗУ-2026/004"] = sr4
 
        sr5 = SiteMaterialRequest.objects.create(number="ЗУ-2026/005", request_date=TODAY, site_name="Участок Юг-2", contract=c002, requested_by=sm2, status=DocumentStatus.DRAFT)
        SiteMaterialRequestLine.objects.bulk_create([
            SiteMaterialRequestLine(request=sr5, material=mat("MAT-021"), quantity=Decimal("600"), reserve_qty=Decimal("0"),  unit_price=Decimal("1450.00")),
            SiteMaterialRequestLine(request=sr5, material=mat("MAT-022"), quantity=Decimal("120"), reserve_qty=Decimal("0"),  unit_price=Decimal("980.00")),
            SiteMaterialRequestLine(request=sr5, material=mat("MAT-019"), quantity=Decimal("310"), reserve_qty=Decimal("10"), unit_price=Decimal("120.00")),
        ])
        self.site_requests["ЗУ-2026/005"] = sr5
        self.stdout.write("  5 заявок участков")
 
    def _create_procurement_requests(self):
        self.stdout.write("Заявки на закупку...")
        proc = User.objects.get(username="procurement")
        sup1, sup2, sup3 = list(Supplier.objects.all())[:3]
        c001, c002 = self.contracts["СМР-2026/001"], self.contracts["СМР-2026/002"]
        sr1, sr2 = self.site_requests["ЗУ-2026/001"], self.site_requests["ЗУ-2026/002"]
        def mat(c): return Material.objects.get(code=c)
        self.proc_requests = {}
 
        pr1 = ProcurementRequest.objects.create(number="ЗК-2026/001", request_date=date(2026, 2, 5), site_name="Участок Север-1", contract=c001, site_request=sr1, supplier=sup1, requested_by=proc, status=DocumentStatus.APPROVED, notes="Кабельная продукция для 1-го этапа.")
        ProcurementRequestLine.objects.bulk_create([
            ProcurementRequestLine(request=pr1, material=mat("MAT-001"), quantity=Decimal("2675"), unit_price=Decimal("85.00")),
            ProcurementRequestLine(request=pr1, material=mat("MAT-006"), quantity=Decimal("2850"), unit_price=Decimal("18.50")),
            ProcurementRequestLine(request=pr1, material=mat("MAT-010"), quantity=Decimal("825"),  unit_price=Decimal("8.50")),
            ProcurementRequestLine(request=pr1, material=mat("MAT-012"), quantity=Decimal("1250"), unit_price=Decimal("3.50")),
            ProcurementRequestLine(request=pr1, material=mat("MAT-013"), quantity=Decimal("1750"), unit_price=Decimal("2.10")),
        ])
        self.proc_requests["ЗК-2026/001"] = pr1
 
        pr2 = ProcurementRequest.objects.create(number="ЗК-2026/002", request_date=date(2026, 2, 22), site_name="Участок Север-1", contract=c001, site_request=sr2, supplier=sup2, requested_by=proc, status=DocumentStatus.APPROVED, notes="Электроустановочные изделия и светильники.")
        ProcurementRequestLine.objects.bulk_create([
            ProcurementRequestLine(request=pr2, material=mat("MAT-017"), quantity=Decimal("13"),  unit_price=Decimal("2800.00")),
            ProcurementRequestLine(request=pr2, material=mat("MAT-014"), quantity=Decimal("101"), unit_price=Decimal("280.00")),
            ProcurementRequestLine(request=pr2, material=mat("MAT-015"), quantity=Decimal("51"),  unit_price=Decimal("350.00")),
            ProcurementRequestLine(request=pr2, material=mat("MAT-016"), quantity=Decimal("26"),  unit_price=Decimal("1250.00")),
            ProcurementRequestLine(request=pr2, material=mat("MAT-021"), quantity=Decimal("450"), unit_price=Decimal("1450.00")),
        ])
        self.proc_requests["ЗК-2026/002"] = pr2
 
        pr3 = ProcurementRequest.objects.create(number="ЗК-2026/003", request_date=TODAY-timedelta(days=1), site_name="Участок Юг-2", contract=c002, supplier=sup3, requested_by=proc, status=DocumentStatus.APPROVAL, notes="Материалы по ЖК Северный квартал.")
        ProcurementRequestLine.objects.bulk_create([
            ProcurementRequestLine(request=pr3, material=mat("MAT-002"), quantity=Decimal("1200"), unit_price=Decimal("210.00")),
            ProcurementRequestLine(request=pr3, material=mat("MAT-008"), quantity=Decimal("500"),  unit_price=Decimal("320.00")),
            ProcurementRequestLine(request=pr3, material=mat("MAT-025"), quantity=Decimal("3600"), unit_price=Decimal("28.00")),
        ])
        self.proc_requests["ЗК-2026/003"] = pr3
 
        pr4 = ProcurementRequest.objects.create(number="ЗК-2026/004", request_date=TODAY, site_name="Участок Север-1", contract=c001, supplier=sup1, requested_by=proc, status=DocumentStatus.DRAFT)
        ProcurementRequestLine.objects.bulk_create([
            ProcurementRequestLine(request=pr4, material=mat("MAT-024"), quantity=Decimal("15"),   unit_price=Decimal("4500.00")),
            ProcurementRequestLine(request=pr4, material=mat("MAT-025"), quantity=Decimal("1800"), unit_price=Decimal("28.00")),
        ])
        self.proc_requests["ЗК-2026/004"] = pr4
        self.stdout.write("  4 заявки на закупку")
 
    def _create_supplier_documents(self):
        self.stdout.write("Документы поставщиков...")
        sup1, sup2 = list(Supplier.objects.all())[:2]
        u1 = User.objects.get(username="supplier_1")
        u2 = User.objects.get(username="supplier_2")
        pr1, pr2 = self.proc_requests["ЗК-2026/001"], self.proc_requests["ЗК-2026/002"]
        sc1, sc2 = self.supply_contracts["ДП-2026/001"], self.supply_contracts["ДП-2026/002"]
        def mat(c): return Material.objects.get(code=c)
        self.supplier_docs = {}
 
        sd1 = SupplierDocument.objects.create(supplier=sup1, request=pr1, supply_contract=sc1, doc_type="Счёт",             doc_number="ЭК-2026/0215",  doc_date=date(2026, 2, 10), amount=Decimal("513812.50"), vat_amount=Decimal("85635.42"), vat_rate=Decimal("20"), uploaded_by=u1, status=DocumentStatus.SUPPLY_CONFIRMED, notes="Счёт на оплату кабельной продукции.")
        SupplierDocumentLine.objects.bulk_create([SupplierDocumentLine(document=sd1, material=mat("MAT-001"), quantity=Decimal("2675"), unit_price=Decimal("85.00")), SupplierDocumentLine(document=sd1, material=mat("MAT-006"), quantity=Decimal("2850"), unit_price=Decimal("18.50")), SupplierDocumentLine(document=sd1, material=mat("MAT-010"), quantity=Decimal("825"), unit_price=Decimal("8.50"))])
        self.supplier_docs["СЧ-001"] = sd1
 
        sd2 = SupplierDocument.objects.create(supplier=sup1, request=pr1, supply_contract=sc1, doc_type="Товарная накладная", doc_number="ТН-2026/0089",  doc_date=date(2026, 2, 14), amount=Decimal("513812.50"), vat_amount=Decimal("85635.42"), vat_rate=Decimal("20"), uploaded_by=u1, status=DocumentStatus.SUPPLY_CONFIRMED, notes="Накладная по поставке кабельной продукции.")
        SupplierDocumentLine.objects.bulk_create([SupplierDocumentLine(document=sd2, material=mat("MAT-001"), quantity=Decimal("2675"), unit_price=Decimal("85.00")), SupplierDocumentLine(document=sd2, material=mat("MAT-006"), quantity=Decimal("2850"), unit_price=Decimal("18.50")), SupplierDocumentLine(document=sd2, material=mat("MAT-010"), quantity=Decimal("825"), unit_price=Decimal("8.50"))])
        self.supplier_docs["НАК-001"] = sd2
 
        sd3 = SupplierDocument.objects.create(supplier=sup1, request=pr1, supply_contract=sc1, doc_type="Счёт-фактура",      doc_number="СФ-2026/0089",  doc_date=date(2026, 2, 14), amount=Decimal("513812.50"), vat_amount=Decimal("85635.42"), vat_rate=Decimal("20"), uploaded_by=u1, status=DocumentStatus.SUPPLY_CONFIRMED)
        self.supplier_docs["СЧФ-001"] = sd3
 
        sd4 = SupplierDocument.objects.create(supplier=sup2, request=pr2, supply_contract=sc2, doc_type="Счёт",             doc_number="СС-2026/0341",  doc_date=date(2026, 2, 28), amount=Decimal("732600.00"), vat_amount=Decimal("122100.00"), vat_rate=Decimal("20"), uploaded_by=u2, status=DocumentStatus.SUPPLY_CONFIRMED, notes="Электроустановочные изделия и светильники.")
        SupplierDocumentLine.objects.bulk_create([SupplierDocumentLine(document=sd4, material=mat("MAT-017"), quantity=Decimal("13"), unit_price=Decimal("2800.00")), SupplierDocumentLine(document=sd4, material=mat("MAT-014"), quantity=Decimal("101"), unit_price=Decimal("280.00")), SupplierDocumentLine(document=sd4, material=mat("MAT-015"), quantity=Decimal("51"), unit_price=Decimal("350.00")), SupplierDocumentLine(document=sd4, material=mat("MAT-021"), quantity=Decimal("450"), unit_price=Decimal("1450.00"))])
        self.supplier_docs["СЧ-002"] = sd4
 
        sd5 = SupplierDocument.objects.create(supplier=sup2, request=pr2, supply_contract=sc2, doc_type="Товарная накладная", doc_number="ТН-2026/0127", doc_date=date(2026, 3, 2),  amount=Decimal("732600.00"), vat_amount=Decimal("122100.00"), vat_rate=Decimal("20"), uploaded_by=u2, status=DocumentStatus.UPLOADED, notes="Накладная загружена, ожидает проверки снабженца.")
        SupplierDocumentLine.objects.bulk_create([SupplierDocumentLine(document=sd5, material=mat("MAT-017"), quantity=Decimal("13"), unit_price=Decimal("2800.00")), SupplierDocumentLine(document=sd5, material=mat("MAT-021"), quantity=Decimal("450"), unit_price=Decimal("1450.00"))])
        self.supplier_docs["НАК-002"] = sd5
        self.stdout.write("  5 документов поставщиков")
 
    def _create_stock_receipts(self):
        self.stdout.write("Приходные ордера...")
        wh = User.objects.get(username="warehouse")
        sup1, sup2 = list(Supplier.objects.all())[:2]
        sd2, sd4 = self.supplier_docs["НАК-001"], self.supplier_docs["СЧ-002"]
        def mat(c): return Material.objects.get(code=c)
        self.receipts = {}
 
        r1 = StockReceipt.objects.create(number="ПО-2026/001", receipt_date=date(2026, 2, 15), supplier=sup1, supplier_document=sd2, created_by=wh, status=DocumentStatus.APPROVED, notes="Кабельная продукция принята.")
        lines1 = [("MAT-001",Decimal("2675"),Decimal("85.00")),("MAT-006",Decimal("2850"),Decimal("18.50")),("MAT-010",Decimal("825"),Decimal("8.50")),("MAT-012",Decimal("1250"),Decimal("3.50")),("MAT-013",Decimal("1750"),Decimal("2.10")),("MAT-020",Decimal("95"),Decimal("65.00"))]
        StockReceiptLine.objects.bulk_create([StockReceiptLine(receipt=r1, material=mat(c), quantity=q, unit_price=p) for c,q,p in lines1])
        StockMovement.objects.bulk_create([StockMovement(movement_date=date(2026,2,15), material=mat(c), quantity_delta=q, location_name="Центральный склад", source_type="StockReceipt", source_id=r1.id, unit_price=p, created_by=wh) for c,q,p in lines1])
        self.receipts["ПО-2026/001"] = r1
 
        r2 = StockReceipt.objects.create(number="ПО-2026/002", receipt_date=date(2026, 3, 5), supplier=sup2, supplier_document=sd4, created_by=wh, status=DocumentStatus.APPROVED, notes="Электроустановочные и светильники приняты.")
        lines2 = [("MAT-017",Decimal("13"),Decimal("2800.00")),("MAT-014",Decimal("101"),Decimal("280.00")),("MAT-015",Decimal("51"),Decimal("350.00")),("MAT-016",Decimal("26"),Decimal("1250.00")),("MAT-021",Decimal("450"),Decimal("1450.00")),("MAT-022",Decimal("90"),Decimal("980.00"))]
        StockReceiptLine.objects.bulk_create([StockReceiptLine(receipt=r2, material=mat(c), quantity=q, unit_price=p) for c,q,p in lines2])
        StockMovement.objects.bulk_create([StockMovement(movement_date=date(2026,3,5), material=mat(c), quantity_delta=q, location_name="Центральный склад", source_type="StockReceipt", source_id=r2.id, unit_price=p, created_by=wh) for c,q,p in lines2])
        self.receipts["ПО-2026/002"] = r2
 
        r3 = StockReceipt.objects.create(number="ПО-2026/003", receipt_date=TODAY, supplier=sup1, created_by=wh, status=DocumentStatus.DRAFT, notes="Ожидается поставка крепежа.")
        StockReceiptLine.objects.bulk_create([StockReceiptLine(receipt=r3, material=mat("MAT-011"), quantity=Decimal("5000"), unit_price=Decimal("4.20")), StockReceiptLine(receipt=r3, material=mat("MAT-019"), quantity=Decimal("300"), unit_price=Decimal("120.00"))])
        self.receipts["ПО-2026/003"] = r3
        self.stdout.write("  3 приходных ордера")
 
    def _create_stock_issues(self):
        self.stdout.write("Требования-накладные...")
        wh = User.objects.get(username="warehouse")
        c001, c002 = self.contracts["СМР-2026/001"], self.contracts["СМР-2026/002"]
        sr1, sr2 = self.site_requests["ЗУ-2026/001"], self.site_requests["ЗУ-2026/002"]
        r1, r2 = self.receipts["ПО-2026/001"], self.receipts["ПО-2026/002"]
        def mat(c): return Material.objects.get(code=c)
        self.issues = {}
 
        i1 = StockIssue.objects.create(number="ТН-2026/001", issue_date=date(2026,2,18), site_name="Участок Север-1", contract=c001, site_request=sr1, stock_receipt=r1, issued_by=wh, received_by_name="Волков Дмитрий Андреевич", status=DocumentStatus.APPROVED, notes="Отпуск кабельной продукции.")
        li1 = [("MAT-001",Decimal("1500"),Decimal("85.00")),("MAT-006",Decimal("1600"),Decimal("18.50")),("MAT-010",Decimal("400"),Decimal("8.50")),("MAT-012",Decimal("500"),Decimal("3.50")),("MAT-013",Decimal("800"),Decimal("2.10"))]
        StockIssueLine.objects.bulk_create([StockIssueLine(issue=i1, material=mat(c), quantity=q, unit_price=p) for c,q,p in li1])
        mvs = []
        for c,q,p in li1:
            mvs.append(StockMovement(movement_date=date(2026,2,18), material=mat(c), quantity_delta=-q, location_name="Центральный склад", source_type="StockIssue", source_id=i1.id, unit_price=p, created_by=wh))
            mvs.append(StockMovement(movement_date=date(2026,2,18), material=mat(c), quantity_delta=q,  location_name="Участок Север-1",    source_type="StockIssue", source_id=i1.id, unit_price=p, created_by=wh))
        StockMovement.objects.bulk_create(mvs)
        self.issues["ТН-2026/001"] = i1
 
        i2 = StockIssue.objects.create(number="ТН-2026/002", issue_date=date(2026,3,8), site_name="Участок Север-1", contract=c001, site_request=sr2, stock_receipt=r2, issued_by=wh, received_by_name="Волков Дмитрий Андреевич", status=DocumentStatus.APPROVED, notes="Отпуск щитового оборудования и светильников.")
        li2 = [("MAT-017",Decimal("12"),Decimal("2800.00")),("MAT-014",Decimal("96"),Decimal("280.00")),("MAT-015",Decimal("48"),Decimal("350.00")),("MAT-016",Decimal("24"),Decimal("1250.00")),("MAT-021",Decimal("200"),Decimal("1450.00"))]
        StockIssueLine.objects.bulk_create([StockIssueLine(issue=i2, material=mat(c), quantity=q, unit_price=p) for c,q,p in li2])
        mvs2 = []
        for c,q,p in li2:
            mvs2.append(StockMovement(movement_date=date(2026,3,8), material=mat(c), quantity_delta=-q, location_name="Центральный склад", source_type="StockIssue", source_id=i2.id, unit_price=p, created_by=wh))
            mvs2.append(StockMovement(movement_date=date(2026,3,8), material=mat(c), quantity_delta=q,  location_name="Участок Север-1",    source_type="StockIssue", source_id=i2.id, unit_price=p, created_by=wh))
        StockMovement.objects.bulk_create(mvs2)
        self.issues["ТН-2026/002"] = i2
 
        i3 = StockIssue.objects.create(number="ТН-2026/003", issue_date=TODAY-timedelta(days=1), site_name="Участок Юг-2", contract=c002, issued_by=wh, received_by_name="Козлов Андрей Петрович", status=DocumentStatus.APPROVAL, notes="Отпуск кабельной продукции на участок Юг-2.")
        StockIssueLine.objects.bulk_create([StockIssueLine(issue=i3, material=mat("MAT-001"), quantity=Decimal("800"), unit_price=Decimal("85.00")), StockIssueLine(issue=i3, material=mat("MAT-006"), quantity=Decimal("850"), unit_price=Decimal("18.50")), StockIssueLine(issue=i3, material=mat("MAT-022"), quantity=Decimal("90"), unit_price=Decimal("980.00"))])
        self.issues["ТН-2026/003"] = i3
        self.stdout.write("  3 требования-накладных")
 
    def _create_writeoff_acts(self):
        self.stdout.write("Акты списания...")
        sm1 = User.objects.get(username="site_manager_1")
        sm2 = User.objects.get(username="site_manager_2")
        c001, c002 = self.contracts["СМР-2026/001"], self.contracts["СМР-2026/002"]
        def mat(c): return Material.objects.get(code=c)
        self.writeoffs = {}
 
        # АС-001 — ОТПРАВЛЕН В БУХГАЛТЕРИЮ (кабельные трассы, 850 м)
        w1 = WriteOffAct.objects.create(number="АС-2026/001", act_date=date(2026,3,25), contract=c001, site_name="Участок Север-1", work_type="Монтаж кабельной трассы", work_volume=Decimal("850"), volume_unit="м трассы", template_variant="contract", created_by=sm1, status=DocumentStatus.SENT_ACCOUNTING, notes="Списание по кабельным трассам, 1-й этап.")
        wl1 = [("MAT-001",Decimal("1.050"),Decimal("892.50"), Decimal("892.50"), Decimal("85.00")),("MAT-006",Decimal("1.100"),Decimal("935.00"), Decimal("935.00"), Decimal("18.50")),("MAT-010",Decimal("0.250"),Decimal("212.50"), Decimal("212.50"), Decimal("8.50")),("MAT-012",Decimal("0.300"),Decimal("255.00"), Decimal("255.00"), Decimal("3.50")),("MAT-013",Decimal("0.500"),Decimal("425.00"), Decimal("425.00"), Decimal("2.10"))]
        WriteOffLine.objects.bulk_create([WriteOffLine(act=w1, material=mat(c), norm_per_unit=n, calculated_quantity=cq, actual_quantity=aq, unit_price=p) for c,n,cq,aq,p in wl1])
        StockMovement.objects.bulk_create([StockMovement(movement_date=date(2026,3,25), material=mat(c), quantity_delta=-aq, location_name="Участок Север-1", source_type="WriteOffAct", source_id=w1.id, unit_price=p, created_by=sm1) for c,_,_,aq,p in wl1])
        self.writeoffs["АС-2026/001"] = w1
 
        # АС-002 — УТВЕРЖДЁН (монтаж 8 щитов)
        w2 = WriteOffAct.objects.create(number="АС-2026/002", act_date=date(2026,4,10), contract=c001, site_name="Участок Север-1", work_type="Монтаж электрощита", work_volume=Decimal("8"), volume_unit="щит", template_variant="contract", created_by=sm1, status=DocumentStatus.APPROVED, notes="Списание по монтажу 8 щитов.")
        wl2 = [("MAT-017",Decimal("1.000"),Decimal("8.00"),  Decimal("8.00"),  Decimal("2800.00")),("MAT-014",Decimal("8.000"),Decimal("64.00"), Decimal("64.00"), Decimal("280.00")),("MAT-015",Decimal("4.000"),Decimal("32.00"), Decimal("32.00"), Decimal("350.00")),("MAT-016",Decimal("2.000"),Decimal("16.00"), Decimal("16.00"), Decimal("1250.00")),("MAT-002",Decimal("15.000"),Decimal("120.00"),Decimal("120.00"),Decimal("210.00"))]
        WriteOffLine.objects.bulk_create([WriteOffLine(act=w2, material=mat(c), norm_per_unit=n, calculated_quantity=cq, actual_quantity=aq, unit_price=p) for c,n,cq,aq,p in wl2])
        self.writeoffs["АС-2026/002"] = w2
 
        # АС-003 — НА УТВЕРЖДЕНИИ (монтаж освещения, 200 точек)
        w3 = WriteOffAct.objects.create(number="АС-2026/003", act_date=TODAY-timedelta(days=3), contract=c002, site_name="Участок Юг-2", work_type="Монтаж освещения", work_volume=Decimal("200"), volume_unit="точка", template_variant="contract", created_by=sm2, status=DocumentStatus.APPROVAL, notes="Списание по монтажу освещения 200 точек.")
        wl3 = [("MAT-021",Decimal("1.000"),Decimal("200.00"),Decimal("200.00"),Decimal("1450.00")),("MAT-022",Decimal("0.200"),Decimal("40.00"), Decimal("40.00"), Decimal("980.00")),("MAT-001",Decimal("8.000"),Decimal("1600.00"),Decimal("1600.00"),Decimal("85.00")),("MAT-006",Decimal("8.500"),Decimal("1700.00"),Decimal("1700.00"),Decimal("18.50")),("MAT-019",Decimal("0.500"),Decimal("100.00"),Decimal("100.00"),Decimal("120.00"))]
        WriteOffLine.objects.bulk_create([WriteOffLine(act=w3, material=mat(c), norm_per_unit=n, calculated_quantity=cq, actual_quantity=aq, unit_price=p) for c,n,cq,aq,p in wl3])
        self.writeoffs["АС-2026/003"] = w3
 
        # АС-004 — ЧЕРНОВИК (монтаж розеточной сети, 300 точек)
        w4 = WriteOffAct.objects.create(number="АС-2026/004", act_date=TODAY, contract=c001, site_name="Участок Север-1", work_type="Монтаж розеточной сети", work_volume=Decimal("300"), volume_unit="точка", template_variant="contract", created_by=sm1, status=DocumentStatus.DRAFT)
        wl4 = [("MAT-018",Decimal("1.000"),Decimal("300.00"), Decimal("300.00"), Decimal("185.00")),("MAT-001",Decimal("6.000"),Decimal("1800.00"),Decimal("1800.00"),Decimal("85.00")),("MAT-006",Decimal("6.250"),Decimal("1875.00"),Decimal("1875.00"),Decimal("18.50")),("MAT-020",Decimal("0.500"),Decimal("150.00"), Decimal("150.00"), Decimal("65.00")),("MAT-011",Decimal("3.000"),Decimal("900.00"), Decimal("900.00"), Decimal("4.20"))]
        WriteOffLine.objects.bulk_create([WriteOffLine(act=w4, material=mat(c), norm_per_unit=n, calculated_quantity=cq, actual_quantity=aq, unit_price=p) for c,n,cq,aq,p in wl4])
        self.writeoffs["АС-2026/004"] = w4
 
        # АС-005 — ХОЗНУЖДЫ, УТВЕРЖДЁН
        w5 = WriteOffAct.objects.create(number="АС-2026/005", act_date=date(2026,4,30), contract=c001, site_name="Участок Север-1", work_type="Производственно-хозяйственные нужды", work_volume=Decimal("1"), volume_unit="", template_variant="production_economic", created_by=sm1, status=DocumentStatus.APPROVED, notes="Списание остатков крепежа на хозяйственные нужды.")
        WriteOffLine.objects.bulk_create([WriteOffLine(act=w5, material=mat("MAT-013"), norm_per_unit=Decimal("0"), calculated_quantity=Decimal("120"), actual_quantity=Decimal("120"), unit_price=Decimal("2.10")), WriteOffLine(act=w5, material=mat("MAT-020"), norm_per_unit=Decimal("0"), calculated_quantity=Decimal("18"), actual_quantity=Decimal("18"), unit_price=Decimal("65.00"))])
        self.writeoffs["АС-2026/005"] = w5
        self.stdout.write("  5 актов списания")
 
    def _create_acceptance_acts(self):
        self.stdout.write("Акты сдачи-приёмки...")
        sm1 = User.objects.get(username="site_manager_1")
        sm2 = User.objects.get(username="site_manager_2")
        c001, c002 = self.contracts["СМР-2026/001"], self.contracts["СМР-2026/002"]
        WorkAcceptanceAct.objects.create(number="АКТ-2026/001", act_date=date(2026,3,31), contract=c001, site_name="Участок Север-1", work_description="Монтаж кабельных трасс на объекте БЦ «Горизонт», 1-й этап. Выполнено 850 м.", accepted_volume=Decimal("850"), volume_unit="м трасс", amount=Decimal("1445000.00"), created_by=sm1, status=DocumentStatus.SENT_ACCOUNTING)
        WorkAcceptanceAct.objects.create(number="АКТ-2026/002", act_date=date(2026,4,15), contract=c001, site_name="Участок Север-1", work_description="Монтаж электрощитов ЩРН-24 в количестве 8 штук.", accepted_volume=Decimal("8"), volume_unit="щит", amount=Decimal("320000.00"), created_by=sm1, status=DocumentStatus.APPROVED)
        WorkAcceptanceAct.objects.create(number="АКТ-2026/003", act_date=TODAY, contract=c002, site_name="Участок Юг-2", work_description="Монтаж системы освещения, 1-й этаж ЖК «Северный квартал».", accepted_volume=Decimal("200"), volume_unit="точек", amount=Decimal("680000.00"), created_by=sm2, status=DocumentStatus.DRAFT)
        self.stdout.write("  3 акта сдачи-приёмки")
 
    def _create_ppe_issuances(self):
        self.stdout.write("Ведомости выдачи спецодежды...")
        sm1 = User.objects.get(username="site_manager_1")
        sm2 = User.objects.get(username="site_manager_2")
        wh  = User.objects.get(username="warehouse")
        wn1 = list(Worker.objects.filter(site_name="Участок Север-1"))
        wn2 = list(Worker.objects.filter(site_name="Участок Юг-2"))
        def mat(c): return Material.objects.get(code=c)
 
        # ВС-001 — ПОДТВЕРЖДЕНА (летняя, Север-1)
        ppe1 = PPEIssuance.objects.create(number="ВС-2026/001", issue_date=date(2026,4,1), site_name="Участок Север-1", season="Летняя", issued_by=sm1, confirmed_by=wh, confirmed_at=timezone.make_aware(datetime(2026,4,2,10,30)), status=DocumentStatus.APPROVED, notes="Выдача летней рабочей формы на сезон 2026.")
        PPEIssuanceLine.objects.bulk_create([
            PPEIssuanceLine(issuance=ppe1, worker=wn1[0], material=mat("PPE-004-52"), quantity=Decimal("1"), service_life_months=12, issue_start_date=date(2026,4,1), clothing_size="52-54/170-176"),
            PPEIssuanceLine(issuance=ppe1, worker=wn1[1], material=mat("PPE-004-48"), quantity=Decimal("1"), service_life_months=12, issue_start_date=date(2026,4,1), clothing_size="48-50/170-176"),
            PPEIssuanceLine(issuance=ppe1, worker=wn1[2], material=mat("PPE-004-52"), quantity=Decimal("1"), service_life_months=12, issue_start_date=date(2026,4,1), clothing_size="52-54/170-176"),
            PPEIssuanceLine(issuance=ppe1, worker=wn1[0], material=mat("PPE-001"),    quantity=Decimal("1"), service_life_months=24, issue_start_date=date(2026,4,1)),
            PPEIssuanceLine(issuance=ppe1, worker=wn1[1], material=mat("PPE-001"),    quantity=Decimal("1"), service_life_months=24, issue_start_date=date(2026,4,1)),
        ])
        StockMovement.objects.bulk_create([
            StockMovement(movement_date=date(2026,4,2), material=mat("PPE-004-52"), quantity_delta=Decimal("-2"), location_name="Центральный склад", source_type="PPEIssuance", source_id=ppe1.id, unit_price=mat("PPE-004-52").price, created_by=wh),
            StockMovement(movement_date=date(2026,4,2), material=mat("PPE-004-48"), quantity_delta=Decimal("-1"), location_name="Центральный склад", source_type="PPEIssuance", source_id=ppe1.id, unit_price=mat("PPE-004-48").price, created_by=wh),
            StockMovement(movement_date=date(2026,4,2), material=mat("PPE-001"),    quantity_delta=Decimal("-2"), location_name="Центральный склад", source_type="PPEIssuance", source_id=ppe1.id, unit_price=mat("PPE-001").price,    created_by=wh),
        ])
 
        # ВС-002 — ПОДТВЕРЖДЕНА (перчатки, срок истекает через ~23 дня от TODAY)
        ppe2 = PPEIssuance.objects.create(number="ВС-2026/002", issue_date=date(2026,4,1), site_name="Участок Север-1", season="Перчатки", issued_by=sm1, confirmed_by=wh, confirmed_at=timezone.make_aware(datetime(2026,4,2,11,0)), status=DocumentStatus.APPROVED)
        PPEIssuanceLine.objects.bulk_create([
            PPEIssuanceLine(issuance=ppe2, worker=wn1[i], material=mat("PPE-002-9"), quantity=Decimal("2"), service_life_months=3, issue_start_date=date(2026,4,1), shoe_size="9")
            for i in range(4)
        ])
 
        # ВС-003 — НА УТВЕРЖДЕНИИ (Юг-2, летняя)
        ppe3 = PPEIssuance.objects.create(number="ВС-2026/003", issue_date=TODAY-timedelta(days=1), site_name="Участок Юг-2", season="Летняя", issued_by=sm2, status=DocumentStatus.APPROVAL, notes="Ожидает подтверждения кладовщика.")
        PPEIssuanceLine.objects.bulk_create([
            PPEIssuanceLine(issuance=ppe3, worker=wn2[0], material=mat("PPE-004-56"), quantity=Decimal("1"), service_life_months=12, issue_start_date=TODAY, clothing_size="56-58/182-188"),
            PPEIssuanceLine(issuance=ppe3, worker=wn2[1], material=mat("PPE-004-48"), quantity=Decimal("1"), service_life_months=12, issue_start_date=TODAY, clothing_size="48-50/170-176"),
            PPEIssuanceLine(issuance=ppe3, worker=wn2[0], material=mat("PPE-006"),    quantity=Decimal("1"), service_life_months=12, issue_start_date=TODAY),
            PPEIssuanceLine(issuance=ppe3, worker=wn2[1], material=mat("PPE-006"),    quantity=Decimal("1"), service_life_months=12, issue_start_date=TODAY),
        ])
 
        # ВС-004 — ЧЕРНОВИК (зимняя)
        ppe4 = PPEIssuance.objects.create(number="ВС-2026/004", issue_date=TODAY, site_name="Участок Север-1", season="Зимняя", issued_by=sm1, status=DocumentStatus.DRAFT)
        PPEIssuanceLine.objects.bulk_create([
            PPEIssuanceLine(issuance=ppe4, worker=wn1[0], material=mat("PPE-005-52"), quantity=Decimal("1"), service_life_months=36, clothing_size="52-54/170-176"),
            PPEIssuanceLine(issuance=ppe4, worker=wn1[1], material=mat("PPE-005-48"), quantity=Decimal("1"), service_life_months=36, clothing_size="48-50/170-176"),
        ])
        self.stdout.write("  4 ведомости СИЗ")
 
    def _create_work_schedules(self):
        self.stdout.write("Календарные графики...")
        sm1 = User.objects.get(username="site_manager_1")
        sm2 = User.objects.get(username="site_manager_2")
        c001, c002 = self.contracts["СМР-2026/001"], self.contracts["СМР-2026/002"]
 
        sched1 = WorkSchedule.objects.create(number="ГР-2026/001", contract=c001, site_name="Участок Север-1", period_start=date(2026,2,1), period_end=date(2026,8,31), status=DocumentStatus.APPROVED, created_by=sm1, notes="Основной график по БЦ Горизонт.")
        WorkScheduleLine.objects.bulk_create([
            WorkScheduleLine(schedule=sched1,order=1,work_type="Монтаж кабельной трассы",stage="Разметка трасс",      executor="Сидоров И.П.",   start_date=date(2026,2,1), end_date=date(2026,2,10),actual_start=date(2026,2,1), actual_date=date(2026,2,9), actual_notes="В срок"),
            WorkScheduleLine(schedule=sched1,order=2,work_type="Монтаж кабельной трассы",stage="Установка крепежа",   executor="Кузнецов М.А.", start_date=date(2026,2,11),end_date=date(2026,2,20),actual_start=date(2026,2,11),actual_date=date(2026,2,22),actual_notes="Задержка 2 дня"),
            WorkScheduleLine(schedule=sched1,order=3,work_type="Монтаж кабельной трассы",stage="Прокладка кабеля",    executor="Сидоров И.П.",   start_date=date(2026,2,21),end_date=date(2026,3,15),actual_start=date(2026,2,23),actual_date=date(2026,3,18),actual_notes="Отставание 3 дня"),
            WorkScheduleLine(schedule=sched1,order=4,work_type="Монтаж электрощита",      stage="Монтаж корпуса",     executor="Лебедев О.С.",   start_date=date(2026,3,1), end_date=date(2026,3,10),actual_start=date(2026,3,1), actual_date=date(2026,3,10),actual_notes="В срок"),
            WorkScheduleLine(schedule=sched1,order=5,work_type="Монтаж электрощита",      stage="Установка автоматов",executor="Лебедев О.С.",   start_date=date(2026,3,11),end_date=date(2026,3,25),actual_start=date(2026,3,11),actual_date=date(2026,3,24),actual_notes="Досрочно"),
            WorkScheduleLine(schedule=sched1,order=6,work_type="Монтаж освещения",        stage="Установка светильников",executor="Морозов А.Н.",start_date=date(2026,4,1), end_date=date(2026,5,15),actual_start=date(2026,4,3), actual_date=None,            actual_notes="В процессе"),
            WorkScheduleLine(schedule=sched1,order=7,work_type="Монтаж розеточной сети",  stage="Прокладка кабелей",  executor="Попов Д.В.",    start_date=date(2026,5,1), end_date=date(2026,6,30),actual_start=None,            actual_date=None,            actual_notes="Не начато"),
            WorkScheduleLine(schedule=sched1,order=8,work_type="Монтаж СКС",              stage="Протяжка UTP",       executor="Кузнецов М.А.", start_date=date(2026,6,1), end_date=date(2026,7,31),actual_start=None,            actual_date=None,            actual_notes="Ожидает трасс"),
        ])
 
        sched2 = WorkSchedule.objects.create(number="ГР-2026/002", contract=c002, site_name="Участок Юг-2", period_start=date(2026,4,1), period_end=date(2026,12,31), status=DocumentStatus.DRAFT, created_by=sm2)
        WorkScheduleLine.objects.bulk_create([
            WorkScheduleLine(schedule=sched2,order=1,work_type="Монтаж кабельной трассы",stage="Разметка трасс",       executor="Соловьёв Р.И.", start_date=date(2026,4,1), end_date=date(2026,4,15)),
            WorkScheduleLine(schedule=sched2,order=2,work_type="Монтаж кабельной трассы",stage="Прокладка кабеля",     executor="Соловьёв Р.И.", start_date=date(2026,4,16),end_date=date(2026,6,30)),
            WorkScheduleLine(schedule=sched2,order=3,work_type="Монтаж освещения",        stage="Установка светильников",executor="Васильев Н.Д.",start_date=date(2026,5,1), end_date=date(2026,8,31)),
        ])
        self.stdout.write("  2 графика")
 
    def _create_work_logs(self):
        self.stdout.write("Журнал работ...")
        sm1 = User.objects.get(username="site_manager_1")
        sm2 = User.objects.get(username="site_manager_2")
        c001, c002 = self.contracts["СМР-2026/001"], self.contracts["СМР-2026/002"]
        logs = [
            {"site":"Участок Север-1","contract":c001,"wt":"Монтаж кабельной трассы","stage":"Разметка трасс",   "plan":Decimal("200"),"actual":Decimal("195"),"unit":"м трассы","plan_date":date(2026,2,10),"actual_date":date(2026,2,9), "status":"Выполнено","by":sm1},
            {"site":"Участок Север-1","contract":c001,"wt":"Монтаж кабельной трассы","stage":"Установка крепежа","plan":Decimal("200"),"actual":Decimal("180"),"unit":"м трассы","plan_date":date(2026,2,20),"actual_date":date(2026,2,22),"status":"Выполнено","by":sm1},
            {"site":"Участок Север-1","contract":c001,"wt":"Монтаж кабельной трассы","stage":"Прокладка кабеля", "plan":Decimal("250"),"actual":Decimal("260"),"unit":"м трассы","plan_date":date(2026,3,15),"actual_date":date(2026,3,18),"status":"Выполнено","by":sm1},
            {"site":"Участок Север-1","contract":c001,"wt":"Монтаж кабельной трассы","stage":"Прокладка кабеля", "plan":Decimal("250"),"actual":Decimal("215"),"unit":"м трассы","plan_date":date(2026,4,10),"actual_date":date(2026,4,12),"status":"Выполнено","by":sm1},
            {"site":"Участок Север-1","contract":c001,"wt":"Монтаж кабельной трассы","stage":"Прокладка кабеля", "plan":Decimal("300"),"actual":Decimal("310"),"unit":"м трассы","plan_date":date(2026,5,15),"actual_date":date(2026,5,14),"status":"Выполнено","by":sm1},
            {"site":"Участок Север-1","contract":c001,"wt":"Монтаж кабельной трассы","stage":"Прокладка кабеля", "plan":Decimal("300"),"actual":Decimal("290"),"unit":"м трассы","plan_date":date(2026,6,1), "actual_date":TODAY-timedelta(days=5),"status":"Выполнено","by":sm1},
            {"site":"Участок Север-1","contract":c001,"wt":"Монтаж электрощита",      "stage":"Монтаж корпуса",  "plan":Decimal("4"),  "actual":Decimal("4"),  "unit":"щит",     "plan_date":date(2026,3,10),"actual_date":date(2026,3,10),"status":"Выполнено","by":sm1},
            {"site":"Участок Север-1","contract":c001,"wt":"Монтаж электрощита",      "stage":"Установка автоматов","plan":Decimal("4"),"actual":Decimal("4"), "unit":"щит",     "plan_date":date(2026,3,25),"actual_date":date(2026,3,24),"status":"Выполнено","by":sm1},
            {"site":"Участок Север-1","contract":c001,"wt":"Монтаж электрощита",      "stage":"Наладка",         "plan":Decimal("4"),  "actual":Decimal("3"),  "unit":"щит",     "plan_date":date(2026,4,15),"actual_date":TODAY-timedelta(days=2),"status":"Выполнено","by":sm1},
            {"site":"Участок Юг-2",   "contract":c002,"wt":"Монтаж кабельной трассы","stage":"Разметка трасс",   "plan":Decimal("300"),"actual":Decimal("280"),"unit":"м трассы","plan_date":date(2026,4,15),"actual_date":date(2026,4,18),"status":"Выполнено","by":sm2},
            {"site":"Участок Юг-2",   "contract":c002,"wt":"Монтаж кабельной трассы","stage":"Прокладка кабеля", "plan":Decimal("400"),"actual":Decimal("370"),"unit":"м трассы","plan_date":date(2026,5,31),"actual_date":date(2026,6,3), "status":"Выполнено","by":sm2},
            {"site":"Участок Юг-2",   "contract":c002,"wt":"Монтаж освещения",        "stage":"Установка светильников","plan":Decimal("1000"),"actual":Decimal("0"),"unit":"точка","plan_date":date(2026,6,30),"actual_date":None,"status":"Запланировано","by":sm2},
        ]
        WorkLog.objects.bulk_create([WorkLog(site_name=d["site"],contract=d["contract"],work_type=d["wt"],stage=d["stage"],planned_volume=d["plan"],actual_volume=d["actual"],volume_unit=d["unit"],plan_date=d["plan_date"],actual_date=d["actual_date"],status=d["status"],created_by=d["by"]) for d in logs])
        self.stdout.write(f"  {len(logs)} записей журнала работ")
 
    def _create_notifications(self):
        self.stdout.write("Уведомления...")
        director  = User.objects.get(username="director")
        sm1       = User.objects.get(username="site_manager_1")
        warehouse = User.objects.get(username="warehouse")
        proc      = User.objects.get(username="procurement")
        notifs = [
            Notification(user=director, kind=NotificationType.ACTION_REQUIRED, title="Заявка участка ожидает утверждения",    message="ЗУ-2026/003 от участка Юг-2 ожидает утверждения.",            entity_type="SiteMaterialRequest", entity_id=SiteMaterialRequest.objects.get(number="ЗУ-2026/003").id),
            Notification(user=director, kind=NotificationType.ACTION_REQUIRED, title="Заявка на закупку ожидает утверждения", message="ЗК-2026/003 ожидает утверждения.",                              entity_type="ProcurementRequest",  entity_id=ProcurementRequest.objects.get(number="ЗК-2026/003").id),
            Notification(user=director, kind=NotificationType.ACTION_REQUIRED, title="Акт списания ожидает утверждения",      message="АС-2026/003 (участок Юг-2) ожидает утверждения.",              entity_type="WriteOffAct",         entity_id=WriteOffAct.objects.get(number="АС-2026/003").id),
            Notification(user=director, kind=NotificationType.ACTION_REQUIRED, title="Требование-накладная ожидает утверждения", message="ТН-2026/003 на участок Юг-2 ожидает утверждения.",          entity_type="StockIssue",          entity_id=StockIssue.objects.get(number="ТН-2026/003").id),
            Notification(user=sm1,      kind=NotificationType.STATUS_CHANGED,  title="Заявка возвращена на доработку",        message='ЗУ-2026/004 возвращена. Уточните количество кабеля и добавьте позицию по лоткам.', entity_type="SiteMaterialRequest", entity_id=SiteMaterialRequest.objects.get(number="ЗУ-2026/004").id),
            Notification(user=warehouse,kind=NotificationType.ACTION_REQUIRED, title="Ведомость СИЗ ожидает подтверждения",   message="ВС-2026/003 по участку Юг-2 ожидает подтверждения.",          entity_type="PPEIssuance",         entity_id=PPEIssuance.objects.get(number="ВС-2026/003").id),
            Notification(user=sm1,      kind=NotificationType.ACTION_REQUIRED, title="Истекает срок службы СИЗ",              message="Перчатки диэлектрические (ВС-2026/002, 4 работника) — до замены 23 дня.", entity_type="PPEIssuance", entity_id=PPEIssuance.objects.get(number="ВС-2026/002").id),
            Notification(user=proc,     kind=NotificationType.DOCUMENT_CREATED,title="Поставщик загрузил накладную",          message='ООО "СтройСнаб Групп" загрузил ТН-2026/0127. Требуется проверка.', entity_type="SupplierDocument", entity_id=SupplierDocument.objects.get(doc_number="ТН-2026/0127").id),
        ]
        Notification.objects.bulk_create(notifs)
        self.stdout.write(f"  {len(notifs)} уведомлений")