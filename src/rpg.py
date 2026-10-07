"""Identity and process isolation for the native Sandbox RPG launcher."""
from __future__ import annotations

import os
from collections.abc import Mapping

APP_NAME = "EveJS-RPG-Launcher"
APP_TITLE = "EVEJS RPG LAUNCHER"
UPDATE_REPOSITORY = "klimesrenz/evejs-launcher"
UPDATE_PACKAGE = "EveJS-RPG-Launcher.zip"
DEFAULT_SERVER = r"C:\projects\EveJS-RPG"
DEFAULT_CLIENT = r"C:\CCP\SandboxRPG-3396210\tq"
GAME_PORT = 27000
IMAGE_PORT = 27001
PROXY_PORT = 27002
HTTPS_PORT = 27003
MARKET_HTTP_PORT = 41110
MARKET_RPC_PORT = 41111
PROXY_URL = f"http://127.0.0.1:{PROXY_PORT}"


def runtime_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Match RPG-Environment.cmd without executing an arbitrary batch file.

    Child services and tools must not inherit another world's data paths or
    Node preloads. Launcher-selected mod preloads are added later as arguments.
    """
    source = os.environ if source is None else source
    env = {
        key: value for key, value in source.items()
        if not key.upper().startswith("EVEJS_")
        and key.upper() not in {"NODE_OPTIONS", "NODE_PATH"}
    }
    env["EVEJS_PROXY_LOCAL_INTERCEPT"] = "1"
    # Same port as the regular HTTPS listener suppresses the extra 443 listener.
    env["EVEJS_PROXY_LOOPBACK_CDN_LISTEN_PORT"] = str(HTTPS_PORT)
    return env
