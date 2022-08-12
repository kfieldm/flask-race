import os


basedir = os.path.abspath(os.path.dirname(__file__))


class Config(object):
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    STATIC_FOLDER = f"{os.getenv('APP_FOLDER')}/project/static"

    SQLALCHEMY_DATABASE_URI = "postgresql://" + \
        f"{os.getenv('POSTGRES_USER')}" + ":" + \
        f"{os.getenv('POSTGRES_PASSWORD')}" + \
        f"@{os.getenv('SQL_HOST')}:{os.getenv('SQL_PORT')}/" + \
        f"{os.getenv('POSTGRES_DB')}"
