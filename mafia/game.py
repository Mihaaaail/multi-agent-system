"""Игровая среда, передача сообщений и ночные проверки."""

from dataclasses import asdict, dataclass, field, replace
from random import Random

from .agents import Clue, Player, Statement, View, rank, scores, tally


NAMES = ("Алиса", "Борис", "Вера", "Глеб", "Дина", "Егор", "Жанна", "Илья", "Кира")
SCENARIOS = ("normal", "rumor", "bad_check", "offline", "combined")
COORDINATION = ("host", "vote")
PEOPLE = tuple(range(len(NAMES)))


@dataclass(frozen=True)
class World:
    seed: int
    team: frozenset[int]
    order: tuple[int, ...]
    players: tuple[Player, ...]
    public: tuple[Clue, ...]
    primary: tuple[Clue, ...]
    reserve: tuple[Clue, ...]


def make_world(seed: int, mafia_count: int) -> World:
    if not 1 <= mafia_count <= len(PEOPLE) // 2:
        raise ValueError("В игре может быть от одного до четырёх сообщников.")
    rng = Random(seed)
    team = frozenset(rng.sample(PEOPLE, mafia_count))
    order = tuple(rng.sample(PEOPLE, len(PEOPLE)))

    def observation(target: int, reliability: float, source: str,
                    holder: int | None = None) -> Clue:
        sign = 1 if target in team else -1
        if rng.random() >= reliability:
            sign = -sign
        key = f"{source}-{target}" if holder is None else f"{source}-{holder}-{target}"
        return Clue(key, target, sign, reliability, source, holder)

    public = tuple(observation(target, 0.62, "public") for target in PEOPLE)
    players = []
    for number in PEOPLE:
        others = tuple(target for target in PEOPLE if target != number)
        local = tuple(observation(target, 0.74, "witness", number)
                      for target in rng.sample(others, 3))
        players.append(Player(number, local, team if number in team else frozenset()))
    primary = tuple(observation(target, 0.88, "primary") for target in PEOPLE)
    reserve = tuple(observation(target, 0.88, "reserve") for target in PEOPLE)
    return World(seed, team, order, tuple(players), public, primary, reserve)


@dataclass(frozen=True)
class Rules:
    coordination: str = "vote"
    debate: bool = True
    guarded: bool = False
    scenario: str = "normal"
    nights: int = 4

    def __post_init__(self):
        if self.coordination not in COORDINATION or self.scenario not in SCENARIOS:
            raise ValueError("Неизвестный способ координации или сценарий.")
        if not 1 <= self.nights < len(PEOPLE):
            raise ValueError("Допустимо от одной до восьми ночей.")


@dataclass
class Outcome:
    checks_on_mafia: int = 0
    usable_clues: int = 0
    wrong_clues: int = 0
    disagreements: int = 0
    outages: int = 0
    unsupported: int = 0
    deliveries: int = 0
    statements: int = 0
    vote_changes: int = 0
    visits: list[int] = field(default_factory=list)
    verdict: tuple[int, ...] = ()

    def metrics(self, world: World, nights: int) -> dict[str, float]:
        found = len(world.team.intersection(self.verdict))
        return {
            "check_precision": self.checks_on_mafia / nights,
            "recall": found / len(world.team),
            "solved": float(found == len(world.team)),
            "false_rate": (len(self.verdict) - found) / (len(PEOPLE) - len(world.team)),
            "deliveries": self.deliveries,
            "statements": self.statements,
            "vote_changes": self.vote_changes,
            "usable_clues": self.usable_clues,
            "wrong_clues": self.wrong_clues,
            "disagreements": self.disagreements,
            "outages": self.outages,
            "unsupported": self.unsupported,
        }


class Game:
    def __init__(self, world: World, rules: Rules, *, trace: bool = False):
        self.world = world
        self.rules = rules
        self.board = {clue.key: clue for clue in world.public}
        self.statements = []
        self.tested = set()
        self.outcome = Outcome()
        self.events = [] if trace else None
        self.day = 0
        self.phase = "start"

    def _record(self, kind: str, sender=None, recipients: tuple = (), **details):
        self.outcome.deliveries += len(recipients)
        if self.events is not None:
            self.events.append({
                "kind": kind, "day": self.day, "phase": self.phase,
                "sender": sender, "recipients": recipients, **details,
            })

    def _witness_weights(self) -> tuple[float, ...]:
        verified = {clue.target: clue.sign for clue in self.board.values()
                    if clue.source in ("primary", "reserve", "agreement")}
        balances = [0] * len(PEOPLE)
        for clue in self.board.values():
            if clue.holder is not None and clue.target in verified:
                balances[clue.holder] += 1 if clue.sign == verified[clue.target] else -1
        return tuple(min(1.4, max(0.6, 1 + 0.2 * balance)) for balance in balances)

    def _view(self, *, final: bool = False) -> View:
        candidates = tuple(target for target in self.world.order if final or target not in self.tested)
        return View(self.world.order, candidates, tuple(self.board.values()),
                    tuple(self.statements), self.rules.guarded, self._witness_weights())

    def _council(self, view: View) -> int | None:
        members = tuple(player for player in self.world.players if player.team)
        leader = members[0].number
        ballots = []
        for player in members:
            target = player.decoy(view)
            if target is None:
                continue
            ballots.append((target,))
            if player.number != leader:
                self._record("council_proposal", player.number, (leader,), target=target)
        if not ballots:
            return None
        candidates = tuple(target for target in view.candidates if target not in members[0].team)
        target = tally(replace(view, candidates=candidates, statements=()), ballots)[0]
        recipients = tuple(player.number for player in members if player.number != leader)
        if recipients:
            self._record("council_decision", leader, recipients, target=target)
        return target

    def _publish(self, statement: Statement):
        if statement.evidence is not None:
            observations = self.world.players[statement.sender].observations
            proof = next((clue for clue in observations if clue.key == statement.evidence), None)
            if proof is None or (proof.target, proof.sign) != (statement.target, statement.sign):
                self._record("rejected_statement", statement.sender, target=statement.target)
                return
            self.board.setdefault(proof.key, proof)
        else:
            self.outcome.unsupported += 1

        self.statements.append(statement)
        self.outcome.statements += 1
        audience = tuple(number for number in PEOPLE if number != statement.sender)
        self._record("statement", statement.sender, audience, target=statement.target,
                     sign=statement.sign, evidence=statement.evidence, reason=statement.reason,
                     counted=statement.evidence is not None or not self.rules.guarded)

    def _debate(self, decoy: int | None):
        for reply in (False, True):
            self.phase = "reply" if reply else "argument"
            view = self._view()
            scripted = self.rules.scenario in ("rumor", "combined")
            proposals = [player.speak(view, reply, decoy, scripted) for player in self.world.players]
            for proposal in proposals:
                if proposal is not None:
                    self._publish(proposal)

    def _ballots(self, view: View, seats: int, decoy: int | None,
                 before: tuple[tuple[int, ...], ...] = ()) -> list[tuple[int, ...]]:
        ballots = []
        for player in self.world.players:
            ballot = player.vote(view, seats, decoy if player.team else None)
            ballots.append(ballot)
            changed = bool(before and ballot != before[player.number])
            self.outcome.vote_changes += changed
            self._record("ballot", player.number, ("host",), choices=ballot, changed=changed,
                         previous=before[player.number] if changed else ())
        return ballots

    def _inspect(self, target: int):
        self.phase = "night"
        self.tested.add(target)
        self.outcome.visits.append(target)
        self.outcome.checks_on_mafia += target in self.world.team
        primary = self.world.primary[target]
        self._record("check_request", "host", ("primary",), target=target)
        if self.rules.scenario == "offline" and self.day <= 2:
            self.outcome.outages += 1
            primary = None
            self._record("outage", "primary", target=target)
        else:
            injected = self.day == 1 and self.rules.scenario in ("bad_check", "combined")
            if injected:
                wrong_sign = -1 if target in self.world.team else 1
                primary = replace(primary, sign=wrong_sign)
            self._record("check_answer", "primary", ("host",), target=target,
                         sign=primary.sign, injected=injected)

        clue = primary
        if self.rules.guarded:
            self._record("check_request", "host", ("reserve",), target=target)
            reserve = self.world.reserve[target]
            self._record("check_answer", "reserve", ("host",), target=target, sign=reserve.sign)
            if primary is None:
                clue = reserve
            elif primary.sign != reserve.sign:
                self.outcome.disagreements += 1
                clue = None
                self._record("disagreement", "host", target=target, primary=primary.sign,
                             reserve=reserve.sign)
            else:
                clue = replace(primary, key=f"agreement-{target}", source="agreement")

        previous_weights = self._witness_weights() if self.events is not None else ()
        if clue is not None:
            self.board[clue.key] = clue
            self.outcome.usable_clues += 1
            correct_sign = 1 if target in self.world.team else -1
            self.outcome.wrong_clues += clue.sign != correct_sign
        self._record("check_result", "host", PEOPLE, target=target,
                     sign=clue.sign if clue else None, evidence=clue.key if clue else None,
                     source=clue.source if clue else None)
        if previous_weights:
            for player, (old, new) in enumerate(zip(previous_weights, self._witness_weights())):
                if old != new:
                    self._record("trust_change", "host", target=player, before=old, after=new)

    def play(self) -> Outcome:
        if self.day:
            raise RuntimeError("Для новой партии нужен новый экземпляр игры.")
        self._record("initial", clues=tuple(asdict(clue) for clue in self.world.public))
        for day in range(1, self.rules.nights + 1):
            self.day = day
            self.phase = "start"
            self.statements.clear()
            view = self._view()
            self._record("day_start", candidates=view.candidates)
            decoy = self._council(view) if self.rules.debate or self.rules.coordination == "vote" else None
            before = ()
            if self.rules.debate:
                before = tuple(player.vote(view, 1, decoy if player.team else None)
                               for player in self.world.players)
                self._debate(decoy)
            view = self._view()
            self.phase = "choice"
            if self.rules.coordination == "host":
                target = rank(view.candidates, scores(view))[0]
            else:
                ballots = self._ballots(view, 1, decoy, before)
                target = tally(view, ballots)[0]
            self._record("nomination", "host", target=target, method=self.rules.coordination)
            self._inspect(target)

        self.phase = "verdict"
        view = self._view(final=True)
        seats = len(self.world.team)
        ballots = self._ballots(view, seats, self._council(view))
        self.outcome.verdict = tally(view, ballots, seats)
        self._record("verdict", "host", PEOPLE, choices=self.outcome.verdict)
        return self.outcome

    def replay(self) -> dict:
        if self.events is None or not self.outcome.verdict:
            raise ValueError("Трасса доступна после игры с включённой записью.")
        return {
            "seed": self.world.seed,
            "names": NAMES,
            "team": sorted(self.world.team),
            "rules": asdict(self.rules),
            "events": self.events,
            "outcome": asdict(self.outcome),
            "metrics": self.outcome.metrics(self.world, self.rules.nights),
        }
