from django.contrib.postgres.operations import CreateExtension
from django.contrib.gis.db import models
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0002_enable_rls"),
    ]

    operations = [
        CreateExtension("postgis"),
        migrations.AddField(
            model_name="customer",
            name="location",
            field=models.PointField(blank=True, null=True, srid=4326),
        ),
    ]
