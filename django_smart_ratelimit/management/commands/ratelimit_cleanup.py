"""Management command to clean up expired rate limit records from the database."""

import json
import time
from argparse import ArgumentParser
from typing import Any, Dict

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    """
    Clean up expired rate limit records from the database.

    This command removes expired rate limit counters, sliding window entries,
    stale token buckets, and stale leaky buckets from the database. It's
    designed to be run periodically via cron or celery beat.

    Examples:
        # Basic cleanup
        python manage.py ratelimit_cleanup

        # Preview what would be deleted (dry run)
        python manage.py ratelimit_cleanup --dry-run

        # Custom batch size for large databases
        python manage.py ratelimit_cleanup --batch-size=500

        # Clean up stale buckets older than 14 days
        python manage.py ratelimit_cleanup --stale-days=14

        # JSON output for monitoring/automation
        python manage.py ratelimit_cleanup --json

        # Verbose output with progress
        python manage.py ratelimit_cleanup --verbose
    """

    help = "Clean up expired rate limit records from the database"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Add command arguments."""
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of records to delete per batch (default: 1000)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )
        parser.add_argument(
            "--stale-days",
            type=int,
            default=7,
            help="Delete token/leaky buckets not updated in this many days (default: 7)",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output results in JSON format",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed progress information",
        )

    def handle(self, *_args: str, **options: Any) -> None:
        """Handle the command."""
        batch_size: int = options.get("batch_size", 1000)
        dry_run: bool = options.get("dry_run", False)
        stale_days: int = options.get("stale_days", 7)
        json_output: bool = options.get("json", False)
        verbose: bool = options.get("verbose", False)

        start_time = time.time()

        if dry_run and not json_output:
            self.stdout.write(
                self.style.WARNING("DRY RUN - No records will be deleted")
            )
            self.stdout.write("")

        results: Dict[str, Any] = {
            "dry_run": dry_run,
            "batch_size": batch_size,
            "stale_days": stale_days,
            "counters": {"deleted": 0, "found": 0},
            "entries": {"deleted": 0, "found": 0},
            "token_buckets": {"deleted": 0, "found": 0},
            "leaky_buckets": {"deleted": 0, "found": 0},
            "errors": [],
        }

        # Clean up counters (fixed window)
        try:
            counter_result = self._cleanup_counters(
                batch_size, dry_run, verbose, json_output
            )
            results["counters"] = counter_result
        except Exception as e:
            results["errors"].append(f"Counter cleanup error: {e}")
            if not json_output:
                self.stdout.write(self.style.ERROR(f"Counter cleanup failed: {e}"))

        # Clean up entries (sliding window)
        try:
            entry_result = self._cleanup_entries(
                batch_size, dry_run, verbose, json_output
            )
            results["entries"] = entry_result
        except Exception as e:
            results["errors"].append(f"Entry cleanup error: {e}")
            if not json_output:
                self.stdout.write(self.style.ERROR(f"Entry cleanup failed: {e}"))

        # Clean up stale token buckets
        try:
            bucket_result = self._cleanup_token_buckets(
                batch_size, stale_days, dry_run, verbose, json_output
            )
            results["token_buckets"] = bucket_result
        except Exception as e:
            results["errors"].append(f"Token bucket cleanup error: {e}")
            if not json_output:
                self.stdout.write(self.style.ERROR(f"Token bucket cleanup failed: {e}"))

        # Clean up stale leaky buckets
        try:
            leaky_result = self._cleanup_leaky_buckets(
                batch_size, stale_days, dry_run, verbose, json_output
            )
            results["leaky_buckets"] = leaky_result
        except Exception as e:
            results["errors"].append(f"Leaky bucket cleanup error: {e}")
            if not json_output:
                self.stdout.write(self.style.ERROR(f"Leaky bucket cleanup failed: {e}"))

        elapsed_time = time.time() - start_time
        results["elapsed_seconds"] = round(elapsed_time, 3)

        # Calculate totals
        total_found = (
            results["counters"]["found"]
            + results["entries"]["found"]
            + results["token_buckets"]["found"]
            + results["leaky_buckets"]["found"]
        )
        total_deleted = (
            results["counters"]["deleted"]
            + results["entries"]["deleted"]
            + results["token_buckets"]["deleted"]
            + results["leaky_buckets"]["deleted"]
        )
        results["total_found"] = total_found
        results["total_deleted"] = total_deleted

        if json_output:
            self.stdout.write(json.dumps(results, indent=2))
        else:
            self._print_summary(results, dry_run)

    def _cleanup_counters(
        self, batch_size: int, dry_run: bool, verbose: bool, json_output: bool
    ) -> Dict[str, int]:
        """Clean up expired rate limit counters."""
        from django_smart_ratelimit.models import RateLimitCounter

        now = timezone.now()
        expired_query = RateLimitCounter.objects.filter(window_end__lt=now)
        found = expired_query.count()

        if not json_output and verbose:
            self.stdout.write(f"Counters: Found {found} expired records")

        if dry_run:
            return {"found": found, "deleted": 0}

        deleted = 0
        while True:
            expired_ids = list(expired_query.values_list("id", flat=True)[:batch_size])
            if not expired_ids:
                break

            batch_deleted, _ = RateLimitCounter.objects.filter(
                id__in=expired_ids
            ).delete()
            deleted += batch_deleted

            if verbose and not json_output:
                self.stdout.write(f"  Deleted batch: {batch_deleted} counters")

            if batch_deleted < batch_size:
                break

        return {"found": found, "deleted": deleted}

    def _cleanup_entries(
        self, batch_size: int, dry_run: bool, verbose: bool, json_output: bool
    ) -> Dict[str, int]:
        """Clean up expired sliding window entries."""
        from django_smart_ratelimit.models import RateLimitEntry

        now = timezone.now()
        expired_query = RateLimitEntry.objects.filter(expires_at__lt=now)
        found = expired_query.count()

        if not json_output and verbose:
            self.stdout.write(f"Entries: Found {found} expired records")

        if dry_run:
            return {"found": found, "deleted": 0}

        deleted = 0
        while True:
            expired_ids = list(expired_query.values_list("id", flat=True)[:batch_size])
            if not expired_ids:
                break

            batch_deleted, _ = RateLimitEntry.objects.filter(
                id__in=expired_ids
            ).delete()
            deleted += batch_deleted

            if verbose and not json_output:
                self.stdout.write(f"  Deleted batch: {batch_deleted} entries")

            if batch_deleted < batch_size:
                break

        return {"found": found, "deleted": deleted}

    def _cleanup_token_buckets(
        self,
        batch_size: int,
        stale_days: int,
        dry_run: bool,
        verbose: bool,
        json_output: bool,
    ) -> Dict[str, int]:
        """Clean up stale token buckets."""
        from datetime import timedelta

        from django_smart_ratelimit.models import RateLimitTokenBucket

        cutoff = timezone.now() - timedelta(days=stale_days)
        stale_query = RateLimitTokenBucket.objects.filter(last_update__lt=cutoff)
        found = stale_query.count()

        if not json_output and verbose:
            self.stdout.write(
                f"Token Buckets: Found {found} stale records (>{stale_days} days old)"
            )

        if dry_run:
            return {"found": found, "deleted": 0}

        deleted = 0
        while True:
            stale_ids = list(stale_query.values_list("id", flat=True)[:batch_size])
            if not stale_ids:
                break

            batch_deleted, _ = RateLimitTokenBucket.objects.filter(
                id__in=stale_ids
            ).delete()
            deleted += batch_deleted

            if verbose and not json_output:
                self.stdout.write(f"  Deleted batch: {batch_deleted} token buckets")

            if batch_deleted < batch_size:
                break

        return {"found": found, "deleted": deleted}

    def _cleanup_leaky_buckets(
        self,
        batch_size: int,
        stale_days: int,
        dry_run: bool,
        verbose: bool,
        json_output: bool,
    ) -> Dict[str, int]:
        """Clean up stale leaky buckets."""
        from datetime import timedelta

        from django_smart_ratelimit.models import RateLimitLeakyBucket

        cutoff = timezone.now() - timedelta(days=stale_days)
        stale_query = RateLimitLeakyBucket.objects.filter(last_leak__lt=cutoff)
        found = stale_query.count()

        if not json_output and verbose:
            self.stdout.write(
                f"Leaky Buckets: Found {found} stale records (>{stale_days} days old)"
            )

        if dry_run:
            return {"found": found, "deleted": 0}

        deleted = 0
        while True:
            stale_ids = list(stale_query.values_list("id", flat=True)[:batch_size])
            if not stale_ids:
                break

            batch_deleted, _ = RateLimitLeakyBucket.objects.filter(
                id__in=stale_ids
            ).delete()
            deleted += batch_deleted

            if verbose and not json_output:
                self.stdout.write(f"  Deleted batch: {batch_deleted} leaky buckets")

            if batch_deleted < batch_size:
                break

        return {"found": found, "deleted": deleted}

    def _print_summary(self, results: Dict[str, Any], dry_run: bool) -> None:
        """Print a summary of the cleanup operation."""
        self.stdout.write("")
        self.stdout.write("=" * 50)
        action = "Would delete" if dry_run else "Deleted"

        self.stdout.write(
            f"Counters:      {action} {results['counters']['deleted']} "
            f"(found {results['counters']['found']})"
        )
        self.stdout.write(
            f"Entries:       {action} {results['entries']['deleted']} "
            f"(found {results['entries']['found']})"
        )
        self.stdout.write(
            f"Token Buckets: {action} {results['token_buckets']['deleted']} "
            f"(found {results['token_buckets']['found']})"
        )
        self.stdout.write(
            f"Leaky Buckets: {action} {results['leaky_buckets']['deleted']} "
            f"(found {results['leaky_buckets']['found']})"
        )
        self.stdout.write("=" * 50)
        self.stdout.write(
            f"Total: {action} {results['total_deleted']} records "
            f"in {results['elapsed_seconds']:.3f}s"
        )

        if results["errors"]:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("Errors:"))
            for error in results["errors"]:
                self.stdout.write(self.style.ERROR(f"  - {error}"))

        if dry_run:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "This was a dry run. Run without --dry-run to delete records."
                )
            )
        elif results["total_deleted"] > 0:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Cleanup completed successfully."))
