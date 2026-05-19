"""
utils/chatbot.py
Groq-powered AI analyst with a floating bubble toggle.
- The bubble button & chat panel are pure Streamlit (st.chat_input / st.chat_message)
- A CSS trick slides a named container in/out when the toggle is clicked
- No iframe bridge hacks — works reliably on Streamlit Cloud
"""

import streamlit as st
import pandas as pd
import json

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False


# ─────────────────────────────────────────────────────────────
#  System prompt
# ─────────────────────────────────────────────────────────────

def _build_system_prompt(df: pd.DataFrame) -> str:
    lines = [
        "You are an expert cybersecurity and incident intelligence analyst.",
        "You are embedded in a live incident monitoring dashboard.",
        "Answer questions concisely and accurately using the data context below.",
        "If asked to analyse trends or make predictions, reason step by step.",
        "",
        "=== CURRENT DASHBOARD DATA SUMMARY ===",
        f"Total incidents: {len(df)}",
    ]

    def top5(col):
        if col in df.columns:
            return df[col].value_counts().head(5).to_dict()
        return {}

    for label, col in [
        ("Top categories",        "category"),
        ("Top incident types",    "incident_type"),
        ("Top countries",         "country"),
        ("Impact breakdown",      "impact"),
        ("Top sources",           "source"),
        ("Top entities affected", "entity_affected"),
    ]:
        d = top5(col)
        if d:
            lines.append(f"{label}: {json.dumps(d)}")

    if "incident_date" in df.columns:
        dated = df.dropna(subset=["incident_date"])
        if not dated.empty:
            lines.append(
                f"Date range: {dated['incident_date'].min().date()} "
                f"to {dated['incident_date'].max().date()} (GMT+8)"
            )

    lines += [
        "===",
        "",
        "Respond in clear English. Use bullet points for lists.",
        "Keep responses under 300 words unless more detail is requested.",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  Groq client (cached)
# ─────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def _get_client(_bust=None):
    if not GROQ_AVAILABLE:
        return None, "package_missing"
    if "groq" not in st.secrets or "api_key" not in st.secrets["groq"]:
        return None, "missing_key"
    try:
        return Groq(api_key=st.secrets["groq"]["api_key"]), "ok"
    except Exception as e:
        return None, str(e)


# ─────────────────────────────────────────────────────────────
#  Main UI
# ─────────────────────────────────────────────────────────────

def chatbot_ui(df: pd.DataFrame):
    # ── Session state ──────────────────────────────────────────
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "chat_open" not in st.session_state:
        st.session_state.chat_open = False

    # ── Global CSS: floating bubble + slide-in panel ───────────
    st.markdown("""
    <style>
    /* ── Floating Action Button ── */
    #groq-fab-anchor {
        position: fixed;
        bottom: 28px;
        right: 28px;
        z-index: 9999;
    }
    /* ── Chat panel wrapper ── */
    #groq-chat-panel {
        position: fixed;
        bottom: 100px;
        right: 28px;
        width: 400px;
        max-height: 600px;
        background: #0d1117;
        border: 1px solid #30363d;
        border-radius: 16px;
        box-shadow: 0 12px 48px rgba(0,0,0,0.65);
        z-index: 9998;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        font-family: 'IBM Plex Sans', sans-serif;
    }
    /* panel header */
    #groq-chat-panel .gcp-header {
        background: linear-gradient(135deg,#161b22,#1c2128);
        border-bottom: 1px solid #21262d;
        padding: 14px 16px;
        display: flex;
        align-items: center;
        gap: 10px;
        flex-shrink: 0;
    }
    #groq-chat-panel .gcp-avatar {
        width:32px; height:32px;
        background: linear-gradient(135deg,#f55036,#f97316);
        border-radius:50%;
        display:flex; align-items:center; justify-content:center;
        font-size:15px; flex-shrink:0;
    }
    #groq-chat-panel .gcp-title  { font-weight:600; font-size:14px; color:#f0f6fc; }
    #groq-chat-panel .gcp-sub    { font-size:11px; color:#8b949e; margin-top:1px; }
    /* scrollable messages area */
    #groq-chat-panel .gcp-body {
        flex:1; overflow-y:auto; padding:14px;
        display:flex; flex-direction:column; gap:10px;
        scrollbar-width:thin; scrollbar-color:#30363d transparent;
    }
    #groq-chat-panel .gcp-body::-webkit-scrollbar { width:4px; }
    #groq-chat-panel .gcp-body::-webkit-scrollbar-thumb { background:#30363d; border-radius:4px; }
    /* message bubbles */
    .gc-msg { display:flex; flex-direction:column; max-width:88%; }
    .gc-msg.user { align-self:flex-end; align-items:flex-end; }
    .gc-msg.bot  { align-self:flex-start; align-items:flex-start; }
    .gc-role { font-size:10px; font-weight:600; letter-spacing:.07em;
               text-transform:uppercase; margin-bottom:3px; }
    .gc-msg.user .gc-role { color:#388bfd; }
    .gc-msg.bot  .gc-role { color:#f55036; }
    .gc-bubble { padding:10px 13px; border-radius:14px;
                 font-size:13px; line-height:1.55; color:#c9d1d9; }
    .gc-msg.user .gc-bubble { background:#1f3349; border:1px solid #2d4a6e; border-bottom-right-radius:4px; }
    .gc-msg.bot  .gc-bubble { background:#161b22; border:1px solid #21262d; border-bottom-left-radius:4px; }
    /* suggestion chips row */
    .gc-chips { padding:8px 14px 6px; display:flex; flex-wrap:wrap; gap:6px;
                border-top:1px solid #161b22; flex-shrink:0; }
    /* input area — we push st.chat_input here via a container trick */
    .gc-input-wrap {
        border-top: 1px solid #21262d;
        flex-shrink: 0;
        padding: 6px 10px 8px;
        background: #0d1117;
    }
    /* restyle Streamlit's chat input inside the panel */
    #groq-chat-panel .stChatInput { border: none !important; background: transparent !important; }
    #groq-chat-panel .stChatInput > div { background: #161b22 !important;
        border: 1px solid #30363d !important; border-radius: 20px !important; }
    #groq-chat-panel .stChatInput textarea {
        color: #c9d1d9 !important; font-size:13px !important; }
    #groq-chat-panel .stChatInput button {
        background: linear-gradient(135deg,#f55036,#f97316) !important;
        border-radius: 50% !important; }
    /* empty state */
    .gc-empty { text-align:center; padding:28px 16px;
                color:#484f58; font-size:13px; line-height:1.7; }
    .gc-empty-icon { font-size:34px; margin-bottom:8px; }
    /* typing dots */
    .gc-typing { display:flex; gap:4px; align-items:center; padding:4px 2px; }
    .gc-dot { width:6px; height:6px; background:#f55036; border-radius:50%;
              animation:gc-bounce 1.2s infinite; }
    .gc-dot:nth-child(2){ animation-delay:.2s; }
    .gc-dot:nth-child(3){ animation-delay:.4s; }
    @keyframes gc-bounce {
        0%,60%,100%{ transform:translateY(0); }
        30%{ transform:translateY(-5px); }
    }
    </style>
    """, unsafe_allow_html=True)

    # ── FAB toggle button (native Streamlit, fixed position via CSS) ──────────
    # We render the button inside a container that's CSS-positioned
    st.markdown('<div id="groq-fab-anchor">', unsafe_allow_html=True)
    msg_count = len(st.session_state.chat_history)
    badge = f" ({msg_count})" if msg_count > 0 and not st.session_state.chat_open else ""
    fab_label = "✕ Close" if st.session_state.chat_open else f"💬 Ask AI{badge}"

    if st.button(fab_label, key="groq_fab_btn", help="Toggle Groq AI Analyst"):
        st.session_state.chat_open = not st.session_state.chat_open
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # Style the FAB button
    st.markdown("""
    <style>
    #groq-fab-anchor button {
        position: fixed !important;
        bottom: 28px !important;
        right: 28px !important;
        z-index: 9999 !important;
        background: linear-gradient(135deg, #f55036, #f97316) !important;
        color: white !important;
        border: none !important;
        border-radius: 28px !important;
        padding: 12px 20px !important;
        font-size: 14px !important;
        font-weight: 600 !important;
        box-shadow: 0 4px 20px rgba(245,80,54,0.45) !important;
        cursor: pointer !important;
        transition: transform 0.2s, box-shadow 0.2s !important;
        white-space: nowrap !important;
        min-width: unset !important;
        width: auto !important;
        height: auto !important;
    }
    #groq-fab-anchor button:hover {
        transform: scale(1.05) !important;
        box-shadow: 0 6px 28px rgba(245,80,54,0.6) !important;
    }
    /* hide the streamlit wrapper chrome */
    #groq-fab-anchor > div { margin: 0 !important; }
    div[data-testid="stButton"]:has(button[kind="secondary"]#groq_fab_btn) { display:contents; }
    </style>
    """, unsafe_allow_html=True)

    # ── Chat panel (only rendered when open) ──────────────────────────────────
    if not st.session_state.chat_open:
        return

    st.markdown('<div id="groq-chat-panel">', unsafe_allow_html=True)

    # Header
    st.markdown("""
    <div class="gcp-header">
        <div class="gcp-avatar">⚡</div>
        <div>
            <div class="gcp-title">Groq AI Analyst</div>
            <div class="gcp-sub">Llama 3.3-70b · Free tier · Incident Intelligence</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Messages body
    st.markdown('<div class="gcp-body">', unsafe_allow_html=True)
    if not st.session_state.chat_history:
        st.markdown("""
        <div class="gc-empty">
            <div class="gc-empty-icon">🛡️</div>
            <strong style="color:#8b949e">Groq Analyst ready</strong><br>
            Ask about incidents, trends,<br>or threat intelligence.
        </div>
        """, unsafe_allow_html=True)
    else:
        for msg in st.session_state.chat_history:
            role  = "user" if msg["role"] == "user" else "bot"
            label = "You" if msg["role"] == "user" else "Groq Analyst"
            safe  = msg["content"].replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            st.markdown(f"""
            <div class="gc-msg {role}">
                <div class="gc-role">{label}</div>
                <div class="gc-bubble">{safe}</div>
            </div>
            """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # Quick suggestion chips (as real buttons)
    suggestions = [
        "Top critical incidents",
        "Which country has most incidents?",
        "Main threat categories",
        "Any emerging trends?",
    ]
    st.markdown('<div class="gc-chips">', unsafe_allow_html=True)
    chip_cols = st.columns(len(suggestions))
    for i, (col, tip) in enumerate(zip(chip_cols, suggestions)):
        with col:
            if st.button(tip, key=f"chip_{i}", help=tip):
                st.session_state["_groq_chip"] = tip
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # Input area
    st.markdown('<div class="gc-input-wrap">', unsafe_allow_html=True)
    user_input = st.chat_input("Ask the analyst…", key="groq_chat_input")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)  # close #groq-chat-panel

    # ── Handle chip pre-fill ───────────────────────────────────────────────────
    question = user_input
    if not question and "_groq_chip" in st.session_state:
        question = st.session_state.pop("_groq_chip")

    # ── Call Groq and stream answer ────────────────────────────────────────────
    if question and question.strip():
        question = question.strip()

        # Deduplicate
        if (st.session_state.chat_history
                and st.session_state.chat_history[-1]["role"] == "user"
                and st.session_state.chat_history[-1]["content"] == question):
            return

        st.session_state.chat_history.append({"role": "user", "content": question})

        client, status = _get_client()
        if status == "package_missing":
            answer = "❌ `groq` package not installed. Run: `pip install groq`"
        elif status == "missing_key":
            answer = "❌ Groq API key missing. Add `[groq]` with `api_key` to `.streamlit/secrets.toml`."
        elif client is None:
            answer = f"❌ Groq init error: {status}"
        else:
            try:
                messages = [{"role": "system", "content": _build_system_prompt(df)}]
                for m in st.session_state.chat_history:
                    r = "assistant" if m["role"] == "assistant" else "user"
                    messages.append({"role": r, "content": m["content"]})

                with st.spinner("Groq is thinking…"):
                    resp = client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=messages,
                        max_tokens=1024,
                        temperature=0.4,
                    )
                answer = resp.choices[0].message.content
            except Exception as e:
                answer = f"❌ Groq error: {e}"

        st.session_state.chat_history.append({"role": "assistant", "content": answer})
        st.rerun()
