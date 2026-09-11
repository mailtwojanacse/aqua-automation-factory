import io

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
