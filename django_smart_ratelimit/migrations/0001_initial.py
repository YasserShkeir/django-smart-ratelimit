"""Initial migration for Django Smart Ratelimit v2.0 database models.

This migration creates the database tables for:
- RateLimitCounter: Fixed window rate limiting
- RateLimitEntry: Sliding window rate limiting
- RateLimitTokenBucket: Token bucket algorithm state
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Initial migration for rate limit models."""

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="RateLimitCounter",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "key",
                    models.CharField(
                        db_index=True,
                        help_text="Rate limit key (e.g., 'ip:192.168.1.1', 'user:42')",
                        max_length=255,
                    ),
                ),
                (
                    "count",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Number of requests in this window",
                    ),
                ),
                (
                    "window_start",
                    models.DateTimeField(
                        help_text="Start timestamp of the rate limit window",
                    ),
                ),
                (
                    "window_end",
                    models.DateTimeField(
                        db_index=True,
                        help_text="End timestamp of the rate limit window (for cleanup queries)",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When this counter was first created",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="When this counter was last updated",
                    ),
                ),
            ],
            options={
                "verbose_name": "Rate Limit Counter",
                "verbose_name_plural": "Rate Limit Counters",
                "db_table": "ratelimit_counter",
                "unique_together": {("key", "window_start")},
            },
        ),
        migrations.CreateModel(
            name="RateLimitEntry",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "key",
                    models.CharField(
                        db_index=True,
                        help_text="Rate limit key",
                        max_length=255,
                    ),
                ),
                (
                    "timestamp",
                    models.DateTimeField(
                        db_index=True,
                        help_text="Timestamp of the request",
                    ),
                ),
                (
                    "expires_at",
                    models.DateTimeField(
                        db_index=True,
                        help_text="When this entry should be cleaned up",
                    ),
                ),
            ],
            options={
                "verbose_name": "Rate Limit Entry",
                "verbose_name_plural": "Rate Limit Entries",
                "db_table": "ratelimit_entry",
            },
        ),
        migrations.CreateModel(
            name="RateLimitTokenBucket",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "key",
                    models.CharField(
                        help_text="Rate limit key (unique per bucket)",
                        max_length=255,
                        unique=True,
                    ),
                ),
                (
                    "tokens",
                    models.FloatField(
                        help_text="Current number of tokens in the bucket",
                    ),
                ),
                (
                    "last_update",
                    models.DateTimeField(
                        help_text="When the bucket was last updated",
                    ),
                ),
                (
                    "bucket_size",
                    models.PositiveIntegerField(
                        help_text="Maximum capacity of the bucket",
                    ),
                ),
                (
                    "refill_rate",
                    models.FloatField(
                        help_text="Tokens added per second",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When this bucket was created",
                    ),
                ),
            ],
            options={
                "verbose_name": "Rate Limit Token Bucket",
                "verbose_name_plural": "Rate Limit Token Buckets",
                "db_table": "ratelimit_token_bucket",
            },
        ),
        # Add indexes for RateLimitCounter
        migrations.AddIndex(
            model_name="ratelimitcounter",
            index=models.Index(
                fields=["key", "window_start"],
                name="ratelimit_counter_key_win",
            ),
        ),
        migrations.AddIndex(
            model_name="ratelimitcounter",
            index=models.Index(
                fields=["window_end"],
                name="ratelimit_counter_win_end",
            ),
        ),
        # Add indexes for RateLimitEntry
        migrations.AddIndex(
            model_name="ratelimitentry",
            index=models.Index(
                fields=["key", "timestamp"],
                name="ratelimit_entry_key_ts",
            ),
        ),
        migrations.AddIndex(
            model_name="ratelimitentry",
            index=models.Index(
                fields=["expires_at"],
                name="ratelimit_entry_expires",
            ),
        ),
        # Add indexes for RateLimitTokenBucket
        migrations.AddIndex(
            model_name="ratelimittokenbucket",
            index=models.Index(
                fields=["key"],
                name="ratelimit_bucket_key",
            ),
        ),
    ]
