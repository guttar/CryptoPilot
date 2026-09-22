"""Compatibility entry point; database schema is managed by Alembic."""

from alembic import command
from alembic.config import Config


if __name__ == "__main__":
    command.upgrade(Config("alembic.ini"), "head")
    print("Database migrated to the latest revision.")
