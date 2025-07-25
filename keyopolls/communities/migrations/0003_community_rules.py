# Generated by Django 5.2.3 on 2025-07-02 19:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "communities",
            "0002_community_avatar_community_banner_community_category_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="community",
            name="rules",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="List of community rules. Each rule should be between 10 and 280 characters.",
            ),
        ),
    ]
