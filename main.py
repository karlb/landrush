import os
import jinja2
import webapp2
import json
import sys
from datetime import datetime, timedelta
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


class BaseHandler(webapp2.RequestHandler):

    def __init__(self, *args, **kwargs):
        self.template_vars = {
            'handler': self,
            'uri_for': lambda name, *args, **kwargs: \
                webapp2.uri_for(name, self.request, *args, **kwargs),
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
                                       player=player, game=game))
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

    def get(self, game_id, player_id=None):
        game, player = get_game(game_id, player_id)

        # redirect to player page if cookie is present
        cookie_secret = self.request.cookies.get('game-%s' % game_id)
        if not player and cookie_secret in [p.secret for p in game.players]:
            return self.redirect(game.url(player_secret=cookie_secret))

        self.check_for_changes(game, player)

        # set cookie
        if player:
            self.set_cookie('game-%s' % game_id, str(player.secret))

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

    def get(self, game_id, player_id=None):
        game, player = get_game(game_id, player_id)
        self.check_for_changes(game, player)
        self.response.headers['Content-Type'] = 'application/json'
        player.me = True
        data = json.dumps(game, default=dumper, sort_keys=True, indent=4)
        self.response.write(data)


class NewPlayer(BaseHandler):

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
                               'different device.', 'success')
        self.redirect("/game/%d/%s" % (game.key.id(), player.secret))


class IndexPage(BaseHandler):

    template = 'index.html'


class NewGameForm(wtforms.Form):

    name = wtforms.StringField('Game name')
    players = wtforms.SelectField('Number of Players',
                                  choices=zip(range(2, 11), range(2, 11)),
                                  default=4, coerce=int)
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
                                   default=24, coerce=float)
    auction_order = wtforms.SelectField('Field Auction Order',
                                        choices=[
                                            ('random', 'Random'),
                                            ('go_west', 'Go West!'),
                                            ('small_first', 'Small lands first'),
                                            ('small_last', 'Small lands last'),
                                        ],
                                        default='random')
    public = wtforms.BooleanField('Show game in public games list')


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


class ResolveAuction(BaseHandler):

    def get(self, game_id):
        game, _ = get_game(game_id, None)
        game.resolve_auction()
        game.put()
        self.redirect("/game/%d/" % game.key.id())


class StartGame(BaseHandler):

    def post(self, game_id, player_secret):
        game, _ = get_game(game_id, None)
        assert int(player_secret) == game.players[0].secret
        game.start()
        game.put()
        self.redirect(game.url(player_secret))


class Notifications(BaseHandler):

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
        self.template_vars['open_games'] = Game.query(Game.public == True, Game.status == 'new')
        self.template_vars['games_in_progress'] = Game.query(Game.public == True, Game.status == 'in_progress')
        self.template_vars['finished_games'] = Game.query(Game.public == True, Game.status == 'finished')
        BaseHandler.get(self)


application = webapp2.WSGIApplication([
    (r'/', IndexPage, 'index'),
    (r'/game/test', GamePage),
    (r'/new_game', NewGame, 'new_game'),
    (r'/list_games', ListGames, 'list_games'),
    webapp2.Route(r'/game/<:\d+>/<:\d*>', ShowGame, 'game'),
    (r'/game/(\d+)/(\d+)/start', StartGame),
    (r'/game/(\d+)/(\d+)/notifications', Notifications),
    (r'/game/(\d+)/(\d+)/json', JSONGame),
    (r'/game/(\d+)', RedirectToGame),
    (r'/game/(\d+)/new_player', NewPlayer),
    (r'/game/(\d+)/resolve_auction', ResolveAuction),
], debug=True, config=config)
