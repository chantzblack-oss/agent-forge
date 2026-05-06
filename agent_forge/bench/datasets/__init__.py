"""External benchmark dataset loaders.

Each loader returns a list[BenchTask] suitable for runner.run_suite. Built-in
starter sets are tiny (≤10 questions) so CI can include them without IP risk
or download dependencies. Larger official sets are loaded by path from disk.
"""

from .hotpot import load_hotpot_starter, load_hotpot_from_file

__all__ = ["load_hotpot_starter", "load_hotpot_from_file"]
