from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0033_stockmovement_contract"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(blank=True, max_length=255, verbose_name="Наименование организации")),
                ("tax_id", models.CharField(blank=True, max_length=32, verbose_name="ИНН")),
                ("kpp", models.CharField(blank=True, max_length=32, verbose_name="КПП")),
                ("ogrn", models.CharField(blank=True, max_length=32, verbose_name="ОГРН")),
                ("address", models.CharField(blank=True, max_length=512, verbose_name="Адрес")),
                ("bank_name", models.CharField(blank=True, max_length=255, verbose_name="Банк")),
                ("bik", models.CharField(blank=True, max_length=32, verbose_name="БИК")),
                ("account", models.CharField(blank=True, max_length=64, verbose_name="Расчётный счёт")),
                ("corr_account", models.CharField(blank=True, max_length=64, verbose_name="Корреспондентский счёт")),
                ("okpo", models.CharField(blank=True, max_length=32, verbose_name="ОКПО")),
                ("bank_details", models.TextField(blank=True, verbose_name="Банковские реквизиты (текстом)")),
                ("requisites", models.TextField(blank=True, verbose_name="Реквизиты (текстом)")),
                ("contractor_signer_name", models.CharField(blank=True, max_length=255, verbose_name="ФИО подписанта")),
                ("contractor_signer_position", models.CharField(blank=True, max_length=255, verbose_name="Должность подписанта")),
                ("contractor_signer_name_genitive", models.CharField(blank=True, max_length=255, verbose_name="ФИО подписанта (родительный падеж)")),
                ("contractor_signer_position_genitive", models.CharField(blank=True, max_length=255, verbose_name="Должность подписанта (родительный падеж)")),
                ("contractor_auth_doc", models.CharField(blank=True, max_length=255, verbose_name="Документ полномочий")),
            ],
            options={"verbose_name": "Профиль организации"},
        ),
    ]