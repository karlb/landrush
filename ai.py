from __future__ import division
import random
import string

adjectives = (
    'electronic automatic binary numeric mechanic robotic programmed '
    'mechanized electric'
).split(' ')
names = (
    'Eddie Frank Sam James Bill George Jack Bob Joe Jane Jill Anne '
    'Fred Hank Maria'
).split(' ')


def player_name():
    adj = random.choice(adjectives)
    name = random.choice(names)
    return string.capwords(adj + ' ' + name)


def calc_bid_for_land(game, player, land):
    base_price = game.remaining_payout / game.remaining_turns
    neighbors_factor = sum(
        2 if n.owner == player else
        1 if n.owner is None else
        0
        for n in land.neighbors
    ) / len(land.neighbors)
    spending_factor = player.money / game.start_money
    return base_price * neighbors_factor * spending_factor


def calculate_bids(game, player):
    return [
        calc_bid_for_land(game, player, land)
        for land in game.auction
    ]
