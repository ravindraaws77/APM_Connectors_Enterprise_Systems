import base64
from pathlib import Path

import pytest

from apm_connectors.config import Settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools import drive_tool as drive_tool_module
from apm_connectors.tools.base import Capability
from apm_connectors.tools.drive_tool import DriveTool, build_configured_drive_tool

FOLDER_ID = "folder-abc"


def _settings(*, drive_folder_id: str | None = None) -> Settings:
    return Settings(
        google_client_id=None,
        google_client_secret=None,
        excel_workbook_path=None,
        excel_drive_file_id=None,
        state_dir=Path("state"),
        drive_folder_id=drive_folder_id,
    )


class FakeDriveClient:
    """In-memory DriveClient -- no network, no credentials -- so
    DriveTool's logic (including the folder-scoping guardrail) can be
    unit tested directly.
    """

    def __init__(self) -> None:
        # file_id -> {"name", "mimeType", "parents", "content"}
        self.files: dict[str, dict] = {}
        self.upload_count = 0
        self.update_count = 0

    def add_file(self, file_id: str, name: str, mime_type: str, parents: list[str], content: bytes) -> None:
        self.files[file_id] = {"name": name, "mimeType": mime_type, "parents": parents, "content": content}

    def list_files(self, query: str, max_results: int) -> list[dict]:
        # Fake just needs to honor the folder-scoping this test cares
        # about, not parse real Drive query syntax.
        results = [
            {"id": fid, "name": f["name"], "mimeType": f["mimeType"]}
            for fid, f in self.files.items()
            if f"'{FOLDER_ID}' in parents" in query and FOLDER_ID in f["parents"]
        ]
        return results[:max_results]

    def get_metadata(self, file_id: str) -> dict:
        f = self.files[file_id]
        return {"id": file_id, "name": f["name"], "mimeType": f["mimeType"], "parents": f["parents"]}

    def download(self, file_id: str) -> bytes:
        return self.files[file_id]["content"]

    def upload(self, name: str, content: bytes, mime_type: str, folder_id: str) -> dict:
        self.upload_count += 1
        file_id = f"new-{self.upload_count}"
        self.files[file_id] = {"name": name, "mimeType": mime_type, "parents": [folder_id], "content": content}
        return {"id": file_id, "name": name, "webViewLink": f"https://drive/{file_id}"}

    def update_content(self, file_id: str, content: bytes) -> dict:
        self.update_count += 1
        self.files[file_id]["content"] = content
        return {"id": file_id, "name": self.files[file_id]["name"]}


def test_drive_tool_capabilities() -> None:
    assert DriveTool.capabilities == frozenset({Capability.READ, Capability.WRITE})


def test_list_files_scoped_to_folder_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeDriveClient()
    client.add_file("f1", "Contract.pdf", "application/pdf", [FOLDER_ID], b"pdf-bytes")
    client.add_file("f2", "Other.pdf", "application/pdf", ["other-folder"], b"other-bytes")
    tool = DriveTool(store, client, folder_id=FOLDER_ID)

    results = tool.list_files("order-1")

    assert [r.file_id for r in results] == ["f1"]
    assert results[0].name == "Contract.pdf"
    events = store.list_events("order-1")
    assert any(e["event_type"] == "read" and e["details"]["folder_id"] == FOLDER_ID for e in events)


def test_read_file_returns_base64_content_and_logs_without_it(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeDriveClient()
    client.add_file("f1", "Contract.pdf", "application/pdf", [FOLDER_ID], b"pdf-bytes")
    tool = DriveTool(store, client, folder_id=FOLDER_ID)

    result = tool.read_file("order-1", file_id="f1")

    assert result.name == "Contract.pdf"
    assert result.size == len(b"pdf-bytes")
    assert base64.b64decode(result.content_base64) == b"pdf-bytes"

    events = store.list_events("order-1")
    read_events = [e for e in events if e["event_type"] == "read"]
    assert any(e["details"].get("size") == len(b"pdf-bytes") for e in read_events)
    # The audit trail records that the file was read, not a copy of it.
    assert all("content_base64" not in e["details"] for e in read_events)


def test_read_file_outside_configured_folder_is_refused(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeDriveClient()
    client.add_file("f1", "Other.pdf", "application/pdf", ["other-folder"], b"data")
    tool = DriveTool(store, client, folder_id=FOLDER_ID)

    with pytest.raises(PermissionError, match="not inside the configured folder"):
        tool.read_file("order-1", file_id="f1")


def test_health_check_true(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = DriveTool(store, FakeDriveClient(), folder_id=FOLDER_ID)
    assert tool.health_check() is True


def test_health_check_false_on_client_error(tmp_path: Path) -> None:
    class BrokenClient(FakeDriveClient):
        def list_files(self, query: str, max_results: int) -> list[dict]:
            raise RuntimeError("simulated failure")

    store = StateStore(tmp_path / "state.json")
    tool = DriveTool(store, BrokenClient(), folder_id=FOLDER_ID)
    assert tool.health_check() is False


def test_upload_file_dry_run_does_not_touch_client(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeDriveClient()
    tool = DriveTool(store, client, folder_id=FOLDER_ID)

    content_b64 = base64.b64encode(b"new-doc").decode("ascii")
    result = tool.upload_file("order-1", name="Renewal.pdf", content_base64=content_b64, mime_type="application/pdf")

    assert result.executed is False
    assert client.upload_count == 0
    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_proposed" and e["details"]["dry_run"] is True for e in events)


def test_upload_file_real_call_creates_file_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeDriveClient()
    tool = DriveTool(store, client, folder_id=FOLDER_ID)

    content_b64 = base64.b64encode(b"new-doc").decode("ascii")
    result = tool.upload_file(
        "order-1", name="Renewal.pdf", content_base64=content_b64, mime_type="application/pdf", dry_run=False
    )

    assert result.executed is True
    assert client.upload_count == 1
    new_file_id = result.details["file_id"]
    assert client.files[new_file_id]["content"] == b"new-doc"
    assert client.files[new_file_id]["parents"] == [FOLDER_ID]

    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_executed" and e["details"]["dry_run"] is False for e in events)


def test_update_file_dry_run_does_not_touch_client(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeDriveClient()
    client.add_file("f1", "Contract.pdf", "application/pdf", [FOLDER_ID], b"old-bytes")
    tool = DriveTool(store, client, folder_id=FOLDER_ID)

    content_b64 = base64.b64encode(b"new-bytes").decode("ascii")
    result = tool.update_file("order-1", file_id="f1", content_base64=content_b64)

    assert result.executed is False
    assert client.update_count == 0
    assert client.files["f1"]["content"] == b"old-bytes"


def test_update_file_real_call_replaces_content(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeDriveClient()
    client.add_file("f1", "Contract.pdf", "application/pdf", [FOLDER_ID], b"old-bytes")
    tool = DriveTool(store, client, folder_id=FOLDER_ID)

    content_b64 = base64.b64encode(b"new-bytes").decode("ascii")
    result = tool.update_file("order-1", file_id="f1", content_base64=content_b64, dry_run=False)

    assert result.executed is True
    assert client.update_count == 1
    assert client.files["f1"]["content"] == b"new-bytes"


def test_update_file_outside_configured_folder_is_refused(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeDriveClient()
    client.add_file("f1", "Other.pdf", "application/pdf", ["other-folder"], b"data")
    tool = DriveTool(store, client, folder_id=FOLDER_ID)

    content_b64 = base64.b64encode(b"new-bytes").decode("ascii")
    with pytest.raises(PermissionError, match="not inside the configured folder"):
        tool.update_file("order-1", file_id="f1", content_base64=content_b64, dry_run=False)

    assert client.update_count == 0


def test_build_configured_drive_tool_returns_none_when_unconfigured(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    assert build_configured_drive_tool(store, _settings()) is None


def test_build_configured_drive_tool_builds_tool_when_folder_id_set(tmp_path: Path, monkeypatch) -> None:
    """Doesn't touch real Google OAuth/Drive -- monkeypatches
    load_credentials and GoogleApiDriveClient (which otherwise builds a
    real googleapiclient service object) so this confirms the wiring
    (folder id and credentials reach the built DriveTool) without any
    network call.
    """
    store = StateStore(tmp_path / "state.json")
    monkeypatch.setattr("apm_connectors.tools.google_auth.load_credentials", lambda *a, **k: "fake-credentials")
    monkeypatch.setattr(drive_tool_module, "GoogleApiDriveClient", lambda credentials: ("fake-client", credentials))

    tool = build_configured_drive_tool(store, _settings(drive_folder_id=FOLDER_ID))

    assert isinstance(tool, DriveTool)
    assert tool._folder_id == FOLDER_ID
    assert tool._client == ("fake-client", "fake-credentials")
