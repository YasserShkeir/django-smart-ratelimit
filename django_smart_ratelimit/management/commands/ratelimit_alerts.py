"""Management command: alert on rate-limit offenders (roadmap 4.3.4).

Finds keys whose blocked-request count over a window exceeds a threshold and
dispatches email and/or webhook alerts. Intended to run on a schedule (cron /
celery beat), e.g. every few minutes::

    python manage.py ratelimit_alerts --threshold 100 --days 1

Thresholds and channels default to the ``RATELIMIT_ALERT_THRESHOLD`` /
``RATELIMIT_ALERT_EMAILS`` / ``RATELIMIT_ALERT_WEBHOOK`` settings when the
corresponding flags are omitted.
"""

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Dispatch alerts for rate-limit offenders over a threshold."""

    help = "Alert (email/webhook) on rate-limit offenders over a threshold."

    def add_arguments(self, parser: Any) -> None:
        """Register the threshold/window/dry-run options."""
        parser.add_argument(
            "--threshold",
            type=int,
            default=None,
            help="Min blocked requests to alert on (default: RATELIMIT_ALERT_THRESHOLD).",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=1,
            help="Look-back window in days (default 1).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List matching offenders without sending any alert.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Find offenders over the threshold and (unless dry-run) alert."""
        from django_smart_ratelimit.analytics import (
            find_alertable_offenders,
            send_offender_alerts,
        )

        days = max(1, int(options["days"]))
        threshold = options["threshold"]

        if options["dry_run"]:
            if not threshold:
                self.stdout.write(
                    self.style.WARNING(
                        "No --threshold and RATELIMIT_ALERT_THRESHOLD unset; "
                        "nothing to do."
                    )
                )
                return
            offenders = find_alertable_offenders(int(threshold), days=days)
            self.stdout.write(
                f"{len(offenders)} offender(s) >= {threshold} blocked in "
                f"{days} day(s):"
            )
            for row in offenders:
                self.stdout.write(f"  {row['key']}: {row['blocked_count']}")
            return

        result = send_offender_alerts(threshold=threshold, days=days)
        if not result["enabled"]:
            self.stdout.write(
                self.style.WARNING(
                    "Alerting disabled (set --threshold or RATELIMIT_ALERT_THRESHOLD)."
                )
            )
            return

        offenders = result["offenders"]
        channels = result.get("channels", {})
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(offenders)} offender(s) over threshold {result['threshold']}; "
                f"channels: {channels or 'none configured'}"
            )
        )
