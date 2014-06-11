import os
import jinja2
import webapp2
from random import sample, randint
from google.appengine.ext import ndb

from field import Board

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])


class GameState(ndb.Model):
    board = ndb.PickleProperty()
    next_auction = ndb.PickleProperty()
    players = ndb.PickleProperty()

    @classmethod
    def new_game(cls):
        board = Board()
        next_auction = sample(board.lands, 2)
        return cls(
            board=board,
            next_auction=next_auction,
            players=[],
        )


class Player():

    def __init__(self, name):
        self.name = name
        self.id = randint(1, 10000000)


class MainPage(webapp2.RequestHandler):

    def get(self):
        self.show_game(GameState.new_game())

    def show_game(self, state, player):
        template_values = dict(board=state.board, auction=state.next_auction,
                               players=state.players, player=player)
        template = JINJA_ENVIRONMENT.get_template('index.html')
        self.response.write(template.render(template_values))


class ShowGame(MainPage):

    def get(self, game_id, player_id=None):
        state = ndb.Key(GameState, int(game_id)).get()
        assert state
        try:
            player = [p for p in state.players if p.id == int(player_id)][0]
        except IndexError:
            player = None
        self.show_game(state, player)


class NewPlayer(webapp2.RequestHandler):

    def post(self, game_id):
        state = ndb.Key(GameState, int(game_id)).get()
        assert state

        player = Player(self.request.get('name'))
        state.players.append(player)
        state.put()
        self.redirect("/game/%d/%s" % (state.key.id(), player.id))


class NewGame(webapp2.RequestHandler):

    def get(self):
        state = GameState.new_game()
        state.put()
        self.redirect("/game/%d/" % state.key.id())


application = webapp2.WSGIApplication([
    (r'/', MainPage),
    (r'/new_game', NewGame),
    (r'/game/(\d+)/(\d*)', ShowGame),
    (r'/game/(\d+)/new_player', NewPlayer),
], debug=True)
