import os
import jinja2
import webapp2
from random import sample, randint
from google.appengine.ext import ndb
from itertools import chain

from field import Board
from view import jinja_filters

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])
JINJA_ENVIRONMENT.filters.update(jinja_filters)


class Game(ndb.Model):
    state = ndb.PickleProperty()
    players = ndb.PickleProperty()  # TODO: KeyProperty(repeated=True)
    auction_size = ndb.IntegerProperty()
    start_money = ndb.FloatProperty()
    new_money = ndb.FloatProperty()
    final_payout = ndb.FloatProperty()

    @classmethod
    def new_game(cls, auction_size=2, start_money=1000, new_money=100, final_payout=500):
        board = Board()
        auction = sample(board.lands, auction_size)
        upcoming_auction = sample(board.lands - set(auction), auction_size)
        return cls(
            state=dict(
                board=board,
                auction=auction,
                upcoming_auction=upcoming_auction,
                last_auction=[],
            ),
            players=[],
            auction_size=auction_size,
            start_money=start_money,
            new_money=new_money,
            final_payout=final_payout,
        )

    @property
    def board(self):
        return self.state['board']

    @property
    def auction(self):
        return self.state['auction']

    @property
    def upcoming_auction(self):
        return self.state['upcoming_auction']

    def resolve_auction(self):
        # resolve auction
        self.state['last_auction'] = []
        for i in range(len(self.auction)):
            bidding_players = sorted((p for p in self.players if p.bids[i]),
                                     key=lambda p: -p.bids[i])
            if not bidding_players:
                continue
            winner = bidding_players[0]
            land = self.auction[i]
            price = winner.bids[i]
            winner.money -= price
            land.owner = winner
            self.state['last_auction'].append(dict(player=winner, land=land, price=price))

        # clear bids
        for p in self.players:
            p.bids = None

        # prepare next auction
        self.state['auction'] = self.upcoming_auction
        free_lands = {l for l in self.board.lands if not l.owner} - set(self.auction)
        self.state['upcoming_auction'] = sample(free_lands,
                                                min(self.auction_size, len(free_lands)))

        # update connected_lands
        for p in self.players:
            p.update_connected_lands()

        self.distribute_money()

    def distribute_money(self):
        self.players.sort(key=lambda p: (-p.connected_lands, -p.money))
        payouts = list(reversed(range(len(self.players))))
        total_payout = (
            self.new_money if self.upcoming_auction
            else self.final_payout)
        scaling = total_payout / sum(payouts)
        for payout, player in zip(payouts, self.players):
            player.payout = payout * scaling
            player.money += player.payout


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

    def __init__(self, name, game):
        self.name = name
        self.money = game.state['start_money']
        self.bids = None
        self.id = randint(1, 10000000)
        self.player_number = len(game.players) + 1
        self.connected_lands = 0
        self.game_key = game.key

    def update_connected_lands(self):
        if not self.lands:
            return 0
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
        return {l for l in self.game.board.lands if l.owner and l.owner.id == self.id}

    @property
    def game(self):
        return self.game_key.get()


class MainPage(webapp2.RequestHandler):

    def get(self):
        self.show_game(Game.new_game(), None)

    def show_game(self, game, player):
        template_values = dict(players=game.players, player=player)
        template_values.update(game.state)
        template = JINJA_ENVIRONMENT.get_template('index.html')
        self.response.write(template.render(template_values))


def get_game(game_id, player_id):
    game = ndb.Key(Game, int(game_id)).get()
    assert game
    if player_id:
        player = [p for p in game.players if p.id == int(player_id)][0]
    else:
        player = None
    return game, player


class ShowGame(MainPage):

    def get(self, game_id, player_id=None):
        game, player = get_game(game_id, player_id)
        self.show_game(game, player)

    def post(self, game_id, player_id):
        """ Place bids """
        game, player = get_game(game_id, player_id)
        player.bids = [float(b) if b != '' else 0
                       for b in self.request.POST.getall('bid')]
        if all(p.bids is not None for p in game.players):
            game.resolve_auction()
        game.put()
        self.redirect("/game/%d/%s" % (game.key.id(), player.id))


class NewPlayer(webapp2.RequestHandler):

    def post(self, game_id):
        game = ndb.Key(Game, int(game_id)).get()
        assert game

        player = Player(self.request.get('name'), game)
        game.players.append(player)
        game.put()
        self.redirect("/game/%d/%s" % (game.key.id(), player.id))


class NewGame(webapp2.RequestHandler):

    def get(self):
        game = Game.new_game()
        game.put()
        self.redirect("/game/%d/" % game.key.id())


class ResolveAuction(webapp2.RequestHandler):

    def get(self, game_id):
        game, _ = get_game(game_id, None)
        game.resolve_auction()
        game.put()
        self.redirect("/game/%d/" % game.key.id())


application = webapp2.WSGIApplication([
    (r'/', MainPage),
    (r'/new_game', NewGame),
    (r'/game/(\d+)/(\d*)', ShowGame),
    (r'/game/(\d+)/new_player', NewPlayer),
    (r'/game/(\d+)/resolve_auction', ResolveAuction),
], debug=True)
