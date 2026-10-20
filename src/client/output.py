"""Small console-formatting helpers shared by client commands."""

import time


_demo_pace_seconds = 0.0
_demo_pause_seconds = 0.0


def set_demo_pace(seconds: float) -> None:
    """Set an optional presentation-only pause before section headings."""

    global _demo_pace_seconds, _demo_pause_seconds
    if seconds < 0:
        raise ValueError("demo pace must not be negative")
    _demo_pace_seconds = seconds
    _demo_pause_seconds = 0.0


def demo_pause_seconds() -> float:
    """Return time spent in presentation pauses during this process."""

    return _demo_pause_seconds


def heading(title: str) -> None:
    global _demo_pause_seconds
    if _demo_pace_seconds:
        started = time.perf_counter()
        time.sleep(_demo_pace_seconds)
        _demo_pause_seconds += time.perf_counter() - started
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)
