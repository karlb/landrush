import os
import logging

from google.appengine.api import mail

sender_domain = os.environ['DEFAULT_VERSION_HOSTNAME'].replace('appspot',
                                                               'appspotmail')
sender = 'Land Rush <no-reply@%s>' % sender_domain


def send_mail(player, subject, body):
    if not mail.is_email_valid(player.email):
        return
    mail.send_mail(sender=sender, to=player.email, subject=subject, body=body)


def turn_finished(game):
    for p in game.players:
        if p.notify == 'turn':
            subject = 'Turn %d completed in game "%s"' % (game.turn, game.name)
            body = '''
Hey %s,

an auction has been settled. See the results and place your next bids at
%s

Regards,
the Land Rush auctioneer
''' % (p.name, game.url(p.secret))
            send_mail(p, subject, body)
