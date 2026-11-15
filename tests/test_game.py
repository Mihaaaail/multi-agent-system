from dataclasses import replace
from itertools import product
from unittest import TestCase

from mafia.agents import Clue, Statement, View, scores
from mafia.experiments import run_experiment
from mafia.game import COORDINATION, PEOPLE, SCENARIOS, Game, Rules, make_world


def replay(world, rules):
    game = Game(world, rules, trace=True)
    game.play()
    return game.replay()


class GameTests(TestCase):
    def test_pairs_reuse_the_same_initial_world(self):
        world = make_world(206600, 3)
        regular = replay(world, Rules())
        guarded = replay(world, Rules(guarded=True, scenario="combined"))
        self.assertEqual(regular, replay(world, Rules()))
        self.assertEqual(regular["events"][0], guarded["events"][0])
        for player in world.players:
            self.assertEqual(player.team, world.team if player.number in world.team else set())
            self.assertTrue(all(clue.holder == player.number for clue in player.observations))

    def test_constraints_and_counting_hold_in_all_modes(self):
        for scenario, method, debate, guarded in product(SCENARIOS, COORDINATION, (False, True),
                                                         (False, True)):
            rules = Rules(method, debate, guarded, scenario, 8)
            with self.subTest(rules=rules):
                world = make_world(99, 4)
                result = replay(world, rules)
                events, outcome = result["events"], result["outcome"]
                self.assertEqual(len(set(outcome["visits"])), 8)
                self.assertEqual(len(set(outcome["verdict"])), 4)
                self.assertEqual(outcome["deliveries"], sum(len(event["recipients"]) for event in events))
                for event in events:
                    if event["kind"] in ("council_proposal", "council_decision"):
                        self.assertIn(event["sender"], world.team)
                        self.assertTrue(world.team.issuperset(event["recipients"]))
                    if event["kind"] == "ballot":
                        self.assertNotIn(event["sender"], event["choices"])
                        self.assertEqual(len(set(event["choices"])), len(event["choices"]))
                    if event["kind"] == "statement" and event["evidence"] is None:
                        self.assertEqual(event["counted"], not guarded)

    def test_personal_evidence_is_counted_once_and_opinions_can_be_ignored(self):
        evidence = Clue("witness-1-0", 0, 1, 0.74, "witness", 1)
        statement = Statement(2, 0, 1, None, "rumor")
        view = View(PEOPLE, PEOPLE, (evidence,), (statement, statement), False,
                    (1.0,) * len(PEOPLE))
        self.assertAlmostEqual(scores(view, (evidence,))[0], evidence.weight + 0.35)
        self.assertAlmostEqual(scores(replace(view, guarded=True), (evidence,))[0], evidence.weight)

    def test_disagreement_does_not_publish_an_inspection_clue(self):
        world = make_world(206600, 3)
        reserve = tuple(replace(clue, sign=-main.sign) for clue, main in zip(world.reserve, world.primary))
        result = replay(replace(world, reserve=reserve), Rules(guarded=True))
        self.assertEqual(result["outcome"]["disagreements"], 4)
        self.assertEqual(result["outcome"]["usable_clues"], 0)

    def test_reserve_preserves_the_first_two_checks_during_an_outage(self):
        world = make_world(206600, 3)
        regular = replay(world, Rules(scenario="offline"))
        guarded = replay(world, Rules(scenario="offline", guarded=True))
        self.assertEqual(regular["outcome"]["usable_clues"], 2)
        self.assertEqual(guarded["outcome"]["outages"], 2)
        first_checks = [event for event in guarded["events"] if event["kind"] == "check_result"][:2]
        self.assertTrue(all(event["source"] == "reserve" for event in first_checks))

    def test_debate_changes_votes_and_night_clues_update_trust(self):
        result = replay(make_world(206600, 3), Rules())
        self.assertGreater(result["outcome"]["vote_changes"], 0)
        self.assertTrue(any(event["kind"] == "trust_change" for event in result["events"]))

    def test_reported_effect_is_the_difference_of_paired_means(self):
        runs, summaries, effects = run_experiment(2, 5)
        self.assertEqual(len(runs), 20)
        for first, second in zip(runs[::2], runs[1::2]):
            self.assertEqual((first["seed"], first["mafia"]), (second["seed"], second["mafia"]))
        for row in effects:
            first, second = (entry for entry in summaries if entry["mafia"] == row["mafia"])
            metric = row["metric"]
            self.assertAlmostEqual(row["difference"], second[metric] - first[metric])
