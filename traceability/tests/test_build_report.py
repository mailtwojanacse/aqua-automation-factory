import json

import build_report


# ---- _latest_test_results ----

def test_latest_test_results_picks_the_newest_stop_and_carries_history_id(tmp_path):
    (tmp_path / "a-result.json").write_text(json.dumps({
        "fullName": "tests.test_x#test_one", "status": "failed", "stop": 100, "historyId": "abc123",
    }), encoding="utf-8")
    (tmp_path / "b-result.json").write_text(json.dumps({
        "fullName": "tests.test_x#test_one", "status": "passed", "stop": 200, "historyId": "abc123",
    }), encoding="utf-8")

    results = build_report._latest_test_results(tmp_path)

    assert results["tests.test_x#test_one"] == {"status": "passed", "stop": 200, "history_id": "abc123"}


def test_latest_test_results_empty_dir_returns_empty_dict(tmp_path):
    assert build_report._latest_test_results(tmp_path / "does-not-exist") == {}


# ---- _load_history ----

def test_load_history_returns_empty_dict_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(build_report, "ALLURE_HISTORY_PATH", tmp_path / "missing.json")
    assert build_report._load_history() == {}


def test_load_history_returns_empty_dict_on_malformed_json(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    path.write_text("not valid json{{{", encoding="utf-8")
    monkeypatch.setattr(build_report, "ALLURE_HISTORY_PATH", path)
    assert build_report._load_history() == {}


def test_load_history_parses_a_real_file(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"abc123": {"statistic": {"passed": 1}, "items": []}}), encoding="utf-8")
    monkeypatch.setattr(build_report, "ALLURE_HISTORY_PATH", path)
    assert build_report._load_history() == {"abc123": {"statistic": {"passed": 1}, "items": []}}


# ---- _trend_for ----

def _item(status, start):
    return {"status": status, "time": {"start": start}}


def test_trend_for_missing_history_id_returns_empty_list():
    assert build_report._trend_for(None, {"abc": {"items": []}}) == []
    assert build_report._trend_for("not-present", {"abc": {"items": []}}) == []


def test_trend_for_reverses_most_recent_first_items_to_chronological_order():
    # Allure lists items most-recent-first; the trend should read oldest -> newest.
    history_data = {
        "abc": {"items": [_item("passed", 300), _item("failed", 200), _item("passed", 100)]},
    }
    trend = build_report._trend_for("abc", history_data)
    assert [t["status"] for t in trend] == ["passed", "failed", "passed"]
    assert [t["start"] for t in trend] == [100, 200, 300]


def test_trend_for_respects_the_limit():
    history_data = {"abc": {"items": [_item("passed", i) for i in range(20)]}}
    trend = build_report._trend_for("abc", history_data, limit=5)
    assert len(trend) == 5


# ---- _trend_cell / _status_pill rendering ----

def test_trend_cell_with_no_history_shows_placeholder_not_a_broken_ratio():
    html = build_report._trend_cell([], None)
    assert "not enough history" in html
    assert "/0" not in html  # would render as a nonsensical "0/0" without this guard


def test_trend_cell_renders_one_dot_per_run_and_the_pass_rate_text():
    trend = [{"status": "passed", "start": 1}, {"status": "failed", "start": 2}, {"status": "passed", "start": 3}]
    html = build_report._trend_cell(trend, "2/3")
    assert html.count('class="dot pass"') == 2
    assert html.count('class="dot fail"') == 1
    assert "2/3 last 3 runs" in html
