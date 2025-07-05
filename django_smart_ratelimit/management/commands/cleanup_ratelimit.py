"""
Management command to clean up expired rate limit entries.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import transaction
from django.conf import settings

from ...models import RateLimitEntry, RateLimitCounter


class Command(BaseCommand):
    help = "Clean up expired rate limit entries from the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Show what would be deleted without actually deleting",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of records to delete in each batch (default: 1000)",
        )
        parser.add_argument(
            "--older-than",
            type=int,
            default=0,
            help="Delete entries older than N hours (default: 0 = expired entries only)",
        )
        parser.add_argument(
            "--key-pattern",
            type=str,
            help="Only clean entries matching this key pattern (supports wildcards)",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Enable verbose output",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        older_than = options["older_than"]
        key_pattern = options["key_pattern"]
        verbose = options["verbose"]

        if verbose:
            self.stdout.write(self.style.SUCCESS(f"Starting cleanup with options:"))
            self.stdout.write(f"  Dry run: {dry_run}")
            self.stdout.write(f"  Batch size: {batch_size}")
            self.stdout.write(f"  Older than: {older_than} hours")
            self.stdout.write(f'  Key pattern: {key_pattern or "all"}')

        now = timezone.now()
        cutoff_time = now

        if older_than > 0:
            cutoff_time = now - timezone.timedelta(hours=older_than)
            if verbose:
                self.stdout.write(f"  Cutoff time: {cutoff_time}")

        # Clean up rate limit entries
        entries_cleaned = self._cleanup_entries(
            cutoff_time, key_pattern, batch_size, dry_run, verbose
        )

        # Clean up rate limit counters
        counters_cleaned = self._cleanup_counters(
            cutoff_time, key_pattern, batch_size, dry_run, verbose
        )

        # Summary
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would delete {entries_cleaned} entries "
                    f"and {counters_cleaned} counters"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Cleaned up {entries_cleaned} entries "
                    f"and {counters_cleaned} counters"
                )
            )

    def _cleanup_entries(self, cutoff_time, key_pattern, batch_size, dry_run, verbose):
        """Clean up rate limit entries."""
        if cutoff_time == timezone.now():
            # Only expired entries
            queryset = RateLimitEntry.objects.filter(expires_at__lt=cutoff_time)
        else:
            # Entries older than cutoff_time (regardless of expiration)
            queryset = RateLimitEntry.objects.filter(timestamp__lt=cutoff_time)

        if key_pattern:
            if "*" in key_pattern:
                # Simple wildcard support
                key_pattern = key_pattern.replace("*", "%")
                queryset = queryset.extra(where=["key LIKE %s"], params=[key_pattern])
            else:
                queryset = queryset.filter(key=key_pattern)

        total_count = queryset.count()

        if verbose:
            self.stdout.write(f"Found {total_count} expired entries to clean")

        if dry_run:
            return total_count

        cleaned_count = 0

        while True:
            with transaction.atomic():
                # Get a batch of IDs to delete
                batch_ids = list(queryset.values_list("id", flat=True)[:batch_size])

                if not batch_ids:
                    break

                # Delete the batch
                deleted_count = RateLimitEntry.objects.filter(
                    id__in=batch_ids
                ).delete()[0]

                cleaned_count += deleted_count

                if verbose:
                    self.stdout.write(
                        f"Deleted batch: {deleted_count} entries "
                        f"(total: {cleaned_count}/{total_count})"
                    )

        return cleaned_count

    def _cleanup_counters(self, cutoff_time, key_pattern, batch_size, dry_run, verbose):
        """Clean up rate limit counters."""
        if cutoff_time == timezone.now():
            # Only expired counters
            queryset = RateLimitCounter.objects.filter(window_end__lt=cutoff_time)
        else:
            # Counters older than cutoff_time (regardless of window)
            queryset = RateLimitCounter.objects.filter(created_at__lt=cutoff_time)

        if key_pattern:
            if "*" in key_pattern:
                # Simple wildcard support
                key_pattern = key_pattern.replace("*", "%")
                queryset = queryset.extra(where=["key LIKE %s"], params=[key_pattern])
            else:
                queryset = queryset.filter(key=key_pattern)

        total_count = queryset.count()

        if verbose:
            self.stdout.write(f"Found {total_count} expired counters to clean")

        if dry_run:
            return total_count

        cleaned_count = 0

        while True:
            with transaction.atomic():
                # Get a batch of IDs to delete
                batch_ids = list(queryset.values_list("id", flat=True)[:batch_size])

                if not batch_ids:
                    break

                # Delete the batch
                deleted_count = RateLimitCounter.objects.filter(
                    id__in=batch_ids
                ).delete()[0]

                cleaned_count += deleted_count

                if verbose:
                    self.stdout.write(
                        f"Deleted batch: {deleted_count} counters "
                        f"(total: {cleaned_count}/{total_count})"
                    )

        return cleaned_count
