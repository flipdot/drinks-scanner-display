# coding=utf-8

from datetime import datetime

import logging
import requests
from decimal import Decimal
from requests.auth import HTTPBasicAuth

import config
from database.models.recharge_event import RechargeEvent
from database.storage import get_session
from notifications.notification import send_summary
from users import Users

logger = logging.getLogger(__name__)

helper_user = "SEPA"


def get_existing(session):
    rechargeevents = session.query(RechargeEvent) \
        .filter(RechargeEvent.helper_user_id == str(helper_user)).all()
    got_by_user = {}
    for ev in rechargeevents:
        if ev.user_id not in got_by_user:
            got_by_user[ev.user_id] = []
        got_by_user[ev.user_id].append(ev)
    return got_by_user


def sync_recharges():
    try:
        sync_recharges_real()
    except Exception as e:
        logger.exception("Syncing recharges:")


def sync_recharges_real():
    data = None

    try:
        data = requests.get(config.money_url, auth=HTTPBasicAuth(config.money_user, config.money_password))
    except requests.exceptions.ConnectionError:
        logger.exception("Cannot connect to sync recharges:")
        return

    recharges = data.json()
    session = get_session()
    got_by_user = get_existing(session)

    for uid, charges in recharges.iteritems():
        logger.info("Syncing recharges for user %s", uid)
        if uid not in got_by_user:
            logger.info("First recharge for user %s!", uid)
            got_by_user[uid] = []
        got = got_by_user[uid]
        for charge in charges:
            charge_date = datetime.strptime(charge['date'], "%Y-%m-%d")
            charge_amount = Decimal(charge['amount'])
            logger.debug("charge: %s, %s", charge, charge_date)
            found = False
            for exist in got:
                if exist.timestamp != charge_date:
                    continue
                if exist.amount != charge_amount:
                    continue
                # found a matching one
                found = True
                break
            if found:
                continue

            handle_transferred(charge, charge_amount, charge_date, got, session, uid)


def handle_transferred(charge, charge_amount, charge_date, got, session, uid):
    logger.info("User %s transferred %s on %s: %s",
                uid, charge_amount, charge_date, charge)
    ev = RechargeEvent(uid, helper_user, charge_amount, charge_date)
    got.append(ev)
    session.add(ev)
    session.commit()
    try:
        user = Users.get_by_id(uid)
        if not user:
            logger.error("could not find user %s to send email", uid)
        else:
            subject = "Aufladung EUR %s für %s" % (charge_amount, user['name'])
            text = "Deine Aufladung über %s € am %s mit Text '%s' war erfolgreich." % (
                charge_amount, charge_date, charge['info'])
            send_summary(session, user, subject=subject, force=True, prepend_text=text)
    except:
        logger.exception("sending notification mail:")


if __name__ == "__main__":
    sync_recharges()
