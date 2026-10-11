from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import tomllib
from urllib.parse import urlsplit

from .errors import SentraError


@dataclass(frozen=True)
class Connection:
    provider: str
    participant_id: str
    private_dir: Path
    client_file: Path
    redirect_uri: str
    agreed: bool
    publishing_status: str
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)


def load_connection(path: Path, provider: str, *, require_client=True) -> Connection:
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        section = config[provider]
        participant = section["participant_id"]
        if not re.fullmatch(r"p[0-9]{2,4}", participant):
            raise ValueError
        redirect = section["redirect_uri"]
        url = urlsplit(redirect)
        if (url.scheme != "http" or url.hostname != "localhost" or url.port != 8765
                or url.path != "/callback" or url.query or url.fragment or url.username):
            raise ValueError
        private = (path.parent / config["private_dir"]).resolve()
        client_path = (path.parent / section["client_file"]).resolve()
        # Keep local secrets under the repository's explicitly ignored directory.
        if private != (path.parent.parent / ".private").resolve() or not client_path.is_relative_to(private):
            raise ValueError
        client = {}
        if require_client:
            client = json.loads(client_path.read_text(encoding="utf-8"))
            if provider == "google_health":
                client = client["web"]
                if (redirect not in client.get("redirect_uris", [])
                        or client.get("project_id") != section["project_id"]):
                    raise ValueError
            if not all(isinstance(client.get(key), str) and client[key]
                       for key in ("client_id", "client_secret")):
                raise ValueError
        return Connection(provider, participant, private, client_path, redirect,
                          section.get("team_data_agreement") is True,
                          section.get("publishing_status", "unknown"),
                          client.get("client_id", ""), client.get("client_secret", ""))
    except (OSError, ValueError, KeyError, TypeError):
        raise SentraError("Configuration/client file missing or invalid. See docs/stage-1-setup.md.") from None


def require_agreement(connection: Connection):
    if not connection.agreed:
        raise SentraError("Participant agreement to team viewing/downloads must be recorded first.")
