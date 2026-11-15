"""Сборка автономной страницы с трассами, полученными из модели."""

import json
from dataclasses import replace
from pathlib import Path

from .game import Game, Rules, make_world


CASES = {
    "normal": "Штатная игра",
    "rumor": "Согласованный слух",
    "bad_check": "Ошибочная проверка",
    "offline": "Недоступность источника",
    "combined": "Слух и ошибочная проверка",
}


def export_demo(destination: Path, seed: int):
    world = make_world(seed, 3)
    presets = [
        ("Распределение проверок", "Назначение ведущим", Rules("host", False)),
        ("Распределение проверок", "Голосование без обсуждения", Rules("vote", False)),
        ("Переговоры", "Голосование с обсуждением", Rules()),
    ]
    for scenario, label in CASES.items():
        rules = Rules(scenario=scenario)
        presets.extend((
            ("Испытания", f"{label} · исходные правила", rules),
            ("Испытания", f"{label} · с защитой", replace(rules, guarded=True)),
        ))

    replays = []
    for group, label, rules in presets:
        game = Game(world, rules, trace=True)
        game.play()
        replays.append({"group": group, "label": label, **game.replay()})
    data = json.dumps(replays, ensure_ascii=False, separators=(",", ":")).replace("<", r"\u003c")
    template = Path(__file__).with_name("demo_template.html").read_text(encoding="utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(template.replace("__GAME_DATA__", data), encoding="utf-8")
