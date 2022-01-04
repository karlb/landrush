import logging
from email.utils import parseaddr
from email.message import EmailMessage
import smtplib

from flask import current_app as app, request


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

    with smtplib.SMTP("smtp.sendgrid.net", port=587) as smtp:
        try:
            smtp.login(
                request.environ['SMTP_USER'],
                request.environ['SMTP_PASSWORD'],
            )
        except KeyError:
            app.logger.warning('No SMTP credentials: not sending emails')
            app.logger.debug('Mail would be:')
            app.logger.debug(subject)
            app.logger.debug(body)
        else:
            for msg in messages:
                smtp.send_message(msg)


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
