from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("index", "0011_articleversion"),
    ]

    operations = [
        migrations.AddField(
            model_name="articleversion",
            name="difference",
            field=models.JSONField(null=True),
        ),
    ]
