from django.db import migrations, models


def copiar_archivo(apps, schema_editor):
    """Cada pago queda asociado al bordero con que se registró."""
    PagoBordero = apps.get_model("conciliacion", "PagoBordero")
    Relacion = PagoBordero.archivos.through
    Relacion.objects.bulk_create([
        Relacion(pagobordero_id=pago_id, archivocargado_id=archivo_id)
        for pago_id, archivo_id in PagoBordero.objects.filter(archivo__isnull=False).values_list("id", "archivo_id")
    ])


class Migration(migrations.Migration):

    dependencies = [
        ('conciliacion', '0004_formatos_octubre_y_parametros'),
    ]

    operations = [
        migrations.AddField(
            model_name='conciliacion',
            name='observaciones',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='pagobordero',
            name='archivos',
            field=models.ManyToManyField(blank=True, related_name='pagos_incluidos', to='conciliacion.archivocargado'),
        ),
        migrations.RunPython(copiar_archivo, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='pagobordero',
            name='archivo',
        ),
        migrations.AlterField(
            model_name='pagobordero',
            name='archivos',
            field=models.ManyToManyField(blank=True, related_name='pagos', to='conciliacion.archivocargado'),
        ),
    ]
