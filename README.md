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
  Invoices - Processed/     # PDFs after IDP
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
| **B10+** | Item code (optional if C has name) |
| **C10+** | Item name |
| **D10+** | Quantity |
| **E10+** | Unit cost (vendor profile may apply tax, 3 decimal places) |
| **F6** | Column heading: Total Cost |
| **F10+** | Line total (= D × E); Fowler profile nudges E so ΣF matches invoice grand total |

### Vendor profiles (`idp_vendor_profiles.py`)

Per-vendor rules for tax and total reconciliation. **`process_invoices.py`** stays generic; profiles are selected from the matched Aspire vendor name.

| Profile | Vendor | Tax on unit cost | Reconcile ΣF to invoice total |
|---------|--------|------------------|-------------------------------|
| `hd_fowler` | H.D. Fowler Company {Turf} (and names containing “fowler”) | ×1.06 | Yes |
| `default` | Everyone else | None (×1.0) | No |

Add vendors by extending `HD_FOWLER_PROFILE` / `DEFAULT_PROFILE` or calling `register_vendor_profile()` in `idp_vendor_profiles.py`.

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
```

- Uses OpenAI vision + structured JSON (`exports/vendors.csv`, `exports/catalog_items.csv`).
- Writes `{Vendor}_{Invoice-INV}.xlsx` into `Receipts - Ready\`.
- Moves PDFs to `Invoices - Processed\`.
- Appends review notes to `review_dashboard.txt` when confidence is below `IDP_CONFIDENCE_THRESHOLD` (default 0.85).

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
- Creates receipts only (`POST /Receipts`) — does not approve or receive.

## Environment variables

See [`.env.example`](.env.example) for Aspire, IDP, and path overrides.

## API reference

- [Aspire API guide](https://guide.youraspire.com/apidocs)
- [Production Swagger](https://cloud-api.youraspire.com/swagger/index.html)
