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
        game_changed = False
        if game.ready_for_auction:
            game.resolve_auction()
            game_changed = True
        if player and player.messages:
            for m in player.messages:
                self.session.add_flash(*m)
            player.messages = []
            game_changed = True
        if game_changed:
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
            game.start()
        game.put()
        self.session.add_flash('Joined successfully! Please bookmark this URL '
                               'to keep playing as this user.', 'success')
        self.redirect("/game/%d/%s" % (game.key.id(), player.id))


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
        self.redirect("/game/%d/" % game.key.id())


class ResolveAuction(BaseHandler):

    def get(self, game_id):
        game, _ = get_game(game_id, None)
        game.resolve_auction()
        game.put()
        self.redirect("/game/%d/" % game.key.id())


class StartGame(BaseHandler):

    def post(self, game_id, player_id):
        game, _ = get_game(game_id, None)
        assert int(player_id) == game.players[0].id
        game.start()
        game.put()
        self.redirect("/game/%d/%s" % (game.key.id(), player_id))


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
    (r'/game/(\d+)/(\d*)', ShowGame),
    (r'/game/(\d+)/(\d+)/start', StartGame),
    (r'/game/(\d+)', RedirectToGame),
    (r'/game/(\d+)/new_player', NewPlayer),
    (r'/game/(\d+)/resolve_auction', ResolveAuction),
], debug=True, config=config)
