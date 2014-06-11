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
        return repr(sorted(self.index))

    def classes(self):
        ret_vals = []
        for name, off in offsets.items():
            other_index = (
                self.index[0] + off[0],
                self.index[1] + off[1]
            )
            if other_index not in self.board.all_indexes:
                ret_vals.append(name + '_border')
                continue
            other_field = self.board.fields[other_index]
            if other_field.land != self.land:
                ret_vals.append(name + '_border')
        return ' '.join(ret_vals)


class Land():

    def __init__(self, fields):
        #self.color = '#{:06x}'.format(randint(0, 255 ** 3))
        self.color = '#' + '{:02x}'.format(int(0x11 * randint(80, 160) * 0.1)) * 3
        self.fields = []
        self.neighbors = []
        self.neighbor_fields = []
        for f in fields:
            self.add_field(f)

    def add_field(self, field):
        self.fields.append(field)
        if field.land:
            field.land.fields.remove(field)
        field.land = self


class Board():

    def __init__(self, size=(10, 10)):
        self.size = size
        self.all_indexes = set(product(range(self.size[0]), range(self.size[1])))
        self.fields = np.array([
            [Field(self, (x, y)) for y in range(size[0])]
            for x in range(size[1])])

        for field in self:
            Land([field])

        self.calc_neighbors()

        for i in range(60):
            land = choice(list(self.lands))
            joined_field = choice(list(land.neighbor_fields))
            land.add_field(joined_field)
            self.calc_neighbors()

    def __iter__(self):
        return chain(*self.fields)

    def calc_neighbors(self):
        # fields
        for index in self.all_indexes:
            possible_indexes = set((index[0] + o[0], index[1] + o[1])
                                   for o in offsets.values()) & self.all_indexes
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
        for row in self.fields:
            print row

    @property
    def rows(self):
        return np.transpose(self.fields)



#b = Board()
#b.show()
