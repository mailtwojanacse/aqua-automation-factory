# New Requirement: Verify the install is idempotent (clicking Verify twice doesn't break it)

Testers want confidence that re-running the verification step doesn't cause
duplicate success messages or a broken status if someone accidentally
clicks the button twice.

After the existing checks confirm `#install-status` reads `"Verified"` and
`#result` is visible, click the Verify button a second time and assert that
`#install-status` still reads exactly `"Verified"` (not duplicated or
changed) and `#result` is still visible with the same success text.
