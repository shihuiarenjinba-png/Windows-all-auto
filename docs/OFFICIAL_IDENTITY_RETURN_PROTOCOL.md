# Factory ↔ Windows-all-auto: Partner Center Identity return

## Two-stage build and official ID
1. Factory writes and tests app/game source. A new product without official Store Identity remains HOLD for Store MSIX packaging.
2. Authenticate to Microsoft Partner Center from trusted local browser/worker, reserve the product name and read Store ID, Identity Name and Publisher from its Product identity page.
3. Windows-all-auto accepts a JSON record containing schema_version=1, type=app/game, slug, expected_head_sha, official_evidence_url on partner.microsoft.com, operator_verified=true, verified_by, and identity fields store_id, name, publisher, version.
4. all_auto.identity_route derives the correct target Factory repository and work branch from type and validates the input. No Ollama and no model guess is needed.
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
