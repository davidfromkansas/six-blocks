"""Compare every scripted strategy across seeds.

    python tools/benchmark.py --seeds 12 --days 30

Used to check the qualitative ordering the benchmark needs: the balanced baseline beats
do-nothing and random, and no single-lever strategy dominates every seed.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from citysim.harness import run_episode
from citysim.policies import STRATEGIES

ORDER = [
    "do_nothing",
    "random_legal",
    "spend_everything_immediately",
    "parks_only",
    "rent_relief_only",
    "business_only",
    "balanced_baseline",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=8)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--components", action="store_true")
    args = parser.parse_args()

    seeds = [1000 + index * 7 for index in range(args.seeds)]
    table: dict[str, list[float]] = {name: [] for name in ORDER}
    components: dict[str, dict[str, list[float]]] = {name: {} for name in ORDER}
    per_seed_winner: dict[str, int] = {}

    for seed in seeds:
        best_name, best_score = "", -1.0
        for name in ORDER:
            assert name in STRATEGIES
            results = run_episode(seed, strategy=name, total_days=args.days).results()
            table[name].append(results["score"])
            for key, value in results["components"].items():
                components[name].setdefault(key, []).append(value)
            if results["score"] > best_score:
                best_name, best_score = name, results["score"]
        per_seed_winner[best_name] = per_seed_winner.get(best_name, 0) + 1

    print(f"seeds={seeds} days={args.days}\n")
    print(f"{'strategy':<30}{'mean':>8}{'min':>8}{'max':>8}{'wins':>6}")
    for name in ORDER:
        scores = table[name]
        print(f"{name:<30}{statistics.mean(scores):>8.1f}{min(scores):>8.1f}"
              f"{max(scores):>8.1f}{per_seed_winner.get(name, 0):>6}")

    if args.components:
        print()
        keys = sorted(components[ORDER[0]])
        print(f"{'strategy':<30}" + "".join(f"{key[:9]:>10}" for key in keys))
        for name in ORDER:
            row = "".join(f"{statistics.mean(components[name][key]):>10.1f}" for key in keys)
            print(f"{name:<30}{row}")

    if args.json:
        args.json.write_text(json.dumps({"seeds": seeds, "scores": table}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
