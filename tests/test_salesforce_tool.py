from pathlib import Path
from typing import Any

from apm_connectors.state.store import StateStore
from apm_connectors.tools.base import Capability
from apm_connectors.tools.salesforce_tool import SalesforceTool


class FakeSalesforceClient:
    """Implements the SalesforceClient protocol in-memory — no network, no
    credentials — so SalesforceTool's logic can be unit tested directly.
    """

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = {r["Id"]: r for r in records}
        self.created: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []

    def query(self, soql: str) -> list[dict[str, Any]]:
        return list(self._records.values())

    def get_record(self, object_name: str, record_id: str) -> dict[str, Any]:
        return self._records[record_id]

    def create_record(self, object_name: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.created.append({"object_name": object_name, "fields": fields})
        return {"id": f"created-{len(self.created)}"}

    def update_record(self, object_name: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.updated.append({"object_name": object_name, "record_id": record_id, "fields": fields})
        return {"id": record_id}


class BrokenSalesforceClient:
    def query(self, soql: str) -> list[dict[str, Any]]:
        raise RuntimeError("simulated API failure")

    def get_record(self, object_name: str, record_id: str) -> dict[str, Any]:
        raise RuntimeError("simulated API failure")

    def create_record(self, object_name: str, fields: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("simulated API failure")

    def update_record(self, object_name: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("simulated API failure")


def _raw_record(record_id: str, object_type: str, **fields: Any) -> dict[str, Any]:
    return {"Id": record_id, "attributes": {"type": object_type}, **fields}


def test_salesforce_tool_capabilities() -> None:
    assert SalesforceTool.capabilities == frozenset({Capability.READ, Capability.WRITE})


def test_query_records_returns_normalized_records_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeSalesforceClient(
        [_raw_record("006abc", "Opportunity", Name="Acme Renewal", StageName="Negotiation")]
    )
    tool = SalesforceTool(store, client)

    soql = "SELECT Id, Name, StageName FROM Opportunity WHERE StageName = 'Negotiation'"
    results = tool.query_records("order-123", soql)

    assert len(results) == 1
    assert results[0].record_id == "006abc"
    assert results[0].object_type == "Opportunity"
    assert results[0].fields == {"Name": "Acme Renewal", "StageName": "Negotiation"}

    events = store.list_events("order-123")
    assert any(e["event_type"] == "read" and e["details"]["soql"] == soql for e in events)


def test_get_record(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeSalesforceClient([_raw_record("003xyz", "Contact", LastName="Doe")])
    tool = SalesforceTool(store, client)

    record = tool.get_record("order-1", "Contact", "003xyz")

    assert record.record_id == "003xyz"
    assert record.object_type == "Contact"
    assert record.fields == {"LastName": "Doe"}

    events = store.list_events("order-1")
    assert any(e["event_type"] == "read" and e["details"]["record_id"] == "003xyz" for e in events)


def test_health_check_true(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = SalesforceTool(store, FakeSalesforceClient([]))
    assert tool.health_check() is True


def test_health_check_false_on_client_error(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = SalesforceTool(store, BrokenSalesforceClient())
    assert tool.health_check() is False


def test_create_record_dry_run_does_not_call_client(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeSalesforceClient([])
    tool = SalesforceTool(store, client)

    result = tool.create_record("order-1", "Lead", {"LastName": "Doe", "Company": "Acme"})

    assert result.executed is False
    assert client.created == []
    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_proposed" and e["details"]["dry_run"] is True for e in events)


def test_create_record_real_call_invokes_client_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeSalesforceClient([])
    tool = SalesforceTool(store, client)

    result = tool.create_record(
        "order-1", "Lead", {"LastName": "Doe", "Company": "Acme"}, dry_run=False
    )

    assert result.executed is True
    assert result.details["record_id"] == "created-1"
    assert client.created == [{"object_name": "Lead", "fields": {"LastName": "Doe", "Company": "Acme"}}]

    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_executed" and e["details"]["dry_run"] is False for e in events)


def test_update_record_dry_run_does_not_call_client(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeSalesforceClient([])
    tool = SalesforceTool(store, client)

    result = tool.update_record("order-1", "Opportunity", "006abc", {"StageName": "Closed Won"})

    assert result.executed is False
    assert client.updated == []
    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_proposed" and e["details"]["dry_run"] is True for e in events)


def test_update_record_real_call_invokes_client_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeSalesforceClient([])
    tool = SalesforceTool(store, client)

    result = tool.update_record(
        "order-1", "Opportunity", "006abc", {"StageName": "Closed Won"}, dry_run=False
    )

    assert result.executed is True
    assert client.updated == [
        {"object_name": "Opportunity", "record_id": "006abc", "fields": {"StageName": "Closed Won"}}
    ]

    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_executed" and e["details"]["dry_run"] is False for e in events)
