"""Static presentation for the private Streamlit viewer."""

# shortcut: selectors target pinned Streamlit 1.65; recheck layout when upgrading it.
STYLE = """<style>
[data-testid="stAppViewContainer"] { background: #faf9fb; }
[data-testid="stHeader"] { background: #faf9fb; }
[data-testid="stMainBlockContainer"] { max-width: 1280px; padding: 2.2rem 2.7rem 3rem; }
[data-testid="stSidebar"] { background: #f3f2f5; border-right: 1px solid #e7e5eb; }
[data-testid="stSidebarContent"] { padding-top: 1.5rem; }
h1 { font-size: 1.85rem !important; font-weight: 650 !important; letter-spacing: -.045em; }
h3 { font-size: 1.05rem !important; font-weight: 600 !important; letter-spacing: -.02em; }
[data-testid="stCaptionContainer"] { color: #686471; }
[data-testid="stButton"] button { border-radius: 6px; font-size: .82rem; }
[data-testid="stButton"] button[kind="primary"] { background: #181622; border-color: #181622; }
[data-testid="stButton"] button[kind="primary"]:hover { background: #35303f; border-color: #35303f; }
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stDateInput"] [data-baseweb="input"] { background: #fff; border-color: #e2dfe7; border-radius: 6px; }
[data-testid="stExpander"] { background: #fff; border-radius: 8px; border-color: #e7e5eb; }
[data-testid="stDataFrame"] { border-radius: 6px; }
hr { border-color: #e7e5eb; margin: .7rem 0; }
.sentra-brand { display: flex; align-items: center; gap: 10px; margin-bottom: 1.8rem; }
.sentra-mark { width: 30px; height: 30px; border: 1px solid #24212d; border-radius: 50%;
  display: grid; place-items: center; font-size: 17px; font-weight: 600; }
.sentra-wordmark { font-size: 18px; font-weight: 650; letter-spacing: -.04em; }
.sentra-eyebrow { font-size: 10px; letter-spacing: .12em; color: #686471; text-transform: uppercase; }
.st-key-explore [data-testid="stRadio"] > label { display: none; }
.st-key-explore [role="radiogroup"] { gap: 3px; }
.st-key-explore [role="radiogroup"] > div { width: 100%; }
.st-key-explore [data-testid="stRadioOption"] { margin: 0; padding: 10px 11px; border-radius: 6px; width: 100%; }
.st-key-explore [data-testid="stRadioOption"] > div > div:first-child { display: none; }
.st-key-explore [data-testid="stRadioOption"] p { font-size: 13px; }
.st-key-explore [data-testid="stRadioOption"][data-selected="true"] { background: #e5e2ea; color: #181622; }
.st-key-explore [data-testid="stRadioOption"]:has(input:focus-visible) { outline: 2px solid #716187; outline-offset: 2px; }
.st-key-overview-chart, .st-key-recovery-chart, .st-key-record-table { background: #fff; }
.st-key-overview-summary { background: #181622; border-radius: 8px; padding: 24px; min-height: 372px; gap: .6rem; }
.st-key-overview-summary [data-testid="stMetricValue"] { color: #fff; font-size: clamp(1.4rem, 2.5vw, 2rem); letter-spacing: -.04em; }
.st-key-overview-summary [data-testid="stMetricLabel"],
.st-key-overview-summary [data-testid="stCaptionContainer"] { color: #c5c0d0; }
.st-key-overview-summary [data-testid="stMetricLabel"] p { font-size: 12px; }
.st-key-overview-summary hr { border-color: #35313f; margin: 0; }
.st-key-overview-summary [data-testid="stMetric"] { padding: 0; }
.st-key-overview-chart, .st-key-recovery-chart, .st-key-record-table { border-radius: 8px; }
.st-key-page-heading { padding-bottom: 12px; border-bottom: 1px solid #e7e5eb; margin-bottom: 10px; }
@media (min-width: 920px) {
  [data-testid="stSidebar"] { width: 245px !important; min-width: 245px !important; max-width: 245px !important; }
}
@media (max-width: 920px) {
  [data-testid="stMainBlockContainer"] { padding: 1.8rem 1.2rem 2rem; }
  .st-key-metric-panels > [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
  .st-key-metric-panels > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    width: 100% !important; flex: 1 1 100% !important; min-width: 0 !important;
  }
  .st-key-overview-summary { min-height: 0; }
}
</style>"""

BRAND = """<div class="sentra-brand"><span class="sentra-mark" aria-hidden="true">s</span>
<div><div class="sentra-wordmark">sentra</div><div class="sentra-eyebrow">Wearable explorer</div></div></div>"""
