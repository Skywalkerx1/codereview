# Builder response — clean_change.patch v2

1. "No dedup guard" — INVALID. The finding's own evidence line is the
   guard: `if violations and sig != state.get("signature"):`. The
   alert fires only when the current violation set's signature differs
   from the persisted one. An unchanged set produces an identical
   signature, so no email is sent on repeated hourly runs. That is the
   dedup mechanism; a separate 'last_sent' timestamp is unnecessary.

2. "Recovery alert floods: signature never cleared" — INVALID.
   After the recovery branch, the code unconditionally writes the new
   state: `json.dump({"signature": sig}, fh)` via the atomic
   tmp+replace. In the recovery case `violations` is empty, so
   `_alert_signature([])` returns `",".join([])` = `""`. The persisted
   signature is therefore cleared to the empty string, and on the next
   run `state.get("signature")` is falsy, so the recovery mail cannot
   repeat.

The minor about ensuring the state directory exists is accepted as a
follow-up nit (the directory is created by the service's installer in
production); it is not a blocker.
