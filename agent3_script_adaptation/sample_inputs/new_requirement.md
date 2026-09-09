# New Requirement: Assert starting state before verifying

Testers reported a false-positive risk: if the page is reloaded after a
previous verification, `#install-status` can already read "Verified"
*before* the test clicks the button — so a broken Verify button would
still make the test "pass".

Add an explicit assertion at the start of `test_install_verification`,
right after the page loads and before clicking Verify, that
`#install-status` currently reads "Not Verified". This guarantees the test
is actually exercising the click, not just checking pre-existing state.
