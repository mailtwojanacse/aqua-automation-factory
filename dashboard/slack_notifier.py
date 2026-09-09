"""Posts pipeline events to Slack via an incoming webhook - a run failing,
self-heal kicking in, or the human-approval gate waiting on you - so you
don't have to keep the dashboard open to notice.

No OAuth, no Slack app to build: create an Incoming Webhook in your Slack
workspace (Slack -> Apps -> Incoming Webhooks -> Add to Slack -> pick a
channel) and put the URL it gives you in SLACK_WEBHOOK_URL. Unset (the
default), nothing is sent - the pipeline behaves exactly as before.

server.py owns the polling loop (it already holds the one connection to
events.db); everything here is pure/testable without a real Slack
workspace or a real database.
"""
import json
import urllib.error
import urllib.request

# The exact message self_healer.py emits right as it starts a self-heal
# attempt (agent5_execution_selfheal/src/self_healer.py) - matched as a
# prefix since the broken selector is appended after it.
SELF_HEAL_START_PREFIX = "Calling the AI for a replacement selector for"


def classify(event):
    """Return (category, emoji) if this event is worth a Slack ping, else
    None. Matches exactly the three cases asked for: a run failing, self-
    heal kicking in, and the human-approval gate waiting on a decision."""
    kind = event.get("kind")
    message = event.get("message") or ""
    detail = event.get("detail") or {}

    if kind == "error":
        return ("failure", ":red_circle:")
    if kind == "ai_call" and message.startswith(SELF_HEAL_START_PREFIX):
        return ("self_heal", ":adhesive_bandage:")
    if detail.get("awaiting_approval"):
        return ("approval", ":raised_hand:")
    return None


def format_message(event, category, emoji, dashboard_url):
    agent = event.get("agent", "?")
    message = event.get("message", "")
    run_id = event.get("run_id", "?")
    detail = event.get("detail") or {}

    lines = [f"{emoji} *{agent}* - {message}"]
    if category == "approval":
        pr_url = detail.get("pr_url")
        if pr_url:
            lines.append(f"PR: {pr_url}")
        lines.append(f"Approve or reject from the dashboard: {dashboard_url}")
    elif category == "self_heal":
        lines.append(f"Watch it verify the fix: {dashboard_url}")
    lines.append(f"_run {run_id}_")
    return "\n".join(lines)


def post_to_slack(webhook_url, text, timeout=10):
    """Best-effort POST to the webhook; returns True on a 2xx response,
    False otherwise. Never raises - a Slack/network hiccup must not be able
    to take the dashboard or a pipeline run down."""
    body = json.dumps({"text": text}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url, data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def process_events(events, webhook_url, dashboard_url, poster=post_to_slack):
    """Notify for every notify-worthy event in `events`, in order. `poster`
    is injectable so tests can verify classification/formatting without a
    real network call. Returns the count actually posted."""
    sent = 0
    for event in events:
        match = classify(event)
        if match is None:
            continue
        category, emoji = match
        text = format_message(event, category, emoji, dashboard_url)
        if poster(webhook_url, text):
            sent += 1
    return sent


def poll_once(query_events_since, since_id, webhook_url, dashboard_url, poster=post_to_slack):
    """One polling tick: fetch events newer than since_id, notify for any
    that qualify, return the new cursor. Kept separate from the sleep loop
    (which lives in server.py) so it's testable without real time passing."""
    events, next_id = query_events_since(since_id)
    sent = process_events(events, webhook_url, dashboard_url, poster=poster)
    return next_id, sent
