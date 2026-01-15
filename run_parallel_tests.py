#!/usr/bin/env python3
"""
Parallel Test Runner with Live Table Display

Runs tox environments or docker matrix tests in parallel with a real-time
table view showing the status of each worker.

Usage:
    ./run_parallel_tests.py tox              # Run tox in parallel
    ./run_parallel_tests.py tox --fast       # Skip benchmarks and slow tests
    ./run_parallel_tests.py docker           # Run docker matrix in parallel
    ./run_parallel_tests.py docker --fast    # Quick docker verification
"""

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional


# ANSI color codes
class Colors:
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Background colors
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"

    # Bright foreground
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_CYAN = "\033[96m"


class Status(Enum):
    """Test execution status."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkerState:
    """State of a single test worker."""

    name: str
    status: Status = Status.PENDING
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    current_test: str = ""
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0
    last_output_line: str = ""
    log_lines: List[str] = field(default_factory=list)
    exit_code: Optional[int] = None
    failure_lines: List[str] = field(default_factory=list)
    in_failure_section: bool = False
    _seen_summary: bool = False


class LiveTableDisplay:
    """Real-time table display for parallel test execution."""

    def __init__(self, workers: List[str], show_logs: bool = False) -> None:
        """Initialize the live table display.

        Args:
            workers: List of worker names to display.
            show_logs: Whether to show detailed logs.
        """
        self.workers: Dict[str, WorkerState] = {
            name: WorkerState(name=name) for name in workers
        }
        self.lock = threading.Lock()
        self.running = True
        self.show_logs = show_logs
        self.start_time = datetime.now()
        self._display_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the display refresh thread."""
        self._display_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._display_thread.start()

    def stop(self) -> None:
        """Stop the display refresh."""
        self.running = False
        if self._display_thread:
            self._display_thread.join(timeout=1)

    def update(self, worker_name: str, **kwargs: object) -> None:
        """Update a worker's state."""
        with self.lock:
            if worker_name in self.workers:
                worker = self.workers[worker_name]
                for key, value in kwargs.items():
                    if hasattr(worker, key):
                        setattr(worker, key, value)

    def add_log_line(self, worker_name: str, line: str) -> None:
        """Add a log line for a worker."""
        with self.lock:
            if worker_name in self.workers:
                worker = self.workers[worker_name]
                worker.log_lines.append(line)
                # Keep only last 100 lines per worker
                if len(worker.log_lines) > 100:
                    worker.log_lines = worker.log_lines[-100:]

                # Only update last_output_line for meaningful lines
                stripped = line.strip()
                if stripped and not stripped.startswith("Backend operation"):
                    worker.last_output_line = stripped[:60]

                # Parse test progress
                self._parse_progress(worker, line)

    def _parse_progress(self, worker: WorkerState, line: str) -> None:
        """Parse pytest output to extract progress."""
        stripped = line.strip()

        # Parse final summary line like "495 passed, 83 skipped" or "5 failed, 10 passed"
        # This line contains multiple stats and should override accumulated counts
        if re.search(r"\d+\s+(passed|failed|skipped)", line) and (
            "passed" in line or "failed" in line
        ):
            summary_match = re.search(r"(\d+)\s+passed", line)
            if summary_match:
                worker.tests_passed = int(summary_match.group(1))
                worker._seen_summary = True

            skipped_match = re.search(r"(\d+)\s+skipped", line)
            if skipped_match:
                worker.tests_skipped = int(skipped_match.group(1))

            failed_match = re.search(r"(\d+)\s+failed", line)
            if failed_match:
                worker.tests_failed = int(failed_match.group(1))
            elif worker._seen_summary:
                # If we see a summary with passed but no failed, reset failed to 0
                worker.tests_failed = 0

        # Only do incremental counting if we haven't hit a summary yet
        elif not worker._seen_summary:
            # Match verbose patterns like "tests/file.py::TestClass::test_name PASSED"
            if " PASSED" in line.upper() and "::" in line:
                worker.tests_passed += 1
            elif " FAILED" in line.upper() and "::" in line:
                worker.tests_failed += 1
            elif " SKIPPED" in line.upper() and "::" in line:
                worker.tests_skipped += 1

            # Match pytest-xdist compact format (usually just percentage)
            # Count dots/s/F only on lines that look like test output
            if re.match(r"^[.\ssFxE]+$", stripped) and len(stripped) > 5:
                for char in stripped:
                    if char == ".":
                        worker.tests_passed += 1
                    elif char == "s":
                        worker.tests_skipped += 1
                    elif char in "FxE":
                        worker.tests_failed += 1

        # Extract current test name
        test_match = re.search(r"(test_\w+)", line)
        if test_match:
            worker.current_test = test_match.group(1)[:25]

        # Detect success messages
        if "congratulations" in line.lower() or ": OK" in line:
            worker.status = Status.PASSED

        # Capture failure details
        if "FAILED" in line and "::" in line:
            # This is a failed test line like "FAILED tests/unit/test_foo.py::TestClass::test_method"
            worker.failure_lines.append(stripped)
            worker.in_failure_section = True
        elif "short test summary" in line.lower():
            worker.in_failure_section = True
        elif worker.in_failure_section and stripped.startswith("FAILED"):
            worker.failure_lines.append(stripped)
        elif "======" in line and worker.in_failure_section:
            worker.in_failure_section = False

    def _get_status_icon(self, status: Status) -> str:
        """Get colored status icon."""
        icons = {
            Status.PENDING: f"{Colors.DIM}⏳{Colors.RESET}",
            Status.RUNNING: f"{Colors.BRIGHT_CYAN}🔄{Colors.RESET}",
            Status.PASSED: f"{Colors.BRIGHT_GREEN}✅{Colors.RESET}",
            Status.FAILED: f"{Colors.BRIGHT_RED}❌{Colors.RESET}",
            Status.SKIPPED: f"{Colors.YELLOW}⏭️{Colors.RESET}",
        }
        return icons.get(status, "❓")

    def _get_duration(self, worker: WorkerState) -> str:
        """Get formatted duration string."""
        if worker.started_at is None:
            return "--:--"

        end_time = worker.finished_at or datetime.now()
        duration = end_time - worker.started_at
        minutes = int(duration.total_seconds() // 60)
        seconds = int(duration.total_seconds() % 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _get_progress_bar(self, worker: WorkerState, width: int = 15) -> str:
        """Get a simple progress indicator."""
        total = worker.tests_passed + worker.tests_failed + worker.tests_skipped
        if total == 0:
            return f"{Colors.DIM}{'─' * width}{Colors.RESET}"

        # Animated progress for running
        if worker.status == Status.RUNNING:
            filled = int(time.time() * 2) % width
            bar = "─" * filled + "▶" + "─" * (width - filled - 1)
            return f"{Colors.CYAN}{bar}{Colors.RESET}"

        return f"{Colors.GREEN}{'█' * min(total, width)}{Colors.RESET}"

    def _render_table(self) -> str:
        """Render the current state as a table."""
        lines = []

        # Header
        elapsed = datetime.now() - self.start_time
        elapsed_str = str(timedelta(seconds=int(elapsed.total_seconds())))

        lines.append("")
        lines.append(f"{Colors.BOLD}{Colors.CYAN}╔{'═' * 90}╗{Colors.RESET}")
        lines.append(
            f"{Colors.BOLD}{Colors.CYAN}║{Colors.RESET}  {Colors.BOLD}PARALLEL TEST RUNNER{Colors.RESET}  │  Elapsed: {Colors.YELLOW}{elapsed_str}{Colors.RESET}  │  Workers: {Colors.CYAN}{len(self.workers)}{Colors.RESET}".ljust(
                100
            )
            + f"{Colors.BOLD}{Colors.CYAN}║{Colors.RESET}"
        )
        lines.append(f"{Colors.BOLD}{Colors.CYAN}╠{'═' * 90}╣{Colors.RESET}")

        # Column headers
        header = f"{'Worker':<25} {'Status':<8} {'Time':<7} {'Pass':<6} {'Fail':<6} {'Skip':<6} {'Current Activity':<25}"
        lines.append(
            f"{Colors.BOLD}{Colors.CYAN}║{Colors.RESET} {Colors.BOLD}{header}{Colors.RESET} {Colors.BOLD}{Colors.CYAN}║{Colors.RESET}"
        )
        lines.append(f"{Colors.CYAN}╟{'─' * 90}╢{Colors.RESET}")

        # Worker rows
        with self.lock:
            for name, worker in self.workers.items():
                status_icon = self._get_status_icon(worker.status)
                duration = self._get_duration(worker)

                # Color code the counts
                passed = (
                    f"{Colors.GREEN}{worker.tests_passed:>4}{Colors.RESET}"
                    if worker.tests_passed
                    else f"{Colors.DIM}   0{Colors.RESET}"
                )
                failed = (
                    f"{Colors.RED}{worker.tests_failed:>4}{Colors.RESET}"
                    if worker.tests_failed
                    else f"{Colors.DIM}   0{Colors.RESET}"
                )
                skipped = (
                    f"{Colors.YELLOW}{worker.tests_skipped:>4}{Colors.RESET}"
                    if worker.tests_skipped
                    else f"{Colors.DIM}   0{Colors.RESET}"
                )

                activity = worker.current_test or worker.last_output_line[:25]
                if worker.status == Status.RUNNING:
                    activity = f"{Colors.CYAN}{activity}{Colors.RESET}"

                # Truncate name if too long
                display_name = name[:23] if len(name) > 23 else name

                row = f"{display_name:<25} {status_icon:<8} {duration:<7} {passed}  {failed}  {skipped}  {activity:<25}"
                lines.append(
                    f"{Colors.CYAN}║{Colors.RESET} {row} {Colors.CYAN}║{Colors.RESET}"
                )

        lines.append(f"{Colors.BOLD}{Colors.CYAN}╚{'═' * 90}╝{Colors.RESET}")

        # Summary
        with self.lock:
            running = sum(
                1 for w in self.workers.values() if w.status == Status.RUNNING
            )
            summary_passed = sum(
                1 for w in self.workers.values() if w.status == Status.PASSED
            )
            summary_failed = sum(
                1 for w in self.workers.values() if w.status == Status.FAILED
            )
            pending = sum(
                1 for w in self.workers.values() if w.status == Status.PENDING
            )

        summary = f"  Running: {Colors.CYAN}{running}{Colors.RESET}  │  Passed: {Colors.GREEN}{summary_passed}{Colors.RESET}  │  Failed: {Colors.RED}{summary_failed}{Colors.RESET}  │  Pending: {Colors.DIM}{pending}{Colors.RESET}"
        lines.append(summary)
        lines.append("")

        return "\n".join(lines)

    def _refresh_loop(self) -> None:
        """Continuously refresh the display."""
        while self.running:
            # Clear screen and move cursor to top
            print("\033[2J\033[H", end="")
            print(self._render_table())
            time.sleep(0.5)

    def print_final_summary(self) -> None:
        """Print final summary after all tests complete."""
        print("\033[2J\033[H", end="")  # Clear screen

        elapsed = datetime.now() - self.start_time

        print(f"\n{Colors.BOLD}{'=' * 80}{Colors.RESET}")
        print(f"{Colors.BOLD}                    FINAL TEST RESULTS{Colors.RESET}")
        print(f"{Colors.BOLD}{'=' * 80}{Colors.RESET}\n")

        total_passed = 0
        total_failed = 0
        total_skipped = 0

        for name, worker in self.workers.items():
            status_icon = self._get_status_icon(worker.status)
            duration = self._get_duration(worker)

            status_color = (
                Colors.GREEN
                if worker.status == Status.PASSED
                else (Colors.RED if worker.status == Status.FAILED else Colors.YELLOW)
            )

            print(
                f"  {status_icon} {status_color}{name:<30}{Colors.RESET} "
                f"│ {duration} │ "
                f"{Colors.GREEN}✓{worker.tests_passed}{Colors.RESET} "
                f"{Colors.RED}✗{worker.tests_failed}{Colors.RESET} "
                f"{Colors.YELLOW}⊘{worker.tests_skipped}{Colors.RESET}"
            )

            total_passed += worker.tests_passed
            total_failed += worker.tests_failed
            total_skipped += worker.tests_skipped

        print(f"\n{Colors.BOLD}{'─' * 80}{Colors.RESET}")
        print(
            f"  Total Time: {Colors.CYAN}{str(timedelta(seconds=int(elapsed.total_seconds())))}{Colors.RESET}"
        )
        print(
            f"  Total Tests: {Colors.GREEN}{total_passed} passed{Colors.RESET}, "
            f"{Colors.RED}{total_failed} failed{Colors.RESET}, "
            f"{Colors.YELLOW}{total_skipped} skipped{Colors.RESET}"
        )

        # Overall status
        all_passed = all(w.status == Status.PASSED for w in self.workers.values())
        if all_passed:
            print(
                f"\n  {Colors.BG_GREEN}{Colors.WHITE}{Colors.BOLD} ALL TESTS PASSED {Colors.RESET} 🎉\n"
            )
        else:
            failed_workers = [
                w.name for w in self.workers.values() if w.status == Status.FAILED
            ]
            print(
                f"\n  {Colors.BG_RED}{Colors.WHITE}{Colors.BOLD} SOME TESTS FAILED {Colors.RESET}"
            )
            print(f"  Failed: {', '.join(failed_workers)}\n")

            # Print failure details for each failed worker
            for worker in self.workers.values():
                if worker.status == Status.FAILED and worker.failure_lines:
                    print(
                        f"\n{Colors.BOLD}{Colors.RED}═══ {worker.name} Failures ═══{Colors.RESET}"
                    )
                    for failure in worker.failure_lines[:20]:  # Limit to 20 failures
                        print(f"  {Colors.RED}•{Colors.RESET} {failure}")
                    if len(worker.failure_lines) > 20:
                        print(
                            f"  ... and {len(worker.failure_lines) - 20} more failures"
                        )
            print()


def run_tox_worker(env: str, display: LiveTableDisplay, fast: bool = False) -> bool:
    """Run a single tox environment."""
    display.update(env, status=Status.RUNNING, started_at=datetime.now())

    cmd = ["./run_with_venv.sh", "tox", "-e", env, "--"]
    if fast:
        cmd.extend(["-m", "not benchmark and not slow"])

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
        )

        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                display.add_log_line(env, line)

        process.wait()

        display.update(
            env,
            status=Status.PASSED if process.returncode == 0 else Status.FAILED,
            finished_at=datetime.now(),
            exit_code=process.returncode,
        )

        return process.returncode == 0

    except Exception as e:
        display.update(
            env,
            status=Status.FAILED,
            finished_at=datetime.now(),
            last_output_line=str(e),
        )
        return False


def run_docker_worker(
    backend: str, port: int, desc: str, display: LiveTableDisplay
) -> bool:
    """Run a single docker test."""
    worker_name = f"{backend}:{port}"
    display.update(worker_name, status=Status.RUNNING, started_at=datetime.now())

    cmd = [
        "python3",
        "tests/test_project/verify_scenarios.py",
        "--url",
        f"http://localhost:{port}",
    ]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
        )

        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                display.add_log_line(worker_name, line)

        process.wait()

        display.update(
            worker_name,
            status=Status.PASSED if process.returncode == 0 else Status.FAILED,
            finished_at=datetime.now(),
            exit_code=process.returncode,
        )

        return process.returncode == 0

    except Exception as e:
        display.update(
            worker_name,
            status=Status.FAILED,
            finished_at=datetime.now(),
            last_output_line=str(e),
        )
        return False


def get_available_tox_envs() -> List[str]:
    """Get list of available tox environments that can actually run."""
    try:
        result = subprocess.run(
            ["./run_with_venv.sh", "tox", "-l"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
        )
        all_envs = [e.strip() for e in result.stdout.strip().split("\n") if e.strip()]

        # Filter to only include Python versions that are installed
        available_envs = []
        for env in all_envs:
            # Extract python version from env name (e.g., py39, py310)
            match = re.match(r"py(\d)(\d+)", env)
            if match:
                major, minor = match.groups()
                py_version = f"{major}.{minor}"
                # Check if this Python version exists
                check = subprocess.run(
                    ["python" + py_version, "--version"], capture_output=True
                )
                if check.returncode == 0:
                    available_envs.append(env)

        return available_envs if available_envs else all_envs[:4]  # Fallback to first 4

    except Exception:
        # Fallback to some common environments
        return ["py311-django42", "py311-django50", "py311-django51"]


def run_tox_parallel(fast: bool = False, max_workers: int = 4) -> bool:
    """Run tox environments in parallel with live display."""
    envs = get_available_tox_envs()

    if not envs:
        print(f"{Colors.RED}No tox environments available!{Colors.RESET}")
        return False

    print(
        f"{Colors.CYAN}Found {len(envs)} tox environments: {', '.join(envs)}{Colors.RESET}"
    )
    print(
        f"{Colors.YELLOW}Starting parallel execution with {max_workers} workers...{Colors.RESET}"
    )
    time.sleep(1)

    display = LiveTableDisplay(envs)
    display.start()

    results = []

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(run_tox_worker, env, display, fast): env for env in envs
            }

            for future in as_completed(futures):
                env = futures[future]
                try:
                    results.append(future.result())
                except Exception as e:
                    display.update(env, status=Status.FAILED, last_output_line=str(e))
                    results.append(False)

    finally:
        display.stop()
        time.sleep(0.5)
        display.print_final_summary()

    return all(results)


def run_docker_parallel() -> bool:
    """Run docker matrix tests in parallel with live display."""
    # Docker test configuration
    tests = [
        ("memory", 8001, "Memory Backend"),
        ("redis", 8002, "Redis Backend"),
        ("redis-async", 8003, "Async Redis Backend"),
        ("mongodb", 8004, "MongoDB Backend"),
        ("multi", 8005, "Multi-Backend"),
    ]

    worker_names = [f"{t[0]}:{t[1]}" for t in tests]

    display = LiveTableDisplay(worker_names)
    display.start()

    results = []

    try:
        with ThreadPoolExecutor(max_workers=len(tests)) as executor:
            futures = {
                executor.submit(
                    run_docker_worker, backend, port, desc, display
                ): f"{backend}:{port}"
                for backend, port, desc in tests
            }

            for future in as_completed(futures):
                name = futures[future]
                try:
                    results.append(future.result())
                except Exception as e:
                    display.update(name, status=Status.FAILED, last_output_line=str(e))
                    results.append(False)

    finally:
        display.stop()
        time.sleep(0.5)
        display.print_final_summary()

    return all(results)


def main() -> None:
    """Main entry point for the parallel test runner."""
    parser = argparse.ArgumentParser(
        description="Parallel Test Runner with Live Table Display",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s tox              Run all tox environments in parallel
    %(prog)s tox --fast       Skip benchmarks and slow tests
    %(prog)s docker           Run docker matrix in parallel
    %(prog)s tox -w 2         Limit to 2 parallel workers
        """,
    )

    parser.add_argument(
        "mode",
        choices=["tox", "docker"],
        help="Test mode: 'tox' for multi-version testing, 'docker' for container matrix",
    )

    parser.add_argument(
        "--fast",
        "-f",
        action="store_true",
        help="Fast mode: skip benchmarks and slow tests",
    )

    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=4,
        help="Maximum number of parallel workers (default: 4)",
    )

    args = parser.parse_args()

    print(f"\n{Colors.BOLD}{Colors.CYAN}╔{'═' * 50}╗{Colors.RESET}")
    print(
        f"{Colors.BOLD}{Colors.CYAN}║{Colors.RESET}  Parallel Test Runner v1.0                        {Colors.BOLD}{Colors.CYAN}║{Colors.RESET}"
    )
    print(
        f"{Colors.BOLD}{Colors.CYAN}║{Colors.RESET}  Mode: {args.mode:<15} Fast: {str(args.fast):<10} Workers: {args.workers:<3} {Colors.BOLD}{Colors.CYAN}║{Colors.RESET}"
    )
    print(f"{Colors.BOLD}{Colors.CYAN}╚{'═' * 50}╝{Colors.RESET}\n")

    if args.mode == "tox":
        success = run_tox_parallel(fast=args.fast, max_workers=args.workers)
    else:
        success = run_docker_parallel()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
