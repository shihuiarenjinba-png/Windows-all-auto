# User-provided Store / GDK identity registry

This branch records non-secret Microsoft Store identifiers explicitly supplied by the user.

## Signal Sprint
- Product type: GAME
- Packaging family: GDK
- Store ID: 9N21MJM7S57P
- Package Identity Name: OkinawaDesktopTools.SignalSprint
- Publisher: CN=46263F21-A700-41DB-8C9B-114C22FB82FC
- Publisher display name: Okinawa Desktop Tools
- PFN: OkinawaDesktopTools.SignalSprint_j8yefg9jgfh58
- Package SID: S-1-15-2-1437967488-3265478925-1925977903-994526844-2895000717-1943620661-378024715
- Xbox Title ID: 68721417
- SCID: 00000000-0000-0000-0000-000068721417
- MSA App ID: 39852fc3-fa46-4bda-88aa-b35385488ced

The scheduler materializes these values into the existing local secure Identity path only when the pinned request_id/source_sha/repository/branch still match. It does not acquire Identity from Partner Center and does not store cookies, tokens, sessions, passwords, PFX/private keys or authenticated HTML.

Package Version is intentionally not part of this Identity snapshot. GDK package versioning remains a later build/release gate.

## Offline Notes Canary
The Store Identity is recorded in `ops/user_provided_store_identities.json`, but the APP source_sha/request_id are not yet fixed. The scheduler must not bind or CAS this Identity until Factory promote and exact APP source binding are complete.

No Store submission is performed by this branch.
