import math
import os
from random import shuffle, randint
from itertools import chain
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Optional
import pickle

import pkg_resources
from flask import g, url_for

import landrush.ai as ai
import landrush.mail as mail
from landrush.field import Board


@dataclass
class Game:
    game_id: int
    state: dict
    number_of_players: int
    max_time: float
    auction_size: int
    start_money: int
    new_money: int
    final_payout: int
    auction_type: str
    name: str
    version: str
    created_at: datetime
    finished_at: Optional[datetime] = None
    status: str = "new"
    turn: int = 0
    auction_order: str = "random"
    next_auction_time: Optional[datetime] = None
    payout_exponent: float = 2
    allowed_missed_deadlines: int = 2
    public: bool = False

    def __post_init__(self):
        # convert values from db to python
        if isinstance(self.state, bytes):
            self.state = pickle.loads(self.state)  # type: ignore
        for key in ["created_at", "finished_at", "next_auction_time"]:
            value = getattr(self, key)
            if isinstance(value, float):
                setattr(self, key, datetime.utcfromtimestamp(value))

    @classmethod
    def new_game(
        cls,
        name,
        start_money=500,
        auction_type="1st_price",
        players=4,
        max_time=24,
        public=False,
        auction_order="random",
    ):
        auction_size = 3 + (players - 2) // 3
        x_size = 9
        y_size = int(round(auction_size * 2.3))
        board = Board(size=(x_size, y_size), joins=int(x_size * y_size * 0.4))
        new_money = 25 * players
        final_payout = new_money * 5
        self = cls(
            game_id=g.next_game_id,
            state=dict(
                board=board,
                auction=[],
                upcoming_auction=[],
                last_auction=[],
                players=[],
            ),
            number_of_players=players,
            max_time=max_time,
            auction_size=auction_size,
            start_money=start_money,
            new_money=new_money,
            final_payout=final_payout,
            auction_type=auction_type,
            public=public,
            name=name,
            auction_order=auction_order,
            version=pkg_resources.get_distribution("landrush").version.split(".")[0],
            created_at=datetime.utcnow(),
        )
        self.state["auction"] = self.make_auction()
        self.state["upcoming_auction"] = self.make_auction()
        g.next_game_id += 1
        return self

    @property
    def board(self):
        return self.state["board"]

    @property
    def players(self):
        return self.state["players"]

    @property
    def auction(self):
        return self.state["auction"]

    @property
    def upcoming_auction(self):
        return self.state["upcoming_auction"]

    @property
    def ready_for_auction(self):
        if self.status != "in_progress":
            return False
        assert self.next_auction_time

        if all(p.bids is not None or p.ai or p.quit for p in self.players):
            # all players have placed bids
            return True

        return datetime.utcnow() > self.next_auction_time

    @property
    def remaining_turns(self):
        return int(
            math.ceil(
                len([l for l in self.board.lands if not l.owner]) / self.auction_size
            )
        )

    @property
    def remaining_payout(self):
        if self.remaining_turns == 0:
            return 0
        return (self.remaining_turns - 1) * self.new_money + self.final_payout

    def resolve_auction(self):
        # place bids for ai and missing players
        for p in self.players:
            if p.bids is None and not p.ai and not p.quit:
                p.missed_deadlines += 1
                times_left = self.allowed_missed_deadlines - p.missed_deadlines
                if times_left == 0:
                    p.ai = True
                    message = """ You have missed the auction deadline too
                               often.  We don't need you, anymore. Be on time
                               during your next game! """
                else:
                    if times_left == 1:
                        more_text = "one more time"
                    else:
                        more_text = "%d more times" % times_left
                    message = (
                        """ You have missed the auction deadline, so
                               your nephew placed some bids for you. If you do
                               this %s, he will go on without you."""
                        % more_text
                    )
                p.messages.append([message, "danger"])
            if p.ai or p.bids is None:
                p.bids = ai.calculate_bids(self, p)

        # resolve auction
        self.state["last_auction"] = []
        for i in range(len(self.auction)):
            # reduce bids to available money
            for p in self.players:
                p.bids[i] = min(p.bids[i], p.money)

            # detect winner
            bidding_players = sorted(
                self.players, key=lambda p: (-p.bids[i], randint(0, 1000))
            )
            if not bidding_players:
                continue
            winner = bidding_players[0]

            # transfer land to winner
            land = self.auction[i]
            if self.auction_type == "1st_price":
                price = winner.bids[i]
            elif self.auction_type == "2nd_price":
                price = bidding_players[1].bids[i]
            else:
                raise Exception("Unknown auction type")
            winner.money -= price
            land.owner = winner
            land.price = price
            self.state["last_auction"].append(land)

        # clear bids
        for p in self.players:
            p.last_bid_sum = sum(p.bids)
            p.bids = None

        # prepare next auction
        self.state["auction"] = self.upcoming_auction
        self.state["upcoming_auction"] = self.make_auction()
        self.next_auction_time = datetime.utcnow() + timedelta(hours=self.max_time)

        # update connected_lands
        for p in self.players:
            p.update_connected_lands()

        self.distribute_money()
        self.turn += 1
        mail.turn_finished(self)

    def make_auction(self):
        free_lands = list(
            {l for l in self.board.lands if not l.owner} - set(self.auction)
        )
        shuffle(free_lands)
        sort_order = {
            "random": lambda l: 0,
            "go_west": lambda l: -max(f.index[0] for f in l.fields),
            "small_first": lambda l: len(l.fields),
            "small_last": lambda l: -len(l.fields),
            "connected": lambda l: len(
                [n for n in l.neighbors if n.owner is not None or n in self.auction]
            )
            == 0,
            "edge_first": lambda l: l.distance_to_edge,
            "edge_last": lambda l: l.distance_to_center,
        }
        sorted_lands = sorted(free_lands, key=sort_order[self.auction_order])
        return sorted_lands[: self.auction_size]

    def url(self, player_secret=None):
        return url_for(
            "show_game",
            game_id=self.game_id,
            player_secret=player_secret,
            _external=True,
        )

    @property
    def payouts(self):
        payouts = [
            p ** self.payout_exponent for p in reversed(range(self.number_of_players))
        ]
        # penalize last player (especially when playing with many players)
        payouts[-1] -= max((self.number_of_players - 2) / 2, 0)
        total_payout = self.new_money
        if not self.auction:
            self.status = "finished"
            total_payout = self.final_payout
            self.finished_at = datetime.utcnow()
        scaling = total_payout / sum(payouts)  # type: ignore
        return [int(round(pay * scaling)) for pay in payouts]

    def distribute_money(self):
        self.players.sort(
            key=lambda p: (
                -p.connected_lands,
                -len(p.lands),
                -p.last_bid_sum,
                p.money,
                randint(0, 1000),
            )
        )
        for payout, player in zip(self.payouts, self.players):
            player.payout = payout
            player.money += player.payout
            if player.money <= 0:
                player.quit = True

    def start(self):
        self.status = "in_progress"
        self.next_auction_time = datetime.utcnow() + timedelta(hours=self.max_time)
        # add AI players
        for i in range(self.number_of_players - len(self.players)):
            player = Player(ai.player_name(), self, ai=True)
            self.players.append(player)

    def as_db_dict(self):
        d = asdict(self)
        d["state"] = pickle.dumps(self.state)
        for key in ["created_at", "finished_at", "next_auction_time"]:
            if d[key] is not None:
                d[key] = d[key].timestamp()
        return d


def flatten(listOfLists):
    "Flatten one level of nesting"
    return chain.from_iterable(listOfLists)


class Player(object):
    def __init__(self, name, game, ai=False):
        self.name = name
        self.money = game.start_money
        self.bids = None
        self.id = randint(1, 10000000)
        self.secret = randint(1, 1000000000)
        self.player_number = len(game.players) + 1
        self.connected_lands = 0
        self.game_id = game.game_id
        self.ai = ai
        self.quit = False
        self.missed_deadlines = 0
        self.messages = []
        self.email = ""
        self.notify = "turn"
        self.game = game

    def to_json(self):
        data = dict(
            (key, getattr(self, key))
            for key in "name money bids connected_lands ai missed_deadlines "
            "messages email notify id player_number me secret".split(" ")
        )
        data["bids_placed"] = bool(data["bids"])
        if not data["me"]:
            # make bids secret
            del data["bids"]
            del data["secret"]
        return data

    def islands(self):
        """Islands are a set of connected lands"""
        last_islands = None
        islands = {frozenset([l]) for l in self.lands}
        while islands != last_islands:
            last_islands = islands
            islands = {
                frozenset(
                    l
                    for l in flatten(land.neighbors.union({land}) for land in i)
                    if l.owner and l.owner.id == self.id
                )
                for i in islands
            }
        return islands

    def update_connected_lands(self):
        if not self.lands:
            return
        self.connected_lands = max(len(i) for i in self.islands())

    @property
    def lands(self):
        return {l for l in self.game.board.lands if l.owner and l.owner.id == self.id}
