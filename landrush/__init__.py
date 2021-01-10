import os
import sqlite3
from random import randint

from flask import Flask, render_template, g, request, flash, redirect, url_for, make_response
import wtforms  # type: ignore
import aiosql  # type: ignore
import jinja2

from landrush.model import Game, Player

app = Flask(__name__)
app.config.from_mapping(SECRET_KEY='dev')
DB_PATH = os.path.join(app.instance_path, 'main.sqlite3')
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
queries = aiosql.from_path(
    APP_ROOT + "/schema.sql",
    'sqlite3',
    record_classes=dict(
        game=Game,
    )
)


@app.template_filter('money')
def money(m):
    return '' if isinstance(m, jinja2.Undefined) else '%d' % m


@app.before_request
def get_db():
    db = getattr(g, 'db', None)
    if db is None:
        db = g.db = sqlite3.connect(DB_PATH)
        db.execute("PRAGMA foreign_keys = ON")
        if not db.execute(
                "SELECT name from sqlite_master WHERE type='table' AND name='game'"
                ).fetchone():
            with db:
                queries.create_schema(db)
        g.next_game_id = db.execute(
            'SELECT coalesce(max(game_id), 0) FROM game'
            ).fetchall()[0][0] + 1


@app.after_request
def close_connection(response):
    db = getattr(g, 'db', None)
    if db is not None:
        db.close()

    return response


auction_order_labels = dict([
    ('random', 'Random'),
    ('go_west', 'Go West!'),
    ('small_first', 'Small lands first'),
    ('small_last', 'Largest lands first'),
    ('connected', 'Fields adjacent to fields lands first'),
    ('edge_first', 'From edge to center'),
    ('edge_last', 'From center to edge'),
])


class NewGameForm(wtforms.Form):

    name = wtforms.StringField('Game name')
    players = wtforms.SelectField('Number of Players',
            choices=[(i, i) for i in range(2, 11)],
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


def get_game(game_id, player_secret):
    game = queries.get_game(g.db, game_id)

    # Recognize player from URL secret
    if player_secret:
        player = [p for p in game.players if p.secret == int(player_secret)][0]
    else:
        player = None

    return game, player


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/new_game', methods=['POST', 'GET'])
def new_game():
    if request.method == 'POST':
        form = NewGameForm(request.args)
        game = Game.new_game(**form.data)
        queries.save_game(g.db, **game.as_db_dict())
        g.db.commit()
        flash(
            'Game created succesfully! Please send the current URL to other '
            'people to allow them to join the game.', 'success')
        return redirect(url_for('show_game', game_id=game.game_id))

    return render_template('new_game.html', form=NewGameForm())


@app.route('/game/<game_id>/')
@app.route('/game/<game_id>/<player_secret>', methods=['POST', 'GET'])
def show_game(game_id, player_secret=None):
    game, player = get_game(game_id, player_secret)

    if request.method == 'POST':
        bids = request.form.getlist('bid')

        player.bids = [float(b) if b != '' else 0
                       for b in bids]
        if game.ready_for_auction:
            game.resolve_auction()

        queries.save_game(g.db, **game.as_db_dict())
        g.db.commit()

        flash('Bids placed succesfully!', 'success')
        return redirect(url_for('show_game', game_id=game_id, player_secret=player_secret))

    # Redirect to player page if cookie is present
    cookie_secret = request.cookies.get('game-%s' % game_id)
    all_secrets = [p.secret for p in game.players]
    if not player and cookie_secret and int(cookie_secret) in all_secrets:
        return redirect(url_for('game', game_id=game.game_id, player_secret=cookie_secret))

    game_changed = False

    # Trigger auction if the time is up
    if game.ready_for_auction:
        game.resolve_auction()
        game_changed = True

    # Show queued messages
    if player and player.messages:
        for m in player.messages:
            flash(*m)
        player.messages = []
        game_changed = True

    if game_changed:
        queries.save_game(g.db, **game.as_db_dict())
        g.db.commit()

    # Sort players by money if game has finished
    if game.status == 'finished':
        game.players.sort(key=lambda p: -p.money)
    ctx = dict(
        players=game.players,
        player=player,
        game=game,
        auction_order_labels=auction_order_labels,
    )
    ctx.update(game.state)

    resp = make_response(render_template('game.html', **ctx))

    # Set player cookie, so that players get to their game page when using the
    # general game link
    if player:
        resp.set_cookie('game-%s' % game_id, str(player.secret))

    return resp


@app.route('/game/<game_id>/new_player', methods=['POST'])
def new_player(game_id):
    game = queries.get_game(g.db, game_id)
    assert game

    player = Player(request.form['name'] or 'Anonymous', game)
    notify_defaults = request.cookies.get('notify-defaults')
    if notify_defaults:
        player.email, player.notify = notify_defaults.split('|')
    game.players.append(player)
    if len(game.players) == game.number_of_players:
        game.start()

    queries.save_game(g.db, **game.as_db_dict())
    g.db.commit()

    flash('Joined successfully! Please bookmark this URL '
          'if you want to continue playing on a '
          'different device. You can now place your bids '
          'for the first round of auctions.', 'success')

    return redirect("/game/%d/%s" % (game.game_id, player.secret))


@app.route('/game/<game_id>/<player_secret>/notifications', methods=['POST'])
def save_notification_settings(game_id, player_secret):
    game, player = get_game(game_id, player_secret)

    # change settings
    player.email = request.form['email']
    player.notify = request.form['when']
    queries.save_game(g.db, **game.as_db_dict())
    g.db.commit()

    flash('Notification settings changed successfully', 'success')
    resp = make_response(redirect("/game/%d/%s" % (game.game_id, player.secret)))

    # change defaults in cookie
    defaults = '%s|%s' % (player.email, player.notify)
    resp.set_cookie('notify-defaults', defaults)

    return resp


@app.route('/game/<game_id>/<player_secret>/start', methods=['POST'])
def start_game(game_id, player_secret=None):
    game = queries.get_game(g.db, game_id)
    assert int(player_secret) == game.players[0].secret

    game.start()
    queries.save_game(g.db, **game.as_db_dict())
    g.db.commit()

    return redirect("/game/%d/%s" % (game.game_id, player_secret))


@app.route('/game/test')
def test_game():
    game = Game.new_game('test')
    queries.save_game(g.db, **game.as_db_dict())
    g.db.commit()
    return redirect(url_for('show_game', game_id=game.game_id))


@app.route('/quick_ai_game')
def quick_ai_game():
    game = Game.new_game('Test Game')
    player = Player('Human', game)
    player.email, player.notify = '', 'turn'
    game.players.append(player)
    game.start()
    queries.save_game(g.db, **game.as_db_dict())
    g.db.commit()
    flash(
        'This game has been set up for you to try Land Rush '
        'against AI players. The real fun will be playing against humans.',
        'success')
    return redirect(url_for('show_game', game_id=game.game_id, player_secret=player.secret))


@app.route('/rules')
def rules():
    return render_template('page.html', content=jinja2.Markup(
            open(os.path.dirname(__file__) + '/templates/markdown/rules.html').read()
        )
    )


@app.route('/list_games')
def list_games():
    open_games = queries.get_open_games(g.db)
    if not open_games:
        name = 'Newbies %d' % randint(1000, 9999)
        game = Game.new_game(name, public=True)
        queries.save_game(g.db, **game.as_db_dict())
        g.db.commit()
        open_games = [game]

    ctx = {
        'open_games': open_games,
        'games_in_progress': queries.get_games_by_status(g.db, status='in_progress', limit=100),
        'finished_games': queries.get_games_by_status(g.db, status='finished', limit=10),
    }

    return render_template('list_games.html', **ctx)
