"""Запуск игр, опытов и наглядного просмотра."""

import argparse
import json
from pathlib import Path

from .experiments import DEFAULT_GAMES, export_experiment
from .game import COORDINATION, NAMES, SCENARIOS, Game, Rules, make_world


def parse_args():
    parser = argparse.ArgumentParser(description="Имитационная модель «Мафия с уликами»")
    commands = parser.add_subparsers(dest="command", required=True)
    game = commands.add_parser("play", help="Сыграть одну партию")
    game.add_argument("--seed", type=int, default=206600, help="Начальное число генератора")
    game.add_argument("--mafia", type=int, choices=range(1, 5), default=3)
    game.add_argument("--nights", type=int, choices=range(1, 9), default=4)
    game.add_argument("--method", choices=COORDINATION, default="vote")
    game.add_argument("--scenario", choices=SCENARIOS, default="normal")
    game.add_argument("--silent", action="store_true", help="Убрать открытые переговоры")
    game.add_argument("--guarded", action="store_true", help="Включить проверку оснований и резерв")
    game.add_argument("--trace", type=Path, help="Записать полную трассу партии")

    experiment = commands.add_parser("experiment", help="Повторить серию опытов")
    experiment.add_argument("lab", choices=("2", "3", "4", "all"))
    experiment.add_argument("--games", type=int, default=DEFAULT_GAMES,
                            help="Число начальных миров для каждой пары условий")
    experiment.add_argument("--out", type=Path, default=Path("results"))

    demo = commands.add_parser("demo", help="Собрать страницу просмотра партий")
    demo.add_argument("--out", type=Path, default=Path("demo.html"))
    demo.add_argument("--seed", type=int, default=206600)
    return parser, parser.parse_args()


def main():
    parser, args = parse_args()
    if args.command == "experiment":
        if args.games < 2:
            parser.error("Для каждой пары условий укажи хотя бы две игры.")
        labs = (2, 3, 4) if args.lab == "all" else (int(args.lab),)
        for lab in labs:
            export_experiment(lab, args.games, args.out)
            print(f"Работа № {lab}. Результаты записаны в {args.out / f'{lab:02d}'}")
    elif args.command == "demo":
        from .demo import export_demo

        export_demo(args.out, args.seed)
        print(f"Просмотр партий записан в {args.out}")
    else:
        world = make_world(args.seed, args.mafia)
        rules = Rules(args.method, not args.silent, args.guarded, args.scenario, args.nights)
        game = Game(world, rules, trace=args.trace is not None)
        outcome = game.play()
        if args.trace is not None:
            args.trace.parent.mkdir(parents=True, exist_ok=True)
            args.trace.write_text(json.dumps(game.replay(), ensure_ascii=False, indent=2),
                                  encoding="utf-8")

        print("Ночные проверки — " + ", ".join(NAMES[index] for index in outcome.visits))
        print("Итоговое подозрение — " + ", ".join(NAMES[index] for index in outcome.verdict))
        print("Тайные сообщники — " + ", ".join(NAMES[index] for index in sorted(world.team)))
        print(f"Сообщников найдено {len(world.team.intersection(outcome.verdict))} из {args.mafia}. "
              f"Доставлено сообщений {outcome.deliveries}.")


if __name__ == "__main__":
    main()
