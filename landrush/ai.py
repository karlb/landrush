from __future__ import division
import random
import string

adjectives = (
    "electronic automatic binary numeric mechanic robotic programmed "
    "mechanized electric"
).split(" ")
names = (
    "Eddie Frank Sam James Bill George Jack Bob Joe Jane Jill Anne Fred Hank Maria"
).split(" ")


def player_name():
    adj = random.choice(adjectives)
    name = random.choice(names)
    return string.capwords(adj + " " + name)


def calc_bid_for_land(game, player, land):
    base_price = game.remaining_payout / len(game.board.lands)

    if player.lands:
        islands = player.islands()
        max_island_size = max(len(i) for i in islands)
        largest_islands = [i for i in islands if len(i) == max_island_size]
        lands_in_largest_islands = set().union(*largest_islands)
        connected_to_largest_island = bool(land.neighbors & lands_in_largest_islands)
        base_factor = 0.5 if connected_to_largest_island else 0.1
    else:
        base_factor = 0.5

    neighbors_factor = sum(
        0.15 if n.owner == player else 0.3 if n.owner is None else 0
        for n in land.neighbors
    )
    spending_factor = player.money / game.start_money
    return round(base_price * (base_factor + neighbors_factor) * spending_factor)


def calculate_bids(game, player):
    return [calc_bid_for_land(game, player, land) for land in game.auction]
