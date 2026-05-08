from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from scraper import (
    REQUIRED_FIELDS,
    load_field_schema,
    load_sources_from_docx,
    project_to_target_schema,
    scrape_sources,
)

DEFAULT_DOCX = r"C:\Users\Administrator\Downloads\Venue Events Links (2).docx"
DEFAULT_XLSX = r"C:\Users\Administrator\Downloads\Event Info.xlsx"

st.set_page_config(page_title="Scraping Dashboard", page_icon=":satellite:", layout="wide")

st.markdown(
    """
    <style>
        .stApp {
            background: radial-gradient(circle at 15% 85%, rgba(0,175,240,0.20), rgba(0,0,0,0.65) 45%),
                        radial-gradient(circle at 85% 20%, rgba(90,40,255,0.18), rgba(0,0,0,0.70) 40%),
                        #070b14;
            color: #d6dfef;
        }
        [data-testid="stSidebar"] {
            background: #0b1324;
            border-right: 1px solid rgba(80, 130, 230, 0.25);
        }
        .block-card {
            border: 1px solid rgba(60, 110, 220, 0.35);
            border-radius: 10px;
            padding: 18px;
            margin-bottom: 14px;
            background: rgba(8, 15, 34, 0.8);
            box-shadow: 0 0 20px rgba(13, 95, 255, 0.12);
        }
        .title-label {
            font-size: 0.8rem;
            text-transform: uppercase;
            color: #8aa6d8;
            letter-spacing: 0.08rem;
            margin-bottom: 8px;
        }
        .metric-line {
            font-size: 1.1rem;
            font-weight: 600;
            color: #def7ef;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Scraping Dashboard")
st.caption("Select categories to scrape, then view and export results.")

with st.sidebar:
    st.subheader("Inputs")
    docx_path = st.text_input("Venue Links .docx path", value=DEFAULT_DOCX)
    xlsx_path = st.text_input("Field Schema .xlsx path", value=DEFAULT_XLSX)
    uploaded_docx = st.file_uploader("Or upload .docx", type=["docx"])
    uploaded_xlsx = st.file_uploader("Or upload .xlsx", type=["xlsx"])


def _resolve_file(uploaded_file, fallback_path: str, suffix: str) -> Path | None:
    if uploaded_file:
        temp_path = Path(".runtime_uploads")
        temp_path.mkdir(exist_ok=True)
        output = temp_path / f"uploaded{suffix}"
        output.write_bytes(uploaded_file.getbuffer())
        return output

    path = Path(fallback_path)
    if path.exists():
        return path
    return None


docx_file = _resolve_file(uploaded_docx, docx_path, ".docx")
xlsx_file = _resolve_file(uploaded_xlsx, xlsx_path, ".xlsx")

if not docx_file:
    st.error("Provide a valid .docx file path or upload one.")
    st.stop()

sources = load_sources_from_docx(docx_file)
if not sources:
    st.error("No valid sources found in the .docx file.")
    st.stop()

field_schema = load_field_schema(xlsx_file) if xlsx_file else REQUIRED_FIELDS
available_categories = sorted({s.category for s in sources})

st.markdown('<div class="block-card">', unsafe_allow_html=True)
left, right = st.columns([4, 1.4])

with left:
    selected_categories = st.multiselect(
        "Categories",
        options=available_categories,
        default=available_categories[: min(len(available_categories), 4)],
        help="Choose one or more category groups from your docx file.",
    )
    venue_search = st.text_input("Search venues", placeholder="Search by venue name...")

with right:
    st.markdown('<div class="title-label">Action</div>', unsafe_allow_html=True)
    start_scraping = st.button("Start Scraping", use_container_width=True, type="primary")

st.markdown("</div>", unsafe_allow_html=True)

filtered_sources = [
    src
    for src in sources
    if (not selected_categories or src.category in selected_categories)
    and (not venue_search or venue_search.lower() in src.venue_name.lower())
]

if not filtered_sources:
    st.warning("No venues match the selected filters.")
    st.stop()

st.markdown(
    f"""
    <div class="block-card">
        <div class="title-label">Selected Sources</div>
        <div class="metric-line">{len(filtered_sources)} venues selected from {len(sources)} total.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

if start_scraping:
    progress = st.progress(0, text="Preparing scraping jobs...")

    def _on_progress(current: int, total: int, message: str) -> None:
        ratio = int((current / max(total, 1)) * 100)
        progress.progress(ratio, text=message)

    result_df = scrape_sources(filtered_sources, progress_cb=_on_progress)
    progress.progress(100, text="Scraping complete.")

    if result_df.empty:
        st.warning("No records extracted. Some sites may require JavaScript rendering.")
        st.stop()

    target_df = project_to_target_schema(result_df, field_schema)

    st.markdown('<div class="block-card">', unsafe_allow_html=True)
    st.subheader("Scraping complete")
    st.caption(f"{len(result_df)} unique records extracted.")

    required_map = {
        "name": "event_name",
        "venuesName": "venue_name",
        "startDate": "start_date",
        "startTime": "start_time",
    }
    filled = 0
    for field_name, col_name in required_map.items():
        if col_name in result_df.columns:
            filled += int(result_df[col_name].notna().sum())

    st.write(f"Required fields coverage (non-null values): `{filled}`")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="block-card">', unsafe_allow_html=True)
    st.subheader("Results")
    essential_cols = ["category", "venue_name", "event_name", "start_date", "start_time", "event_url"]
    st.caption("Quick preview")
    st.dataframe(result_df[essential_cols], use_container_width=True, hide_index=True)
    st.caption("Full export schema preview (all columns from your Excel template)")
    st.dataframe(target_df, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

    csv_bytes = target_df.to_csv(index=False).encode("utf-8")
    excel_buffer = BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        target_df.to_excel(writer, index=False, sheet_name="events")

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Download CSV",
            data=csv_bytes,
            file_name="scraped_events.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "Download Excel",
            data=excel_buffer.getvalue(),
            file_name="scraped_events.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
else:
    st.info("Pick categories and click Start Scraping.")
