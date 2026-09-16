import io
from unittest import mock

import server

# ---- Handler._read_json_body: found during a bug-hunt review - only
# json.JSONDecodeError was caught, so a bad Content-Length header, a
# non-UTF-8 body, or valid-but-non-object JSON (e.g. `5`, `[]`, `null`) all
# crashed the request handler uncaught instead of falling into the same {}
# sentinel "no body sent" already uses - which /run and /run_agent5's
# existing field validation (mode must be 'dry-run' or 'real', etc.)
# already turns into a clean 400.


def _make_handler(content_length, body_bytes):
    handler = server.Handler.__new__(server.Handler)
    handler.headers = {} if content_length is None else {"Content-Length": content_length}
    handler.rfile = io.BytesIO(body_bytes)
    return handler


def test_read_json_body_returns_empty_dict_for_no_body():
    assert _make_handler(None, b"")._read_json_body() == {}


def test_read_json_body_parses_a_normal_object():
    body = b'{"mode": "dry-run"}'
    assert _make_handler(str(len(body)), body)._read_json_body() == {"mode": "dry-run"}


def test_read_json_body_returns_empty_dict_for_invalid_content_length():
    assert _make_handler("not-a-number", b"")._read_json_body() == {}


def test_read_json_body_returns_empty_dict_for_non_utf8_bytes():
    body = b"\xff\xfe\x00\x01"
    assert _make_handler(str(len(body)), body)._read_json_body() == {}


def test_read_json_body_returns_empty_dict_for_non_object_json():
    for payload in (b"5", b"[]", b"null", b'"just a string"'):
        assert _make_handler(str(len(payload)), payload)._read_json_body() == {}, payload


# ---- _terminate_in_flight_run: found during a bug-hunt review - a run in
# flight when the dashboard is shut down (e.g. Ctrl-C) used to be left
# running, orphaned against the shared automation_target checkout, with a
# restarted dashboard's fresh RUN_STATE having no idea it exists.

def test_terminate_in_flight_run_does_nothing_when_no_run_is_active():
    server.RUN_STATE["proc"] = None
    server._terminate_in_flight_run()  # must not raise


def test_terminate_in_flight_run_does_nothing_for_an_already_finished_process():
    mock_proc = mock.Mock()
    mock_proc.poll.return_value = 0  # already exited
    server.RUN_STATE["proc"] = mock_proc

    server._terminate_in_flight_run()

    mock_proc.terminate.assert_not_called()


def test_terminate_in_flight_run_terminates_a_still_running_process():
    mock_proc = mock.Mock()
    mock_proc.poll.return_value = None  # still running
    server.RUN_STATE["proc"] = mock_proc

    server._terminate_in_flight_run()

    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()


def test_terminate_in_flight_run_kills_if_terminate_does_not_stop_it_in_time():
    mock_proc = mock.Mock()
    mock_proc.poll.return_value = None
    mock_proc.wait.side_effect = server.subprocess.TimeoutExpired(cmd="x", timeout=5)
    server.RUN_STATE["proc"] = mock_proc

    server._terminate_in_flight_run()

    mock_proc.kill.assert_called_once()
