import os
from datetime import timedelta

from werkzeug.utils import secure_filename
from flask import (
    Flask,
    jsonify,
    send_from_directory,
    request,
    redirect,
    url_for,
    make_response

)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import exc, inspect, event
from celery import Celery
import requests
import json
import re
import time

import logging
logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

app = Flask(__name__)
app.config.from_object("project.config.Config")
db = SQLAlchemy(app)

celery = Celery(__name__)
celery.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379")
celery.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379")


class UpdateJob(db.Model):
    __tablename__ = "update_jobs"

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False)
    created_date = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        nullable=False
    )
    contact_id = db.Column(db.Integer, db.ForeignKey('contacts.id'), nullable=False)
    contact_was_updated = db.Column(db.Boolean, default=False, nullable=False)
    updated_contact = db.relationship('Contact')


class FieldChange(db.Model):
    __tablename__ = "field_changes"

    id = db.Column(db.Integer, primary_key=True)
    field_name = db.Column(db.Text, nullable=False)
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    update_job_id = db.Column(db.Integer, db.ForeignKey('update_jobs.id'), nullable=False)
    update_trigger = db.relationship('UpdateJob', backref='field_changes')

    def __str__(self):
        return f"Old: {self.old_value} new: {self.new_value} field: {self.field_name}"


class Contact(db.Model):
    __tablename__ = "contacts"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.Text, nullable=False)
    phone = db.Column(db.Text, nullable=False)
    email = db.Column(db.Text, nullable=False)


@app.route("/update", methods=['GET'])
def update():

    db.drop_all()
    db.create_all()

    contact = Contact(first_name="Jacob", phone="123", email="jacob@gmail.com")
    db.session.add(contact)
    db.session.commit()

    update = UpdateJob(data=json.dumps({"first_name": "Jake", "phone": "789", "email": "jake@gmail.com"}), contact_id=contact.id)
    db.session.add(update)
    db.session.commit()

    for i in range(20):
        process_update.delay(update.id)

    return jsonify(result="world")


@celery.task(name="process_update")
def process_update(update_id):
    print("Starting")
    time.sleep(.5)
    update = UpdateJob.query.get(update_id)

    # Wait for previous updates to finish and abort after timeout
    for attempt in range(40):
        unfinished_changes_to_contact = db.session.query(UpdateJob).filter(
            UpdateJob.contact_id == update.contact_id,
            UpdateJob.id < update.id,
            UpdateJob.contact_was_updated == False  # noqa
        ).order_by(UpdateJob.id.desc()).first()
        if unfinished_changes_to_contact is None:
            break
        time.sleep(.5)
    else:
        print(f"{update.id} waiting for {unfinished_changes_to_contact.id} to finish")
        raise Exception("Already existing update to contact that is not finishing")

    print("We are clear")

    time.sleep(.5)

    contact = db.session.query(Contact).get(update.contact_id)

    for key, value in json.loads(update.data).items():
        setattr(contact, key, value)

    changes = field_changes_from_contact(contact)

    for change in changes:
        change.update_job_id = update.id

    # Did another task already cover this update?
    print("Rechecking. Locking")
    processed_update = UpdateJob.query.with_for_update().get(update_id)
    if processed_update.contact_was_updated is True:
        print(processed_update)
        print("Already done.  Abandoning.")
        return

    print("Looks good.  Committing.")
    processed_update.contact_was_updated = True

    db.session.add(processed_update)
    db.session.add(contact)
    db.session.bulk_save_objects(changes)
    db.session.commit()
    print("Commited")


def field_changes_from_contact(contact):
    return [
        FieldChange(
            old_value=attr.history.deleted[0],
            new_value=attr.history.added[0],
            field_name=attr.key
        )
        for attr in inspect(contact).attrs
        if attr.history.has_changes()
    ]
