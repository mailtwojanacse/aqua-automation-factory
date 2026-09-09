# Live Pipeline Dashboard

Serves the dashboard page (`index.html`), the durable event audit trail
(`events.db`), Run/Approve/Reject controls, and the generated Allure and
Requirement Traceability reports - all from one stdlib-only server, no
extra install needed.

```
http://localhost:8787/
```

## Running it as a persistent service (recommended)

The server is a plain Python process - it does not survive a terminal
close, session restart, or reboot on its own. Rather than restart it by
hand every time, run it as a `systemd --user` service so it starts
automatically and restarts itself if it ever crashes:

```bash
mkdir -p ~/.config/systemd/user
cp aqua-dashboard.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now aqua-dashboard.service
```

`aqua-dashboard.service` hardcodes this machine's paths (`ExecStart`,
`WorkingDirectory`) - update both to match wherever this repo actually
lives before copying it in (e.g. once this moves onto the client's VM).

Useful commands:

```bash
systemctl --user status aqua-dashboard.service     # is it running?
systemctl --user restart aqua-dashboard.service    # picked up a server.py change
journalctl --user -u aqua-dashboard.service -f     # tail its output
```

This machine also has lingering enabled for this user
(`loginctl enable-linger`), so the service keeps running even when nothing
is logged in - not just across terminal restarts, but across logout too.

## Slack alerts

Optional. Posts to a Slack channel automatically for the three things
worth interrupting you for: a run failing, self-heal kicking in, and the
human-approval gate waiting on a decision - so you don't have to keep the
dashboard open to notice them.

No Slack app to build, no OAuth: in Slack, go to **Apps -> Incoming
Webhooks -> Add to Slack**, pick a channel, and copy the webhook URL it
gives you. Then set `SLACK_WEBHOOK_URL` to that URL wherever the server
runs:

```bash
# Direct run
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..." python3 server.py
```

```ini
# systemd-managed run: add this line under [Service] in
# ~/.config/systemd/user/aqua-dashboard.service, then:
#   systemctl --user daemon-reload && systemctl --user restart aqua-dashboard.service
Environment=SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

Unset (the default), nothing is sent and the pipeline behaves exactly as
before - startup just logs "Slack alerts disabled." When set, it starts
watching from whatever event is newest at startup, so turning this on
doesn't replay the entire event history as a wall of Slack messages.

Polls `events.db` every 3 seconds (`slack_notifier.py`'s `classify()`
decides what's notify-worthy) - independent of whether the dashboard tab
is open, since every code path (CLI, dashboard Run button, auto-trigger)
already writes to the same shared `events.db`.

## Running it directly (for quick local edits)

```bash
python3 server.py
```

Useful while iterating on `server.py` itself; stop the systemd-managed
instance first (`systemctl --user stop aqua-dashboard.service`) so the two
don't fight over port 8787.
