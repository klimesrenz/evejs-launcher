"""QThread workers for EveJS Launcher background tasks."""

from .db_worker import AccountLoader, CharacterDetailLoader
from .portrait_worker import PortraitLoader

__all__ = [
    "AccountLoader",
    "CharacterDetailLoader",
    "PortraitLoader",
    "ServiceMonitor",
    "ServiceProbe",
]


def __getattr__(name):
    # Portrait-only clients must not initialize local server logs/configuration.
    # Preserve the public worker imports for the full native launcher.
    if name in {"ServiceMonitor", "ServiceProbe"}:
        from .server_worker import ServiceMonitor, ServiceProbe
        globals().update(ServiceMonitor=ServiceMonitor, ServiceProbe=ServiceProbe)
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
