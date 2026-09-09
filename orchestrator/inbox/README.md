# Inbox

Drop things here and `auto_trigger.py` picks them up on its next poll - no
manual command needed.

- **`jobs/<job_name>/`** - a subfolder per Baramundi job, containing its
  `.bds` file, an XML/JSON config file with `config` in its name, and a job
  file with `job` in its name (matching the existing sample folders'
  naming, e.g. `Install_7zip.bds` / `Install_7zip_config.xml` /
  `Install_7zip_job.json`). Triggers Agent 1 then Agent 2.

- **`requirements/*.md`** - a new or changed requirement. Triggers Agent 3
  (adapts the default target script and opens a PR) then Agent 4 (reviews
  it). Merging is still a human decision - nothing here merges anything.

Already-processed jobs/requirements are tracked in `.auto_trigger_state.json`
(next to `auto_trigger.py`) so unchanged files aren't re-run on every poll.
Touching a file's contents (which updates its modified time) makes it
eligible to be picked up again.
