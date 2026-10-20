"""Bootstrap an admin user. Run: uv run python -m scripts.create_admin <username>

The password is read from the ADMIN_PASSWORD env var, or prompted if unset.
"""

import argparse
import getpass
import os
import sys

from exam_core.db import SessionLocal
from exam_core.models import Role
from app.users import UsernameTaken, create_user


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    args = parser.parse_args()

    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        try:
            create_user(db, args.username, password, Role.admin)
        except UsernameTaken:
            print(f"User '{args.username}' already exists", file=sys.stderr)
            return 1
    print(f"Created admin '{args.username}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
