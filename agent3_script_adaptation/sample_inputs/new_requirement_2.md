# New Requirement: Assert the exact success message text

The current test only checks that `#result` is *visible*, not what it
actually says. If a future content change silently altered or blanked the
success message, the test would still pass.

Add an assertion right after the existing visibility check that `#result`'s
text is exactly `"Installation verified successfully."`.
