from pathlib import Path
from typing import Any

from apm_connectors.state.store import StateStore
from apm_connectors.tools.base import Capability
from apm_connectors.tools.gmail_tool import GmailTool


class FakeGmailClient:
    """Implements the GmailClient protocol in-memory — no network, no
    credentials — so GmailTool's logic can be unit tested directly.
    """

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages = {m["id"]: m for m in messages}
        self.sent: list[dict[str, Any]] = []

    def list_message_ids(self, query: str, max_results: int) -> list[str]:
        return list(self._messages.keys())[:max_results]

    def get_message(self, message_id: str) -> dict[str, Any]:
        return self._messages[message_id]

    def send_message(self, to: str, subject: str, body: str) -> dict[str, Any]:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return {"id": f"sent-{len(self.sent)}"}


class BrokenGmailClient:
    def list_message_ids(self, query: str, max_results: int) -> list[str]:
        raise RuntimeError("simulated API failure")

    def get_message(self, message_id: str) -> dict[str, Any]:
        raise RuntimeError("simulated API failure")

    def send_message(self, to: str, subject: str, body: str) -> dict[str, Any]:
        raise RuntimeError("simulated API failure")


def _raw_message(msg_id: str, sender: str, subject: str, snippet: str, date: str) -> dict[str, Any]:
    return {
        "id": msg_id,
        "threadId": f"thread-{msg_id}",
        "snippet": snippet,
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date},
            ]
        },
    }


def test_gmail_tool_capabilities() -> None:
    assert GmailTool.capabilities == frozenset({Capability.READ, Capability.ACTION})


def test_search_emails_returns_summaries_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient(
        [_raw_message("m1", "customer@example.com", "Order #123 delayed",
                       "Sorry for the delay on your order...", "Mon, 1 Sep 2026 10:00:00 +0000")]
    )
    tool = GmailTool(store, client)

    results = tool.search_emails("order-123", query="order 123", max_results=5)

    assert len(results) == 1
    assert results[0].message_id == "m1"
    assert results[0].sender == "customer@example.com"
    assert results[0].subject == "Order #123 delayed"

    events = store.list_events("order-123")
    assert any(e["event_type"] == "read" and "order 123" in e["details"]["query"] for e in events)


def test_read_message(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient([_raw_message("m1", "a@b.com", "Hi there", "snippet text", "date")])
    tool = GmailTool(store, client)

    summary = tool.read_message("order-1", "m1")

    assert summary.message_id == "m1"
    assert summary.subject == "Hi there"


def test_missing_headers_fall_back_to_defaults(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient([{"id": "m2", "snippet": "no headers here"}])
    tool = GmailTool(store, client)

    summary = tool.read_message("order-1", "m2")

    assert summary.sender == "unknown"
    assert summary.subject == "(no subject)"
    assert summary.thread_id == "m2"


def test_health_check_true(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = GmailTool(store, FakeGmailClient([]))
    assert tool.health_check() is True


def test_health_check_false_on_client_error(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = GmailTool(store, BrokenGmailClient())
    assert tool.health_check() is False


def test_send_email_dry_run_does_not_call_client(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient([])
    tool = GmailTool(store, client)

    result = tool.send_email("order-1", to="customer@realcorp.io", subject="Hi", body="body text")

    assert result.executed is False
    assert client.sent == []
    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_proposed" and e["details"]["dry_run"] is True for e in events)


def test_send_email_real_call_invokes_client_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient([])
    tool = GmailTool(store, client)

    result = tool.send_email(
        "order-1", to="customer@realcorp.io", subject="Delay update", body="Sorry for the delay", dry_run=False
    )

    assert result.executed is True
    assert result.details["message_id"] == "sent-1"
    assert client.sent == [{"to": "customer@realcorp.io", "subject": "Delay update", "body": "Sorry for the delay"}]

    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_executed" and e["details"]["dry_run"] is False for e in events)


def test_send_email_refuses_reserved_placeholder_domain(tmp_path: Path) -> None:
    """Reproduces the real scenario: the reasoner proposed sending to a
    fabricated 'customer@example.com' since no real customer address was
    in the fetched data. The refusal must happen even with dry_run=False
    -- this is the last line of defense before an actual send.
    """
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient([])
    tool = GmailTool(store, client)

    result = tool.send_email(
        "order-1", to="customer@example.com", subject="Update", body="body", dry_run=False
    )

    assert result.executed is False
    assert result.details["reason"] == "reserved_placeholder_domain"
    assert client.sent == []  # never reached the real client

    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_failed" for e in events)


def test_send_email_refuses_reserved_tld_not_just_literal_domains(tmp_path: Path) -> None:
    """RFC 2606 reserves whole TLDs (.test, .example, .invalid,
    .localhost) -- any subdomain under them is fake, not just the exact
    strings example.com/net/org.
    """
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient([])
    tool = GmailTool(store, client)

    for address in ["a@foo.test", "b@bar.example", "c@baz.invalid", "d@service.localhost"]:
        result = tool.send_email("order-1", to=address, subject="x", body="y", dry_run=False)
        assert result.executed is False, address
        assert client.sent == []


def test_send_email_does_not_false_positive_on_domains_containing_reserved_words(tmp_path: Path) -> None:
    """A real company domain like testcorp.com must not be blocked just
    because it contains the substring 'test' -- only the reserved TLD
    itself (.test) or the exact example.* domains are refused.
    """
    store = StateStore(tmp_path / "state.json")
    client = FakeGmailClient([])
    tool = GmailTool(store, client)

    result = tool.send_email("order-1", to="c@testcorp.com", subject="x", body="y", dry_run=False)

    assert result.executed is True
    assert client.sent == [{"to": "c@testcorp.com", "subject": "x", "body": "y"}]
