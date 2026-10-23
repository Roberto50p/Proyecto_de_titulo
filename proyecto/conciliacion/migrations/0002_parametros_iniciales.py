from django.db import migrations

EQUIVALENCIAS = [
    ("RCO", "DEBITO"), ("RCO", "PREPAGO"),
    ("V$", "CREDITO"), ("MC$", "CREDITO"), ("AME$", "CREDITO"), ("D$", "CREDITO"),
]


def cargar(apps, schema_editor):
    apps.get_model("conciliacion", "ParametrosSistema").objects.get_or_create(pk=1)
    Equivalencia = apps.get_model("conciliacion", "EquivalenciaMedio")
    for cod_deb, medio in EQUIVALENCIAS:
        Equivalencia.objects.get_or_create(cod_deb=cod_deb, medio=medio)


def quitar(apps, schema_editor):
    apps.get_model("conciliacion", "EquivalenciaMedio").objects.all().delete()
    apps.get_model("conciliacion", "ParametrosSistema").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("conciliacion", "0001_initial")]
    operations = [migrations.RunPython(cargar, quitar)]
