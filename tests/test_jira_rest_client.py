"""Unit tests for JiraRestClient's Atlassian Document Format (ADF)
normalization -- added after a real create_issue call against a live
Jira Cloud site 400'd on a plain-string `description` with no further
detail in the error message. No live credentials or network needed.
"""

from __future__ import annotations

from typing import Any

import pytest

from apm_connectors.tools.jira_tool import JiraRestClient, _normalize_fields_for_jira_api, _text_to_adf


def test_text_to_adf_single_line():
    doc = _text_to_adf("Fix the thing")
    assert doc == {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Fix the thing"}]}],
    }


def test_text_to_adf_multiple_paragraphs_and_hard_breaks():
    doc = _text_to_adf("Line one\nLine two\n\nSecond paragraph")

    assert doc["type"] == "doc"
    assert len(doc["content"]) == 2

    first_paragraph = doc["content"][0]["content"]
    assert first_paragraph == [
        {"type": "text", "text": "Line one"},
        {"type": "hardBreak"},
        {"type": "text", "text": "Line two"},
    ]

    second_paragraph = doc["content"][1]["content"]
    assert second_paragraph == [{"type": "text", "text": "Second paragraph"}]


def test_text_to_adf_empty_string_still_valid_doc():
    doc = _text_to_adf("")
    assert doc == {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": []}]}


def test_normalize_converts_plain_string_description():
    fields = {"project": {"key": "KAN"}, "summary": "x", "description": "hello"}
    normalized = _normalize_fields_for_jira_api(fields)

    assert normalized["description"]["type"] == "doc"
    assert normalized["project"] == {"key": "KAN"}  # untouched
    assert fields["description"] == "hello"  # original left alone


def test_normalize_leaves_existing_adf_description_untouched():
    adf = {"type": "doc", "version": 1, "content": []}
    fields = {"description": adf}

    normalized = _normalize_fields_for_jira_api(fields)

    assert normalized["description"] is adf


def test_normalize_leaves_missing_description_untouched():
    fields = {"summary": "x"}
    assert _normalize_fields_for_jira_api(fields) == {"summary": "x"}


class _FakeResponse:
    status_code = 201

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return {"key": "KAN-99"}


def test_create_issue_sends_normalized_description(monkeypatch: pytest.MonkeyPatch):
    import requests

    captured = {}

    def fake_post(url, auth, headers, json, timeout):
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    client = JiraRestClient(base_url="https://example.atlassian.net", email="a@b.com", api_token="tok")
    client.create_issue({"project": {"key": "KAN"}, "description": "line one\nline two"})

    sent_description = captured["json"]["fields"]["description"]
    assert sent_description["type"] == "doc"
    assert "hardBreak" in str(sent_description)
