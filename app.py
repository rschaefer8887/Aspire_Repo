"""
Streamlit dashboard for reviewing low-confidence IDP extractions.

Run from project root:
  streamlit run app.py

Workflow:
  1. py scripts/process_invoices.py  (queues flagged invoices as JSON, skips Excel)
  2. streamlit run app.py            (correct catalog matches, approve to write Excel)
  3. py scripts/import_purchase_receipt.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from idp_costs import effective_invoice_total  # noqa: E402
from idp_excel import write_from_extraction  # noqa: E402
from idp_openai import format_invoice_number  # noqa: E402
from idp_paths import confidence_threshold, receipts_ready_dir, review_pending_dir  # noqa: E402
from idp_reference import ReferenceData  # noqa: E402
from idp_review import (  # noqa: E402
    ReviewSession,
    build_catalog_options,
    build_vendor_options,
    delete_session,
    label_for_line,
    list_pending_sessions,
    load_session,
    resolve_catalog_label,
    build_catalog_label_index,
    pdf_page_count,
    render_pdf_for_streamlit,
    resolve_pdf_path,
    save_session,
    session_to_extraction,
)


@st.cache_resource
def load_reference_data() -> ReferenceData:
    refs = ReferenceData()
    refs.load()
    return refs


@st.cache_data
def cached_catalog_options() -> list[str]:
    return build_catalog_options(load_reference_data())


@st.cache_data
def cached_catalog_index() -> dict[str, tuple[str | None, str | None]]:
    return build_catalog_label_index(load_reference_data())


@st.cache_data
def cached_vendor_options() -> list[str]:
    return build_vendor_options(load_reference_data())


def session_to_dataframe(session: ReviewSession) -> pd.DataFrame:
    rows = []
    for i, line in enumerate(session.lines):
        rows.append(
            {
                "#": i + 1,
                "Description": line.description_raw,
                "Qty": line.quantity,
                "Unit Price": line.unit_price,
                "Confidence": round(line.confidence, 2),
                "Catalog Item": label_for_line(line.item_code, line.item_name),
                "Needs Review": line.needs_review,
                "Exclude from invoice": line.excluded,
            }
        )
    return pd.DataFrame(rows)


def apply_dataframe_to_session(
    session: ReviewSession,
    df: pd.DataFrame,
    catalog_index: dict[str, tuple[str | None, str | None]],
) -> None:
    for i in range(min(len(df), len(session.lines))):
        row = df.iloc[i]
        line = session.lines[i]
        excluded = bool(row.get("Exclude from invoice", False))
        line.excluded = excluded
        if excluded:
            line.item_code = None
            line.item_name = None
            line.needs_review = False
            continue
        code, name = resolve_catalog_label(
            str(row.get("Catalog Item") or ""), catalog_index
        )
        line.item_code = code
        line.item_name = name or line.description_raw
        line.quantity = float(row["Qty"])
        line.unit_price = float(row["Unit Price"])
        line.needs_review = bool(row.get("Needs Review", False))


def missing_catalog_lines(session: ReviewSession) -> list[int]:
    missing: list[int] = []
    for i, line in enumerate(session.lines):
        if line.excluded:
            continue
        if not line.item_code and not line.item_name:
            missing.append(i + 1)
    return missing


def included_line_count(session: ReviewSession) -> int:
    return sum(1 for ln in session.lines if not ln.excluded)


def render_invoice_panel(
    pdf_path: Path,
    *,
    focus_line: int,
    total_lines: int,
    page_index: int,
    full_page: bool,
) -> None:
    try:
        img = render_pdf_for_streamlit(
            pdf_path,
            page_index=page_index,
            line_index=focus_line,
            total_lines=total_lines,
            full_page=full_page,
        )
        st.image(img, use_container_width=True)
    except Exception as exc:
        st.error(f"Could not render PDF: {exc}")


def main() -> None:
    st.set_page_config(
        page_title="Invoice Review",
        page_icon="📄",
        layout="wide",
    )
    st.title("Invoice IDP Review")
    st.caption(
        "Correct low-confidence catalog matches, then approve to write the Aspire import workbook. "
        "Catalog dropdown shows Material items only."
    )

    pending = list_pending_sessions()
    if not pending:
        st.info(
            "No pending reviews. Run `py scripts/process_invoices.py` on invoices that need review."
        )
        st.markdown(f"Pending folder: `{review_pending_dir()}`")
        return

    refs = load_reference_data()
    catalog_options = cached_catalog_options()
    catalog_index = cached_catalog_index()
    vendor_options = cached_vendor_options()
    threshold = confidence_threshold()

    with st.sidebar:
        st.header("Pending invoices")
        labels = [
            f"{sess.session_id} ({sum(1 for ln in sess.lines if ln.needs_review and not ln.excluded)} flags"
            f"{', ' + str(sum(1 for ln in sess.lines if ln.excluded)) + ' excluded' if any(ln.excluded for ln in sess.lines) else ''})"
            for _, sess in pending
        ]
        choice = st.selectbox(
            "Select invoice",
            range(len(pending)),
            format_func=lambda i: labels[i],
        )
        st.caption(f"{len(pending)} pending · threshold {threshold:.0%}")
        if st.button("Reload list", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    path, session = pending[choice]
    pdf_path = resolve_pdf_path(session)

    inv_num = format_invoice_number(session.invoice_number_raw)
    st.subheader(f"{session.vendor_name or session.vendor_raw} — {inv_num}")
    st.caption(f"PDF: {session.pdf_name} · saved {session.created_at}")

    if session.flags:
        with st.expander("Review flags from IDP", expanded=False):
            for flag in session.flags:
                st.text(flag)

    vendor_needs_review = (
        not session.vendor_name or session.vendor_confidence < threshold
    )
    original_total = session.original_invoice_total()
    adjusted_total = effective_invoice_total(original_total, session.lines)
    excluded_count = sum(1 for ln in session.lines if ln.excluded)

    cols_meta = st.columns(5)
    cols_meta[0].metric("Lines", len(session.lines))
    cols_meta[1].metric("Included", included_line_count(session))
    cols_meta[2].metric(
        "Needs review",
        sum(1 for ln in session.lines if ln.needs_review and not ln.excluded),
    )
    cols_meta[3].metric(
        "Original total",
        f"${original_total:,.2f}" if original_total else "—",
    )
    cols_meta[4].metric(
        "Adjusted total",
        f"${adjusted_total:,.2f}" if adjusted_total is not None else "—",
        help="Invoice total minus excluded lines (incl. 6% tax)",
    )

    if excluded_count:
        excluded_amount = (
            round(original_total - adjusted_total, 2)
            if original_total is not None and adjusted_total is not None
            else None
        )
        st.info(
            f"{excluded_count} line(s) excluded from import"
            + (
                f" · ${excluded_amount:,.2f} removed from total"
                if excluded_amount is not None
                else ""
            )
        )

    if vendor_needs_review:
        st.warning("Vendor match is below confidence threshold — confirm vendor below.")

    st.caption(f"Vendor confidence: {session.vendor_confidence:.0%}")

    vendor_pick = st.selectbox(
        "Vendor (Aspire)",
        vendor_options,
        index=vendor_options.index(session.vendor_name)
        if session.vendor_name in vendor_options
        else 0,
    )
    session.vendor_name = vendor_pick

    review_indices = [
        i for i, ln in enumerate(session.lines) if ln.needs_review and not ln.excluded
    ]
    default_focus = review_indices[0] if review_indices else 0

    if "focus_line" not in st.session_state:
        st.session_state.focus_line = default_focus
    if st.session_state.get("active_session") != session.session_id:
        st.session_state.focus_line = default_focus
        st.session_state.active_session = session.session_id

    focus_options = list(range(len(session.lines)))

    def focus_label(i: int) -> str:
        line = session.lines[i]
        if line.excluded:
            marker = " ⊘"
        elif line.needs_review:
            marker = " ⚠"
        else:
            marker = ""
        desc = line.description_raw[:55]
        return f"Line {i + 1}{marker}: {desc}"

    left, right = st.columns([1.05, 1], gap="large")

    with left:
        st.markdown("#### Invoice image")
        if pdf_path is None:
            st.error("PDF not found. Check Invoices - Processed folder.")
        else:
            page_count = pdf_page_count(pdf_path)
            img_controls = st.columns(2)
            page_index = int(
                img_controls[0].number_input(
                    "Page",
                    min_value=1,
                    max_value=max(page_count, 1),
                    value=1,
                )
                - 1
            )
            full_page = img_controls[1].checkbox("Full page", value=False)

            focus_line = st.selectbox(
                "Zoom to line",
                focus_options,
                index=st.session_state.focus_line,
                format_func=focus_label,
                key=f"focus_{session.session_id}",
            )
            st.session_state.focus_line = focus_line

            if not full_page:
                st.caption(
                    f"Showing focus band for line {focus_line + 1} "
                    f"(heuristic crop — use Full page if needed)"
                )
            render_invoice_panel(
                pdf_path,
                focus_line=focus_line,
                total_lines=len(session.lines),
                page_index=page_index,
                full_page=full_page,
            )

    with right:
        st.markdown("#### Line items")
        df = session_to_dataframe(session)

        edited = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "#": st.column_config.NumberColumn("#", disabled=True, width="small"),
                "Description": st.column_config.TextColumn(
                    "Description",
                    disabled=True,
                    width="large",
                ),
                "Qty": st.column_config.NumberColumn("Qty", min_value=0.0, format="%.2f"),
                "Unit Price": st.column_config.NumberColumn(
                    "Unit Price",
                    min_value=0.0,
                    format="%.4f",
                ),
                "Confidence": st.column_config.NumberColumn(
                    "Confidence",
                    disabled=True,
                    format="%.2f",
                ),
                "Catalog Item": st.column_config.SelectboxColumn(
                    "Catalog Item",
                    options=catalog_options,
                    required=False,
                    width="large",
                ),
                "Needs Review": st.column_config.CheckboxColumn(
                    "Needs Review",
                    help="Uncheck after you have verified the line",
                ),
                "Exclude from invoice": st.column_config.CheckboxColumn(
                    "Exclude from invoice",
                    help="Remove from Excel import; subtracts taxed line total from invoice total",
                ),
            },
            key=f"editor_{session.session_id}",
        )

        btn_save, btn_approve, btn_discard = st.columns(3)
        if btn_save.button("Save draft", use_container_width=True):
            apply_dataframe_to_session(session, edited, catalog_index)
            save_session(session)
            st.success("Draft saved.")

        if btn_approve.button("Approve & write Excel", type="primary", use_container_width=True):
            apply_dataframe_to_session(session, edited, catalog_index)
            if included_line_count(session) == 0:
                st.error("Cannot approve — at least one line must be included.")
            else:
                missing = missing_catalog_lines(session)
                if missing:
                    st.error(
                        "Cannot approve — assign a catalog item for lines: "
                        + ", ".join(str(n) for n in missing)
                    )
                elif not session.vendor_name:
                    st.error("Select a vendor before approving.")
                else:
                    try:
                        extraction = session_to_extraction(session)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        out_path, reconciled, col_f_total = write_from_extraction(
                            extraction, receipts_ready_dir()
                        )
                        delete_session(session.session_id)
                        adj = session.adjusted_invoice_total()
                        msg = f"Wrote **{out_path.name}** to `{receipts_ready_dir()}`"
                        if adj is not None:
                            msg += (
                                f" · Column F sum ${col_f_total:,.2f}"
                                f" {'✓' if reconciled else '(total mismatch)'}"
                            )
                        st.success(msg)
                        st.balloons()
                        st.rerun()

        if btn_discard.button("Discard review", use_container_width=True):
            delete_session(session.session_id)
            st.warning(f"Removed {session.session_id} from pending review.")
            st.rerun()


if __name__ == "__main__":
    main()
