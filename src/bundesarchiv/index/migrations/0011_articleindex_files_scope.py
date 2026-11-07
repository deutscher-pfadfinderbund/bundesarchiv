import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("index", "0010_articleindex_media_hashes"),
    ]

    operations = [
        migrations.AddField(
            model_name="articleindex",
            name="files_archivist_only",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="articleindex",
            name="files_groups",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.TextField(), default=list
            ),
        ),
        migrations.AddField(
            model_name="articleindex",
            name="files_tier",
            field=models.TextField(null=True),
        ),
    ]
