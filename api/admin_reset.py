"""Set a new password for an account from the server, for the day nobody can sign in (the owner forgot it and has no recovery code and no working e-mail).

Run it on the server, inside the web container, so the password is typed there and never travels through chat:

    docker exec -it stataxis-web-1 python -m api.admin_reset --login you@example.com

It asks for the new password twice (nothing is shown while typing), needs at least 12 characters, keeps the account's other settings, and clears "must change password".
It changes nothing else and never prints the password.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy.orm import Session

from api.auth import hash_password
from collector.storage import User, create_database


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip() or os.getenv("STAXIS_DATABASE_URL", "").strip() or "sqlite:///stataxis.db"


def set_password(session: Session, login: str, new_password: str) -> None:
    if len(new_password) < 12:
        raise ValueError("the password must be at least 12 characters")
    if len(new_password) > 256:
        raise ValueError("the password is too long")
    user = session.query(User).filter_by(email=login.strip().lower()).one_or_none()
    if user is None:
        raise LookupError("there is no account with that login ID")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    session.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set a new password for one account from the server.")
    parser.add_argument("--login", required=True, help="the login ID (e-mail or username) of the account")
    args = parser.parse_args(argv)
    first = getpass.getpass("New password (at least 12 characters): ")
    if first != getpass.getpass("Type it again: "):
        print("The two passwords are not the same. Nothing was changed.")
        return 1
    try:
        with Session(create_database(database_url())) as session:
            set_password(session, args.login, first)
    except (ValueError, LookupError) as exc:
        print(f"Nothing was changed: {exc}.")
        return 1
    print("Done. The new password works now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
