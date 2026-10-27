# Factory ↔ Windows-all-auto: Partner Center Identity return

## Two-stage build and official ID
1. Factory writes and tests app/game source. A new product without official Store Identity remains HOLD for Store MSIX packaging.
2. Authenticate to Microsoft Partner Center from trusted local browser/worker, reserve the product name and read Store ID, Identity Name and Publisher from its Product identity page.
3. Windows-all-auto accepts a JSON record containing schema_version=1, request_id, type=app/game/3d-game, product_type, source_factory, source_repository, source_branch, source_sha, slug, expected_head_sha, package_sha256, signature_status, collected PFN/Package SID, official_evidence_url on partner.microsoft.com, operator_verified=true, verified_by, and official identity fields store_id, name, publisher, version, PFN and Package SID.
4. all_auto.identity_route derives the fixed Factory repository from the lane, validates the exact request/provenance/package fields, and preserves the validated job `source_branch`. Only safe `codex/*` work branches are accepted; main/release and cross-lane destinations are rejected. No Ollama and no model guess is needed.
5. all_auto.identity_commit checks that the exact Factory branch SHA and product manifest match. Its --apply option uses authenticated gh CLI and GitHub GraphQL createCommitOnBranch with expectedHeadOid. Conflicts stop, existing approved identity is never overwritten.
6. Saving products/<slug>/store/approved-identity.json on the Factory work branch triggers Windows Actions msix-export.yml, provided real executable source and approved PNG assets are present.
7. Factory exports MSIX and provenance as an Actions Artifact, Windows-all-auto receives and verifies it, and the local QA worker fetches it without duplicating packages.

## Windows usage (in an authenticated local checkout of Windows-all-auto)
Generate a proposal first: python -m all_auto.identity_route --input identity-from-partner-center.json --output proposed-return.json
Dry run: python -m all_auto.identity_commit --input identity-from-partner-center.json
Only after verifying actual Microsoft account evidence: python -m all_auto.identity_commit --input identity-from-partner-center.json --apply

## Strict limitations
- The JSON operator_verified marker is an operator attestation, not cryptographic proof of Microsoft account identity. The local authenticated worker must truly verify Partner Center values.
- GH CLI credentials with contents:write access to the appropriate Factory are required for --apply, but no OpenAI API key is required.
- Do not store authentication cookies, access tokens, passwords or account credentials in GitHub.
- No published identity can be guessed from an arbitrary MSIX, and Package Family Name or SID are not replacements for a newly issued Store ID.
- Store price, privacy/security declarations, signing, MSIXUPLOAD, device tests, WACK, certification and publication remain independently gated.
- Contract and mock tests do not prove a real Partner Center identity retrieval or a complete Factory-to-local MSIX E2E run.

## 3D-specific status
- Verified Identity can now be **routed and conditionally committed** to shihuiarenjinba-png/3d-game-factory on the same validated `codex/*` branch supplied by its Factory job. Set type=3d-game and product_type=GAME_3D in the internal identity_route/identity_commit contract.
- This only returns official Identity JSON. The 3D Godot Windows export, a Store-appropriate MSIX manifest, real GPU/Windows UI testing and Factory-to-Windows-all-auto MSIX Artifact transfer are **not yet implemented or verified**. Those stages stay HOLD, even if the Identity JSON write passes.
- Never fabricate a new Store ID from PFN/SID/Package Identity or copy another product's Store registration.

## Current verification status (2026-10-27)

- Windows-all-auto integrated 2D/3D full unit suite: 188 tests, 186 PASS, 0 FAIL, 2 SKIP. The two skips are Windows symlink-permission dependent and are not live E2E evidence.
- The three Provisioners share byte-semantically identical versioned job/result schemas and their combined offline suite is 219 tests, 216 PASS, 0 FAIL, 3 SKIP.
- Signal Sprint (`AI-Game-Factory@c058cbf7fe38e02d929c67d047d717ff74bd522e`) was downloaded from the pinned Factory Artifact, its archive/provenance checked, DRY_RUN completed, and a real local unsigned PE EXE rebuilt and inspected. Local result is correctly `HOLD / OBTAIN_AUTHENTICATED_OFFICIAL_IDENTITY`.
- No Partner Center official identity was acquired, no Factory identity file was written, no Store MSIX was regenerated, no Windows-all-auto MSIX receipt exists, and no Store submission was attempted. Overall E2E remains HOLD.
