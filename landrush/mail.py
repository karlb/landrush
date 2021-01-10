import os
import logging
from email.utils import parseaddr
from email.message import EmailMessage
import smtplib

from flask import current_app as app


sender_domain = 'landrush.karl.berlin'
sender = 'Land Rush <no-reply@%s>' % sender_domain


def send_mails(mails):
    messages  =[]
    for (player, subject, body) in mails:
        if not '@' in parseaddr(player.email)[1]:
            # email address invalid or not set
            continue

        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = player.email
        msg.set_content(body)
        messages.append(msg)

    s = smtplib.SMTP('localhost')
    try:
        s.login(
            os.environ['SMTP_USER'],
            os.environ['SMTP_PASSWORD'],
        )
    except KeyError:
        app.logger.warning('No SMTP credentials: not sending emails')

    for msg in messages:
        s.send_message(msg)
    s.quit()


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

    send_mails(mails)
