# Channel Manager

Admin-only dashboard provision for adding YouTube channels manually.

Required flow:
1. Paste a YouTube channel URL.
2. Resolve and validate the channel ID server-side using the configured YouTube integration.
3. Preview resolved channel name/network/language/region.
4. Admin confirms activation.
5. Persist the channel in the existing Channel registry; do not require source-code changes.
6. Duplicate channel IDs must be rejected safely.
7. Existing collector discovery must pick up the new active channel automatically.

The UI must never accept a client-supplied channel ID as authoritative. The URL is input; server-side resolution is authoritative.

This first surface is intentionally a safe shell until the authenticated admin mutation endpoint is wired to the repository's existing auth/session contract.
