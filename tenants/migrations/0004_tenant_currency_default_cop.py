from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0003_enable_rls"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenant",
            name="currency",
            field=models.CharField(default="COP", max_length=3),
        ),
    ]
