# Generated by Django 5.2.3 on 2025-07-27 19:37

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("polls", "0011_auratransaction_communitystreak_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auratransaction",
            name="description",
            field=models.CharField(blank=True),
        ),
        migrations.AlterField(
            model_name="polloption",
            name="text",
            field=models.CharField(blank=True),
        ),
    ]
