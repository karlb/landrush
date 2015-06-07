import numpy as np
from random import randint, choice
from itertools import chain, product

offsets = {
    'top': (0, -1),
    'right': (1, 0),
    'bottom': (0, 1),
    'left': (-1, 0),
}


class Field():

    def __init__(self, board, index):
        self.board = board
        self.index = index
        self.land = None
        self.neighbors = []

    def __repr__(self):
        return '%d/%d' % self.index

    def to_json(self):
        return dict(
            land=self.land.id
        )

    def classes(self):
        ret_vals = []

        # borders
        for name, off in offsets.items():
            other_index = (
                self.index[0] + off[0],
                self.index[1] + off[1]
            )
            # border at edge of board
            if other_index not in self.board.all_indexes:
                ret_vals.append(name + '_border')
                continue
            # border between lands
            other_field = self.board.fields[other_index]
            if other_field.land != self.land:
                ret_vals.append(name + '_border')

        # land class
        ret_vals.append(self.land.id)
        ret_vals.append('free-land-%d' % self.land.color)

        # background color
        if self.land.owner:
            ret_vals.append('background-p%d' % self.land.owner.player_number)

        return ' '.join(ret_vals)


class Land():

    def __init__(self, board, fields):
        self.color = randint(1, 5)
        self.fields = []
        self.board = board
        self.neighbors = []
        self.neighbor_fields = []
        for f in fields:
            self.add_field(f)
        self.id = 'land-%d-%d' % sorted(self.fields)[0].index
        self.owner = None

    def __repr__(self):
        return repr(self.fields)

    def to_json(self):
        d = dict(
            id=self.id,
            color=self.color,
        )
        if self.owner:
            d['owner'] = self.owner.id
        return d

    def add_field(self, field):
        self.fields.append(field)
        if field.land:
            field.land.fields.remove(field)
        field.land = self

    def add_land(self, land):
        for field in list(land.fields):
            self.add_field(field)
        self.board.lands.remove(land)


class Board():

    def __init__(self, size=(10, 10), joins=20):
        self.size = size
        self.all_indexes = set(
                product(range(self.size[0]), range(self.size[1])))
        self.fields = np.array([
            [Field(self, (x, y)) for y in range(size[1])]
            for x in range(size[0])])

        for field in self:
            Land(self, [field])

        self.calc_neighbors()

        for i in range(joins):
            land = choice(list(self.lands))
            joined_land = choice(list(land.neighbors))
            land.add_land(joined_land)
            self.calc_neighbors()

    def __iter__(self):
        return chain(*self.fields)

    def to_json(self):
        return dict(
            fields=self.fields,
            lands=self.lands,
        )

    def calc_neighbors(self):
        # fields
        for index in self.all_indexes:
            possible_indexes = set(
                    (index[0] + o[0], index[1] + o[1])
                    for o in offsets.values()
                ) & self.all_indexes
            neighbors = []
            for p in possible_indexes:
                neighbors.append(self.fields[p])
            assert neighbors
            self.fields[index].neighbors = neighbors

        # lands
        self.lands = set(f.land for f in self)
        for land in self.lands:
            land.neighbor_fields = set(
                chain.from_iterable(f.neighbors for f in land.fields))
            land.neighbors = set(f.land for f in land.neighbor_fields)
            assert land.neighbors

    def show(self):
        for row in self.rows:
            print row

    @property
    def rows(self):
        return self.fields.transpose()



#b = Board((3,2))
#b.show()
