# New Requirement: Reloading the page resets the status

Testers want to confirm that reloading the install-verification page after a
successful verification does not "remember" the verified state - since the
real check should always run fresh, not rely on stale UI state.

After confirming `#install-status` reads `"Verified"`, reload the page and
assert that `#install-status` reads `"Not Verified"` again.
