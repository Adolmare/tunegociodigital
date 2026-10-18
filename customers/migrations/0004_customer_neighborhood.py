from django.db import migrations, models


def move_imported_neighborhoods(apps, schema_editor):
    Customer = apps.get_model("customers", "Customer")
    database = schema_editor.connection.alias
    prefix = "Zona del Excel: "
    customers = Customer._base_manager.using(database).filter(notes__startswith=prefix)
    for customer in customers.iterator():
        zones = customer.notes[len(prefix):].split("; ")
        if len(zones) == 1 and zones[0]:
            customer.neighborhood = zones[0]
            customer.save(using=database, update_fields=["neighborhood"])


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0003_customer_location"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="neighborhood",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.RunPython(
            move_imported_neighborhoods,
            migrations.RunPython.noop,
        ),
    ]
