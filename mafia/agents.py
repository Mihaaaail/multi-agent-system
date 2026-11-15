"""Локальные сведения и правила принятия решений у игровых агентов."""

from collections import Counter
from dataclasses import dataclass
from math import log


@dataclass(frozen=True)
class Clue:
    key: str
    target: int
    sign: int
    reliability: float
    source: str
    holder: int | None = None

    @property
    def weight(self) -> float:
        return log(self.reliability / (1 - self.reliability))


@dataclass(frozen=True)
class Statement:
    sender: int
    target: int
    sign: int
    evidence: str | None
    reason: str


@dataclass(frozen=True)
class View:
    order: tuple[int, ...]
    candidates: tuple[int, ...]
    clues: tuple[Clue, ...]
    statements: tuple[Statement, ...]
    guarded: bool
    witness_weights: tuple[float, ...]


OPINION_WEIGHT = 0.35


def strength(view: View, clue: Clue) -> float:
    trust = view.witness_weights[clue.holder] if clue.holder is not None else 1.0
    return clue.sign * clue.weight * trust


def scores(view: View, private: tuple[Clue, ...] = (),
           ignore: frozenset[int] = frozenset()) -> dict[int, float]:
    result = dict.fromkeys(view.order, 0.0)
    known = set()
    for clue in (*view.clues, *private):
        if clue.key not in known:
            result[clue.target] += strength(view, clue)
            known.add(clue.key)

    if not view.guarded:
        opinions = set()
        for statement in view.statements:
            pair = (statement.sender, statement.target)
            if statement.evidence is None and statement.sender not in ignore and pair not in opinions:
                result[statement.target] += (statement.sign * OPINION_WEIGHT
                                             * view.witness_weights[statement.sender])
                opinions.add(pair)
    return result


def rank(candidates: tuple[int, ...], values: dict[int, float]) -> tuple[int, ...]:
    # Сортировка сохраняет заранее выбранный порядок при равенстве.
    return tuple(sorted(candidates, key=values.__getitem__, reverse=True))


def tally(view: View, ballots: list[tuple[int, ...]], seats: int = 1) -> tuple[int, ...]:
    counts = Counter(target for ballot in ballots for target in ballot)
    public = scores(view)
    return tuple(sorted(view.candidates, key=lambda target: (counts[target], public[target]),
                        reverse=True)[:seats])


@dataclass(frozen=True)
class Player:
    number: int
    observations: tuple[Clue, ...]
    team: frozenset[int] = frozenset()

    def assess(self, view: View) -> dict[int, float]:
        ignored = self.team or frozenset((self.number,))
        return scores(view, self.observations, ignored)

    def decoy(self, view: View) -> int | None:
        """Выбор правдоподобного соперника, за которого могут проголосовать жители."""
        public = scores(view, ignore=self.team)
        personal = self.assess(view)
        choices = tuple(target for target in view.candidates if target not in self.team)
        persuasive = {target: 0.75 * public[target] + 0.25 * personal[target] for target in choices}
        return next(iter(rank(choices, persuasive)), None)

    def vote(self, view: View, seats: int, joint_decoy: int | None) -> tuple[int, ...]:
        values = self.assess(view)
        excluded = self.team or frozenset((self.number,))
        choices = tuple(target for target in view.candidates if target not in excluded)
        ranked = rank(choices, values)
        if joint_decoy in choices:
            ranked = (joint_decoy,) + tuple(target for target in ranked if target != joint_decoy)
        return ranked[:seats]

    def speak(self, view: View, reply: bool, decoy: int | None,
              scripted_rumor: bool) -> Statement | None:
        if self.team and scripted_rumor and not reply and decoy is not None:
            return Statement(self.number, decoy, 1, None, "rumor")

        candidates = tuple(target for target in view.candidates if target != self.number)
        if not candidates:
            return None
        public = scores(view, ignore=self.team)
        beliefs = self.assess(view)
        before = rank(candidates, public)[0]
        published = {clue.key for clue in view.clues}
        contested = {(statement.target, statement.sign) for statement in view.statements
                     if statement.sender != self.number}
        best = None
        best_value = 0.0

        def utility(target: int) -> float:
            if self.team:
                return float(target not in self.team)
            return beliefs[target]

        for clue in self.observations:
            if clue.key in published or clue.target not in candidates:
                continue
            if self.team and (clue.sign > 0) != (clue.target not in self.team):
                continue

            revised = public.copy()
            change = strength(view, clue)
            revised[clue.target] += change
            after = rank(candidates, revised)[0]
            margin = abs(public[before] - public[clue.target])
            rebuts = reply and (clue.target, -clue.sign) in contested
            effect = 2 * (utility(after) - utility(before)) + abs(change) / (1 + margin)
            effect += 0.9 * rebuts + 0.25 * (clue.target == decoy)
            if effect > best_value:
                best = Statement(self.number, clue.target, clue.sign, clue.key,
                                 "rebuttal" if rebuts else "evidence")
                best_value = effect

        if best is not None:
            return best
        if self.team and not reply and decoy is not None and before in self.team:
            if public[before] - public[decoy] <= 1.3:
                return Statement(self.number, decoy, 1, None, "suspicion")
        return None
