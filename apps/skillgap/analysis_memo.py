import threading

_local = threading.local()


def run_once(user, analyzer):
    """Return the CareerContext for this user, computing it once per request.

    The three skill-gap endpoints (gap, courses, roadmap) all call
    ``CareerAnalyzer.analyze`` internally; this memo ensures a single page
    load performs one analysis (skill extraction, profession classification,
    job ranking) instead of three.
    """
    cached = getattr(_local, "context", None)
    if cached is not None and cached.user.pk == user.pk:
        return cached
    context = analyzer()
    _local.context = context
    return context


def clear():
    if hasattr(_local, "context"):
        del _local.context
