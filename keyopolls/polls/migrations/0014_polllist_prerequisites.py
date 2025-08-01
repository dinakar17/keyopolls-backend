# Generated by Django 5.2.3 on 2025-07-29 14:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("polls", "0013_polllist_polllistcollaborator_polllistitem_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="polllist",
            name="prerequisites",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Optional prerequisites for viewing this list (e.g., must follow community)",
            ),
        ),
    ]
