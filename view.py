

def player(p):
    return p.name


def land(l):
    return l.fields


def money(m):
    return '%.2f' % m

jinja_filters = locals()
