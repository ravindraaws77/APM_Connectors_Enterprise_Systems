"""MS Excel connector (via Microsoft Graph).

Read (list worksheets, read a range) has been available since phase 4.
This phase (5) adds write_range — the write capability deferred until
now, same reasoning as Gmail's send_email / Calendar's create_event: only
ever called with dry_run=False from inside the agent graph's
execute_node, after an approved interrupt.

Unlike Gmail/Calendar (which operate on "the" mailbox/calendar), an Excel
connector is bound to one specific workbook — a OneDrive/SharePoint drive
item — chosen when the tool is built. Microsoft Graph's Excel API has no
concept of a local .xlsx file; the workbook must already be on
OneDrive/SharePoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from apm_connectors.config import Settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools._retry import with_retry
from apm_connectors.tools.base import ActionResult, BaseTool, Capability

EXCEL_READONLY_SCOPE = "Files.Read"
EXCEL_READWRITE_SCOPE = "Files.ReadWrite"


class ExcelClient(Protocol):
    """The minimal surface ExcelTool needs from a workbook. Both the real
    client (`GraphApiExcelClient`, below) and test fakes implement just
    this.
    """

    def list_worksheets(self) -> list[str]: ...

    def get_range(self, sheet_name: str, address: str) -> dict[str, Any]: ...

    def update_range(self, sheet_name: str, address: str, values: list[list[Any]]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RangeData:
    sheet_name: str
    address: str
    values: list[list[Any]] = field(default_factory=list)


class ExcelTool(BaseTool):
    """Excel connector, bound to one workbook at construction time (see
    build_excel_tool): reads worksheets/ranges, and writes a range — the
    latter only ever reachable through the agent's approval interrupt
    (see apm_connectors.agent.graph).
    """

    name = "ms_excel"
    capabilities = frozenset({Capability.READ, Capability.WRITE})

    def __init__(self, state: StateStore, client: ExcelClient) -> None:
        super().__init__(state)
        self._client = client

    def health_check(self) -> bool:
        try:
            self._client.list_worksheets()
            return True
        except Exception:
            return False

    def list_worksheets(self, process_id: str) -> list[str]:
        names = self._client.list_worksheets()
        self._log(process_id, "read", f"Listed {len(names)} worksheet(s)", {"worksheets": names})
        return names

    def read_range(self, process_id: str, sheet_name: str, address: str) -> RangeData:
        """Read a cell range (e.g. sheet_name="Renewals", address="A1:D20")
        and return its values as a list of rows.
        """
        raw = self._client.get_range(sheet_name, address)
        data = RangeData(
            sheet_name=sheet_name,
            address=raw.get("address", address),
            values=raw.get("values", []),
        )
        self._log(
            process_id,
            "read",
            f"Read range {sheet_name}!{address} ({len(data.values)} row(s))",
            {"sheet_name": sheet_name, "address": address, "row_count": len(data.values)},
        )
        return data


    def write_range(
        self, process_id: str, sheet_name: str, address: str, values: list[list[Any]], dry_run: bool = True
    ) -> ActionResult:
        """Overwrite a cell range with new values (a list of rows). Only
        ever call this with dry_run=False from inside the agent graph,
        after the human-approval interrupt has returned an approval.
        """
        summary = f"Write {len(values)} row(s) to {sheet_name}!{address}"
        self.require_dry_run_guard(dry_run, process_id, summary)

        if dry_run:
            return ActionResult(
                executed=False,
                description=summary,
                details={"sheet_name": sheet_name, "address": address, "values": values},
            )

        self._client.update_range(sheet_name, address, values)
        return ActionResult(
            executed=True,
            description=summary,
            details={"sheet_name": sheet_name, "address": address, "row_count": len(values)},
        )


class GraphApiExcelClient:
    """Real Microsoft Graph client for one workbook (a OneDrive/SharePoint
    drive item). Imports `requests` lazily so this module — and
    ExcelTool's unit tests, which use a fake client — don't require that
    dependency at import time.
    """

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, access_token: str, item_id: str, drive_id: str | None = None) -> None:
        self._access_token = access_token
        # /me/drive/items/{id} for the signed-in user's own OneDrive, or
        # /drives/{drive_id}/items/{id} for a specific SharePoint drive.
        if drive_id:
            self._workbook_base = f"{self.GRAPH_BASE}/drives/{drive_id}/items/{item_id}/workbook"
        else:
            self._workbook_base = f"{self.GRAPH_BASE}/me/drive/items/{item_id}/workbook"

    @with_retry()
    def _get(self, path: str) -> dict[str, Any]:
        import requests

        response = requests.get(
            f"{self._workbook_base}{path}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def list_worksheets(self) -> list[str]:
        data = self._get("/worksheets")
        return [w["name"] for w in data.get("value", [])]

    def get_range(self, sheet_name: str, address: str) -> dict[str, Any]:
        return self._get(f"/worksheets('{sheet_name}')/range(address='{address}')")

    # Deliberately NOT retried -- see apm_connectors.tools._retry's module docstring:
    # a dropped connection after the server already wrote the range must
    # not turn into an automatic duplicate write.
    def update_range(self, sheet_name: str, address: str, values: list[list[Any]]) -> dict[str, Any]:
        import requests

        response = requests.patch(
            f"{self._workbook_base}/worksheets('{sheet_name}')/range(address='{address}')",
            headers={"Authorization": f"Bearer {self._access_token}"},
            json={"values": values},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


def build_excel_tool(
    state: StateStore, settings: Settings, item_id: str, drive_id: str | None = None
) -> ExcelTool:
    """Convenience factory: runs the device-code auth flow (if needed) and
    returns an ExcelTool bound to the given workbook (drive item id).
    """
    from apm_connectors.tools.ms_graph_auth import acquire_access_token

    access_token = acquire_access_token(settings, scopes=[EXCEL_READWRITE_SCOPE])
    return ExcelTool(state, GraphApiExcelClient(access_token, item_id, drive_id))
