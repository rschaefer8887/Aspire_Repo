# Aspire Purchase Receipt Importer + Invoice IDP

Two-step workflow:

1. **IDP** — PDF invoices → Excel workbooks (`process_invoices.py`)
2. **Human review** — `Receipts - Ready/review_dashboard.txt`
3. **Aspire import** — Excel → purchase receipts (`import_purchase_receipt.py`)

## Folder layout

```
Receipts - Ready/
  PR Template.xlsx          # Template (excluded from import scan)
  review_dashboard.txt      # Low-confidence extractions for review
  *.xlsx                    # Generated import files (one receipt each)
  Invoices - Ready/         # Drop PDF invoices here
  Invoices - Processed/
    Complete/               # PDFs after IDP (default processed folder)
exports/
  vendors.csv               # Vendor list for IDP matching
  catalog_items.csv         # Catalog for IDP (A–F: ID, Code, Name, AlternateName, Type, Active)
```

## Excel layout (`Invoice_Import` sheet)

| Cell / range | Field |
|--------------|--------|
| **B1** | Invoice date |
| **B2** | Vendor (exact Aspire vendor name) |
| **B3** | Branch (default from `ASPIRE_DEFAULT_BRANCH`) |
| **B4** | *(ignored)* |
| **B5** | Invoice number (IDP appends `-INV`) |
| **B6** | Receipt note (Idaho Sod variance / manual split instructions) |
| **B10+** | Item code (optional if C has name) |
| **C10+** | Item name |
| **D10+** | Quantity |
| **E10+** | Unit cost (vendor profile may apply tax, 3 decimal places) |
| **F6** | Column heading: Total Cost |
| **F10+** | Line total (= D × E); Fowler profile nudges E so ΣF matches invoice grand total |

### Vendor profiles (`idp_vendor_profiles.py`)

Per-vendor rules for tax and total reconciliation. **`process_invoices.py`** stays generic; profiles are selected from the matched Aspire vendor name.

| Profile | Vendor | Tax on unit cost | Reconcile ΣF to invoice total | Skip import consolidation |
|---------|--------|------------------|-------------------------------|---------------------------|
| `hd_fowler` | H.D. Fowler Company {Turf} (and names containing “fowler”) | ×1.06 | Yes | No |

**HD Fowler freight:** `INBOUND FRT / BILLABLE` lines are not imported as catalog items. Taxed freight (×1.06) is summed and added **per material unit** to each line’s unit cost (total freight ÷ total material quantity).
| `idaho_sod` | Idaho Sod (Vendor 136) | None (×1.0) | Yes | No |
| `cedron_sod` | Cedron Sod | None (×1.0) | Yes | No |
| `default` | Everyone else | None (×1.0) | No | No |

**Idaho Sod:** Invoices use **Total Due** ÷ **square feet** for unit cost (delivery, pallet deposit, and fuel surcharge are included in Total Due, not separate Aspire lines). Kentucky → Bluegrass Sod; RTF → Rhizomatous Tall Fescue Sod. IDP writes **one import line**; when 3 decimals cannot match Total Due exactly, **B6** documents the variance and a manual two-line split for Aspire UI. Import sends B6 as `ReceiptNote`.

**Cedron Sod:** Invoices use the **bottom-left invoice total** ÷ **total sod square feet** when there is a **single grass type** (pallet credit, pallet charge, and tax are included in the total, not separate Aspire lines). Multiple grass types are left for review. Same B6 variance / `ReceiptNote` behavior as Idaho Sod.

Catalog matching treats **tee, elbow, coupler, adapter, plug** as product families with strict size rules.

Add vendors by extending `HD_FOWLER_PROFILE` / `DEFAULT_PROFILE` or calling `register_vendor_profile()` in `idp_vendor_profiles.py`.

**HD Fowler Turf vs Waterworks:** IDP always maps Fowler invoices to `H.D. Fowler Company {Turf}` (override with `IDP_HD_FOWLER_VENDOR_NAME`). Waterworks is omitted from the OpenAI vendor list and remapped on import if Excel still has the wrong Fowler variant.

## Setup

```powershell
cd "c:\Users\ryanc\OneDrive\repos\Aspire Project"
copy .env.example .env
# Edit .env: ASPIRE_CLIENT_ID, ASPIRE_SECRET, OPENAI_API_KEY

py -m pip install -r requirements.txt
py scripts/ensure_pr_template.py
```

Refresh exports from Aspire before IDP (recommended when new catalog items are added):

```powershell
py scripts/export_reference_data.py --out exports
```

## 1) Process PDF invoices (IDP)

Place PDFs in `Receipts - Ready\Invoices - Ready\`.

```powershell
py scripts/process_invoices.py --fresh-dashboard
py scripts/process_invoices.py --no-catalog-prompt --no-dashboard path/to/invoice.pdf
# Model: interactive 1/2/3 prompt, or --model 2, or --no-model-prompt to use OPENAI_MODEL from .env
# Extraction audit JSON saved to Receipts - Ready/review/JSONs (use --no-extraction-json to skip)
```

- Uses OpenAI vision + structured JSON (`exports/vendors.csv`, `exports/catalog_items.csv`).
- Writes `{Vendor}_{Invoice-INV}.xlsx` into `Receipts - Ready\`.
- Moves PDFs to `Invoices - Processed\Complete\`.
- **HD Fowler only:** appends each matched line to `exports/HD Fowler Item Match Log.xlsx` (auto path, or on Streamlit approve after review). Uses **xlwings** so your Excel formatting is preserved; Microsoft Excel must be installed and the log file should be closed while IDP runs.
- Backfill archived Fowler PDFs: `py scripts/backfill_fowler_match_log.py` (no Aspire import).

## 2) Review dashboard

Open `Receipts - Ready\review_dashboard.txt` and fix any low-confidence vendor/line matches in the generated `.xlsx` before importing.

## 3) Import to Aspire

```powershell
py scripts/import_purchase_receipt.py --dry-run
py scripts/import_purchase_receipt.py
```

- Skips `*Template*.xlsx` and `*-imported.xlsx` files.
- After a successful import, renames the workbook to `{name}-imported.xlsx`.
- Resolves catalog items by **item code (B)** first, then **item name (C)** if code is empty.
- **MD Internal Vendor (347):** prompts to refresh `exports/catalog_items.csv` from Aspire before matching (`--yes-refresh-catalog` / `--no-refresh-catalog` / `--no-catalog-prompt` to control).
- Creates receipts only (`POST /Receipts`) — does not approve or receive.
- After each successful create, prompts **Y/N** to upload the matching PDF from `Invoices - Processed\Complete` (`--yes-attach` / `--no-attach` skip the prompt). PDFs are named `Aspire-{Vendor}-{Invoice-INV}__{MMDDYYYY}.pdf` (e.g. `Aspire-HD Fowler-I7331698-INV__06042026.pdf`).
- Optionally prompts **Y/N** to mark the receipt **received** via `POST /Receipts/Receive` (`--yes-receive` / `--no-receive` skip the prompt). Receive date is set by Aspire to today when you run import (not approved).
- **Bulk import** (2+ files): attach and receive are asked **once** for the whole run (`Y` = all, `N` = ask for each receipt). Use `--per-receipt-prompt` to skip the batch question. Use `--no-attach` / `--no-receive` to skip entirely.

## Environment variables

See [`.env.example`](.env.example) for Aspire, IDP, and path overrides.

## API reference

- [Aspire API guide](https://guide.youraspire.com/apidocs)
- [Production Swagger](https://cloud-api.youraspire.com/swagger/index.html)
- [Attachments API probe notes](docs/aspire_attachments_api.md) — receipt PDF attach flow (WIP)
