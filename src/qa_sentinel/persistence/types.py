"""Portable ISO datetime storage preserves supplied offsets and naive datetimes."""
from datetime import datetime
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


class ISODateTime(TypeDecorator[datetime]):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else value.isoformat()

    def process_result_value(self, value, dialect):
        return None if value is None else datetime.fromisoformat(value)
