from __future__ import division
import math
from random import sample, randint
from itertools import chain
from datetime import datetime, timedelta

from google.appengine.ext import ndb

import ai
from field import Board


class Game(ndb.Model):
    state = ndb.PickleProperty()
    number_of_players = ndb.IntegerProperty()
    max_time = ndb.FloatProperty()
    auction_size = ndb.IntegerProperty()
    start_money = ndb.FloatProperty()
    new_money = ndb.FloatProperty()
    final_payout = ndb.FloatProperty()
    auction_type = ndb.TextProperty()
    status = ndb.TextProperty(default='new')
    turn = ndb.IntegerProperty(default=0)
    next_auction_time = ndb.DateTimeProperty()

    @classmethod
    def new_game(cls, auction_size=3, start_money=1000, new_money=100,
                 final_payout=500, auction_type='1st_price', players=2,
                 max_time=24):
        board = Board(size=(8, 8))
        auction = sample(board.lands, auction_size)
        upcoming_auction = sample(board.lands - set(auction), auction_size)
        return cls(
            state=dict(
                board=board,
                auction=auction,
                upcoming_auction=upcoming_auction,
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
        )

    @property
    def board(self):
        return self.state['board']

    @property
    def players(self):
        return self.state['players']

    @property
    def auction(self):
        return self.state['auction']

    @property
    def upcoming_auction(self):
        return self.state['upcoming_auction']

    @property
    def ready_for_auction(self):
        if self.status != 'in_progress':
            return False

        if all(
                p.bids is not None
                or p.ai
                or p.quit
                for p in self.players
            ):
            # all players have placed bids
            return True

        return datetime.utcnow() > self.next_auction_time

    @property
    def remaining_turns(self):
        print '>>>', [l for l in self.board.lands if not l.owner]
        return math.ceil(
            len(
                [l for l in self.board.lands if not l.owner]
            ) / self.auction_size
        )

    @property
    def remaining_payout(self):
        if self.remaining_turns == 0:
            return 0
        return (self.remaining_turns - 1) * self.new_money + self.final_payout

    def resolve_auction(self):
        # ai players
        for p in self.players:
            if p.ai:
                p.bids = ai.calculate_bids(self, p)

        # resolve auction
        self.state['last_auction'] = []
        players = [p for p in self.players if p.bids is not None]
        for i in range(len(self.auction)):
            # reduce bids to available money
            for p in players:
                p.bids[i] = min(p.bids[i], p.money)

            # detect winner
            bidding_players = sorted(players, key=lambda p: (-p.bids[i],
                                                             randint(0, 1000)))
            if not bidding_players:
                continue
            winner = bidding_players[0]

            # transfer land to winner
            land = self.auction[i]
            if self.auction_type == '1st_price':
                price = winner.bids[i]
            elif self.auction_type == '2nd_price':
                price = bidding_players[1].bids[i]
            else:
                raise Exception('Unknown auction type')
            winner.money -= price
            land.owner = winner
            land.price = price
            self.state['last_auction'].append(land)

        # clear bids
        for p in self.players:
            p.bids = None

        # prepare next auction
        self.state['auction'] = self.upcoming_auction
        free_lands = {l for l in self.board.lands
                      if not l.owner} - set(self.auction)
        self.state['upcoming_auction'] = sample(free_lands,
                                                min(self.auction_size,
                                                    len(free_lands)))
        self.next_auction_time = (
            datetime.utcnow() + timedelta(hours=self.max_time))

        # update connected_lands
        for p in self.players:
            p.update_connected_lands()

        self.distribute_money()
        self.turn += 1

    def distribute_money(self):
        self.players.sort(key=lambda p: (-p.connected_lands, -len(p.lands),
                                         -p.money, randint(0, 1000)))
        payouts = list(reversed(range(len(self.players))))
        total_payout = self.new_money
        if not self.auction:
            self.status = 'finished'
            total_payout = self.final_payout
        scaling = total_payout / sum(payouts)
        for payout, player in zip(payouts, self.players):
            player.payout = round(payout * scaling)
            player.money += player.payout
            if player.money == 0:
                player.quit = True

    def start(self):
        self.status = 'in_progress'
        self.next_auction_time = (
            datetime.utcnow() + timedelta(hours=self.max_time))
        # add AI players
        for i in range(self.number_of_players - len(self.players)):
            player = Player(ai.player_name(), self, ai=True)
            self.players.append(player)


def flatten(listOfLists):
    "Flatten one level of nesting"
    return chain.from_iterable(listOfLists)


class Player():
    #name = ndb.TextProperty()
    #money = ndb.FloatProperty()
    #bids = ndb.FloatProperty(repeated=True)
    #id = ndb.IntegerProperty()
    #player_number = ndb.IntegerProperty()
    #connected_lands = ndb.IntegerProperty()
    #game_key = ndb.KeyProperty(kind=Game)

    def __init__(self, name, game, ai=False):
        self.name = name
        self.money = game.start_money
        self.bids = None
        self.id = randint(1, 10000000)
        self.player_number = len(game.players) + 1
        self.connected_lands = 0
        self.game_key = game.key
        self.ai = ai
        self.quit = False

    def update_connected_lands(self):
        if not self.lands:
            return
        last_islands = None
        islands = {frozenset([l]) for l in self.lands}
        while islands != last_islands:
            last_islands = islands
            islands = {
                frozenset(
                    l for l in flatten(
                        land.neighbors.union({land}) for land in i
                    ) if l.owner and l.owner.id == self.id
                ) for i in islands}
        self.connected_lands = max(len(i) for i in islands)

    @property
    def lands(self):
        return {l for l in self.game.board.lands
                if l.owner and l.owner.id == self.id}

    @property
    def game(self):
        return self.game_key.get()
