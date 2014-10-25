import os
import jinja2
import webapp2
import json
import sys
from random import sample, randint
from itertools import chain
from datetime import datetime, timedelta
sys.path.insert(0, 'libs')

from google.appengine.ext import ndb
from google.appengine.api import channel
from google.appengine.runtime.apiproxy_errors import OverQuotaError
from webapp2_extras import sessions
import wtforms

from field import Board
from view import jinja_filters

config = {}
config['webapp2_extras.sessions'] = {
    'secret_key': 'my-super-secret-key',
}

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__) + '/templates'),
    autoescape=True)
JINJA_ENVIRONMENT.filters.update(jinja_filters)


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

        if all(p.bids is not None for p in self.players):
            # all players have placed bids
            return True

        return datetime.utcnow() > self.next_auction_time


    def resolve_auction(self):
        # resolve auction
        self.state['last_auction'] = []
        players = [p for p in self.players if p.bids is not None]
        for i in range(len(self.auction)):
            # reduce bids to available money
            for p in players:
                p.bids[i] = min(p.bids[i], p.money)

            # detect winner
            bidding_players = sorted(players, key=lambda p: (-p.bids[i], randint(0, 1000)))
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
        free_lands = {l for l in self.board.lands if not l.owner} - set(self.auction)
        self.state['upcoming_auction'] = sample(free_lands,
                                                min(self.auction_size, len(free_lands)))
        self.next_auction_time = datetime.utcnow() + timedelta(hours=self.max_time)

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
        self.money = game.start_money
        self.bids = None
        self.id = randint(1, 10000000)
        self.player_number = len(game.players) + 1
        self.connected_lands = 0
        self.game_key = game.key

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
        return {l for l in self.game.board.lands if l.owner and l.owner.id == self.id}

    @property
    def game(self):
        return self.game_key.get()


class BaseHandler(webapp2.RequestHandler):

    def __init__(self, *args, **kwargs):
        self.template_vars = {
            'handler': self,
        }
        webapp2.RequestHandler.__init__(self, *args, **kwargs)

    def get(self):
        template = JINJA_ENVIRONMENT.get_template(self.template)
        self.template_vars['route'] = self.request.route.name
        self.response.write(template.render(self.template_vars))

    def dispatch(self):
        # Get a session store for this request.
        self.session_store = sessions.get_store(request=self.request)

        try:
            # Dispatch the request.
            webapp2.RequestHandler.dispatch(self)
        finally:
            # Save all sessions.
            self.session_store.save_sessions(self.response)

    @webapp2.cached_property
    def session(self):
        # Returns a session using the default cookie key.
        return self.session_store.get_session()


class GamePage(BaseHandler):
    template = 'game.html'

    def get(self):
        self.show_game(Game.new_game(), None)

    def show_game(self, game, player):
        self.template_vars.update(dict(players=game.players, player=player, game=game))
        self.template_vars.update(game.state)
        self.template_vars['len'] = len
        if player:
            client_id = '%d/%d' % (game.key.id(), player.id)
            try:
                self.template_vars['channel_token'] = channel.create_channel(client_id)
            except OverQuotaError:
                pass
        BaseHandler.get(self)


def get_game(game_id, player_id):
    game = ndb.Key(Game, int(game_id)).get()
    assert game
    if player_id:
        player = [p for p in game.players if p.id == int(player_id)][0]
    else:
        player = None
    return game, player


def send_updates(game, player):
    for p in game.players:
        if p == player:
            continue
        client_id = '%d/%d' % (game.key.id(), p.id)
        message = dict(
            turn=game.turn,
            finished_players=[p.id for p in game.players if p.bids]
        )
        channel.send_message(client_id, json.dumps(message))


class ShowGame(GamePage):

    def get(self, game_id, player_id=None):
        game, player = get_game(game_id, player_id)
        if game.ready_for_auction:
            game.resolve_auction()
            game.put()
        self.show_game(game, player)

    def post(self, game_id, player_id):
        """ Place bids """
        game, player = get_game(game_id, player_id)
        player.bids = [float(b) if b != '' else 0
                       for b in self.request.POST.getall('bid')]
        if game.ready_for_auction:
            game.resolve_auction()
        send_updates(game, player)
        game.put()
        self.redirect("/game/%d/%s" % (game.key.id(), player.id))


class NewPlayer(BaseHandler):

    def post(self, game_id):
        game = ndb.Key(Game, int(game_id)).get()
        assert game

        player = Player(self.request.get('name'), game)
        game.players.append(player)
        if len(game.players) == game.number_of_players:
            game.status = 'in_progress'
            game.next_auction_time = datetime.utcnow() + timedelta(hours=game.max_time)
        game.put()
        self.session.add_flash('Joined successfully! Please bookmark this URL '
                               'to keep playing as this user.', 'success')
        self.redirect("/game/%d/%s" % (game.key.id(), player.id))


class IndexPage(BaseHandler):

    template = 'index.html'


class NewGameForm(wtforms.Form):

    players = wtforms.SelectField('Number of Players',
                                  choices=zip(range(2,11), range(2,11)),
                                  default=4, coerce=int)
    max_time = wtforms.SelectField('Maximum Hours per Turn',
                                   choices=zip(range(1,49), range(1,49)),
                                   default=24, coerce=float)


class NewGame(BaseHandler):

    template = 'new_game.html'

    def get(self):
        self.template_vars['form'] = NewGameForm()
        BaseHandler.get(self)

    def post(self):
        form = NewGameForm(self.request.POST)
        game = Game.new_game(**form.data)
        game.put()
        self.session.add_flash(
            'Game created succesfully! Please send the current URL to other '
            'people to allow them to join the game.', 'success')
        self.redirect("/game/%d/" % game.key.id())


class ResolveAuction(BaseHandler):

    def get(self, game_id):
        game, _ = get_game(game_id, None)
        game.resolve_auction()
        game.put()
        self.redirect("/game/%d/" % game.key.id())


class RedirectToGame(BaseHandler):

    def get(self, game_id):
        self.redirect("/game/%s/" % game_id)


application = webapp2.WSGIApplication([
    (r'/', IndexPage, 'index'),
    (r'/game/test', GamePage),
    (r'/new_game', NewGame, 'new_game'),
    (r'/game/(\d+)/(\d*)', ShowGame),
    (r'/game/(\d+)', RedirectToGame),
    (r'/game/(\d+)/new_player', NewPlayer),
    (r'/game/(\d+)/resolve_auction', ResolveAuction),
], debug=True, config=config)
