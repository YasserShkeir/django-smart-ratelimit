"""Widen counter/bucket integer fields to BigInteger.

``count`` (fixed-window), ``bucket_size`` (token bucket) and ``bucket_capacity``
(leaky bucket) were ``PositiveIntegerField`` (max 2**31-1), so a very large limit
overflowed on PostgreSQL/MySQL. Widening to ``PositiveBigIntegerField`` (max
2**63-1) is a safe column widening with no data loss.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Alter count / bucket_size / bucket_capacity to PositiveBigIntegerField."""

    dependencies = [
        ("django_smart_ratelimit", "0002_ratelimitleakybucket"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ratelimitcounter",
            name="count",
            field=models.PositiveBigIntegerField(
                default=0, help_text="Number of requests in this window"
            ),
        ),
        migrations.AlterField(
            model_name="ratelimitleakybucket",
            name="bucket_capacity",
            field=models.PositiveBigIntegerField(
                help_text="Maximum capacity of the bucket"
            ),
        ),
        migrations.AlterField(
            model_name="ratelimittokenbucket",
            name="bucket_size",
            field=models.PositiveBigIntegerField(
                help_text="Maximum capacity of the bucket"
            ),
        ),
    ]
