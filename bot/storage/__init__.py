"""
Storage backend factory — JSON files or MySQL/MariaDB.
"""

from typing import Optional, Union

from bot.config import Config
from bot.storage.json_storage import JSONStorage
from bot.storage.mysql_storage import MySQLStorage

StorageType = Union[JSONStorage, MySQLStorage]

_storage_instance: Optional[StorageType] = None


def get_storage(force_new: bool = False) -> StorageType:
    """Return the shared storage instance (MySQL when configured, else JSON)."""
    global _storage_instance
    if _storage_instance is not None and not force_new:
        return _storage_instance

    config = Config()
    if config.use_mysql():
        _storage_instance = MySQLStorage()
    else:
        _storage_instance = JSONStorage()
    return _storage_instance
