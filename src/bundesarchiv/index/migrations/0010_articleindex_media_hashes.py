import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("index", "0009_mediatext"),
    ]

    operations = [
        migrations.AddField(
            model_name="articleindex",
            name="media_hashes",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.TextField(), default=list
            ),
        ),
    ]
