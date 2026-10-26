"""Declarative base and shared constraint naming.

Alembic owns every table and index, so constraint names must be predictable.
The prefixes match the approved schema design: pk_, fk_, uq_, ck_, ix_.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# 24 lowercase hex characters, used by every id, user_id and instrument_id.
ID_PATTERN = "^[0-9a-f]{24}$"

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
