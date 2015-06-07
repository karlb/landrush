import os
import logging

from google.appengine.api import mail
from google.appengine.ext import deferred

sender_domain = os.environ['DEFAULT_VERSION_HOSTNAME'].replace('appspot',
                                                               'appspotmail')
sender = 'Land Rush <no-reply@%s>' % sender_domain


def send_mails(mails):
    for (player, subject, body) in mails:
        if not mail.is_email_valid(player.email):
            continue
        mail.send_mail(sender=sender, to=player.email,
                       subject=subject, body=body)


def turn_finished(game):
    mails = []
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
            mails.append((p, subject, body))

    deferred.defer(send_mails, mails, _transactional=True)
