"""
agents/srv/hdb_srv.py

Thread-local SAP HANA Cloud connection manager.
Each request thread gets its own hdbcli connection — never share across threads.
"""
import os
import threading
from hdbcli import dbapi
from dotenv import load_dotenv

load_dotenv()

_local = threading.local()


def get_connection() -> dbapi.Connection:
    """
    Returns a HANA connection for the current thread.
    Creates one on first access; reuses it on subsequent calls within the same thread.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = dbapi.connect(
            address=os.getenv("HANA_HOST"),
            port=int(os.getenv("HANA_PORT", 443)),
            user=os.getenv("HANA_USER"),
            password=os.getenv("HANA_PASSWORD"),
            encrypt=True,
            sslValidateCertificate=False,
            # For production: set sslValidateCertificate=True and supply sslTrustStore
        )
    return _local.conn


def close_thread_connection() -> None:
    """Closes and clears the HANA connection for the current thread."""
    if hasattr(_local, "conn") and _local.conn is not None:
        try:
            _local.conn.close()
        except Exception:
            pass
        _local.conn = None
