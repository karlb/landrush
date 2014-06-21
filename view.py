from jinja2 import Undefined

def player(p):
    return p.name


def land(l):
    return l.fields


def money(m):
    return '' if isinstance(m, Undefined) else '%d' % m

jinja_filters = locals()
