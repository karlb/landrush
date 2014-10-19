from jinja2 import Undefined

def player(p):
    return p.name


def land(l):
    return l.fields


def money(m):
    return '' if isinstance(m, Undefined) else '%d' % m


def datetime(d):
    return d.strftime("%Y-%m-%d %H:%M")


jinja_filters = locals()
