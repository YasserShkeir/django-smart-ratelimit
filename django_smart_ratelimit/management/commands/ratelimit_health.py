"""Management command to check rate limiting backend health."""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

from django_smart_ratelimit.backends import get_backend


class Command(BaseCommand):
    """
    Check rate limiting backend health status.

    This command checks the health of configured rate limiting backends
    and provides status information for monitoring purposes.

    Examples:
        # Basic health check
        python manage.py ratelimit_health

        # Detailed health check with verbose output
        python manage.py ratelimit_health --verbose

        # JSON output for monitoring scripts
        python manage.py ratelimit_health --json

        # Combined verbose and JSON output
        python manage.py ratelimit_health --verbose --json
    """

    help = "Check the health of rate limiting backends"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Add command arguments."""
        parser.add_argument(
            "--verbose",
            action="store_true",
            help=(
                "Show detailed backend information including last check times "
                "and configurations"
            ),
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help=(
                "Output results in JSON format (useful for monitoring scripts "
                "and automation)"
            ),
        )

    def handle(self, *args: str, **options: dict) -> None:
        """Handle the command."""
        verbose: bool = bool(options.get("verbose", False))
        json_output: bool = bool(options.get("json", False))

        try:
            backend = get_backend()

            if hasattr(backend, "get_backend_status"):
                # Multi-backend
                self.check_multi_backend(backend, verbose, json_output)
            else:
                # Single backend
                self.check_single_backend(backend, verbose, json_output)

        except Exception as e:
            if json_output:
                import json

                output = {"error": str(e), "healthy": False}
                self.stdout.write(json.dumps(output, indent=2))
            else:
                self.stdout.write(self.style.ERROR(f"Failed to get backend: {e}"))
            return

    def check_single_backend(
        self, backend: Any, verbose: bool, json_output: bool
    ) -> None:
        """Check health of a single backend."""
        try:
            # Simple health check
            test_key = "_health_check_test"
            backend.get_count(test_key)
            healthy = True
            error = None
        except Exception as e:
            healthy = False
            error = str(e)

        if json_output:
            import json

            output = {
                "type": "single-backend",
                "backend_class": backend.__class__.__name__,
                "healthy": healthy,
                "error": error,
            }

            # Add MongoDB specific information
            if backend.__class__.__name__ == "MongoDBBackend":
                try:
                    from django_smart_ratelimit.backends.mongodb import MongoDBBackend

                    if isinstance(backend, MongoDBBackend):
                        mongo_info = {
                            "algorithm": backend.config.get(
                                "algorithm", "sliding_window"
                            ),
                            "database": backend.config.get("database", "ratelimit"),
                            "host": backend.config.get("host", "localhost"),
                            "port": backend.config.get("port", 27017),
                        }
                        output.update(mongo_info)

                        if verbose:
                            try:
                                stats = backend.get_stats()
                                output["stats"] = stats
                            except Exception as e:
                                output["stats_error"] = str(e)
                except ImportError:
                    output["mongodb_error"] = "pymongo not installed"

            self.stdout.write(json.dumps(output, indent=2))
        else:
            self.stdout.write(f"Backend: {backend.__class__.__name__}")

            if healthy:
                self.stdout.write(self.style.SUCCESS("✓ Backend is healthy"))
            else:
                self.stdout.write(self.style.ERROR(f"✗ Backend is unhealthy: {error}"))

            if verbose:
                self.stdout.write(f"  Type: {backend.__class__.__name__}")

                # Add MongoDB specific verbose information
                if backend.__class__.__name__ == "MongoDBBackend":
                    try:
                        from django_smart_ratelimit.backends.mongodb import (
                            MongoDBBackend,
                        )

                        if isinstance(backend, MongoDBBackend):
                            algo = backend.config.get("algorithm", "sliding_window")
                            self.stdout.write(f"  Algorithm: {algo}")
                            db = backend.config.get("database", "ratelimit")
                            self.stdout.write(f"  Database: {db}")
                            host = backend.config.get("host", "localhost")
                            self.stdout.write(f"  Host: {host}")
                            self.stdout.write(
                                f"  Port: {backend.config.get('port', 27017)}"
                            )

                            try:
                                stats = backend.get_stats()
                                total_docs = stats.get("total_documents", "N/A")
                                self.stdout.write(f"  Total Documents: {total_docs}")
                                collection = stats.get("collection", "N/A")
                                self.stdout.write(f"  Collection: {collection}")
                            except Exception as e:
                                self.stdout.write(f"  Stats Error: {e}")
                    except ImportError:
                        self.stdout.write("  Warning: pymongo not installed")

    def check_multi_backend(
        self, backend: Any, verbose: bool, json_output: bool
    ) -> None:
        """Check health of a multi-backend."""
        try:
            status = backend.get_backend_status()
            stats = backend.get_stats()

            if json_output:
                import json

                output = {
                    "type": "multi-backend",
                    "stats": stats,
                    "backends": status,
                    "healthy": stats["healthy_backends"] > 0,
                }
                self.stdout.write(json.dumps(output, indent=2))
            else:
                self.stdout.write(f"Total backends: {stats['total_backends']}")
                self.stdout.write(f"Healthy backends: {stats['healthy_backends']}")
                self.stdout.write(f"Fallback strategy: {stats['fallback_strategy']}")
                self.stdout.write("")

                for name, info in status.items():
                    if info["healthy"]:
                        self.stdout.write(self.style.SUCCESS(f"✓ {name}"))
                    else:
                        self.stdout.write(self.style.ERROR(f"✗ {name}"))

                    if verbose:
                        self.stdout.write(f"    Class: {info['backend_class']}")
                        self.stdout.write(f"    Last check: {info['last_check']}")
                        self.stdout.write("")

        except Exception as e:
            if json_output:
                import json

                output = {"error": str(e), "healthy": False}
                self.stdout.write(json.dumps(output, indent=2))
            else:
                self.stdout.write(
                    self.style.ERROR(f"Failed to check multi-backend: {e}")
                )
