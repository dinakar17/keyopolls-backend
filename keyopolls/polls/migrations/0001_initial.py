# Generated by Django 5.2.3 on 2025-06-30 14:30

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("communities", "0001_initial"),
        ("profile", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Poll",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                (
                    "poll_type",
                    models.CharField(
                        choices=[
                            ("single", "Single Choice"),
                            ("multiple", "Multiple Choice"),
                            ("ranking", "Ranking Poll"),
                        ],
                        default="single",
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("active", "Active"),
                            ("closed", "Closed"),
                            ("archived", "Archived"),
                        ],
                        default="active",
                        max_length=20,
                    ),
                ),
                ("is_pinned", models.BooleanField(default=False)),
                ("allow_multiple_votes", models.BooleanField(default=False)),
                ("max_choices", models.PositiveIntegerField(blank=True, null=True)),
                ("requires_aura", models.PositiveIntegerField(default=0)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("total_votes", models.PositiveIntegerField(default=0)),
                ("total_voters", models.PositiveIntegerField(default=0)),
                ("option_count", models.PositiveIntegerField(default=0)),
                ("view_count", models.PositiveIntegerField(default=0)),
                ("comment_count", models.PositiveIntegerField(default=0)),
                ("share_count", models.PositiveIntegerField(default=0)),
                ("bookmark_count", models.PositiveIntegerField(default=0)),
                ("like_count", models.PositiveIntegerField(default=0)),
                ("dislike_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False)),
                (
                    "community",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="polls",
                        to="communities.community",
                    ),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="polls",
                        to="profile.pseudonymousprofile",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="PollOption",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("text", models.CharField(blank=True, max_length=200)),
                (
                    "image",
                    models.ImageField(blank=True, null=True, upload_to="poll_options/"),
                ),
                ("order", models.PositiveIntegerField(default=0)),
                ("vote_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "poll",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="options",
                        to="polls.poll",
                    ),
                ),
            ],
            options={
                "ordering": ["order"],
            },
        ),
        migrations.CreateModel(
            name="PollVote",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("rank", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "option",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="votes",
                        to="polls.polloption",
                    ),
                ),
                (
                    "poll",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="votes",
                        to="polls.poll",
                    ),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="poll_votes",
                        to="profile.pseudonymousprofile",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="poll",
            index=models.Index(
                fields=["profile", "-created_at"], name="polls_poll_profile_ddfa81_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="poll",
            index=models.Index(
                fields=["community", "-created_at"],
                name="polls_poll_communi_93bb8e_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="poll",
            index=models.Index(
                fields=["community", "is_pinned", "-created_at"],
                name="polls_poll_communi_39e390_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="poll",
            index=models.Index(
                fields=["status", "-created_at"], name="polls_poll_status_1abc97_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="poll",
            index=models.Index(
                fields=["poll_type", "-created_at"],
                name="polls_poll_poll_ty_1d9219_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="poll",
            index=models.Index(
                fields=["expires_at"], name="polls_poll_expires_0c4433_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="poll",
            index=models.Index(
                fields=["-total_votes"], name="polls_poll_total_v_19c0d8_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="poll",
            index=models.Index(
                fields=["is_deleted", "status"], name="polls_poll_is_dele_73e3aa_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="polloption",
            index=models.Index(
                fields=["poll", "order"], name="polls_pollo_poll_id_0d29f4_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="polloption",
            index=models.Index(
                fields=["poll", "-vote_count"], name="polls_pollo_poll_id_ff6e34_idx"
            ),
        ),
        migrations.AlterUniqueTogether(
            name="polloption",
            unique_together={("poll", "order")},
        ),
        migrations.AddIndex(
            model_name="pollvote",
            index=models.Index(
                fields=["poll", "profile"], name="polls_pollv_poll_id_37e927_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="pollvote",
            index=models.Index(
                fields=["option", "-created_at"], name="polls_pollv_option__3e1df7_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="pollvote",
            index=models.Index(
                fields=["profile", "-created_at"], name="polls_pollv_profile_ee69d0_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="pollvote",
            index=models.Index(
                fields=["poll", "option", "profile"],
                name="polls_pollv_poll_id_76cc5d_idx",
            ),
        ),
    ]
