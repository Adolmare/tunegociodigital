import django.contrib.auth.validators
import django.db.models
import django.utils.text
from django.db import migrations


def populate_usernames(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    database = schema_editor.connection.alias
    used_usernames = set()

    for user in User.objects.using(database).order_by("pk").iterator(chunk_size=500):
        base_username = django.utils.text.slugify(user.email.partition("@")[0]) or "usuario"
        username = base_username[:150]
        suffix = 1
        while username in used_usernames:
            suffix_text = f"-{suffix}"
            username = f"{base_username[:150 - len(suffix_text)]}{suffix_text}"
            suffix += 1
        User.objects.using(database).filter(pk=user.pk).update(username=username)
        used_usernames.add(username)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="username",
            field=django.db.models.CharField(max_length=150, null=True, unique=True),
        ),
        migrations.RunPython(populate_usernames, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="username",
            field=django.db.models.CharField(
                max_length=150,
                unique=True,
                validators=[django.contrib.auth.validators.UnicodeUsernameValidator()],
            ),
        ),
    ]
