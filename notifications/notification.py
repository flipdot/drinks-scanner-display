# -*- coding: utf-8 -*-

import time
from datetime import datetime, timedelta

import jinja2
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from sqlalchemy import text

import config
from database.models.recharge_event import RechargeEvent
from database.storage import get_session
from env import is_pi
from users.users import Users

SUBJECT_PREFIX = "[fd-noti]"
MINIMUM_BALANCE = -5
REMIND_MAIL_EVERY_X_HOURS = 24 * 7

# THese entries describe when to send a summary
FREQUENCIES = {
    "daily": 60 * 60 * 24,
    "instant and daily": 60 * 60 * 24,
    "weekly": 60 * 60 * 24 * 7,
    "instant and weekly": 60 * 60 * 24 * 7
}
FOOTER = u"""
Besuchen Sie uns bald wieder!

Einstellungen: http://ldap.fd/
Aufladen: http://drinks-touch.fd/
Oder per SEPA:
  Kontoinhaber: flipdot e.V.
  IBAN: DE07 5205 0353 0001 1477 13
  Verwendungszweck: "drinks {uid} hinweistext"
  Der Hinweistext ist frei wählbar.
"""


def send_notification(to_address, subject, content_text, content_html, uid):
    msg = MIMEMultipart('alternative')

    plain = MIMEText(content_text, 'plain', _charset='utf-8')
    html = MIMEText(content_html, 'html', _charset='utf-8')

    msg.attach(plain)
    msg.attach(html)

    msg['Subject'] = SUBJECT_PREFIX + " " + subject
    msg['From'] = config.MAIL_FROM
    msg['To'] = to_address
    msg['Date'] = formatdate(time.time(), localtime=True)
    msg['Message-id'] = make_msgid()
    msg['X-LDAP-ID'] = uid

    logging.info("Mailing %s: '%s'", to_address, subject)
    logging.debug("Content: ---\n%s\n---", content_text)
    if config.NO_MAILS:
        if str(config.FORCE_MAIL_TO) != str(uid):
            logging.info("skipping mail, because config.NO_MAILS")
            return

    s = smtplib.SMTP()
    s.connect(host=config.MAIL_HOST, port=config.MAIL_PORT)
    s.ehlo()
    s.starttls()
    s.login(user=config.MAIL_FROM, password=config.MAIL_PW)
    s.sendmail(config.MAIL_FROM, [to_address], msg.as_string())
    s.quit()


def send_drink(user, drink, with_summary=False):
    try:
        if user['email'] and 'instant' in user['meta']['drink_notification']:
            content_text = u"Du hast das folgende Getränk getrunken: {drink_name}.".format(drink_name=drink['name'])
            content_html = render_jinja_html('instant.html', drink_name=drink['name'])

            if not with_summary:
                content_text += FOOTER.format(uid=user['id'])
                content_html = render_jinja_html('main.html', prepend_html=content_html)

                send_notification(user['email'], "Getränk getrunken", content_text, content_html, user['id'])
                return

            session = get_session()
            send_summary(session, user,
                         subject="Getränk getrunken",
                         prepend_text=content_text,
                         prepend_html=content_html,
                         force=True)
    except Exception:
        logging.exception("while sending drink noti")
        pass


def send_low_balances(with_summary=True):
    session = get_session()

    if config.FORCE_MAIL_TO:
        send_low_balance(session, Users.get_by_id(config.FORCE_MAIL_TO), with_summary, force=True)
        return

    for user in Users.get_all():
        try:
            send_low_balance(session, user, with_summary)
        except Exception:
            logging.exception("while sending lowbalances:")
            continue


def send_low_balance(session, user, with_summary=False, force=False):
    balance = Users.get_balance(user['id'])

    if not force and balance >= MINIMUM_BALANCE:
        # reset time
        user['meta']['last_emailed'] = time.time()
        Users.save(user)
        return

    last_emailed = user['meta'].get('last_emailed', 0)
    diff = time.time() - last_emailed
    diff_hours = diff / 60 / 60
    diff_days = diff_hours / 24

    if not force and diff_hours <= REMIND_MAIL_EVERY_X_HOURS:
        return

    logging.info("%s's low balance last emailed %.2f days (%.2f hours) ago. Mailing now.",
                 user['name'], diff_days, diff_hours)
    content_text = (u"Du hast seit mehr als {diff_days} Tagen "
                    u"ein Guthaben von unter {minimum_balance}€!\n"
                    u"Aktueller Kontostand: {balance:.2f}€.\n"
                    u"Zum Aufladen im Space-Netz http://drinks-touch.fd/ besuchen.").format(
        diff_days=diff_days,
        minimum_balance=MINIMUM_BALANCE,
        balance=balance)
    content_html = render_jinja_html('low_balance.html',
                                     diff_days=diff_days,
                                     minimum_balance=MINIMUM_BALANCE,
                                     balance=balance,
                                     uid=user['id'])

    if not with_summary:
        content_text += FOOTER.format(uid=user['id'])
        content_html = render_jinja_html('main.html', prepend_html=content_html)

        send_notification(user['email'], "Negatives Guthaben", content_text, content_html, user['id'])
        return

    send_summary(session, user,
                 subject="Negatives Guthaben",
                 prepend_text=content_text,
                 prepend_html=content_html,
                 force=True)
    user['meta']['last_emailed'] = time.time()
    Users.save(user)


def send_summaries():
    session = get_session()

    if config.FORCE_MAIL_TO:
        send_summary(session, Users.get_by_id(config.FORCE_MAIL_TO), "Getränkeübersicht", force=True)
        return

    for user in Users.get_all():
        try:
            send_summary(session, user, "Getränkeübersicht")
        except Exception:
            logging.exception("While sending summary for %s", user)
            continue


def send_summary(session, user, subject, prepend_text=None, prepend_html=None, force=False):
    frequency_str = user['meta']['drink_notification']
    balance = Users.get_balance(user['id'])

    if not force and frequency_str not in FREQUENCIES.keys():
        return

    freq_secs = FREQUENCIES[frequency_str]
    last_emailed = user['meta']['last_drink_notification']
    if type(last_emailed) not in [int, float]:
        last_emailed = 0

    last_emailed_str = datetime.fromtimestamp(last_emailed).strftime("%d.%m.%Y %H:%M:%S")
    diff = time.time() - last_emailed
    diff_hours = diff / 60 / 60
    diff_days = diff_hours / 24

    if force is True:
        logging.info("Forcing mail.")
    else:
        if diff <= freq_secs:
            return

    logging.info("%s's summary last emailed %.2f days (%.2f hours) ago. Mailing now.",
                 user['name'], diff_days, diff_hours)

    content_text = u""

    if prepend_text:
        content_text += prepend_text + u"\n==========\n"

    content_text += u"Hier ist deine Getränkeübersicht seit {since}.\n" \
                    u"Dein aktuelles Guthaben beträgt EUR {balance:.2f}.\n" \
        .format(since=last_emailed_str, balance=balance)

    drinks_consumed = get_drinks_consumed(session, user, last_emailed)
    recharges = get_recharges(session, user, last_emailed)

    if drinks_consumed:
        content_text += format_drinks(drinks_consumed)

    if recharges:
        content_text += format_recharges(recharges)

    content_text += FOOTER.format(uid=user['id'])
    content_html = render_jinja_html('main.html',
                                     with_report=True,
                                     balance=balance,
                                     since_text=last_emailed_str,
                                     drinks=drinks_consumed,
                                     recharges=recharges,
                                     prepend_html=prepend_html,
                                     limit_days=REMIND_MAIL_EVERY_X_HOURS / 24,
                                     minimum_balance=MINIMUM_BALANCE,
                                     uid=user['id'])

    email = user['email']

    if not email:
        logging.warn("User %s has no email. skipping.", user)
        return

    if len(drinks_consumed) == 0 and len(recharges) == 0 and not force:
        logging.debug("got no rows. skipping.")
        return

    logging.info("Got %d drinks and %d recharges. Mailing.", len(drinks_consumed), len(recharges))
    send_notification(email, subject, content_text, content_html, user['id'])
    user['meta']['last_drink_notification'] = time.time()
    Users.save(user)


def format_drinks(drinks_consumed):
    drinks_fmt = "\nGetrunken:\n"
    drinks_fmt += "    #                 datum                drink groesse\n"

    for i, event in enumerate(drinks_consumed):
        date = event['timestamp'].strftime("%F %T Z")
        name = event['name']
        size = event['size']
        drinks_fmt += "  % 3d % 15s % 20s % 5s l\n" % (
            i, date, name, size if size else "?"
        )

    return drinks_fmt


def format_recharges(recharges):
    recharges_fmt = "\nAufladungen:\n" \
                    "    #                 datum     mit aufgeladen\n"

    for i, event in enumerate(recharges):
        date = event['timestamp'].strftime("%F %T Z")
        mit = event['helper_user_id']

        try:
            mit = Users.get_by_id(mit)['name']
        except Exception:
            pass

        amount = event['amount']
        recharges_fmt += "  % 3d % 15s %7s %10s\n" % (i, date, mit, amount)

    return recharges_fmt


def get_drinks_consumed(session, user, since_timestamp):
    sql = text("""SELECT
    se.barcode,
    se.timestamp,
    d.name,
    d.size
FROM scanevent se
    LEFT OUTER JOIN drink d ON d.ean = se.barcode
WHERE user_id = :userid
    AND se.timestamp >= TO_TIMESTAMP('%d')
ORDER BY se.timestamp""" % since_timestamp)
    drinks_consumed = session.connection().execute(sql, userid=user['id']).fetchall()
    return drinks_consumed


def get_recharges(session, user, since_timestamp):
    return session.query(RechargeEvent) \
        .filter(RechargeEvent.user_id == user['id']) \
        .filter(RechargeEvent.timestamp >= datetime.utcfromtimestamp(since_timestamp)) \
        .order_by(RechargeEvent.timestamp) \
        .all()


def render_jinja_html(file_name, template_loc='notifications/templates', **context):
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_loc)
    ).get_template(file_name).render(context)
