from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

from apm_connectors.config import Settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools import excel_file_tool as excel_file_tool_module
from apm_connectors.tools.base import Capability
from apm_connectors.tools.excel_file_tool import (
    ExcelFileTool,
    LocalWorkbookSource,
    build_configured_excel_tool,
    resolve_drive_file_id,
)


def _settings(*, excel_workbook_path: str | None = None, excel_drive_file_id: str | None = None) -> Settings:
    return Settings(
        google_client_id=None,
        google_client_secret=None,
        ms_graph_client_id=None,
        ms_graph_client_secret=None,
        ms_graph_tenant_id=None,
        excel_workbook_path=excel_workbook_path,
        excel_drive_file_id=excel_drive_file_id,
        state_dir=Path("state"),
    )


class FakeWorkbookSource:
    """Implements the WorkbookSource protocol in-memory — no disk, no
    network, no credentials — so ExcelFileTool's logic can be unit
    tested directly, for both the local-file and Google-Drive cases
    (they only differ in where the bytes ultimately live).
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.write_count = 0

    def describe(self) -> str:
        return "fake:workbook"

    def read_bytes(self) -> bytes:
        return self._data

    def write_bytes(self, data: bytes) -> None:
        self._data = data
        self.write_count += 1


class BrokenWorkbookSource:
    def describe(self) -> str:
        return "fake:broken"

    def read_bytes(self) -> bytes:
        raise RuntimeError("simulated read failure")

    def write_bytes(self, data: bytes) -> None:
        raise RuntimeError("simulated write failure")


def _sample_workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Renewals"
    sheet.append(["Customer", "RenewalDate"])
    sheet.append(["Acme Corp", "2026-10-01"])
    workbook.create_sheet("Orders")
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_excel_file_tool_capabilities() -> None:
    assert ExcelFileTool.capabilities == frozenset({Capability.READ, Capability.WRITE})


def test_list_worksheets_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    source = FakeWorkbookSource(_sample_workbook_bytes())
    tool = ExcelFileTool(store, source)

    names = tool.list_worksheets("order-123")

    assert names == ["Renewals", "Orders"]
    events = store.list_events("order-123")
    assert any(e["event_type"] == "read" and e["details"]["worksheets"] == names for e in events)


def test_read_range_returns_values_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    source = FakeWorkbookSource(_sample_workbook_bytes())
    tool = ExcelFileTool(store, source)

    data = tool.read_range("order-123", sheet_name="Renewals", address="A1:B2")

    assert data.sheet_name == "Renewals"
    assert data.address == "A1:B2"
    assert data.values == [["Customer", "RenewalDate"], ["Acme Corp", "2026-10-01"]]

    events = store.list_events("order-123")
    read_events = [e for e in events if e["event_type"] == "read"]
    assert any(e["details"].get("row_count") == 2 for e in read_events)


def test_read_range_defaults_to_first_sheet_and_used_range(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    source = FakeWorkbookSource(_sample_workbook_bytes())
    tool = ExcelFileTool(store, source)

    data = tool.read_range("order-123")

    assert data.sheet_name == "Renewals"
    assert data.address == "A1:B2"
    assert data.values == [["Customer", "RenewalDate"], ["Acme Corp", "2026-10-01"]]


def test_read_range_default_address_with_explicit_sheet(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    source = FakeWorkbookSource(_sample_workbook_bytes())
    tool = ExcelFileTool(store, source)

    data = tool.read_range("order-123", sheet_name="Orders")

    assert data.sheet_name == "Orders"
    assert data.address == "A1:A1"  # empty sheet -- openpyxl's default dimensions
    assert data.values == [[None]]


def test_read_range_single_cell_address(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    source = FakeWorkbookSource(_sample_workbook_bytes())
    tool = ExcelFileTool(store, source)

    data = tool.read_range("order-1", sheet_name="Renewals", address="A2")

    assert data.values == [["Acme Corp"]]


def test_health_check_true(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = ExcelFileTool(store, FakeWorkbookSource(_sample_workbook_bytes()))
    assert tool.health_check() is True


def test_health_check_false_on_source_error(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = ExcelFileTool(store, BrokenWorkbookSource())
    assert tool.health_check() is False


def test_write_range_dry_run_does_not_touch_source(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    source = FakeWorkbookSource(_sample_workbook_bytes())
    tool = ExcelFileTool(store, source)

    result = tool.write_range("order-1", sheet_name="Renewals", address="A2:B2", values=[["Acme", "2026-11-01"]])

    assert result.executed is False
    assert source.write_count == 0
    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_proposed" and e["details"]["dry_run"] is True for e in events)


def test_write_range_real_call_updates_source_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    source = FakeWorkbookSource(_sample_workbook_bytes())
    tool = ExcelFileTool(store, source)

    result = tool.write_range(
        "order-1", sheet_name="Renewals", address="A2:B2", values=[["Acme", "2026-11-01"]], dry_run=False
    )

    assert result.executed is True
    assert result.details["row_count"] == 1
    assert source.write_count == 1

    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_executed" and e["details"]["dry_run"] is False for e in events)

    # The write actually landed, and other data (Orders sheet) survived.
    reread = tool.read_range("order-1", sheet_name="Renewals", address="A2:B2")
    assert reread.values == [["Acme", "2026-11-01"]]
    assert tool.list_worksheets("order-1") == ["Renewals", "Orders"]


def test_local_workbook_source_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "workbook.xlsx"
    path.write_bytes(_sample_workbook_bytes())
    source = LocalWorkbookSource(path)

    assert source.describe() == f"local:{path}"
    assert source.read_bytes() == path.read_bytes()

    source.write_bytes(b"new-bytes")
    assert path.read_bytes() == b"new-bytes"


def test_build_configured_excel_tool_returns_none_when_unconfigured(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    assert build_configured_excel_tool(store, _settings()) is None


def test_build_configured_excel_tool_raises_when_both_are_set(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    settings = _settings(excel_workbook_path="./workbook.xlsx", excel_drive_file_id="some-file-id")

    with pytest.raises(ValueError, match="ambiguous"):
        build_configured_excel_tool(store, settings)


def test_build_configured_excel_tool_builds_local_tool_from_path(tmp_path: Path) -> None:
    path = tmp_path / "workbook.xlsx"
    path.write_bytes(_sample_workbook_bytes())
    store = StateStore(tmp_path / "state.json")

    tool = build_configured_excel_tool(store, _settings(excel_workbook_path=str(path)))

    assert isinstance(tool, ExcelFileTool)
    assert tool.list_worksheets("order-1") == ["Renewals", "Orders"]


def test_build_configured_excel_tool_builds_drive_tool_from_file_id(tmp_path: Path, monkeypatch) -> None:
    """Doesn't touch real Google OAuth/Drive -- monkeypatches
    build_gdrive_excel_tool (looked up at call time via the module, so
    this substitution takes effect) to confirm build_configured_excel_tool
    reaches it with the right file id, without any network call.
    """
    store = StateStore(tmp_path / "state.json")
    calls: list[tuple[object, object, str]] = []

    def fake_build_gdrive_excel_tool(state, settings, file_id):
        calls.append((state, settings, file_id))
        return "fake-tool"

    monkeypatch.setattr(excel_file_tool_module, "build_gdrive_excel_tool", fake_build_gdrive_excel_tool)

    result = build_configured_excel_tool(store, _settings(excel_drive_file_id="some-file-id"))

    assert result == "fake-tool"
    assert len(calls) == 1
    assert calls[0][0] is store
    assert calls[0][2] == "some-file-id"


class _FakeDriveFilesList:
    def __init__(self, response: dict) -> None:
        self._response = response

    def execute(self) -> dict:
        return self._response


class _FakeDriveFiles:
    def __init__(self, response: dict) -> None:
        self._response = response

    def list(self, **kwargs: object) -> _FakeDriveFilesList:
        return _FakeDriveFilesList(self._response)


class _FakeDriveService:
    def __init__(self, response: dict) -> None:
        self._response = response

    def files(self) -> _FakeDriveFiles:
        return _FakeDriveFiles(self._response)


def _patch_drive_search(monkeypatch: pytest.MonkeyPatch, matches: list[dict]) -> None:
    """resolve_drive_file_id lazily imports both google_auth.load_credentials
    and googleapiclient.discovery.build inside its body -- monkeypatching
    the module attributes here takes effect because a `from x import y`
    executed at call time re-reads x's current attribute.
    """
    monkeypatch.setattr("apm_connectors.tools.google_auth.load_credentials", lambda *a, **k: object())
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *a, **k: _FakeDriveService({"files": matches}))


def test_resolve_drive_file_id_returns_bare_id_unchanged(tmp_path: Path) -> None:
    # No "." -- treated as an id already, no Drive search/network call.
    assert resolve_drive_file_id(_settings(), "1AbCdEf-some-id_no-dot") == "1AbCdEf-some-id_no-dot"


def test_resolve_drive_file_id_resolves_a_name_via_search(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_drive_search(monkeypatch, [{"id": "real-id-123", "name": "APM_Invoice_Details.xlsx"}])

    assert resolve_drive_file_id(_settings(), "APM_Invoice_Details.xlsx") == "real-id-123"


def test_resolve_drive_file_id_raises_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_drive_search(monkeypatch, [])

    with pytest.raises(ValueError, match="No Drive file named"):
        resolve_drive_file_id(_settings(), "Nonexistent.xlsx")


def test_resolve_drive_file_id_raises_when_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_drive_search(
        monkeypatch,
        [{"id": "id-1", "name": "Dup.xlsx"}, {"id": "id-2", "name": "Dup.xlsx"}],
    )

    with pytest.raises(ValueError, match="ambiguous"):
        resolve_drive_file_id(_settings(), "Dup.xlsx")


def test_build_configured_excel_tool_resolves_a_drive_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact bug this was all fixed for: APM_EXCEL_DRIVE_FILE_ID set
    to a file *name* must resolve to a real id before reaching
    build_gdrive_excel_tool, not be sent to Drive as a literal file id.
    """
    store = StateStore(tmp_path / "state.json")
    _patch_drive_search(monkeypatch, [{"id": "real-id-123", "name": "APM_Invoice_Details.xlsx"}])

    calls: list[str] = []
    monkeypatch.setattr(
        excel_file_tool_module,
        "build_gdrive_excel_tool",
        lambda state, settings, file_id: calls.append(file_id) or "fake-tool",
    )

    result = build_configured_excel_tool(store, _settings(excel_drive_file_id="APM_Invoice_Details.xlsx"))

    assert result == "fake-tool"
    assert calls == ["real-id-123"]
