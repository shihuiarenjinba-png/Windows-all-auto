# Data Contract Auditor Partner Center read-only observation

Observed 2026-11-28 in the already-authenticated local Edge session. Navigation started at Apps and games Overview, where **Data Contract Auditor** linked to Product ID `9PDL4ZWSB45P`; the existing submission link resolved to Draft ID `1152921505702212222`. No form control was edited, no file was selected, and no Save button was pressed.

## Overview

- Product page shows `In draft`; Submission 1 shows `Product submission: In draft` (last modified 11/23/2026).
- Overview status: Pricing and availability `Not started`; Properties `Not started`; Age ratings `Not started`; Packages `Incomplete`; Store listings `Not started`; Submission Options `Recommended`.
- The overview displayed `Submit for certification` disabled. No certification submission or publishing action occurred.

## Section observations

| Section | Live read | Current state / required items | Write status |
| --- | --- | --- | --- |
| Properties | Required category, optional secondary category, required privacy answer; support URLs/contact/address; product declarations; hardware requirements. Save control present. | Category is `Pick a category`; subcategory `None`; required personal-information answer is `Choose an answer to see corresponding actions`. Current values for product declarations are not exposed reliably in the accessibility tree. | Read only; no write/reload test. |
| Store listings | Manage Store listing languages view; package-supported and additional language grids. | No languages are shown until packages are uploaded. Additional-language management and Save are disabled. No listing text/image editor is available in this state. | Read only; no write/reload test. |
| Pricing and availability | Market scope, future-market choice, audience, discoverability, schedule, base-price/market groups, free trial, sale pricing and organizational licensing. | `No PriceSchedule created for purchasable product` and `You must configure a price`. All worldwide markets selected; future-market availability checked; public audience and Store discoverability selected; release `as soon as possible`; stop acquisition `never`; 240 markets; no base price. Save draft disabled. | Read only; no write/reload test. |
| Age ratings | IARC questionnaire or existing IARC Certificate/GRID path; App Type and external ratings/physical media question visible. | IARC questionnaire route is selected. App types include Game, Social or Communication, and All Other App Types. The questionnaire is incomplete. | Read only; no questionnaire answers changed or saved. |
| Submission Options | Publishing hold choices: publish after certification/schedule, manual “Publish now”, or specific date/time; certification notes link and notification audience link. | Time shown `7:00 AM UTC`; date field shows 11/28/2026 but is disabled. The selected radio value was not exposed and is not inferred. Save disabled. | Read only; no write/reload test. |
| Packages | Single package file input; package validation area; device-family availability controls and Save. | 0 package rows; message `You must upload at least one package`. Desktop, Mobile, Xbox, Team, Mixed Reality checkboxes were unchecked; `Let Microsoft decide whether to make this app available to any future device families` was checked. Microsoft explains this delegates future device-family availability to Microsoft. No package-level server SHA is displayed. | Read only; no file selection, checkbox change, or Save. |

The map records observed field names and values but deliberately leaves every section `verified: false`. A live read is not evidence that its write selector, Save, reload, or reconciliation behavior works.

## Reusable evidence

- UI map: `uploader/config/store_ui_maps/msix_pwa_app.v1.json`.
- The map is a route/selector teacher input. `live_read_observation` must not be treated as write authorization.
- `store run` writes a separate, unique owner-decision report under the run output. Approved values remain product-profile scoped; they are reused only after a Product/Draft/section-scoped approval record is present.
