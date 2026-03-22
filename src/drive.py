import os
import json
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def _get_service():
    creds = None

    # Tenta carregar o token da variável de ambiente (produção no Railway)
    token_env = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_env:
        creds = Credentials.from_authorized_user_info(json.loads(token_env), SCOPES)

    # Fallback: lê do arquivo local (desenvolvimento)
    elif Path(TOKEN_FILE).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Salva localmente se não estiver no Railway
        if not token_env:
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def upload(file_path: Path, filename: str) -> str:
    folder_id = os.environ["DRIVE_FOLDER_ID"]
    service = _get_service()

    file_metadata = {
        "name": filename,
        "parents": [folder_id],
        "mimeType": "text/markdown",
    }
    media = MediaFileUpload(str(file_path), mimetype="text/markdown")

    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink"
    ).execute()

    return uploaded.get("webViewLink", "")