import streamlit as st

st.set_page_config(
    page_title="Incident Intelligence Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from supabase import create_client          # ← direct client so we can paginate
from utils.charts import (
    render_incidents_by_category,
    render_incidents_by_type,
    render_incidents_by_country,
    render_impact_distribution,
    render_timeline,
    render_wordcloud,
    render_source_breakdown,
)
from utils.chatbot import chatbot_ui
from utils.risk_scorer import score_dataframe

TZ_MY = ZoneInfo("Asia/Kuala_Lumpur")
def now_my(): return datetime.now(tz=TZ_MY)


# ══════════════════════════════════════════════════════════════════════════════
#  SUPABASE — paginated fetch (replaces get_data so ALL rows are returned)
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def _supabase():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)


def get_data(table: str) -> pd.DataFrame:
    """Fetch every row from *table* using 1 000-row pages."""
    client   = _supabase()
    all_rows = []
    page     = 0
    page_size = 1000

    while True:
        start = page * page_size
        end   = start + page_size - 1
        try:
            resp = client.table(table).select("*").range(start, end).execute()
        except Exception as e:
            st.error(f"Supabase error fetching {table}: {e}")
            break

        batch = resp.data or []
        all_rows.extend(batch)

        if len(batch) < page_size:   # last page
            break
        page += 1

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)

    # ── column normalisation for incidents ───────────────────────────────────
    # Your DB uses "publication_date"; charts expect "incident_date".
    # Also derive "country" / "category" / "impact" if missing.
    if table == "incidents":
        # date alias
        if "incident_date" not in df.columns and "publication_date" in df.columns:
            df["incident_date"] = df["publication_date"]

        # country  — try common column names, else "Unknown"
        if "country" not in df.columns:
            for alt in ("nation", "location", "geo", "region"):
                if alt in df.columns:
                    df["country"] = df[alt]
                    break
            else:
                df["country"] = "Unknown"

        # category — try common alternatives, else "Uncategorised"
        if "category" not in df.columns:
            for alt in ("type", "threat_type", "incident_category"):
                if alt in df.columns:
                    df["category"] = df[alt]
                    break
            else:
                df["category"] = "Uncategorised"

        # incident_type alias
        if "incident_type" not in df.columns:
            for alt in ("type", "attack_type", "threat_type"):
                if alt in df.columns:
                    df["incident_type"] = df[alt]
                    break
            else:
                df["incident_type"] = df.get("category", "Unknown")

        # impact — try common alternatives, else "Unknown"
        # Note: do NOT use "severity" as fallback here — severity is its own column
        # and is read directly in render_intel_feed.
        if "impact" not in df.columns:
            for alt in ("criticality", "priority"):
                if alt in df.columns:
                    df["impact"] = df[alt]
                    break
            else:
                df["impact"] = "Unknown"

        # ── Apply custom risk formula — overwrites DB severity in-memory ─────
        df = score_dataframe(df)

    return df


# ══════════════════════════════════════════════════════════════════════════════
#  CSS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body { font-family: 'IBM Plex Sans', sans-serif; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0a0d13 !important;
    border-right: 1px solid #1a1f2e !important;
}
[data-testid="stSidebar"] > div:first-child { padding-top: 0 !important; }
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label { color: #8b949e !important; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: #f0f6fc !important; }

/* ── Top nav bar ── */
[data-testid="stTopNavigation"] {
    background: #0d1117 !important;
    border-bottom: 1px solid #21262d !important;
}
[data-testid="stTopNavigation"] a { color: #8b949e !important; font-size: 13px !important; }
[data-testid="stTopNavigation"] a[aria-current="page"] {
    color: #f0f6fc !important;
    border-bottom: 2px solid #388bfd !important;
}

/* ── Page header ── */
.dash-header {
    background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
    border: 1px solid #21262d; border-radius: 12px;
    padding: 20px 28px; margin-bottom: 22px;
    display: flex; align-items: center; justify-content: space-between;
}
.dash-title    { font-size: 22px; font-weight: 600; color: #f0f6fc; letter-spacing: -0.3px; }
.dash-subtitle { font-size: 12.5px; color: #8b949e; margin-top: 3px; }
.dash-live     { font-size: 11.5px; color: #3fb950; font-family:IBM Plex Mono,monospace; }
.live-dot {
    display: inline-block; width: 7px; height: 7px;
    background: #3fb950; border-radius: 50%; margin-right: 5px;
    animation: blink 2s infinite; vertical-align: middle;
}
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.25} }

/* ── KPI cards ── */
.kpi-card {
    background: #161b22; border: 1px solid #21262d;
    border-radius: 10px; padding: 18px 20px; text-align: center; transition: border-color .2s;
}
.kpi-card:hover { border-color: #388bfd; }
.kpi-number { font-size: 36px; font-weight: 600; color: #f0f6fc; font-family:IBM Plex Mono,monospace; line-height: 1; }
.kpi-label  { font-size: 12px; color: #8b949e; margin-top: 6px; text-transform: uppercase; letter-spacing: .08em; }
.kpi-delta  { font-size: 12px; margin-top: 6px; font-family:IBM Plex Mono,monospace; }
.kpi-up   { color: #3fb950; }
.kpi-warn { color: #f78166; }

/* ── Section headers ── */
.section-header {
    font-size: 13px; font-weight: 500; color: #8b949e;
    text-transform: uppercase; letter-spacing: .1em;
    margin: 24px 0 12px; border-bottom: 1px solid #21262d; padding-bottom: 8px;
}

/* ── Victim cards ── */
.victim-card {
    background: #161b22; border: 1px solid #21262d;
    border-left: 3px solid #f78166; border-radius: 8px;
    padding: 14px 16px; margin-bottom: 10px;
}
.victim-name  { font-size: 15px; font-weight: 600; color: #f0f6fc; }
.victim-meta  { font-size: 12px; color: #8b949e; margin-top: 4px; font-family:IBM Plex Mono,monospace; }
.victim-badge {
    display: inline-block; font-size: 11px; font-family:IBM Plex Mono,monospace;
    padding: 2px 8px; border-radius: 4px; margin-top: 6px; font-weight: 600;
}
.sev-critical { background:#3d0f0f; color:#ff6b6b; }
.sev-high     { background:#2d1b0a; color:#ffa94d; }
.sev-medium   { background:#1e2a0a; color:#a9d64b; }
.sev-low      { background:#0a1f2a; color:#4fc3f7; }

/* ── Chat hero ── */
.chat-hero {
    background: linear-gradient(135deg,#0d1117 0%,#161b22 60%,#1a2332 100%);
    border: 1px solid #21262d; border-radius: 14px;
    padding: 36px; margin-bottom: 24px; text-align: center;
}
.chat-hero-title { font-size: 26px; font-weight: 600; color: #f0f6fc; margin-top: 10px; }
.chat-hero-sub   { font-size: 14px; color: #8b949e; margin-top: 6px; }

/* ── Intel feed cards ── */
.intel-feed-card {
    background: #161b22; border: 1px solid #21262d;
    border-radius: 10px; padding: 14px 18px;
    margin-bottom: 10px; position: relative;
    overflow: hidden; transition: border-color .2s;
}
.intel-feed-card:hover { border-color: #388bfd; }
.intel-accent { position: absolute; left: 0; top: 0; bottom: 0; width: 3px; }
.accent-critical { background: #ff6b6b; }
.accent-high     { background: #ffa94d; }
.accent-medium   { background: #4fc3f7; }
.accent-low      { background: #3fb950; }
.intel-top {
    display: flex; align-items: center; gap: 7px;
    flex-wrap: wrap; margin-bottom: 7px;
}
.intel-badge {
    font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 600;
    letter-spacing: .07em; padding: 3px 9px; border-radius: 100px; text-transform: uppercase;
}
.ibadge-critical { background: #3d0f0f; color: #ff6b6b; }
.ibadge-high     { background: #2d1b0a; color: #ffa94d; }
.ibadge-medium   { background: #0a1f2a; color: #4fc3f7; }
.ibadge-low      { background: #0a1f17; color: #3fb950; }
.ibadge-unknown  { background: #1c1c1c; color: #8b949e; }
.intel-cat {
    font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 500;
    padding: 2px 9px; border-radius: 100px; border: 1px solid #21262d;
    color: #8b949e; text-transform: uppercase; letter-spacing: .06em;
}
.intel-hot {
    background: #ff6b6b; color: #fff;
    font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 700;
    padding: 3px 9px; border-radius: 100px; letter-spacing: .1em; text-transform: uppercase;
    animation: blink 1.8s ease-in-out infinite;
}
.intel-title   { font-size: 16px; font-weight: 600; color: #f0f6fc; line-height: 1.45; margin-bottom: 6px; }
.intel-summary { font-size: 14px; color: #c9d1d9; line-height: 1.6; margin-bottom: 10px; }
.intel-footer  {
    display: flex; align-items: center;
    justify-content: space-between; flex-wrap: wrap; gap: 6px;
}
.intel-source {
    font-family: 'IBM Plex Mono', monospace; font-size: 12.5px;
    color: #6e7681; display: flex; align-items: center; gap: 5px;
}
.intel-source-dot { width: 5px; height: 5px; border-radius: 50%; background: #21262d; flex-shrink: 0; }
.intel-time { font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; color: #6e7681; }

hr { border-color: #21262d !important; }
[data-testid="stMetric"] { background: transparent; }
.stPlotlyChart { border: 1px solid #21262d; border-radius: 10px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def page_header(title: str, subtitle: str):
    st.markdown(f"""
    <div class="dash-header">
        <div>
            <div class="dash-title">{title}</div>
            <div class="dash-subtitle">{subtitle}</div>
        </div>
        <div class="dash-live">
            <span class="live-dot"></span>
            {now_my().strftime('%d %b %Y, %H:%M:%S')} GMT+8
        </div>
    </div>
    """, unsafe_allow_html=True)


def kpi_row(specs: list):
    for col, val, label, delta, dtype in specs:
        val_str     = f"{val:,}" if isinstance(val, int) else str(val)
        num_size    = "24px" if isinstance(val, str) and len(val) > 6 else "36px"
        delta_class = f"kpi-{dtype}" if dtype else "kpi-label"
        col.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-number" style="font-size:{num_size}">{val_str}</div>
            <div class="kpi-label">{label}</div>
            <div class="kpi-delta {delta_class}">{delta}</div>
        </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED SIDEBAR COMPONENTS
# ══════════════════════════════════════════════════════════════════════════════
def _sidebar_branding():
    st.markdown(f"""
    <div style="padding:20px 4px 14px;border-bottom:1px solid #1a1f2e;margin-bottom:10px;">
        <div style="font-size:16px;font-weight:600;color:#f0f6fc;">🛡️ Incident Intel</div>
        <div style="font-size:11px;color:#484f58;font-family:IBM Plex Mono,monospace;margin-top:3px;">
            <span class="live-dot"></span> LIVE · {now_my().strftime('%H:%M')} GMT+8
        </div>
    </div>
    """, unsafe_allow_html=True)


def _filter_label(text="Filters"):
    return (
        f"<div style='font-size:10px;font-weight:600;color:#484f58;"
        f"text-transform:uppercase;letter-spacing:.12em;"
        f"padding:12px 16px 4px;border-top:1px solid #1a1f2e;margin-top:10px;'>"
        f"{text}</div>"
    )


def _sidebar_footer():
    st.markdown("---")
    auto_refresh = st.toggle("Auto-refresh (60s)", value=False, key="auto_refresh")
    if auto_refresh:
        st.info("Auto-refresh enabled (refresh page manually every 60s)")
    st.markdown(
        "<div style='font-size:10.5px;color:#484f58;line-height:1.8;margin-top:6px;'>"
        "Data source: Supabase Postgres<br>"
        "Model: claude-sonnet-4-20250514<br>"
        "Feed: ransomware.live"
        "</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  INTEL FEED RENDERER
# ══════════════════════════════════════════════════════════════════════════════
import re as _re

def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities, returning clean plain text."""
    text = str(text)
    text = _re.sub(r'<[^>]+>', '', text)   # strip all <tags>
    text = text.replace("&amp;",  "&")
    text = text.replace("&lt;",   "<")
    text = text.replace("&gt;",   ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;",  "'")
    text = text.replace("&nbsp;", " ")
    text = _re.sub(r'\s+', ' ', text)      # collapse extra whitespace
    return text.strip()


# ── Category → colour helpers ─────────────────────────────────────────────────
CATEGORY_BASE_COLORS = {
    "data breach":       "#e53935",
    "data breached":     "#e53935",
    "ransomware":        "#ff6f00",
    "phishing":          "#f9a825",
    "malware":           "#6a1b9a",
    "ddos":              "#1565c0",
    "insider threat":    "#2e7d32",
    "zero-day":          "#00838f",
    "social engineering":"#ad1457",
    "supply chain":      "#4527a0",
    "credential theft":  "#c62828",
    "iot attack":        "#558b2f",
    "cryptojacking":     "#ef6c00",
    "apt":               "#283593",
    "uncategorised":     "#546e7a",
}

def _get_category_color(category: str) -> str:
    if not category or str(category).lower() in ("nan", "none", ""):
        return CATEGORY_BASE_COLORS["uncategorised"]
    key = str(category).strip().lower()
    for k, v in CATEGORY_BASE_COLORS.items():
        if k in key or key in k:
            return v
    palette = ["#e53935","#ff6f00","#6a1b9a","#1565c0","#2e7d32","#00838f","#ad1457","#4527a0"]
    return palette[hash(key) % len(palette)]

def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    return f"rgba({r},{g},{b},{alpha})"

def _lighten_hex(hex_color: str, factor: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    r = int(r + (255-r)*factor)
    g = int(g + (255-g)*factor)
    b = int(b + (255-b)*factor)
    return f"#{r:02x}{g:02x}{b:02x}"



def render_intel_feed(df: pd.DataFrame, max_items: int = 20):
    """Render news cards with st.markdown (so HTML renders), tiny invisible button for click."""

    SEV_FG     = {"critical":"#f76c6c","high":"#f7a94f","medium":"#4f8ef7","low":"#3ecf8e","unknown":"#7a8599"}
    SEV_BG     = {"critical":"#3d0f0f","high":"#2d1b0a","medium":"#0a1f2a","low":"#0a1f17","unknown":"#1c1c1c"}
    SEV_BORDER = {"critical":"#f76c6c","high":"#f7a94f","medium":"#4f8ef7","low":"#3ecf8e","unknown":"#484f58"}

    title_col    = next((c for c in ("title","headline","name")                      if c in df.columns), None)
    summary_col  = next((c for c in ("summary","description","content")              if c in df.columns), None)
    source_col   = next((c for c in ("source","origin","feed")                       if c in df.columns), None)
    severity_col = next((c for c in ("severity",)                                    if c in df.columns), None)
    impact_col   = next((c for c in ("impact","criticality")                         if c in df.columns), None)
    inc_type_col = next((c for c in ("incident_type","type","attack_type")           if c in df.columns), None)
    entity_col   = next((c for c in ("entity_affected","entity","target","victim")   if c in df.columns), None)
    date_col     = next((c for c in ("incident_date","publication_date","date")      if c in df.columns), None)
    pub_date_col = "publication_date" if "publication_date" in df.columns else None
    inc_date_col = "incident_date"    if "incident_date"    in df.columns else None
    cat_col      = "category"         if "category"         in df.columns else None
    country_col  = "country"          if "country"          in df.columns else None
    url_col      = next((c for c in ("url","link","source_url")                      if c in df.columns), None)
    kw_col       = next((c for c in ("relevant_keywords","keywords","tags")          if c in df.columns), None)

    feed_df = df.copy()
    if date_col:
        feed_df = feed_df.sort_values(date_col, ascending=False)
    feed_df = feed_df.head(max_items).reset_index(drop=True)

    if feed_df.empty:
        st.info("No incidents match the current filters.")
        return

    now = now_my()

    if "intel_selected_idx" not in st.session_state:
        st.session_state["intel_selected_idx"] = None

    # ── CSS: hide button chrome, make it overlay the card invisibly ──────────
    st.markdown("""
    <style>
    .card-wrap { position: relative; margin-bottom: 6px; }
    .card-wrap button {
        position: absolute !important;
        inset: 0 !important;
        width: 100% !important;
        height: 100% !important;
        opacity: 0 !important;
        cursor: pointer !important;
        z-index: 10 !important;
        border: none !important;
        background: transparent !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    .card-wrap [data-testid="stButton"] {
        position: absolute !important;
        inset: 0 !important;
        width: 100% !important;
        height: 100% !important;
    }
    </style>
    """, unsafe_allow_html=True)

    for i, (_, row) in enumerate(feed_df.iterrows()):
        sev_raw  = str(row.get(severity_col,"") if severity_col else "").strip().lower()
        imp_raw  = str(row.get(impact_col,  "") if impact_col   else "").strip().lower()
        sev_key  = sev_raw if sev_raw in SEV_FG else imp_raw if imp_raw in SEV_FG else "unknown"
        fg       = SEV_FG[sev_key]
        bg       = SEV_BG[sev_key]
        border   = SEV_BORDER[sev_key]

        title    = _strip_html(str(row.get(title_col,   "Untitled") if title_col   else "Untitled"))
        summary  = _strip_html(str(row.get(summary_col, "")         if summary_col else ""))
        source   = _strip_html(str(row.get(source_col,  "Unknown")  if source_col  else "Unknown"))
        cat      = str(row.get(cat_col,     "") if cat_col      else "").strip()
        inc_type = str(row.get(inc_type_col,"") if inc_type_col else "").strip()

        short_sum = summary[:160] + "…" if len(summary) > 160 else summary

        time_str = ""
        if date_col and pd.notna(row.get(date_col)):
            try:
                mins = int((now - row[date_col]).total_seconds() / 60)
                if   mins < 1:     time_str = "just now"
                elif mins < 60:    time_str = f"{mins}m ago"
                elif mins < 1440:  time_str = f"{mins//60}h ago"
                else:              time_str = f"{mins//1440}d ago"
            except: pass

        is_hot = (sev_key in ("critical","high") and date_col
                  and pd.notna(row.get(date_col))
                  and (now - row[date_col]).total_seconds() < 21600)

        cat_color  = _get_category_color(cat)
        type_color = _lighten_hex(cat_color, 0.4) if cat else "#7a8599"
        is_selected = st.session_state["intel_selected_idx"] == i

        hot_html  = '<span style="background:#f76c6c;color:#fff;font-size:9px;font-weight:700;padding:1px 7px;border-radius:100px;letter-spacing:.1em;">🔥 HOT</span>' if is_hot else ""
        cat_html  = (f'<span style="background:{_hex_to_rgba(cat_color,0.15)};color:{cat_color};font-size:9px;font-weight:700;padding:1px 7px;border-radius:100px;text-transform:uppercase;">{cat}</span>'
                     if cat and cat.lower() not in ("nan","none","") else "")
        type_html = (f'<span style="background:{_hex_to_rgba(type_color,0.13)};color:{type_color};font-size:9px;font-weight:700;padding:1px 7px;border-radius:100px;text-transform:uppercase;">{inc_type}</span>'
                     if inc_type and inc_type.lower() not in ("nan","none","") else "")

        sel_bg     = "#15192c"               if is_selected else "#131829"
        sel_border = fg                      if is_selected else "#1e2130"
        sel_shadow = f"0 0 16px {fg}33;"     if is_selected else ""
        chevron    = "▾"                     if is_selected else "›"
        chev_col   = fg                      if is_selected else "#4a5568"

        # Rendered as HTML — will display correctly
        card_html = f"""
<div class="card-wrap">
  <div style="background:{sel_bg};border:1px solid {sel_border};border-left:3px solid {border};
              border-radius:10px;padding:14px 18px;box-shadow:{sel_shadow};user-select:none;">
    <div style="display:flex;align-items:flex-start;gap:10px;">
      <div style="flex:1;min-width:0;overflow:hidden;">
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:7px;">
          <span style="background:{bg};color:{fg};font-size:9px;font-weight:700;
                       padding:1px 8px;border-radius:100px;text-transform:uppercase;">{sev_key.upper()}</span>
          {cat_html}{type_html}{hot_html}
          <span style="margin-left:auto;font-size:10px;color:#4a5568;">{time_str}</span>
        </div>
        <div style="font-size:14px;font-weight:600;color:#e8ecf4;line-height:1.4;margin-bottom:5px;
                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{title}</div>
        <div style="font-size:12px;color:#7a8599;line-height:1.5;
                    display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">{short_sum}</div>
        <div style="font-size:10px;color:#4a5568;margin-top:7px;">📰 {source}</div>
      </div>
      <div style="flex-shrink:0;font-size:18px;color:{chev_col};padding-top:2px;">{chevron}</div>
    </div>
  </div>"""

        st.markdown(card_html, unsafe_allow_html=True)
        # Invisible button sits on top of the card via CSS absolute positioning
        if st.button("click", key=f"card_{i}"):
            st.session_state["intel_selected_idx"] = None if is_selected else i
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

        # Detail panel expands right below the clicked card
        if is_selected:
            _render_detail_panel(row, {
                "title_col": title_col, "summary_col": summary_col,
                "source_col": source_col, "severity_col": severity_col,
                "impact_col": impact_col, "inc_type_col": inc_type_col,
                "entity_col": entity_col, "inc_date_col": inc_date_col,
                "pub_date_col": pub_date_col, "cat_col": cat_col,
                "country_col": country_col, "url_col": url_col, "kw_col": kw_col,
            }, sev_key, fg, bg)


def _render_detail_panel(row: "pd.Series", cols: dict, sev_key: str, fg: str, bg: str):
    """Render the expanded detail card — styled like the Flare intelligence UI."""

    SEV_FG = {"critical":"#f76c6c","high":"#f7a94f","medium":"#4f8ef7","low":"#3ecf8e","unknown":"#7a8599"}

    def _val(col_key):
        c = cols.get(col_key)
        if not c: return ""
        v = row.get(c, "")
        return "" if str(v).strip().lower() in ("","nan","none") else _strip_html(str(v))

    def _date_str(col_key):
        c = cols.get(col_key)
        if not c: return ""
        v = row.get(c)
        if pd.isna(v) if v is not None else True: return ""
        try: return v.strftime("%d %b %Y, %H:%M")
        except: return str(v)

    title     = _val("title_col")   or "Untitled"
    summary   = _val("summary_col")
    source    = _val("source_col")  or "Unknown source"
    cat       = _val("cat_col")
    inc_type  = _val("inc_type_col")
    entity    = _val("entity_col")
    country   = _val("country_col")
    url       = cols.get("url_col") and row.get(cols["url_col"],"") or ""
    url       = "" if str(url).strip().lower() in ("","nan","none") else str(url).strip()
    inc_date  = _date_str("inc_date_col")
    pub_date  = _date_str("pub_date_col")

    # keywords — handle plain string, comma-list, or Python list repr
    kw_col = cols.get("kw_col")
    kw_raw = str(row.get(kw_col, "")) if kw_col else ""
    # strip Python list wrapper e.g. "['foo', 'bar']" → "foo, bar"
    kw_raw = kw_raw.strip()
    if kw_raw.startswith("[") and kw_raw.endswith("]"):
        kw_raw = kw_raw[1:-1]
    # remove surrounding quotes on individual tokens
    kw_raw = _re.sub(r'["\']', '', kw_raw)
    keywords = [k.strip() for k in _re.split(r"[,;|]", kw_raw)
                if k.strip() and k.strip().lower() not in ("nan", "none", "")]

    cat_color  = _get_category_color(cat)
    type_color = _lighten_hex(cat_color, 0.4) if cat else "#7a8599"

    # severity score bar (risk_score if available)
    risk_score = row.get("risk_score", None)
    score_html = ""
    if risk_score is not None:
        pct = int(float(risk_score) * 100)
        score_html = f"""
        <div style="margin-bottom:14px;">
            <div style="display:flex;justify-content:space-between;margin-bottom:5px;">
                <span style="font-size:11px;color:#7a8599;font-family:IBM Plex Mono,monospace;text-transform:uppercase;letter-spacing:.09em;">Risk Score</span>
                <span style="font-size:12px;font-weight:700;color:{fg};font-family:IBM Plex Mono,monospace;">{float(risk_score):.3f}</span>
            </div>
            <div style="background:#1e2130;border-radius:4px;height:6px;">
                <div style="width:{pct}%;background:linear-gradient(90deg,{bg},{fg});height:6px;border-radius:4px;"></div>
            </div>
        </div>"""

    # sub-scores
    sub_scores_html = ""
    sub_labels = [("Sector","sector_score"),("Country","country_score"),
                  ("Attack","attack_type_score"),("Exposure","data_exposure_score")]
    sub_rows = [(lbl, row.get(key)) for lbl, key in sub_labels if row.get(key) is not None]
    if sub_rows:
        sub_html = "".join(
            f'<div style="flex:1;background:#0d1022;border:1px solid #1e2130;border-radius:8px;padding:10px 12px;text-align:center;">'
            f'<div style="font-size:18px;font-weight:700;color:{fg};font-family:IBM Plex Mono,monospace;">{float(v):.2f}</div>'
            f'<div style="font-size:10px;color:#7a8599;text-transform:uppercase;letter-spacing:.08em;margin-top:3px;">{lbl}</div>'
            f'</div>'
            for lbl, v in sub_rows
        )
        sub_scores_html = f'<div style="display:flex;gap:8px;margin-bottom:16px;">{sub_html}</div>'

    # keywords html
    kw_html = ""
    if keywords:
        kw_tags = "".join(
            f'<span style="font-size:11px;padding:3px 10px;border-radius:6px;'
            f'border:1px solid #1e2130;color:#7a8599;background:#0d1022;">{k}</span>'
            for k in keywords[:12]
        )
        kw_html = f'<div style="margin-bottom:16px;"><div style="font-size:11px;font-weight:600;color:#7a8599;text-transform:uppercase;letter-spacing:.09em;margin-bottom:8px;">Keywords</div><div style="display:flex;gap:6px;flex-wrap:wrap;">{kw_tags}</div></div>'

    url_html = ""
    if url:
        url_html = f'<a href="{url}" target="_blank" style="display:inline-flex;align-items:center;gap:6px;color:#4f8ef7;font-size:13px;text-decoration:none;font-weight:500;">🔗 View Original Source</a>'

    # meta row items
    meta_items = []
    if inc_date:  meta_items.append(("📅 Incident Date",  inc_date))
    if pub_date:  meta_items.append(("🗓 Published",       pub_date))
    if source:    meta_items.append(("📰 Source",          source))
    if country:   meta_items.append(("🌏 Country",         country))
    if entity:    meta_items.append(("🏢 Entity Affected", entity))
    if inc_type:  meta_items.append(("⚡ Incident Type",   inc_type))

    meta_html = "".join(
        f'<div style="background:#0d1022;border:1px solid #1e2130;border-radius:8px;padding:10px 14px;">'
        f'<div style="font-size:10px;color:#7a8599;text-transform:uppercase;letter-spacing:.09em;margin-bottom:4px;font-weight:600;">{label}</div>'
        f'<div style="font-size:13px;color:#e8ecf4;font-weight:500;">{value}</div>'
        f'</div>'
        for label, value in meta_items
    )
    meta_grid = f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin-bottom:16px;">{meta_html}</div>' if meta_html else ""

    # IQ Analysis block (like the screenshot)
    analysis_html = ""
    if summary:
        analysis_html = f"""
        <div style="background:#0d1535;border:1px solid #1a3a6e;border-radius:10px;padding:16px 18px;margin-bottom:16px;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
                <span style="font-size:16px;">🔍</span>
                <span style="font-size:13px;font-weight:700;color:#4f8ef7;letter-spacing:.04em;">Analysis</span>
            </div>
            <div style="font-size:13.5px;color:#b0bccf;line-height:1.75;">{summary}</div>
        </div>"""

    cat_badge  = f'<span style="background:{_hex_to_rgba(cat_color,0.15)};color:{cat_color};font-size:11px;font-weight:700;font-family:IBM Plex Mono,monospace;padding:3px 10px;border-radius:100px;text-transform:uppercase;">{cat}</span>' if cat else ""
    sev_badge  = f'<span style="background:{bg};color:{fg};font-size:11px;font-weight:700;font-family:IBM Plex Mono,monospace;padding:3px 10px;border-radius:100px;text-transform:uppercase;">{sev_key.upper()}</span>'

    # Build HTML via concatenation — avoids f-string brace conflicts from CSS in sub-vars
    panel_html = (
        f'<div style="background:#131829;border:1px solid {fg};border-top:3px solid {fg};'
        f'border-radius:12px;padding:24px 28px;margin:4px 0 16px;'
        f'box-shadow:0 4px 24px {fg}18;">'
        f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px;">'
        + sev_badge + cat_badge +
        f'</div>'
        f'<div style="font-size:19px;font-weight:700;color:#e8ecf4;line-height:1.4;margin-bottom:16px;">'
        + title +
        f'</div>'
        + score_html
        + sub_scores_html
        + meta_grid
        + analysis_html
        + kw_html
        + f'<div style="padding-top:8px;border-top:1px solid #1e2130;">{url_html}</div>'
        + '</div>'
    )
    st.markdown(panel_html, unsafe_allow_html=True)



# ══════════════════════════════════════════════════════════════════════════════
#  SECTOR CHART  (req #2)
# ══════════════════════════════════════════════════════════════════════════════
def _render_sector_chart(df: pd.DataFrame):
    sector_col = next((c for c in ("sector","industry","vertical") if c in df.columns), None)
    # fallback: derive from category
    if not sector_col and "category" in df.columns:
        sector_col = "category"
    if not sector_col or df[sector_col].dropna().empty:
        st.caption("No sector data available")
        return
    counts = df[sector_col].value_counts().head(12).reset_index()
    counts.columns = ["Sector", "Count"]
    colors = ["#4f8ef7","#3ecf8e","#f76c6c","#f7a94f","#a78bfa",
              "#34d399","#fb923c","#60a5fa","#f472b6","#38bdf8","#818cf8","#4ade80"]
    fig = go.Figure(go.Bar(
        x=counts["Count"], y=counts["Sector"], orientation="h",
        marker=dict(color=colors[:len(counts)]),
        text=counts["Count"], textposition="outside",
        textfont=dict(color="#7a8599", size=11),
        hovertemplate="<b>%{y}</b>: %{x}<extra></extra>",
    ))
    fig.update_layout(
        title="Highest Attacked Sectors",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#7a8599", size=12),
        title_font=dict(color="#e8ecf4", size=13),
        margin=dict(l=10,r=40,t=36,b=10), height=340,
        xaxis=dict(gridcolor="#1e2130", zerolinecolor="#1e2130"),
        yaxis=dict(categoryorder="total ascending",
                   tickfont=dict(color="#e8ecf4", size=11)),
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch")


# ══════════════════════════════════════════════════════════════════════════════
#  LINKED CATEGORY → INCIDENT TYPE CHART  (req #5)
#  Category gets a base colour; each incident_type under it gets a gradient shade
# ══════════════════════════════════════════════════════════════════════════════
def _render_linked_cat_type_chart(df: pd.DataFrame):
    if "category" not in df.columns:
        return
    inc_type_col = next((c for c in ("incident_type","type","attack_type") if c in df.columns), None)

    # ── LEFT: category bar ────────────────────────────────────────────────────
    cat_counts = df["category"].value_counts().head(10).reset_index()
    cat_counts.columns = ["Category","Count"]
    cat_colors = [_get_category_color(c) for c in cat_counts["Category"]]

    fig_cat = go.Figure(go.Bar(
        x=cat_counts["Count"], y=cat_counts["Category"], orientation="h",
        marker=dict(color=cat_colors),
        text=cat_counts["Count"], textposition="outside",
        textfont=dict(color="#7a8599", size=11),
        hovertemplate="<b>%{y}</b>: %{x}<extra></extra>",
    ))
    fig_cat.update_layout(
        title="Incidents by Category",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#7a8599", size=12),
        title_font=dict(color="#e8ecf4", size=13),
        margin=dict(l=10,r=40,t=36,b=10), height=340,
        xaxis=dict(gridcolor="#1e2130", zerolinecolor="#1e2130"),
        yaxis=dict(categoryorder="total ascending",
                   tickfont=dict(color="#e8ecf4", size=11)),
        showlegend=False,
    )

    # ── RIGHT: incident_type bar, coloured as gradient of its parent category ─
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(fig_cat, width="stretch")

    with c2:
        if not inc_type_col or df[inc_type_col].dropna().empty:
            st.caption("No incident type data")
            return

        # For each incident_type, find most common parent category → assign gradient colour
        type_cat = (
            df.dropna(subset=[inc_type_col, "category"])
              .groupby(inc_type_col)["category"]
              .agg(lambda x: x.value_counts().idxmax())
              .reset_index()
        )
        type_cat.columns = ["IncidentType", "ParentCategory"]

        type_counts = df[inc_type_col].value_counts().head(10).reset_index()
        type_counts.columns = ["IncidentType","Count"]
        type_counts = type_counts.merge(type_cat, on="IncidentType", how="left")

        # Each incident type gets a lightened version of its parent category colour
        type_colors = []
        for _, row in type_counts.iterrows():
            base = _get_category_color(str(row.get("ParentCategory","")))
            type_colors.append(_lighten_hex(base, 0.35))

        fig_type = go.Figure(go.Bar(
            x=type_counts["Count"], y=type_counts["IncidentType"], orientation="h",
            marker=dict(color=type_colors),
            text=type_counts["Count"], textposition="outside",
            textfont=dict(color="#7a8599", size=11),
            hovertemplate="<b>%{y}</b>: %{x}<extra></extra>",
        ))
        fig_type.update_layout(
            title="Incidents by Type  <span style='font-size:11px;color:#7a8599'>(colour = parent category)</span>",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#7a8599", size=12),
            title_font=dict(color="#e8ecf4", size=13),
            margin=dict(l=10,r=40,t=36,b=10), height=340,
            xaxis=dict(gridcolor="#1e2130", zerolinecolor="#1e2130"),
            yaxis=dict(categoryorder="total ascending",
                       tickfont=dict(color="#e8ecf4", size=11)),
            showlegend=False,
        )
        st.plotly_chart(fig_type, width="stretch")



def _render_impact_level_chart(df: pd.DataFrame):
    """Vertical bar chart: frequency of incidents by impact level (based on normalized risk_score)."""
    if "risk_score" not in df.columns:
        st.caption("No risk score data available")
        return

    def _classify(score):
        try:
            s = float(score)
        except (ValueError, TypeError):
            return "Unknown"
        if s > 0.8:   return "Critical"
        if s > 0.6:   return "High"
        if s > 0.4:   return "Medium"
        return "Low"

    level_order  = ["Critical", "High", "Medium", "Low"]
    level_colors = {"Critical": "#f76c6c", "High": "#f7a94f", "Medium": "#4f8ef7", "Low": "#3ecf8e"}

    counts = df["risk_score"].apply(_classify).value_counts().reindex(level_order, fill_value=0).reset_index()
    counts.columns = ["Impact Level", "Count"]
    colors = [level_colors[lv] for lv in counts["Impact Level"]]

    fig = go.Figure(go.Bar(
        x=counts["Impact Level"],
        y=counts["Count"],
        marker=dict(color=colors, opacity=0.9),
        text=counts["Count"],
        textposition="outside",
        textfont=dict(color="#e8ecf4", size=12, family="IBM Plex Mono"),
        hovertemplate="<b>%{x}</b><br>Count: %{y}<extra></extra>",
        width=0.5,
    ))
    fig.update_layout(
        title=dict(
            text="Risk Score Distribution  <span style='font-size:11px;color:#7a8599'>"
                 "(Critical >0.8 · High 0.6-0.8 · Medium 0.4-0.6 · Low ≤0.4)</span>",
            font=dict(color="#e8ecf4", size=13),
        ),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#7a8599", size=12),
        margin=dict(l=10, r=20, t=48, b=10),
        height=300,
        xaxis=dict(
            categoryorder="array", categoryarray=level_order,
            tickfont=dict(color="#e8ecf4", size=13, family="IBM Plex Mono"),
            gridcolor="rgba(0,0,0,0)", zeroline=False,
        ),
        yaxis=dict(
            gridcolor="#1e2130", zerolinecolor="#1e2130",
            tickfont=dict(color="#7a8599", size=11),
        ),
        showlegend=False,
        bargap=0.35,
    )
    st.plotly_chart(fig, width="stretch")


def _render_trending_news(df: pd.DataFrame, max_items: int = 5):
    """Display critical-level news as a trending carousel strip."""
    if "risk_score" not in df.columns:
        return

    crit_df = df[df["risk_score"].apply(
        lambda s: (float(s) > 0.8) if str(s) not in ("", "nan", "None") else False
    )].copy()

    date_col = next((c for c in ("incident_date", "publication_date") if c in crit_df.columns), None)
    if date_col:
        crit_df = crit_df.sort_values(date_col, ascending=False)
    crit_df = crit_df.head(max_items).reset_index(drop=True)

    if crit_df.empty:
        return

    title_col   = next((c for c in ("title","headline","name")        if c in crit_df.columns), None)
    source_col  = next((c for c in ("source","origin","feed")         if c in crit_df.columns), None)
    cat_col     = "category" if "category" in crit_df.columns else None
    risk_col    = "risk_score"

    now = now_my()

    cards_html = ""
    for _, row in crit_df.iterrows():
        title  = _strip_html(str(row.get(title_col,  "Untitled") if title_col  else "Untitled"))
        source = _strip_html(str(row.get(source_col, "Unknown")  if source_col else "Unknown"))
        cat    = str(row.get(cat_col, "") if cat_col else "").strip()
        score  = float(row.get(risk_col, 0))

        time_str = ""
        if date_col and pd.notna(row.get(date_col)):
            try:
                mins = int((now - row[date_col]).total_seconds() / 60)
                if   mins < 1:    time_str = "just now"
                elif mins < 60:   time_str = f"{mins}m ago"
                elif mins < 1440: time_str = f"{mins//60}h ago"
                else:             time_str = f"{mins//1440}d ago"
            except: pass

        short_title = title[:80] + "…" if len(title) > 80 else title
        cat_color   = _get_category_color(cat)

        cards_html += f"""
<div style="flex:0 0 280px;background:#1a0a0a;border:1px solid #f76c6c44;
            border-left:3px solid #f76c6c;border-radius:10px;padding:14px 16px;
            display:flex;flex-direction:column;gap:8px;cursor:default;">
  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
    <span style="background:#3d0f0f;color:#f76c6c;font-size:9px;font-weight:700;
                 padding:1px 8px;border-radius:100px;text-transform:uppercase;
                 font-family:'IBM Plex Mono',monospace;">🔥 CRITICAL</span>
    {'<span style="background:' + _hex_to_rgba(cat_color,0.15) + ';color:' + cat_color + ';font-size:9px;font-weight:700;padding:1px 7px;border-radius:100px;text-transform:uppercase;">' + cat + '</span>' if cat and cat.lower() not in ('nan','none','') else ''}
    <span style="margin-left:auto;font-size:10px;color:#4a5568;font-family:'IBM Plex Mono',monospace;">{time_str}</span>
  </div>
  <div style="font-size:13px;font-weight:600;color:#f0f0f0;line-height:1.4;">{short_title}</div>
  <div style="display:flex;align-items:center;justify-content:space-between;margin-top:auto;">
    <span style="font-size:10px;color:#7a8599;">📰 {source}</span>
    <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:700;color:#f76c6c;">
      {score:.3f}
    </span>
  </div>
</div>"""

    st.markdown(f"""
<div style="display:flex;gap:12px;overflow-x:auto;padding:4px 2px 12px;
            scrollbar-width:thin;scrollbar-color:#21262d transparent;">
  {cards_html}
</div>
""", unsafe_allow_html=True)


def page_cyber_news():
    # ── Load ALL incidents first (needed to populate filter options) ──────────
    @st.cache_data(ttl=120, show_spinner=False)
    def load_incidents():
        return get_data("cyber_news")   # ← paginated, returns ALL rows

    with st.spinner("Loading incidents…"):
        df_raw = load_incidents()

    if df_raw is None or df_raw.empty:
        st.error("⚠️ Could not load data from Supabase. Check your `.streamlit/secrets.toml`.")
        with st.sidebar:
            _sidebar_branding()
            _sidebar_footer()
        st.stop()

    # ── Parse dates ──────────────────────────────────────────────────────────
    df_all = df_raw.copy()
    for col in ("incident_date", "publication_date"):
        if col in df_all.columns:
            df_all[col] = pd.to_datetime(
                df_all[col], errors="coerce", utc=True
            ).dt.tz_convert(TZ_MY)

    # ── Sidebar (uses df_all for dynamic filter options) ─────────────────────
    with st.sidebar:
        _sidebar_branding()
        st.markdown(_filter_label(), unsafe_allow_html=True)

        min_date = df_all["incident_date"].dropna().min().date() \
                   if "incident_date" in df_all.columns and not df_all["incident_date"].isna().all() \
                   else date(2026, 1, 1)

        date_range = st.date_input(
            "Date range (GMT+8)",
            value=(min_date, now_my().date()),
            max_value=now_my().date(),
            key="news_date",
        )

        cat_opts     = sorted(df_all["category"].dropna().unique().tolist()) \
                       if "category" in df_all.columns else []
        country_opts = sorted(df_all["country"].dropna().unique().tolist()) \
                       if "country" in df_all.columns else []

        category_filter = st.multiselect("Category", options=cat_opts,
                                          placeholder="All categories", key="news_cat")
        country_filter  = st.multiselect("Country",  options=country_opts,
                                          placeholder="All countries",  key="news_ctry")
        impact_filter   = st.multiselect("Impact",
                                          options=["Critical","High","Medium","Low","Unknown"],
                                          placeholder="All impacts",    key="news_impact")

        _sidebar_footer()

    page_header("📰 Cyber News", "Threat intelligence · Incident feed · Real-time monitoring")

    # ── Apply filters ─────────────────────────────────────────────────────────
    df = df_all.copy()

    if len(date_range) == 2:
        s = pd.Timestamp(date_range[0], tz=TZ_MY)
        e = pd.Timestamp(date_range[1], tz=TZ_MY) + timedelta(days=1) - timedelta(seconds=1)
        if "incident_date" in df.columns:
            df = df[df["incident_date"].between(s, e, inclusive="both")]

    if category_filter and "category" in df.columns:
        df = df[df["category"].isin(category_filter)]
    if country_filter and "country" in df.columns:
        df = df[df["country"].isin(country_filter)]
    if impact_filter and "impact" in df.columns:
        df = df[df["impact"].isin(impact_filter)]

    # ── KPIs ──────────────────────────────────────────────────────────────────
    total_incidents    = len(df)
    total_sources      = df["source"].nunique() if "source" in df.columns else 0
    critical_count     = int((df["risk_score"].apply(
                             lambda s: float(s) > 0.8 if str(s) not in ("","nan","None") else False
                         )).sum()) if "risk_score" in df.columns else (
                             len(df[df["impact"].str.lower() == "critical"])
                             if "impact" in df.columns else 0
                         )
    countries_affected = df.loc[
        df["country"].notna() & (df["country"] != "Unknown"), "country"
    ].nunique() if "country" in df.columns else 0

    new_this_week = len(
        df[df["incident_date"] >= (now_my() - timedelta(days=7))]
    ) if "incident_date" in df.columns else 0

    k1, k2, k3, k4, k5 = st.columns(5)
    kpi_row([
        (k1, total_incidents,    "Total News Crawled", f"+{new_this_week} this week", "up"),
        (k2, total_sources,      "Crawled Sources",    "Unique domains",              ""),
        (k3, critical_count,     "Critical Incidents", "Needs attention",             "warn" if critical_count else ""),
        (k4, countries_affected, "Countries Affected", "Unique nations",              ""),
        (k5, new_this_week,      "New This Week",      "Last 7 days",                 "up"),
    ])

    # ── Search bar (above Cyber News Feed) ───────────────────────────────────
    st.markdown("<div class='section-header'>Search</div>", unsafe_allow_html=True)
    search_q = st.text_input(
        "search_bar",
        placeholder="🔍  Search by keyword, title, entity, category, incident type…",
        label_visibility="collapsed",
        key="feed_search",
    )

    # ── Charts ────────────────────────────────────────────────────────────────
    st.markdown("<div class='section-header'>Incident Overview</div>", unsafe_allow_html=True)
    _render_linked_cat_type_chart(df)

    # ── Impact Level Distribution ─────────────────────────────────────────────
    st.markdown("<div class='section-header'>Impact Level Distribution</div>", unsafe_allow_html=True)
    il1, il2 = st.columns([2, 1])
    with il1: _render_impact_level_chart(df)
    with il2: render_impact_distribution(df)

    st.markdown("<div class='section-header'>Highest Attacked Sectors</div>", unsafe_allow_html=True)
    sc1, sc2 = st.columns([2, 1])
    with sc1: _render_sector_chart(df)

    st.markdown("<div class='section-header'>Trends & Geography</div>", unsafe_allow_html=True)
    c3, c4 = st.columns([2, 1])
    with c3: render_timeline(df)
    with c4: render_incidents_by_country(df)

    st.markdown("<div class='section-header'>Sources & Keywords</div>", unsafe_allow_html=True)
    sw1, sw2 = st.columns(2)
    with sw1: render_source_breakdown(df)
    with sw2: render_wordcloud(df, column="relevant_keywords", title="Relevant Keywords")

    # ── Trending Critical News ────────────────────────────────────────────────
    if "risk_score" in df.columns:
        crit_count = int((df["risk_score"].apply(
            lambda s: float(s) > 0.8 if str(s) not in ("", "nan", "None") else False
        )).sum())
        if crit_count:
            st.markdown(
                f"<div class='section-header'>🔥 Trending — Critical Incidents "
                f"<span style='font-size:11px;background:#3d0f0f;color:#f76c6c;"
                f"border-radius:100px;padding:2px 10px;margin-left:8px;'>{crit_count} critical</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            _render_trending_news(df, max_items=6)

    # ── Cyber News Feed ───────────────────────────────────────────────────────
    st.markdown("<div class='section-header'>Cyber News Feed</div>", unsafe_allow_html=True)

    feed_df = df.copy()
    if search_q.strip():
        q = search_q.strip().lower()
        mask = pd.Series(False, index=feed_df.index)
        for col in ("title","summary","category","incident_type","entity_affected",
                    "relevant_keywords","country","source"):
            if col in feed_df.columns:
                mask |= feed_df[col].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        feed_df = feed_df[mask]

    total_feed = len(feed_df)

    st.markdown(
        f"<div style='display:flex;align-items:center;gap:8px;"
        f"font-family:\"IBM Plex Mono\",monospace;font-size:11px;"
        f"color:#484f58;margin:6px 0 10px;'>"
        f"<span style='width:8px;height:8px;border-radius:50%;background:#ff6b6b;"
        f"display:inline-block;animation:blink 1.8s ease-in-out infinite;flex-shrink:0;'></span>"
        f"<span style='color:#f0f6fc;font-weight:700;text-transform:uppercase;letter-spacing:.12em;'>"
        f"Cyber News Feed</span>"
        f"<span style='background:#161b22;border:1px solid #21262d;border-radius:100px;"
        f"padding:2px 10px;font-size:10px;'>{total_feed} items</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    render_intel_feed(feed_df, max_items=20)


    # ── Raw data expander ─────────────────────────────────────────────────────
    with st.expander("📋 View raw incident data"):
        preferred  = ["id","title","incident_date","publication_date",
                      "category","incident_type","country","impact","source"]
        show_cols  = [c for c in preferred if c in df.columns] or list(df.columns)
        display_df = df[show_cols].copy()
        if "incident_date" in display_df.columns:
            display_df = display_df.sort_values("incident_date", ascending=False)
        st.dataframe(display_df, width='stretch', hide_index=True)
        with st.expander("🔍 Debug: column names & row count"):
            st.code(
                f"Rows fetched (raw): {len(df_raw)}\n"
                f"Rows after filter:  {len(df)}\n"
                f"Columns: {list(df_raw.columns)}"
            )


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 2 — RANSOMWARE LIVE
# ══════════════════════════════════════════════════════════════════════════════
def page_ransomware():
    @st.cache_data(ttl=300, show_spinner=False)
    def load_ransomware():
        return get_data("ransomware_victims")   # ← paginated

    with st.spinner("Loading ransomware data…"):
        rw_raw = load_ransomware()

    with st.sidebar:
        _sidebar_branding()
        st.markdown(_filter_label(), unsafe_allow_html=True)

        _rw_tmp = rw_raw.copy() if rw_raw is not None and not rw_raw.empty else pd.DataFrame()
        if "date" in _rw_tmp.columns:
            _rw_tmp["date"] = pd.to_datetime(_rw_tmp["date"], errors="coerce", utc=True).dt.tz_convert(TZ_MY)

        rw_min_date = _rw_tmp["date"].dropna().min().date() \
                      if "date" in _rw_tmp.columns and not _rw_tmp["date"].isna().all() \
                      else date(2024, 1, 1)

        rw_date_range = st.date_input(
            "Date range",
            value=(rw_min_date, now_my().date()),
            max_value=now_my().date(),
            key="rw_date",
        )

        rw_country_opts = sorted(_rw_tmp["country"].dropna().unique().tolist()) \
                          if "country" in _rw_tmp.columns else []
        rw_sector_opts  = sorted(_rw_tmp["sector"].dropna().unique().tolist()) \
                          if "sector"  in _rw_tmp.columns else []

        rw_country_filter  = st.multiselect("Country",  options=rw_country_opts,
                                             placeholder="All countries",  key="rw_country")
        rw_sector_filter   = st.multiselect("Sector",   options=rw_sector_opts,
                                             placeholder="All sectors",    key="rw_sector")
        rw_severity_filter = st.multiselect("Severity",
                                             options=["Critical","High","Medium","Low"],
                                             placeholder="All severities", key="rw_severity")

        _sidebar_footer()

    page_header("🔴 Ransomware Live", "Real-time victim tracker · Powered by ransomware.live")

    if rw_raw is None or rw_raw.empty:
        st.warning("⚠️ No ransomware data found. The table may be empty or not yet crawled.")
        st.stop()

    rw = rw_raw.copy()
    if "date" in rw.columns:
        rw["date"] = pd.to_datetime(rw["date"], errors="coerce", utc=True).dt.tz_convert(TZ_MY)

    rw_f     = rw.copy()
    date_col = "date" if "date" in rw_f.columns else None

    if date_col and len(rw_date_range) == 2:
        s = pd.Timestamp(rw_date_range[0], tz=TZ_MY)
        e = pd.Timestamp(rw_date_range[1], tz=TZ_MY) + timedelta(days=1) - timedelta(seconds=1)
        rw_f = rw_f[rw_f[date_col].between(s, e, inclusive="both")]
    if rw_country_filter and "country" in rw_f.columns:
        rw_f = rw_f[rw_f["country"].isin(rw_country_filter)]
    if rw_sector_filter and "sector" in rw_f.columns:
        rw_f = rw_f[rw_f["sector"].isin(rw_sector_filter)]
    if rw_severity_filter and "severity" in rw_f.columns:
        rw_f = rw_f[rw_f["severity"].isin(rw_severity_filter)]

    total_victims  = len(rw_f)
    total_sectors  = rw_f["sector"].nunique()  if "sector"  in rw_f.columns else 0
    top_sector     = rw_f["sector"].value_counts().idxmax() \
                     if "sector" in rw_f.columns and total_victims > 0 else "—"
    rw_countries_n = rw_f["country"].nunique() if "country" in rw_f.columns else 0
    new_rw_week    = len(rw_f[rw_f[date_col] >= now_my() - timedelta(days=7)]) \
                     if date_col else 0

    rk1, rk2, rk3, rk4, rk5 = st.columns(5)
    kpi_row([
        (rk1, total_victims,  "Total Victims",        f"+{new_rw_week} this week", "warn"),
        (rk2, total_sectors,  "Affected Sectors",     "Tracked sectors",            "warn"),
        (rk3, f'<span style="color:#cc0000">{top_sector}</span>', "Most Targeted Sector", "By victim count", ""),
        (rk4, rw_countries_n, "Countries Hit",        "Unique nations",             ""),
        (rk5, new_rw_week,    "New This Week",        "Last 7 days",                "warn" if new_rw_week else ""),
    ])

    st.markdown("<div class='section-header'>Attack Trends</div>", unsafe_allow_html=True)
    if date_col and not rw_f.empty:
        tl = rw_f.set_index(date_col).resample("W").size().reset_index(name="victims")
        tl.columns = ["week", "victims"]
        fig = px.area(tl, x="week", y="victims", title="Weekly Victims",
                      color_discrete_sequence=["#f78166"], template="plotly_dark")
        fig.update_traces(fill="tozeroy", fillcolor="rgba(247,129,102,0.15)", line=dict(color="#f78166", width=2))
        fig.update_layout(paper_bgcolor="#161b22", plot_bgcolor="#161b22",
                          font_color="#c9d1d9", title_font_color="#f0f6fc",
                          xaxis=dict(showgrid=False),
                          yaxis=dict(showgrid=True, gridcolor="#21262d", tickformat="d", dtick=1),
                          margin=dict(l=10,r=10,t=40,b=10))
        st.plotly_chart(fig, width='stretch')

    st.markdown("<div class='section-header'>Sectors</div>", unsafe_allow_html=True)
    rc2, rc4 = st.columns([1, 1])
    with rc2:
        if "sector" in rw_f.columns and not rw_f.empty:
            tg = rw_f["sector"].value_counts().head(10).reset_index()
            tg.columns = ["sector", "count"]
            fig = px.pie(tg, names="sector", values="count", title="Top Targeted Sectors",
                         color_discrete_sequence=px.colors.sequential.Reds_r,
                         hole=0.4, template="plotly_dark")
            fig.update_layout(paper_bgcolor="#161b22", font_color="#c9d1d9",
                              title_font_color="#fcf3f0",
                              legend=dict(font=dict(size=10)),
                              margin=dict(l=10,r=10,t=40,b=10))
            st.plotly_chart(fig, width='stretch')

    with rc4:
        if "threat_actor" in rw_f.columns and not rw_f.empty:
            ta = rw_f["threat_actor"].value_counts().head(5).reset_index()
            ta.columns = ["threat_actor", "count"]
            fig = px.bar(ta, x="count", y="threat_actor", orientation="h",
                         title="Top 5 Threat Actors",
                         color="count", color_continuous_scale=["#21262d","#f78166"],
                         template="plotly_dark")
            fig.update_layout(paper_bgcolor="#161b22", plot_bgcolor="#161b22",
                              font_color="#c9d1d9", title_font_color="#f0f6fc",
                              yaxis=dict(autorange="reversed"),
                              coloraxis_showscale=False,
                              margin=dict(l=10,r=10,t=40,b=10))
            st.plotly_chart(fig, width='stretch')

    if "severity" in rw_f.columns and not rw_f.empty:
        st.markdown("<div class='section-header'>Severity Distribution</div>", unsafe_allow_html=True)
        sv1, sv2 = st.columns([1, 2])
        SEV_ORDER  = ["Critical","High","Medium","Low"]
        SEV_COLORS = {"Critical":"#ff6b6b","High":"#ffa94d","Medium":"#a9d64b","Low":"#4fc3f7"}
        sev_counts = (rw_f["severity"].value_counts()
                      .reindex(SEV_ORDER).dropna().reset_index())
        sev_counts.columns = ["severity","count"]
        with sv1:
            for _, row in sev_counts.iterrows():
                pct   = int(row["count"] / total_victims * 100) if total_victims else 0
                color = SEV_COLORS.get(row["severity"], "#8b949e")
                st.markdown(f"""
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;
                            background:#161b22;border:1px solid #21262d;
                            border-left:3px solid {color};border-radius:8px;padding:10px 14px;">
                    <span style="font-size:13px;font-weight:600;color:{color};min-width:68px;">{row['severity']}</span>
                    <div style="flex:1;background:#21262d;border-radius:4px;height:8px;">
                        <div style="width:{pct}%;background:{color};height:8px;border-radius:4px;"></div>
                    </div>
                    <span style="font-family:IBM Plex Mono,monospace;font-size:12px;
                                 color:#8b949e;min-width:72px;text-align:right;">
                        {int(row['count']):,} ({pct}%)
                    </span>
                </div>""", unsafe_allow_html=True)
        with sv2:
            fig = px.bar(sev_counts, x="severity", y="count", title="Victims by Severity",
                         color="severity", color_discrete_map=SEV_COLORS,
                         category_orders={"severity": SEV_ORDER}, template="plotly_dark")
            fig.update_layout(paper_bgcolor="#161b22", plot_bgcolor="#161b22",
                              font_color="#c9d1d9", title_font_color="#f0f6fc",
                              showlegend=False, margin=dict(l=10,r=10,t=40,b=10))
            st.plotly_chart(fig, width='stretch')

    st.markdown("<div class='section-header'>Recent Victim Posts</div>", unsafe_allow_html=True)
    SEV_CLASS = {"critical":"sev-critical","high":"sev-high","medium":"sev-medium","low":"sev-low"}
    if not rw_f.empty and date_col:
        for _, row in rw_f.sort_values(date_col, ascending=False).head(30).iterrows():
            title    = row.get("organization", "Unknown Victim")
            country  = row.get("country",  "—")
            sector   = row.get("sector",   "—")
            severity = row.get("severity", "—")
            disc     = row.get("date", pd.NaT)
            disc_str = disc.strftime("%d %b %Y, %H:%M") if pd.notna(disc) else "—"
            sev_cls  = SEV_CLASS.get(str(severity).lower(), "")
            st.markdown(f"""
            <div class="victim-card">
                <div class="victim-name">{title}</div>
                <div class="victim-meta">
                    📅 {disc_str} &nbsp;·&nbsp; 🌏 {country} &nbsp;·&nbsp; 🏭 {sector}
                </div>
                <span class="victim-badge {sev_cls}">⚠ {severity}</span>
            </div>""", unsafe_allow_html=True)
    else:
        st.info("No victims match the current filters.")

    with st.expander("📋 View raw ransomware data"):
        preferred_rw = ["organization","country","sector","severity","date"]
        show_rw      = [c for c in preferred_rw if c in rw_f.columns] or list(rw_f.columns)
        rw_disp      = rw_f[show_rw].copy()
        if date_col: rw_disp = rw_disp.sort_values(date_col, ascending=False)
        st.dataframe(rw_disp, width='stretch', hide_index=True)
        with st.expander("🔍 Debug: column names"):
            st.code(
                f"Rows fetched (raw): {len(rw_raw)}\n"
                f"Rows after filter:  {len(rw_f)}\n"
                f"Columns: {list(rw_raw.columns)}"
            )


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 3 — AI ANALYST
# ══════════════════════════════════════════════════════════════════════════════
def page_ai_analyst():
    page_header("🤖 AI Analyst", "Ask anything about the threat landscape · Powered by Groq")

    st.markdown("""
    <div class="chat-hero">
        <div style="font-size:48px;">🤖</div>
        <div class="chat-hero-title">Incident Intelligence Analyst</div>
        <div class="chat-hero-sub">
            Ask questions about incidents, ransomware trends, affected sectors,
            countries, threat actors — backed by your live Supabase data.
        </div>
    </div>
    """, unsafe_allow_html=True)

    @st.cache_data(ttl=120, show_spinner=False)
    def load_incidents_for_chat():
        return get_data("cyber_news")

    with st.spinner("Preparing data context for AI…"):
        df_chat = load_incidents_for_chat()

    if df_chat is not None and not df_chat.empty:
        for col in ("incident_date", "publication_date"):
            if col in df_chat.columns:
                df_chat[col] = pd.to_datetime(
                    df_chat[col], errors="coerce", utc=True
                ).dt.tz_convert(TZ_MY)
        chatbot_ui(df_chat)
    else:
        st.error("⚠️ Could not load incident data. Check your Supabase connection.")


# ══════════════════════════════════════════════════════════════════════════════
#  NAVIGATION
# ══════════════════════════════════════════════════════════════════════════════
pg = st.navigation(
    [
        st.Page(page_cyber_news,  title="Cyber News",      icon="📰", default=True),
        st.Page(page_ransomware,  title="Ransomware Live", icon="🔴"),
        st.Page(page_ai_analyst,  title="AI Analyst",      icon="🤖"),
    ],
    position="top",
)

pg.run()
