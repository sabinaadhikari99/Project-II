import logging
import time
from contextlib import contextmanager
from django.conf import settings
from django.db import connection, reset_queries

logger = logging.getLogger("performance")


class PerformanceTimer:
    def __init__(self, name="", enabled=None):
        self.name = name
        self._enabled = enabled
        self.measurements = []
        self._stack = []

    @property
    def enabled(self):
        if self._enabled is not None:
            return self._enabled
        return getattr(settings, "PERFORMANCE_LOGGING_ENABLED", False)

    @contextmanager
    def measure(self, label):
        if not self.enabled:
            yield
            return
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self.measurements.append((label, elapsed))

    def trace(self, label):
        if not self.enabled:
            return _NullTimer()
        start = time.perf_counter()
        return _TraceTimer(self, label, start)

    def count_queries(self, prefix="Database"):
        if not self.enabled:
            return
        if not settings.DEBUG:
            self.measurements.append((f"{prefix} (queries)", "N/A (DEBUG=False)"))
            return
        queries = connection.queries
        total_time = sum(float(q.get("time", 0)) for q in queries)
        slowest = max(queries, key=lambda q: float(q.get("time", 0))) if queries else None
        self.measurements.append((f"{prefix} — count", len(queries)))
        self.measurements.append((f"{prefix} — total time", round(total_time, 4)))
        if slowest:
            self.measurements.append((
                f"{prefix} — slowest",
                f"{slowest.get('time', 0)}s — {slowest.get('sql', '')[:120]}"
            ))

    def reset_queries(self):
        if self.enabled and settings.DEBUG:
            reset_queries()

    def flush(self, prefix=""):
        if not self.enabled or not self.measurements:
            return
        total = 0
        lines = []
        lines.append("")
        lines.append("=" * 50)
        lines.append(f"  Performance: {prefix or self.name}")
        lines.append("=" * 50)
        for label, elapsed in self.measurements:
            if isinstance(elapsed, str):
                lines.append(f"  {label:<38} {elapsed}")
            else:
                lines.append(f"  {label:<38} {elapsed:.4f} sec")
                total += elapsed
        if total > 0:
            lines.append("  " + "-" * 50)
            lines.append(f"  {'TOTAL':<38} {total:.4f} sec")
        lines.append("=" * 50)
        lines.append("")
        output = "\n".join(lines)
        logger.info(output)
        print(output)
        self.measurements.clear()

    def get_report(self):
        return list(self.measurements)

    def total_time(self):
        return sum(t for _, t in self.measurements if isinstance(t, (int, float)))

    def log_cache(self, label, elapsed, hit):
        if not self.enabled:
            return
        status = "HIT" if hit else "MISS"
        self.measurements.append((f"Cache Lookup", round(elapsed, 4)))
        self.measurements.append((f"Cache Status", status))


class _NullTimer:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def stop(self):
        pass


class _TraceTimer:
    def __init__(self, timer, label, start):
        self.timer = timer
        self.label = label
        self.start = start

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stop()

    def stop(self):
        elapsed = time.perf_counter() - self.start
        self.timer.measurements.append((self.label, elapsed))
