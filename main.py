import os
import jinja2
import webapp2
import json
import sys
from datetime import datetime, timedelta
from random import randint
from collections import OrderedDict
sys.path.insert(0, 'libs')

from google.appengine.ext import ndb
from google.appengine.api import channel
from google.appengine.runtime.apiproxy_errors import OverQuotaError
from webapp2_extras import sessions
import wtforms
import numpy

from view import jinja_filters
from model import Game, Player

config = {}
config['webapp2_extras.sessions'] = {
    'secret_key': 'my-super-secret-key',
}

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__) + '/templates'),
    autoescape=True)
JINJA_ENVIRONMENT.filters.update(jinja_filters)


auction_order_labels = OrderedDict([
    ('random', 'Random'),
    ('go_west', 'Go West!'),
    ('small_first', 'Small lands first'),
    ('small_last', 'Largest lands first'),
    ('connected', 'Fields adjacent to fields lands first'),
    ('edge_first', 'From edge to center'),
    ('edge_last', 'From center to edge'),
])


class BaseHandler(webapp2.RequestHandler):

    template_vars = {}

    def __init__(self, *args, **kwargs):
        self.template_vars.update({
            'handler': self,
            'uri_for': lambda name, *args, **kwargs: \
                webapp2.uri_for(name, self.request, *args, **kwargs),
            'index_url': 'http://' + os.environ['DEFAULT_VERSION_HOSTNAME'],
        })
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

    def set_cookie(self, key, value):
        domain = os.environ['DEFAULT_VERSION_HOSTNAME']
        if 'localhost' in domain:
            domain = None
        self.response.set_cookie(key, value,
                            expires=datetime.now() + timedelta(days=300),
                            domain=domain)


class GamePage(BaseHandler):
    template = 'game.html'

    def get(self):
        self.show_game(Game.new_game('test'), None)

    def show_game(self, game, player):
        # sort players by money if game has finished
        if game.status == 'finished':
            game.players.sort(key=lambda p: -p.money)
        self.template_vars.update(dict(players=game.players,
                                       player=player, game=game,
                                       auction_order_labels=auction_order_labels))
        self.template_vars.update(game.state)
        self.template_vars['len'] = len
        if player:
            client_id = '%d/%d' % (game.key.id(), player.id)
            try:
                self.template_vars['channel_token'] \
                        = channel.create_channel(client_id)
            except OverQuotaError:
                pass
        BaseHandler.get(self)


def get_game(game_id, player_secret):
    game = ndb.Key(Game, int(game_id)).get()
    assert game
    if player_secret:
        player = [p for p in game.players if p.secret == int(player_secret)][0]
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

    def check_for_changes(self, game, player):
        game_changed = False

        # trigger auction
        if game.ready_for_auction:
            game.resolve_auction()
            game_changed = True

        # show queued messages
        if player and player.messages:
            for m in player.messages:
                self.session.add_flash(*m)
            player.messages = []
            game_changed = True

        if game_changed:
            game.put()

    @ndb.transactional
    def get(self, game_id, player_id=None):
        game, player = get_game(game_id, player_id)

        # redirect to player page if cookie is present
        cookie_secret = self.request.cookies.get('game-%s' % game_id)
        all_secrets = [p.secret for p in game.players]
        if not player and cookie_secret and int(cookie_secret) in all_secrets:
            return self.redirect(game.url(player_secret=cookie_secret))

        self.check_for_changes(game, player)

        # set cookie
        if player:
            self.set_cookie('game-%s' % game_id, str(player.secret))

        self.show_game(game, player)

    @ndb.transactional
    def post(self, game_id, player_id):
        """ Place bids """
        if self.request.content_type == 'application/json':
            # JSON post
            bids = json.loads(self.request.body)['bids']
        else:
            # form post
            bids = self.request.POST.getall('bid')

        game, player = get_game(game_id, player_id)
        player.bids = [float(b) if b != '' else 0
                       for b in bids]
        if game.ready_for_auction:
            game.resolve_auction()
        game.put()
        send_updates(game, player)
        self.redirect("/game/%d/%s" % (game.key.id(), player.secret))


def dumper(obj):
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, numpy.ndarray):
        return obj.tolist()
    if hasattr(obj, 'to_json'):
        return obj.to_json()
    return obj.__dict__


class JSONGame(ShowGame):

    @ndb.transactional
    def get(self, game_id, player_id=None):
        game, player = get_game(game_id, player_id)
        self.check_for_changes(game, player)
        self.response.headers['Content-Type'] = 'application/json'
        for p in game.players:
            p.me = False
        player.me = True
        data = json.dumps(game, default=dumper, sort_keys=True, indent=4)
        self.response.write(data)


class NewPlayer(BaseHandler):

    @ndb.transactional
    def post(self, game_id):
        game = ndb.Key(Game, int(game_id)).get()
        assert game

        player = Player(self.request.get('name'), game)
        notify_defaults = self.request.cookies.get('notify-defaults')
        if notify_defaults:
            player.email, player.notify = notify_defaults.split('|')
        game.players.append(player)
        if len(game.players) == game.number_of_players:
            game.start()
        game.put()
        self.session.add_flash('Joined successfully! Please bookmark this URL '
                               'if you want to continue playing on a '
                               'different device. You can now place your bids '
                               'for the first round of auctions.', 'success')
        self.redirect("/game/%d/%s" % (game.key.id(), player.secret))


class IndexPage(BaseHandler):

    template = 'index.html'


class NewGameForm(wtforms.Form):

    name = wtforms.StringField('Game name')
    players = wtforms.SelectField('Number of Players',
            choices=zip(range(2, 11), range(2, 11)),
            default=4, coerce=int,
            description='If you start the game with fewer players, AI players '
                        'will take the remaining seats.')
    start_money = wtforms.SelectField('Starting Money for each Player',
            choices=[(x, str(x)) for x in [
                200, 350, 500, 700, 1000, 1500
            ]],
            default=500, coerce=int,
            description='Each new turn will distribute 100 among the players.')
    max_time = wtforms.SelectField('Maximum Time per Turn',
            choices=[
                (0.0166666667, '1 minute'),
                (0.0833333333, '5 minutes'),
                (0.25, '15 minutes'),
                (1, '1 hour'),
                (3, '3 hours'),
                (6, '6 hours'),
                (12, '12 hours'),
                (24, '24 hours'),
                (2 * 24, '2 days'),
                (4 * 24, '4 days'),
                (7 * 24, '1 week'),
            ],
            default=24, coerce=float,
            description='Usually, the next turn begins when all players have '
                        'submitted their bids. If this time limit is reached '
                        'an AI will take the player''s turn.')
    auction_order = wtforms.SelectField('Land Auction Order',
            choices=auction_order_labels.items(),
            default='random',
            description='Which lands are auctioned first? "Random" is '
                        'recommended for new players.')
    public = wtforms.BooleanField('Show game in public games list',
            description='Other players will be able to see your game and '
                        'join, without receiving an invitation.')


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
        self.redirect(game.url())


class QuickAIGame(BaseHandler):

    def get(self):
        game = Game.new_game('Test Game')
        game.put()
        player = Player('You', game)
        player.email, player.notify = '', 'turn'
        game.players.append(player)
        game.start()
        game.put()
        self.session.add_flash(
            'This game has been set up for you to try Land Rush '
            'against AI players. The real fun will be playing against humans.',
            'success')
        self.redirect(game.url(player.secret))


class ResolveAuction(BaseHandler):

    @ndb.transactional
    def get(self, game_id):
        game, _ = get_game(game_id, None)
        game.resolve_auction()
        game.put()
        self.redirect("/game/%d/" % game.key.id())


class StartGame(BaseHandler):

    @ndb.transactional
    def post(self, game_id, player_secret):
        game, _ = get_game(game_id, None)
        assert int(player_secret) == game.players[0].secret
        game.start()
        game.put()
        self.redirect(game.url(player_secret))


class Notifications(BaseHandler):

    @ndb.transactional
    def post(self, game_id, player_secret):
        game, player = get_game(game_id, player_secret)

        # change settings
        player.email = self.request.POST['email']
        player.notify = self.request.POST['when']
        game.put()

        # change defaults in cookie
        defaults = '%s|%s' % (player.email, player.notify)
        self.set_cookie('notify-defaults', defaults)
        self.session.add_flash('Notification settings changed successfully',
                               'success')
        self.redirect(game.url(player_secret))


class RedirectToGame(BaseHandler):

    def get(self, game_id):
        self.redirect("/game/%s/" % game_id)


class ListGames(BaseHandler):

    template = 'list_games.html'

    def get(self):
        open_games = list(
            Game.query(Game.public == True, Game.status == 'new')
        )
        if not open_games:
            name = 'Newbies %d' % randint(1000, 9999)
            game = Game.new_game(name, public=True)
            game.put()
            open_games = [game]

        self.template_vars['open_games'] = open_games
        self.template_vars['games_in_progress'] = Game.query(Game.public == True, Game.status == 'in_progress')
        self.template_vars['finished_games'] = Game.query(Game.public == True, Game.status == 'finished')
        BaseHandler.get(self)


class RulesPage(BaseHandler):

    template = 'rules.html'
    template_vars = {
        'content': jinja2.Markup(
            open(os.path.dirname(__file__) + '/templates/markdown/rules.html').read()
        )
    }


application = webapp2.WSGIApplication([
    # public
    webapp2.Route(r'/', IndexPage, 'index'),
    (r'/game/test', GamePage),
    (r'/new_game', NewGame, 'new_game'),
    (r'/quick_ai_game', QuickAIGame, 'quick_ai_game'),
    (r'/list_games', ListGames, 'list_games'),
    (r'/rules', RulesPage, 'rules'),

    # running game
    webapp2.Route(r'/game/<:\d+>/<:\d*>', ShowGame, 'game'),
    (r'/game/(\d+)/(\d+)/start', StartGame),
    (r'/game/(\d+)/(\d+)/notifications', Notifications),
    (r'/game/(\d+)/(\d+)/json', JSONGame),
    (r'/game/(\d+)', RedirectToGame),
    (r'/game/(\d+)/new_player', NewPlayer),
    (r'/game/(\d+)/resolve_auction', ResolveAuction),
], debug=True, config=config)
