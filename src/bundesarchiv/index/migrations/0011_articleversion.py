from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("index", "0010_articleindex_media_hashes"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArticleVersion",
            fields=[
                (
                    "pk",
                    models.CompositePrimaryKey(
                        "ulid",
                        "version",
                        blank=True,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("ulid", models.TextField()),
                ("version", models.IntegerField()),
                ("changed_at", models.DateTimeField(null=True)),
                ("changed_by", models.TextField(null=True)),
            ],
        ),
    ]
