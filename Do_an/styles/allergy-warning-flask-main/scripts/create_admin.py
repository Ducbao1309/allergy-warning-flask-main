"""Seed the local classroom/demo admin account (not for production use)."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from werkzeug.security import generate_password_hash
from sqlalchemy.exc import SQLAlchemyError

from app import app
from extensions import db
from models import User


# Deliberately confined to this local development/demo seed script.
ADMIN_EMAIL = "admin@gmail.com"
ADMIN_PASSWORD = "1234"


def main():
    with app.app_context():
        try:
            user = User.query.filter_by(email=ADMIN_EMAIL).first()
            created = user is None
            if created:
                user = User(
                    email=ADMIN_EMAIL,
                    full_name="Local Demo Admin",
                    is_active=True,
                    is_superuser=True,
                )
                db.session.add(user)

            user.hashed_password = generate_password_hash(
                ADMIN_PASSWORD,
                method="pbkdf2:sha256",
            )
            user.is_active = True
            user.is_superuser = True
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            print("Could not create the admin account. Check the database and try again.")
            return 1

    action = "created" if created else "updated"
    print(f"Local demo admin {action}: {ADMIN_EMAIL}")
    print("is_active=True; is_superuser=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
