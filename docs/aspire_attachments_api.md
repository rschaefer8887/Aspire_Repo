# Aspire Attachments API — probe notes

Reference for attaching invoice PDFs to purchase receipts after `POST /Receipts`.
Last probed: **2026-06-08** against receipt **1314-INV** (ReceiptID **1214**, MD- 1219).

Raw machine-readable output: [`attachment_probe_results.json`](attachment_probe_results.json)  
Swagger snapshot: [`../exports/swagger.json`](../exports/swagger.json)  
Re-run probes: `py scripts/probe_attachments.py 1314-INV`

---

## Receipt lookup (test case)

| Field | Value | Notes |
|-------|-------|-------|
| **VendorInvoiceNum** | `1314-INV` | Best lookup key for scripts |
| **ReceiptID** | `1214` | Numeric API id used for attach |
| **ReceiptNumber** | `1219` | Display number (not API id) |
| **PurchaseNumberWithBranchPrefix** | `MD- 1219` | Branch purchase # (space after `MD-`) |

```http
GET /Receipts?$filter=VendorInvoiceNum eq '1314-INV'&$top=5
```

`ObjectID` / `ParentID` are **not** valid fields on `/Attachments` OData model.

---

## API permissions (Aspire admin)

| Endpoint | Status after enabling Attachments |
|----------|-----------------------------------|
| `GET /Attachments` | **200** — works |
| `POST /Attachments` | **200** — works with full body |
| `GET /Attachments/AttachmentFileData` | **200** — works (see below) |
| `GET /Attachments/NewLink` | **500** — server error on all `link` values tried |
| `GET /AttachmentTypes` | **200** — use type **20** (`Vendor Invoice`) for invoice PDFs |

Before permissions were enabled, all attachment calls returned **403 Forbidden**.

---

## Endpoints (correct paths from Swagger)

Swagger lists these paths (case-sensitive):

| UI label (Aspire admin) | Actual path |
|-------------------------|-------------|
| Attachments GET/POST | `/Attachments` |
| NEWLink GET | `/Attachments/NewLink` |
| AttachFileData GET | `/Attachments/AttachmentFileData` |

Wrong paths that return 404: `/Attachments/NEWLink`, `/Attachments/AttachFileData`.

---

## GET `/Attachments` — list metadata

Filter purchase-receipt attachments:

```http
GET /Attachments?$filter=ReceiptID eq 1214&$top=10
```

Example attachment on **1314-INV** (UI-uploaded PDF):

```json
{
  "AttachmentID": 11390,
  "AttachmentTypeID": 10,
  "AttachmentTypeName": "Client Executed Signed",
  "AttachmentName": "11390.pdf",
  "FileExtension": ".pdf",
  "OriginalFileName": "Aspire - Cedron Sod 1314__06042026.pdf",
  "ReceiptID": 1214,
  "ReceiptNumber": 1219,
  "DateUploaded": "2026-06-05T17:01:43.907Z",
  "ExposeToCrew": false,
  "AttachToInvoice": false
}
```

Aspire stores files as `{AttachmentID}.pdf` internally; `OriginalFileName` preserves the user-facing name.

---

## POST `/Attachments` — upload (single-step)

**This is the upload path.** One JSON POST with base64 file bytes; no separate multipart step confirmed.

### Request body (`AttachmentUploadRequest`)

| Field | Required | Example / notes |
|-------|----------|-----------------|
| `FileName` | yes | `Idaho_Sod_1314-INV.pdf` (display name) |
| `FileData` | yes | Base64-encoded PDF bytes |
| `ObjectCode` | yes | `"Receipt"` (PascalCase; `RECEIPT` rejected) |
| `AttachmentTypeId` | yes | `10` on test receipt ("Client Executed Signed") |
| `ObjectId` | effectively yes | ReceiptID, e.g. `1214` |
| `AttachToInvoice` | no | `false` |
| `ExposeToCrew` | no | optional |

### Validation errors observed

- Missing `FileData`: `["The FileData field is required."]`
- Missing `ObjectId` / `ObjectCode`: `["ObjectId is required.","ObjectCode is required."]`
- Invalid `ObjectCode`: `"ObjectCode is invalid: RECEIPT"` (uppercase fails)

### Successful probe (2026-06-08)

```json
POST /Attachments
{
  "ObjectId": 1214,
  "ObjectCode": "Receipt",
  "FileName": "probe-test.pdf",
  "AttachmentTypeId": 10,
  "FileData": "<base64>"
}
```

**Response (200):** URL string (hosted file location), not AttachmentID:

```
https://aspire-cloudprod-main.youraspire.com/AspireUploads/1460/<uuid>.pdf
```

After POST, a new row appeared on the receipt:

- `AttachmentID`: 11597
- `OriginalFileName`: `probe-test.pdf`

**Cleanup:** Delete `probe-test.pdf` (AttachmentID **11597**) from receipt 1214 in Aspire UI if still present.

---

## GET `/Attachments/AttachmentFileData` — download

Returns a **single object** (not an OData list). Do **not** pass `$top`, `$skip`, etc.

```http
GET /Attachments/AttachmentFileData?$filter=AttachmentID eq 11390
```

Example response (FileData truncated):

```json
{
  "AttachmentID": 11390,
  "FileName": "Aspire - Cedron Sod 1314__06042026.pdf",
  "FileData": "<base64 ~282 KB>",
  "ObjectId": 1214,
  "ObjectCode": "RECEIPT",
  "AttachmentTypeID": 10,
  "AttachToInvoice": false
}
```

Note: download payload uses `ObjectCode: "RECEIPT"` while POST accepts `"Receipt"`.

---

## GET `/Attachments/NewLink` — not usable yet

Swagger: optional query param `link` (string); response is a string (likely SAS URL).

All probes returned **HTTP 500 Internal Server Error**. Treat as **not required** for upload until Aspire support clarifies; `POST /Attachments` with `FileData` already works.

---

## Implemented pipeline integration

```text
process_invoices.py
  → Excel: Receipts - Ready/{Vendor}_{Invoice-INV}.xlsx
  → PDF:   Invoices - Processed/Complete/Aspire-{Invoice-INV}__{MMDDYYYY}.pdf

import_purchase_receipt.py
  → POST /Receipts
  → Prompt Y/N (or --yes-attach)
  → POST /Attachments (aspire_attachments.py)
```

**AttachmentTypeId:** `20` (`Vendor Invoice`), overridable via `ASPIRE_ATTACHMENT_TYPE_ID`.

**PDF naming:** `Aspire-{Vendor}-{VendorInvoiceNum}__{MMDDYYYY}.pdf` (e.g. `Aspire-HD Fowler-I7331698-INV__06042026.pdf`).

**Idempotency:** Skips upload if `OriginalFileName` already exists on the receipt.

### Still open

1. **NewLink** — returns 500; not needed while `POST /Attachments` accepts base64 `FileData`.
2. **Attach on duplicate skip** — import only attaches after a new `POST /Receipts` create.

---

## Helper scripts

| Script | Purpose |
|--------|---------|
| `scripts/probe_attachments.py [VendorInvoiceNum]` | Full probe; writes `docs/attachment_probe_results.json` |
| `scripts/probe_attachments.py 1314-INV --try-upload` | Includes tiny PDF upload test (creates attachment) |
| `scripts/probe_attachment_filedata.py [ReceiptID] [AttachmentID]` | List receipt attachments + download FileData metadata |
