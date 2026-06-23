"""
Process PDF invoices with OpenAI vision and write Aspire import workbooks.

1. Read PDFs from Receipts - Ready/Invoices - Ready
2. Extract + match vendors (exports/vendors.csv) and catalog (exports/catalog_items.csv)
3. Write .xlsx to Receipts - Ready for import_purchase_receipt.py
   (flagged invoices are queued for Streamlit review first — see app.py)
4. Move PDFs to Invoices - Processed/Complete
5. Append low-confidence items to review_dashboard.txt
6. Save extraction audit JSON to Receipts - Ready/review/JSONs (every invoice)

Usage:
  py scripts/process_invoices.py
  py scripts/process_invoices.py path/to/invoice.pdf
  py scripts/process_invoices.py --dry-run

On start, you will be prompted to refresh exports/catalog_items.csv from Aspire (Y/N),
and to choose an OpenAI vision model (1=gpt-4o, 2=gpt-4.1, 3=gpt-4.1-mini).

If any invoice needs review, the Streamlit dashboard opens automatically (use --no-dashboard to skip).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from idp_excel import write_from_extraction  # noqa: E402
from idp_extraction_json import save_extraction_json  # noqa: E402
from idp_openai import (  # noqa: E402
    collect_review_flags,
    default_openai_model,
    extract_invoice_from_pdf,
    format_invoice_number,
    prompt_openai_model,
    resolve_openai_model,
)
from idp_paths import (  # noqa: E402
    invoices_incoming_dir,
    invoices_processed_dir,
    receipts_ready_dir,
    review_dashboard_path,
    review_pending_dir,
)
from idp_match_log import append_hd_fowler_match_log_from_extraction  # noqa: E402
from idp_reference import ReferenceData  # noqa: E402
from aspire_attachments import move_to_aspire_pdf_name  # noqa: E402
from idp_vendor_profiles import is_sod_vendor_profile, vendor_profile_for  # noqa: E402


def _print_sod_summary(result, profile) -> None:
    if not is_sod_vendor_profile(profile):
        return
    if not result.invoice_total or not result.lines:
        return
    sqft = sum(ln.quantity for ln in result.lines)
    print(f"  Sod: Total Due ${result.invoice_total:,.2f} / {sqft:,.0f} sq ft")
    for i, ln in enumerate(result.lines, 1):
        ext = round(ln.quantity * ln.unit_price, 2)
        print(
            f"    Row {i}: {ln.item_name!r} qty={ln.quantity:,.0f} "
            f"unit=${ln.unit_price:.3f} ext=${ext:,.2f}"
        )
    split = getattr(result, "sod_split", None)
    if split is not None and getattr(split, "line_b", None):
        q1, u1 = split.line_a
        q2, u2 = split.line_b
        print(
            f"  Manual split (for B6 note): {q1:,.0f} @ ${u1:.3f} + "
            f"{q2:,.0f} @ ${u2:.3f}"
        )


def _prompt_refresh_catalog(skip: bool = False) -> None:
    """Ask whether to refresh catalog_items.csv from Aspire before IDP."""
    if skip:
        print("Using existing exports/catalog_items.csv (--no-catalog-prompt)")
        return
    while True:
        reply = input(
            "Refresh catalog_items.csv from Aspire before processing? [Y/N]: "
        ).strip().upper()
        if reply in ("Y", "N"):
            break
        print("Please enter Y or N.")

    if reply != "Y":
        print("Using existing exports/catalog_items.csv")
        return

    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from export_reference_data import export_catalog_items  # noqa: E402

    print("Fetching catalog from Aspire...")
    export_catalog_items(ROOT / "exports")


def _resolve_run_model(args: argparse.Namespace) -> str:
    if args.model:
        return resolve_openai_model(args.model)
    if args.no_model_prompt:
        return default_openai_model()
    return prompt_openai_model()


def _collect_pdfs(args: argparse.Namespace) -> list[Path]:
    if args.files:
        return [Path(p) for p in args.files]
    folder = invoices_incoming_dir()
    folder.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"No PDF files in {folder}", file=sys.stderr)
        sys.exit(1)
    return pdfs


def _append_dashboard(lines: list[str]) -> None:
    path = review_dashboard_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n\n")


def _launch_review_dashboard() -> None:
    """Start Streamlit review app in a new console; Streamlit opens the browser."""
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print(
            "\nReview dashboard not started — install Streamlit:\n"
            "  py -m pip install streamlit",
            file=sys.stderr,
        )
        return

    app_path = ROOT / "app.py"
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.headless",
        "false",
    ]
    print("\nStarting review dashboard (browser should open shortly)...")
    print("When finished reviewing, press Ctrl+C in the Streamlit terminal window.")

    popen_kwargs: dict = {"cwd": str(ROOT)}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

    try:
        subprocess.Popen(cmd, **popen_kwargs)
    except OSError as exc:
        print(f"Could not start Streamlit: {exc}", file=sys.stderr)
        print("Open manually: streamlit run app.py")


def process_pdf(
    pdf_path: Path,
    *,
    refs: ReferenceData,
    dry_run: bool,
    openai_model: str,
    save_json: bool = True,
) -> tuple[bool, bool]:
    """Returns (success, queued_for_review)."""
    print(f"\n=== {pdf_path.name} ===")
    if dry_run:
        print("  [dry-run] Would extract and write workbook (no API call if --no-openai)")
        if getattr(process_pdf, "_skip_openai", False):
            return True, False

    from idp_openai import require_openai_key
    from openai import OpenAI

    client = OpenAI(api_key=require_openai_key())
    result = extract_invoice_from_pdf(
        pdf_path, refs, client=client, model=openai_model
    )
    inv_display = format_invoice_number(result.invoice_number_raw)
    vendor = result.vendor_name or result.vendor_raw
    profile = vendor_profile_for(result.vendor_name, result.vendor_raw)
    print(
        f"  Vendor profile: {profile.display_name} ({profile.profile_id}) — "
        f"{profile.tax_percent_label()}"
        + (
            ", reconcile column F to invoice total"
            if profile.reconcile_to_invoice_total
            else ""
        )
    )
    _print_sod_summary(result, profile)

    flags = collect_review_flags(result)
    if save_json:
        json_path = save_extraction_json(
            result,
            pdf_name=pdf_path.name,
            openai_model=openai_model,
            flags=flags,
        )
        print(f"  Saved extraction JSON: {json_path.name}")

    if dry_run:
        print(f"  Vendor: {vendor!r} ({result.vendor_confidence:.2f})")
        print(f"  Invoice#: {inv_display}")
        print(f"  Lines: {len(result.lines)}")
        for flag in flags:
            print(f"  REVIEW: {flag.split(chr(10))[0]}")
        return True, bool(flags)

    if not flags:
        n_logged = append_hd_fowler_match_log_from_extraction(
            result,
            pdf_name=pdf_path.name,
        )
        if n_logged:
            print(f"  Match log: {n_logged} line(s) → HD Fowler Item Match Log.xlsx")
    out_path: Path | None = None
    reconciled = True
    col_f_total = 0.0
    session = None

    if flags:
        from idp_review import extraction_to_session, save_session

        session = extraction_to_session(result, pdf_path, flags=flags)
    else:
        out_path, reconciled, col_f_total = write_from_extraction(
            result, receipts_ready_dir()
        )
        print(f"  Wrote: {out_path.name}")
        if result.invoice_total:
            print(
                f"  Invoice total: {result.invoice_total:.2f}  "
                f"Column F sum: {col_f_total:.2f}  "
                f"{'OK' if reconciled else 'MISMATCH'}"
            )

    processed = invoices_processed_dir()
    processed.mkdir(parents=True, exist_ok=True)
    if result.invoice_date:
        dest = processed / pdf_path.name
        if dest.exists():
            dest = processed / (
                f"{pdf_path.stem}_{datetime.now().strftime('%H%M%S')}{pdf_path.suffix}"
            )
        shutil.move(str(pdf_path), str(dest))
        dest = move_to_aspire_pdf_name(
            dest,
            inv_display,
            result.invoice_date,
            vendor_name=result.vendor_name,
            vendor_raw=result.vendor_raw,
            processed_dir=processed,
        )
    else:
        dest = processed / pdf_path.name
        if dest.exists():
            dest = processed / (
                f"{pdf_path.stem}_{datetime.now().strftime('%H%M%S')}{pdf_path.suffix}"
            )
        shutil.move(str(pdf_path), str(dest))
        print("  Warning: no invoice date — PDF kept as original filename", file=sys.stderr)
    print(f"  Moved PDF to: {dest.name}")

    if session is not None:
        from idp_review import save_session

        session.pdf_path = str(dest.resolve())
        session.pdf_name = dest.name
        save_session(session)
        print(f"  Queued for review: {session.session_id}.json")

    dash_lines = [
        f"=== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===",
        f"PDF: {dest.name}",
    ]
    if session is not None:
        dash_lines.append(
            f"Review: {session.session_id}.json (pending — use Streamlit dashboard)"
        )
        dash_lines.extend(flags)
        dash_lines.append(
            "Note: Excel not written until approved in review dashboard."
        )
    else:
        dash_lines.append(f"-> {out_path.name if out_path else 'unknown'}")
        dash_lines.append("All fields matched above confidence threshold.")
        if result.invoice_total and not reconciled:
            dash_lines.append(
                "TOTAL RECONCILE FAILED: column F sum could not match invoice total"
            )
    _append_dashboard(dash_lines)
    return True, session is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="IDP: PDF invoices to Excel for Aspire import")
    parser.add_argument("files", nargs="*", help="PDF file(s); default: Invoices - Ready folder")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract with OpenAI and print summary (still calls API)",
    )
    parser.add_argument(
        "--fresh-dashboard",
        action="store_true",
        help="Clear review_dashboard.txt before this run",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Do not auto-open Streamlit when invoices are queued for review",
    )
    parser.add_argument(
        "--no-catalog-prompt",
        action="store_true",
        help="Use existing exports/catalog_items.csv without prompting",
    )
    parser.add_argument(
        "--model",
        metavar="CHOICE",
        help="OpenAI model: 1 or 4o (gpt-4o), 2 or 4.1 (gpt-4.1), 3 or mini (gpt-4.1-mini)",
    )
    parser.add_argument(
        "--no-model-prompt",
        action="store_true",
        help="Use OPENAI_MODEL from .env without prompting",
    )
    parser.add_argument(
        "--no-extraction-json",
        action="store_true",
        help="Do not save extraction audit JSON under review/JSONs",
    )
    args = parser.parse_args()

    if args.fresh_dashboard:
        dash = review_dashboard_path()
        dash.parent.mkdir(parents=True, exist_ok=True)
        dash.write_text("", encoding="utf-8")

    _prompt_refresh_catalog(skip=args.no_catalog_prompt)

    openai_model = _resolve_run_model(args)
    print(f"OpenAI model for this run: {openai_model}")

    refs = ReferenceData()
    refs.load()
    print(
        f"Loaded {len(refs.vendors)} vendors, {len(refs.inventory)} catalog items "
        f"(exports/catalog_items.csv)"
    )

    pdfs = _collect_pdfs(args)
    ok = True
    queued_count = 0
    for pdf in pdfs:
        try:
            success, queued = process_pdf(
                pdf,
                refs=refs,
                dry_run=args.dry_run,
                openai_model=openai_model,
                save_json=not args.no_extraction_json,
            )
            if not success:
                ok = False
            elif queued and not args.dry_run:
                queued_count += 1
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            ok = False
    if not args.dry_run and ok:
        print(f"\nReview: {review_dashboard_path()}")
        if queued_count > 0:
            if args.no_dashboard:
                print(
                    f"{queued_count} invoice(s) queued — open: streamlit run app.py"
                )
            else:
                _launch_review_dashboard()
        elif any(review_pending_dir().glob("*.json")):
            print("Pending reviews exist — open: streamlit run app.py")
        print("Then run: py scripts/import_purchase_receipt.py --dry-run")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
