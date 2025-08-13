# src/packmaker/uploader.py
from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable, Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _load_credentials(root: Path, client_secret_filename: str = "client_secret1.json") -> Credentials:
    client_secret = root / client_secret_filename
    if not client_secret.exists():
        raise FileNotFoundError(
            f"Missing {client_secret_filename} in project root: {root}."
        )

    token_path = root / "token.json"
    creds: Optional[Credentials] = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def _build_service(creds: Credentials):
    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(
    video_path: Path,
    title: str,
    description: str = "",
    privacy_status: str = "unlisted",   # public|unlisted|private
    tags: Optional[Iterable[str]] = None,
    category_id: str = "10",            # Music
    root: Optional[Path] = None,
    client_secret_filename: str = "client_secret1.json",
) -> str:
    root = root or Path.cwd().resolve()
    creds = _load_credentials(root, client_secret_filename)
    yt = _build_service(creds)

    body = {
        "snippet": {
            "title": title,
            "description": description or "",
            "categoryId": category_id,
            "tags": list(tags) if tags else None,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=-1, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    max_attempts = 8
    attempt = 0
    while True:
        try:
            status, response = request.next_chunk()
            if response and response.get("id"):
                vid = response["id"]
                return f"https://youtu.be/{vid}"
        except HttpError as e:
            attempt += 1
            if attempt <= max_attempts and getattr(e, "resp", None) and e.resp.status in (403, 500, 502, 503):
                time.sleep(min(2 ** attempt, 60))
                continue
            raise
        except Exception:
            attempt += 1
            if attempt <= max_attempts:
                time.sleep(min(2 ** attempt, 60))
                continue
            raise
