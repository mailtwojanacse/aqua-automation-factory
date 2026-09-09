import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import slack_notifier


class _CapturingHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.received.append(json.loads(body.decode("utf-8")))
        self.send_response(self.server.respond_with)
        self.send_header("Content-Length", "0")
        self.end_headers()


@pytest.fixture
def mock_slack_server():
    """A real local HTTP server standing in for a Slack incoming webhook -
    proves post_to_slack's request/response handling end-to-end without
    needing a real Slack workspace."""
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    server.received = []
    server.respond_with = 200
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/webhook"
    yield server, url
    server.shutdown()
    thread.join(timeout=5)


# ---- post_to_slack ----

def test_post_to_slack_sends_text_and_returns_true_on_success(mock_slack_server):
    server, url = mock_slack_server
    ok = slack_notifier.post_to_slack(url, "hello from the test")
    assert ok is True
    assert server.received == [{"text": "hello from the test"}]


def test_post_to_slack_returns_false_on_non_2xx_response(mock_slack_server):
    server, url = mock_slack_server
    server.respond_with = 500
    ok = slack_notifier.post_to_slack(url, "should fail")
    assert ok is False


def test_post_to_slack_returns_false_without_raising_when_unreachable():
    # Nothing listens on port 1 on loopback - connection refused, not a hang.
    ok = slack_notifier.post_to_slack("http://127.0.0.1:1/webhook", "unreachable")
    assert ok is False


# ---- classify ----

def test_classify_error_event_is_failure():
    event = {"kind": "error", "message": "Failed: boom", "detail": {}}
    assert slack_notifier.classify(event) == ("failure", ":red_circle:")


def test_classify_self_heal_start_event():
    event = {"kind": "ai_call", "message": "Calling the AI for a replacement selector for #verify-btn", "detail": {}}
    assert slack_notifier.classify(event) == ("self_heal", ":adhesive_bandage:")


def test_classify_other_ai_call_is_not_notify_worthy():
    event = {"kind": "ai_call", "message": "AI returned the updated script (500 chars)", "detail": {}}
    assert slack_notifier.classify(event) is None


def test_classify_awaiting_approval_event():
    event = {
        "kind": "mechanical", "message": "Waiting for human approval to merge PR #3...",
        "detail": {"awaiting_approval": True, "pr_number": 3, "pr_url": "https://github.com/x/y/pull/3"},
    }
    assert slack_notifier.classify(event) == ("approval", ":raised_hand:")


def test_classify_plain_mechanical_event_is_not_notify_worthy():
    event = {"kind": "mechanical", "message": "Checked out a clean main branch", "detail": {}}
    assert slack_notifier.classify(event) is None


def test_classify_done_and_start_events_are_not_notify_worthy():
    assert slack_notifier.classify({"kind": "done", "message": "Finished", "detail": {}}) is None
    assert slack_notifier.classify({"kind": "start", "message": "Starting", "detail": {}}) is None


def test_classify_handles_missing_detail_key_gracefully():
    event = {"kind": "error", "message": "boom"}  # no "detail" key at all
    assert slack_notifier.classify(event) == ("failure", ":red_circle:")


# ---- format_message ----

def test_format_message_failure_includes_agent_message_and_run_id():
    event = {"agent": "Agent 5", "message": "Failed: pytest crashed", "run_id": "run-123", "detail": {}}
    text = slack_notifier.format_message(event, "failure", ":red_circle:", "http://localhost:8787")
    assert ":red_circle: *Agent 5* - Failed: pytest crashed" in text
    assert "run-123" in text


def test_format_message_approval_includes_pr_url_and_dashboard_link():
    event = {
        "agent": "Agent 3", "message": "Waiting for human approval to merge PR #3...", "run_id": "run-abc",
        "detail": {"awaiting_approval": True, "pr_number": 3, "pr_url": "https://github.com/x/y/pull/3"},
    }
    text = slack_notifier.format_message(event, "approval", ":raised_hand:", "http://localhost:8787")
    assert "https://github.com/x/y/pull/3" in text
    assert "http://localhost:8787" in text


def test_format_message_self_heal_includes_dashboard_link():
    event = {
        "agent": "Agent 5", "message": "Calling the AI for a replacement selector for #verify-btn",
        "run_id": "run-xyz", "detail": {},
    }
    text = slack_notifier.format_message(event, "self_heal", ":adhesive_bandage:", "http://localhost:8787")
    assert "http://localhost:8787" in text


# ---- process_events ----

def test_process_events_only_posts_notify_worthy_events():
    events = [
        {"kind": "start", "message": "Starting", "agent": "Agent 5", "run_id": "r1", "detail": {}},
        {"kind": "error", "message": "Failed: boom", "agent": "Agent 5", "run_id": "r1", "detail": {}},
        {"kind": "mechanical", "message": "Checked out main", "agent": "Agent 5", "run_id": "r1", "detail": {}},
    ]
    posted = []

    def fake_poster(url, text):
        posted.append((url, text))
        return True

    sent = slack_notifier.process_events(events, "http://webhook", "http://dash", poster=fake_poster)

    assert sent == 1
    assert len(posted) == 1
    assert "Failed: boom" in posted[0][1]


def test_process_events_counts_only_successful_posts():
    events = [
        {"kind": "error", "message": "Failed: A", "agent": "Agent 5", "run_id": "r1", "detail": {}},
        {"kind": "error", "message": "Failed: B", "agent": "Agent 5", "run_id": "r1", "detail": {}},
    ]
    sent = slack_notifier.process_events(events, "http://webhook", "http://dash", poster=lambda url, text: False)
    assert sent == 0


# ---- poll_once ----

def test_poll_once_advances_cursor_and_notifies():
    events = [{"kind": "error", "message": "Failed: boom", "agent": "Agent 5", "run_id": "r1", "detail": {}}]

    def fake_query(since_id):
        assert since_id == 10
        return events, 11

    posted = []
    next_id, sent = slack_notifier.poll_once(
        fake_query, since_id=10, webhook_url="http://webhook", dashboard_url="http://dash",
        poster=lambda url, text: posted.append(text) or True,
    )

    assert next_id == 11
    assert sent == 1
    assert len(posted) == 1


def test_poll_once_with_no_new_events_does_not_call_poster():
    def fake_query(since_id):
        return [], since_id

    calls = []
    next_id, sent = slack_notifier.poll_once(
        fake_query, since_id=5, webhook_url="http://webhook", dashboard_url="http://dash",
        poster=lambda url, text: calls.append(1) or True,
    )
    assert next_id == 5
    assert sent == 0
    assert calls == []
