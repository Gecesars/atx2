import uuid
from typing import Any, Optional

from sqlalchemy.types import CHAR, TypeDecorator


class GUID(TypeDecorator):  # pragma: no cover - thin wrapper
    """Platform-independent GUID/UUID type.

    Uses PostgreSQL's native UUID when available, otherwise stores as CHAR(36).
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Optional[Any], dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return str(value)
        if value is None:
            return value
        return str(uuid.UUID(str(value)))

    def process_result_value(self, value: Optional[Any], dialect):
        if value is None:
            return value
        return uuid.UUID(str(value))
