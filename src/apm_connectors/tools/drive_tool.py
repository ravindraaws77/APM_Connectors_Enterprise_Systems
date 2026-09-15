"""Google Drive connector for storing/retrieving arbitrary documents
(contracts, purchase orders, signed agreements) — distinct from
excel_file_tool.py's Google-Drive support, which only reads/writes cell
ranges inside one specific `.xlsx` workbook and can't list, fetch, or
upload any other file.

Scoped to a single configured Drive folder (`APM_DRIVE_FOLDER_ID`) by
design, not just convention: `list_files` only ever queries within that
folder, `upload_file` always creates inside it, and `read_file`/
`update_file` both refuse (raising `PermissionError`) if the file they're
given isn't actually a child of it. This matters because the OAuth scope
this connector needs is the full `drive` scope, not a file-scoped one —
same "drive.file only covers files this app created or the user picked
via a Picker, neither true here" limitation excel_file_tool.py's module
docstring already documents for the identical reason. The folder check
is this module's own least-privilege guardrail on top of that broad
grant: even though the token *can* reach any file in the account's
Drive, this connector will only ever act on one, by construction.

Shares excel_file_tool.py's GOOGLE_DRIVE_SCOPE and
DEFAULT_DRIVE_TOKEN_PATH deliberately: both connectors request the exact
same scope, so caching one token under one path serves both without a
second consent screen (unlike Gmail+Calendar's *different* scopes, which
must never share a token path — see google_auth.load_credentials).

Read (list files, read a file's contents) and write (upload a new file,
replace an existing file's contents) both follow the same dry_run-gated
pattern as every other connector's write/action methods: dry_run
defaults to True, and a real call must only ever come from inside the
agent graph's execute_node, after an approved human interrupt (see
.claude/skills/tool-integration/SKILL.md).

Known gap: file content moves over this API as base64 in a JSON body --
fine for typical documents, but there's no chunking/streaming for very
large files. Reflected in docs/capability-map.md, not silently assumed
away.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from apm_connectors.config import Settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools._retry import with_retry
from apm_connectors.tools.base import ActionResult, BaseTool, Capability
from apm_connectors.tools.excel_file_tool import DEFAULT_DRIVE_TOKEN_PATH, GOOGLE_DRIVE_SCOPE


class DriveClient(Protocol):
    """What DriveTool needs from a Drive client -- the real
    GoogleApiDriveClient below and test fakes both implement just this.
    """

    def list_files(self, query: str, max_results: int) -> list[dict[str, Any]]: ...

    def get_metadata(self, file_id: str) -> dict[str, Any]: ...

    def download(self, file_id: str) -> bytes: ...

    def upload(self, name: str, content: bytes, mime_type: str, folder_id: str) -> dict[str, Any]: ...

    def update_content(self, file_id: str, content: bytes) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DriveFileMetadata:
    file_id: str
    name: str
    mime_type: str
    modified_time: str | None
    web_view_link: str | None


@dataclass(frozen=True)
class DriveFileContent:
    file_id: str
    name: str
    mime_type: str
    size: int
    content_base64: str


class DriveTool(BaseTool):
    """Documents connector bound to one Drive folder at construction
    time. See this module's docstring for why every operation is scoped
    to that folder rather than the whole Drive the OAuth token can see.
    """

    name = "drive"
    capabilities = frozenset({Capability.READ, Capability.WRITE})

    def __init__(self, state: StateStore, client: DriveClient, folder_id: str) -> None:
        super().__init__(state)
        self._client = client
        self._folder_id = folder_id

    def health_check(self) -> bool:
        try:
            self._client.list_files(self._folder_query(), max_results=1)
            return True
        except Exception:
            return False

    def list_files(
        self, process_id: str, name_contains: str | None = None, max_results: int = 20
    ) -> list[DriveFileMetadata]:
        """List files directly inside the configured folder, optionally
        filtered by a substring of the file name.
        """
        extra = None
        if name_contains:
            escaped = name_contains.replace("'", "\\'")
            extra = f"name contains '{escaped}'"
        raw_files = self._client.list_files(self._folder_query(extra), max_results)
        results = [
            DriveFileMetadata(
                file_id=f["id"],
                name=f["name"],
                mime_type=f.get("mimeType", ""),
                modified_time=f.get("modifiedTime"),
                web_view_link=f.get("webViewLink"),
            )
            for f in raw_files
        ]
        self._log(
            process_id,
            "read",
            f"Listed {len(results)} file(s) in Drive folder {self._folder_id}",
            {"folder_id": self._folder_id, "files": [{"file_id": r.file_id, "name": r.name} for r in results]},
        )
        return results

    def read_file(self, process_id: str, file_id: str) -> DriveFileContent:
        """Download one file's contents, base64-encoded. Refuses (raises
        PermissionError) if the file isn't inside the configured folder.
        """
        metadata = self._client.get_metadata(file_id)
        self._require_in_folder(metadata, file_id)
        content = self._client.download(file_id)
        result = DriveFileContent(
            file_id=file_id,
            name=metadata.get("name", ""),
            mime_type=metadata.get("mimeType", ""),
            size=len(content),
            content_base64=base64.b64encode(content).decode("ascii"),
        )
        # Deliberately excludes content_base64 -- see security-guardrails.md
        # ("no ... content is persisted beyond what's needed"): the audit
        # trail records that this file was read, not a copy of it.
        self._log(
            process_id,
            "read",
            f"Read file {result.name!r} ({result.size} bytes) from Drive",
            {"file_id": file_id, "name": result.name, "mime_type": result.mime_type, "size": result.size},
        )
        return result

    def upload_file(
        self, process_id: str, name: str, content_base64: str, mime_type: str, dry_run: bool = True
    ) -> ActionResult:
        """Create a new file inside the configured folder. Only ever
        call this with dry_run=False from inside the agent graph, after
        the human-approval interrupt has returned an approval.
        """
        summary = f"Upload document {name!r} ({mime_type}) to Drive folder {self._folder_id}"
        self.require_dry_run_guard(dry_run, process_id, summary)

        if dry_run:
            return ActionResult(
                executed=False,
                description=summary,
                details={"name": name, "mime_type": mime_type, "folder_id": self._folder_id},
            )

        content = base64.b64decode(content_base64)
        created = self._client.upload(name, content, mime_type, self._folder_id)
        return ActionResult(
            executed=True,
            description=summary,
            details={
                "file_id": created.get("id"),
                "name": created.get("name", name),
                "web_view_link": created.get("webViewLink"),
            },
        )

    def update_file(self, process_id: str, file_id: str, content_base64: str, dry_run: bool = True) -> ActionResult:
        """Replace an existing file's contents. Refuses (raises
        PermissionError) if the file isn't inside the configured folder.
        Only ever call this with dry_run=False from inside the agent
        graph, after the human-approval interrupt has returned an
        approval.
        """
        summary = f"Replace contents of Drive file {file_id}"
        self.require_dry_run_guard(dry_run, process_id, summary)

        if dry_run:
            return ActionResult(executed=False, description=summary, details={"file_id": file_id})

        metadata = self._client.get_metadata(file_id)
        self._require_in_folder(metadata, file_id)
        content = base64.b64decode(content_base64)
        updated = self._client.update_content(file_id, content)
        return ActionResult(
            executed=True,
            description=summary,
            details={"file_id": updated.get("id", file_id), "name": updated.get("name")},
        )

    def _folder_query(self, extra: str | None = None) -> str:
        query = f"'{self._folder_id}' in parents and trashed = false"
        return f"{query} and {extra}" if extra else query

    def _require_in_folder(self, metadata: dict[str, Any], file_id: str) -> None:
        parents = metadata.get("parents") or []
        if self._folder_id not in parents:
            raise PermissionError(
                f"Drive file {file_id} is not inside the configured folder "
                f"({self._folder_id}) -- refusing to touch it."
            )


class GoogleApiDriveClient:
    """Real Drive v3 client. Imports googleapiclient lazily so this
    module -- and DriveTool's unit tests, which use a fake client --
    don't require that dependency at import time.
    """

    def __init__(self, credentials: Any) -> None:
        from googleapiclient.discovery import build

        self._service = build("drive", "v3", credentials=credentials)

    @with_retry()
    def list_files(self, query: str, max_results: int) -> list[dict[str, Any]]:
        response = (
            self._service.files()
            .list(q=query, fields="files(id, name, mimeType, modifiedTime, webViewLink)", pageSize=max_results)
            .execute()
        )
        return response.get("files", [])

    @with_retry()
    def get_metadata(self, file_id: str) -> dict[str, Any]:
        return (
            self._service.files()
            .get(fileId=file_id, fields="id, name, mimeType, parents, modifiedTime, webViewLink")
            .execute()
        )

    @with_retry()
    def download(self, file_id: str) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload

        request = self._service.files().get_media(fileId=file_id)
        buffer = BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    # Deliberately NOT retried -- see apm_connectors.tools._retry's module
    # docstring: a dropped connection after Drive already created the
    # file must not turn into an automatic duplicate upload.
    def upload(self, name: str, content: bytes, mime_type: str, folder_id: str) -> dict[str, Any]:
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(BytesIO(content), mimetype=mime_type, resumable=False)
        return (
            self._service.files()
            .create(
                body={"name": name, "parents": [folder_id]},
                media_body=media,
                fields="id, name, mimeType, webViewLink",
            )
            .execute()
        )

    # Also deliberately NOT retried, same reasoning as upload above.
    def update_content(self, file_id: str, content: bytes) -> dict[str, Any]:
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(BytesIO(content), resumable=False)
        return (
            self._service.files()
            .update(fileId=file_id, media_body=media, fields="id, name, mimeType, webViewLink")
            .execute()
        )


def build_configured_drive_tool(
    state: StateStore, settings: Settings, token_path: Path = DEFAULT_DRIVE_TOKEN_PATH
) -> DriveTool | None:
    """Build the Drive documents tool this server is configured for.

    Gated on APM_DRIVE_FOLDER_ID alone -- deliberately: there's no
    single-file id to key off (unlike Excel's APM_EXCEL_DRIVE_FILE_ID),
    and requiring a folder id rather than a separate "enabled" flag
    forces the narrower, safer configuration (see this module's
    docstring) to be the only one this connector supports, in line with
    CLAUDE.md's least-privilege guidance. Returns None if unset -- every
    /tools/drive/* route then 503s, same "the API stays up, only this
    tool's routes 503" spirit as every other optional connector.
    """
    if not settings.drive_folder_id:
        return None

    from apm_connectors.tools.google_auth import load_credentials

    credentials = load_credentials(settings, scopes=[GOOGLE_DRIVE_SCOPE], token_path=token_path)
    return DriveTool(state, GoogleApiDriveClient(credentials), folder_id=settings.drive_folder_id)
