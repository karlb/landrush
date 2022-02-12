from flask import current_app as app
from jinja2 import Undefined

app.template_filter("player")


def player(p):
    return p.name


app.template_filter("land")


def land(l):
    return l.fields


app.template_filter("money")


def money(m):
    return "" if isinstance(m, Undefined) else "%d" % m


app.template_filter("datetime")


def datetime(d):
    return d.strftime("%Y-%m-%d %H:%M")
