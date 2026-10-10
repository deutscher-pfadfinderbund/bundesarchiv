from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("index", "0007_drop_collection_id_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="articleindex",
            name="is_template",
            field=models.BooleanField(default=False),
        ),
    ]
