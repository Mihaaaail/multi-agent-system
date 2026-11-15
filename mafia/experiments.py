"""Парные прогоны на одних и тех же начальных мирах."""

import csv
import json
from dataclasses import replace
from math import sqrt
from pathlib import Path
from statistics import fmean, stdev

from .game import Game, Rules, SCENARIOS, make_world


DEFAULT_GAMES = 500
EFFECT_FIELDS = ("check_precision", "recall", "solved", "false_rate", "deliveries",
                 "usable_clues", "wrong_clues")


def cases(lab: int):
    if lab == 2:
        for count in (2, 3):
            yield count, Rules(coordination="host", debate=False), Rules(debate=False)
    elif lab == 3:
        for count in range(1, 5):
            yield count, Rules(debate=False), Rules()
    elif lab == 4:
        for scenario in SCENARIOS:
            baseline = Rules(scenario=scenario)
            yield 3, baseline, replace(baseline, guarded=True)
    else:
        raise ValueError("Серии опытов заданы для работ 2, 3 и 4.")


def modes(lab: int) -> tuple[str, str]:
    return {
        2: ("host", "vote"),
        3: ("silent", "debate"),
        4: ("unguarded", "guarded"),
    }[lab]


def run_experiment(lab: int, games: int):
    if games < 2:
        raise ValueError("Для оценки разброса нужны хотя бы две игры.")
    all_runs = []
    summaries = []
    effects = []
    for count, baseline, treatment in cases(lab):
        pair = [[], []]
        group = {"mafia": count, "scenario": baseline.scenario}
        for offset in range(games):
            seed = 202600 + 1000 * lab + offset
            world = make_world(seed, count)
            for index, (mode, rules) in enumerate(zip(modes(lab), (baseline, treatment))):
                result = Game(world, rules).play().metrics(world, rules.nights)
                pair[index].append(result)
                all_runs.append({**group, "seed": seed, "mode": mode, **result})

        for mode, runs in zip(modes(lab), pair):
            means = {key: fmean(row[key] for row in runs) for key in runs[0]}
            summaries.append({**group, "mode": mode, "games": games, **means})
        for metric in EFFECT_FIELDS:
            differences = [right[metric] - left[metric] for left, right in zip(*pair)]
            difference = fmean(differences)
            error = 1.96 * stdev(differences) / sqrt(games)
            effects.append({**group, "metric": metric, "games": games,
                            "difference": difference, "low": difference - error,
                            "high": difference + error})
    return all_runs, summaries, effects


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def export_experiment(lab: int, games: int, destination: Path):
    all_runs, summaries, effects = run_experiment(lab, games)
    folder = destination / f"{lab:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in (("runs", all_runs), ("summary", summaries), ("effects", effects)):
        write_csv(folder / f"{name}.csv", data)
    if lab == 4:
        traces = {}
        for count, baseline, treatment in cases(4):
            world = make_world(206600, count)
            for mode, rules in zip(modes(4), (baseline, treatment)):
                game = Game(world, rules, trace=True)
                game.play()
                traces[f"{rules.scenario}/{mode}"] = game.replay()
        (folder / "traces.json").write_text(json.dumps(traces, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
