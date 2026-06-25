"""
Generate the static leaderboard site into docs/: an index (per-track Pareto
tables) plus one detail page per code under docs/codes/<slug>.html.

Pure Python, no framework. A code's displayed distance tier is earned, not
self-declared: it shows d= only when a server certificate exists in
certs/<slug>.json (d_exact), otherwise d<= (the witness upper bound the cheap
verifier confirmed). Detail pages expose the actual witness, certificate, and
parity checks so the verification is transparent.
"""

import glob
import html
import json
import os
import re
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "verify"))
from qldpc_verify import verify

DOCS = os.path.join(ROOT, "docs")
CERTS = os.path.join(ROOT, "certs")


def load_refs():
    """Parse refs.bib into an ordered list of entries. Each entry is a dict of
    lowercased field -> value plus 'key' and 'type'. No external dependency: a
    BibTeX file is regular enough that a brace-aware scan handles it."""
    path = os.path.join(ROOT, "refs.bib")
    try:
        text = open(path).read()
    except Exception:
        return []
    entries = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]+),", text):
        typ, key = m.group(1).lower(), m.group(2).strip()
        # capture the entry body by matching balanced braces from the opening {
        i = text.index("{", m.start())
        depth, j = 0, i
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = text[i + 1:j]
        fields = {"key": key, "type": typ}
        for fm in re.finditer(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|[^,\n]+)",
                              body):
            name, val = fm.group(1).lower(), fm.group(2).strip()
            if name == key.split(",")[0]:  # skip the key token itself
                continue
            val = re.sub(r"\s+", " ", val).strip().strip(",").strip()
            # resolve the few LaTeX accents, then drop all BibTeX braces (they
            # are case-protection markup, not part of the displayed text).
            val = (val.replace("{\\'e}", "e").replace("\\'e", "e")
                      .replace('{\\"o}', "o").replace('\\"o', "o"))
            val = val.replace("{", "").replace("}", "")
            fields[name] = val
        entries.append(fields)
    return entries


REFS = load_refs()


def _surnames(author_field):
    """Surnames from a BibTeX 'and'-joined author string ('Last, First and ...'
    or 'First Last and ...'), lowercased, for loose citation matching."""
    out = []
    for a in author_field.split(" and "):
        a = a.strip()
        out.append((a.split(",")[0] if "," in a else a.split()[-1]).lower())
    return [s for s in out if s]


def resolve_ref(s):
    """Map a free-text reference string from a submission (e.g. 'arXiv:2504.08887'
    or 'Liang, Eberhardt, Chen') to a refs.bib key, or None. Matches by arXiv id
    or DOI when present, else by author-surname subset."""
    low = s.lower()
    # modern (2504.08887) or old-style (quant-ph/9707021) arXiv id
    am = re.search(r"(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})", low)
    aid = am.group(1) if am else None
    for e in REFS:
        if aid and e.get("eprint", "").strip() == aid:
            return e["key"]
        doi = e.get("doi", "").lower()
        if doi and doi in low:
            return e["key"]
    if aid:
        return None
    toks = [t for t in re.split(r"[,\s]+", low) if len(t) > 2]
    for e in REFS:
        sn = set(_surnames(e.get("author", "")))
        if sn and toks and set(toks) <= sn:
            return e["key"]
    return None


def cite(s, rel=""):
    """Render a reference string as a link. An arXiv reference links straight to
    the paper on arXiv; any other reference that resolves to a bib entry links
    to its entry on the references page (reachable from the footer too)."""
    if s.lower().startswith("arxiv:"):
        aid = s.split(":", 1)[1]
        return f'<a href="https://arxiv.org/abs/{aid}">{html.escape(s)}</a>'
    key = resolve_ref(s)
    if key:
        return (f'<a href="{rel}references.html#{key}">{html.escape(s)}</a>')
    return html.escape(s)


REPO_ROOT = "https://github.com/unitaryfoundation/qldpc-challenge"
REPO = REPO_ROOT + "/blob/main"
# Public base URL of the deployed site, used to build shareable per-code links.
# Update this to the real domain once the board is hosted.
SITE_URL = "https://unitaryfoundation.github.io/qldpc-challenge"

# Palette (single source of truth; the CSS :root and the inline SVGs all draw
# from these). Adopts the Unitary Foundation brand: deep purple as the readable
# primary accent, signature bright yellow as the highlight (records, hero glow,
# logo node), near-black surfaces. Green/amber are kept as functional tier
# signals (certified exact / corroborated) for chart and badge legibility.
ACCENT = "#36006c"        # UF deep purple (links, accents, stars) — reads on white
HILITE = "#ffff00"        # UF signature yellow (highlight node, hero glow, records)
EXACT = "#059669"         # certified-exact green, on light backgrounds
CORR = "#d97706"          # heuristically-corroborated amber (between exact and ub)
GREEN_BRIGHT = HILITE     # marks on the dark surface (logo highlight) — now yellow
DARK = "#111111"          # near-black surface: hero background + logo/UI tiles

# Logo mark: a six-node cyclic graph (the node-and-edge structure associated
# with qLDPC / Tanner graphs) on a dark tile, one node highlighted. Used for
# the favicon, hero, and footer. All attributes quoted so it is valid as a
# standalone SVG file (parsed as XML) and inline in HTML.
MARK = f"""\
<rect x="1" y="1" width="62" height="62" rx="14" fill="{DARK}" \
stroke="rgba(255,255,255,0.16)" stroke-width="1.5"/>
<g stroke="#ffffff" stroke-width="4" stroke-linecap="round" opacity="0.9">
<line x1="32" y1="14" x2="16" y2="23"/><line x1="16" y1="23" x2="16" y2="41"/>
<line x1="16" y1="41" x2="32" y2="50"/><line x1="32" y1="50" x2="48" y2="41"/>
<line x1="48" y1="41" x2="48" y2="23"/><line x1="48" y1="23" x2="32" y2="14"/></g>
<g fill="#ffffff"><circle cx="16" cy="23" r="5"/><circle cx="16" cy="41" r="5"/>
<circle cx="32" cy="50" r="5"/><circle cx="48" cy="41" r="5"/>
<circle cx="48" cy="23" r="5"/></g>
<circle cx="32" cy="14" r="5.5" fill="{GREEN_BRIGHT}"/>"""

FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
           + MARK + "</svg>")

# The Unitary Foundation wordmark (yellow notched block + black lettering), used
# in the hero to co-brand the challenge as a UF project. Sized via CSS (.uflogo);
# the black text reads on the yellow block against any background.
UF_LOGO = (
    '<svg class=uflogo viewBox="0 0 295 69" fill="none" '
    'xmlns="http://www.w3.org/2000/svg" role="img" '
    'aria-label="Unitary Foundation">'
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M197.618 0.5H0.166016V68.5'
    'H294.833V35.2556H197.618V0.5Z" fill="#FFFF00"/>'
    '<path d="M30.4623 32.9741H0.166992V2.67886H6.36507V27.0078H24.4959V2.67886'
    'H30.4623V32.9741ZM60.977 8.87694V32.9741H55.0106V14.8433H42.8462V32.9741'
    'H36.8798V8.87694H60.977ZM73.1668 1.11486V5.80686H67.2004V1.11486H73.1668Z'
    'M67.2004 9.22449H73.1668V32.9741H67.2004V9.22449ZM85.329 14.8433V27.0078'
    'H97.4934V32.9741H79.3626V0.999007H85.329V8.87694H97.4934V14.8433H85.329Z'
    'M127.959 8.81901V32.9162H103.63V18.4347H121.761V14.4958H103.63V8.81901'
    'H127.959ZM121.761 27.5291V23.3584H109.828V27.5291H121.761ZM153.007 8.87694'
    'V20.8097H146.809V14.8433H140.206V32.9741H134.008V8.87694H153.007ZM182.542 '
    '32.9741L172.463 42.9374H167.771V39.0563L174.085 32.9741H158.445V8.87694'
    'H164.411V27.0078H176.576V8.87694H182.542V32.9741Z" fill="black"/>'
    '<path d="M6.13336 44.4082V50.6062H30.2306V56.5726H6.13336V68.7371H0.166992'
    'V38.4418H30.2306V44.4082H6.13336ZM61.2087 44.6399V68.7371H36.8798V44.6399'
    'H61.2087ZM55.0106 50.6062H43.0779V62.7707H55.0106V50.6062ZM91.5239 68.7371'
    'H67.4267V44.6399H73.3931V62.7707H85.5575V44.6399H91.5239V68.7371ZM121.731 '
    '44.6399V68.7371H115.765V50.6062H103.601V68.7371H97.6342V44.6399H121.731Z'
    'M152.284 36.5882V68.7371H127.955V44.6399H146.086V36.5882H152.284ZM146.086 '
    '62.7707V50.6062H133.921V62.7707H146.086ZM182.604 44.5819V68.6791H158.275'
    'V54.1977H176.406V50.2587H158.275V44.5819H182.604ZM176.406 63.292V59.1214'
    'H164.473V63.292H176.406ZM194.619 50.6062V62.7707H206.783V68.7371H188.653'
    'V36.7619H194.619V44.6399H206.783V50.6062H194.619ZM218.887 36.8778V41.5698'
    'H212.92V36.8778H218.887ZM212.92 44.9874H218.887V68.7371H212.92V44.9874Z'
    'M249.411 44.6399V68.7371H225.083V44.6399H249.411ZM243.213 50.6062H231.281'
    'V62.7707H243.213V50.6062ZM279.727 44.6399V68.7371H273.76V50.6062H261.596'
    'V68.7371H255.629V44.6399H279.727Z" fill="black"/>'
    '</svg>')

# Small inline copy of the site mark (the hexagon graph), without the dark
# tile and recoloured to the accent so it reads on a light row. Used to flag a
# code as found through the challenge, the way the star flags the frontier.
HEX_MARK = (
    '<svg class=hexmark viewBox="0 0 64 64" width="15" height="15" '
    'aria-hidden="true">'
    '<g stroke="currentColor" stroke-width="5" stroke-linecap="round">'
    '<line x1="32" y1="14" x2="16" y2="23"/><line x1="16" y1="23" x2="16" y2="41"/>'
    '<line x1="16" y1="41" x2="32" y2="50"/><line x1="32" y1="50" x2="48" y2="41"/>'
    '<line x1="48" y1="41" x2="48" y2="23"/><line x1="48" y1="23" x2="32" y2="14"/></g>'
    '<g fill="currentColor"><circle cx="16" cy="23" r="6"/>'
    '<circle cx="16" cy="41" r="6"/><circle cx="32" cy="50" r="6"/>'
    '<circle cx="48" cy="41" r="6"/><circle cx="48" cy="23" r="6"/></g>'
    f'<circle cx="32" cy="14" r="6.5" fill="{GREEN_BRIGHT}"/></svg>')


# GitHub mark (official octocat silhouette), inherits the link color.
GH_ICON = ('<svg viewBox="0 0 16 16" width="18" height="18" fill="currentColor" '
           'aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 '
           '5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49'
           '-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 '
           '1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78'
           '-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 '
           '0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 '
           '2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07'
           '-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 '
           '.21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>')

# share icons (monochrome, currentColor). Brand glyphs for X / Bluesky /
# LinkedIn; a link glyph for copy.
LINK_ICON = ('<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"'
             ' aria-hidden="true"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7'
             'c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1z'
             'M8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1'
             ' 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>')
X_ICON = ('<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" '
          'aria-hidden="true"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 '
          '11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08'
          'l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>')
BSKY_ICON = ('<svg viewBox="0 0 568 501" width="18" height="18" '
             'fill="currentColor" aria-hidden="true"><path d="M123.121 33.664C'
             '188.241 82.553 258.281 181.68 284 234.873c25.719-53.193 95.759'
             '-152.32 160.879-201.21C491.866-1.611 568-28.906 568 57.947c0 '
             '17.346-9.945 145.713-15.778 166.555-20.275 72.453-94.155 90.933'
             '-159.875 79.748C507.222 323.8 536.444 388.56 473.333 453.32c'
             '-119.86 122.992-172.272-30.859-185.702-70.281-2.462-7.227-3.614'
             '-10.608-3.631-7.733-.017-2.875-1.169.506-3.631 7.733-13.43 39.422'
             '-65.842 193.273-185.702 70.281-63.111-64.76-33.889-129.52 80.986'
             '-149.071-65.72 11.185-139.6-7.295-159.875-79.748C9.945 203.66 0 '
             '75.293 0 57.947 0-28.906 76.135-1.611 123.121 33.664Z"/></svg>')
LI_ICON = ('<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" '
           'aria-hidden="true"><path d="M20.447 20.452h-3.554v-5.569c0-1.328'
           '-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351'
           'V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 '
           '4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 '
           '2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H'
           '1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C'
           '23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.225 0z"/></svg>')

CSS = f"""
:root{{--ink:#0f172a;--mut:#64748b;--ln:#e2e8f0;--ac:{ACCENT};--ex:{EXACT};
--corr:{CORR};--exb:{GREEN_BRIGHT};--dark:{DARK};--bg:#fff;--soft:#f8fafc}}
*{{box-sizing:border-box}}
/* Unitary Foundation type stack: Space Grotesk for display/headings, Manrope
   for body, Space Mono for code. Loaded from Google Fonts in head(). */
body{{font-family:'Manrope',system-ui,-apple-system,sans-serif;
color:var(--ink);margin:0;background:var(--bg);line-height:1.55}}
h1,h2,h3,.brand h1,.codehead .big,.lbh,.ph{{font-family:'Space Grotesk',
'Manrope',system-ui,sans-serif;letter-spacing:-.01em}}
.mono{{font-family:'Space Mono',ui-monospace,'SF Mono',Menlo,monospace;
font-weight:700}}
.wrap{{max-width:1080px;margin:0 auto;padding:0 24px}}
header.hero{{background:
radial-gradient(115% 130% at 50% -25%,rgba(255,255,0,.18),transparent 60%),
repeating-linear-gradient(0deg,transparent 0 27px,rgba(255,255,255,.05) 27px 28px),
repeating-linear-gradient(90deg,transparent 0 27px,rgba(255,255,255,.05) 27px 28px),
var(--dark);color:#fff;padding:54px 0 50px;
border-bottom:4px solid {HILITE}}}
.brand{{display:flex;align-items:center;justify-content:space-between;
gap:16px;margin:0 0 18px}}
.brandmark{{display:flex;align-items:center;gap:16px}}
.brand .brandmark svg{{flex:0 0 auto}}
.uflogo{{height:38px;width:auto;display:block;
filter:drop-shadow(0 4px 14px rgba(0,0,0,.35))}}
.ghlink{{display:inline-flex;align-items:center;gap:8px;color:#fff;
text-decoration:none;font-size:14px;font-weight:600;
border:1px solid rgba(255,255,255,.28);border-radius:9px;padding:8px 14px;
background:rgba(255,255,255,.08)}}
.ghlink:hover{{background:rgba(255,255,255,.18)}}
header.hero h1{{font-size:clamp(30px,6vw,44px);margin:0;letter-spacing:-1px}}
header.hero h1 a{{color:#fff}}
header.hero p{{font-size:18px;max-width:640px;margin:0;color:#e4e4e7}}
header.hero p a{{color:{HILITE};text-decoration:underline}}
.topnav{{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}}
.topnav a{{display:inline-flex;align-items:center;gap:7px;color:#e4e4e7;
font-size:14px;font-weight:600;padding:7px 14px;
border:1px solid rgba(255,255,255,.18);border-radius:8px;
background:rgba(255,255,255,.06)}}
.topnav a:hover{{background:{HILITE};color:#111;border-color:{HILITE}}}
.stats{{display:flex;gap:40px;margin-top:30px;flex-wrap:wrap}}
.stat .v{{font-size:30px;font-weight:700}}.stat .l{{color:#c7d2fe;font-size:13px;
text-transform:uppercase;letter-spacing:.05em}}
.statsbar{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:14px;margin:28px 0 8px}}
.stat-card{{border:1px solid var(--ln);border-radius:14px;padding:18px 20px;
background:var(--soft)}}
.stat-card.hero{{border-color:var(--ac);background:#fffbe0}}
.stat-card .v{{font-size:34px;font-weight:700;line-height:1.05}}
.stat-card.hero .v{{color:var(--ac)}}
.stat-card .l{{font-size:13px;color:var(--mut);margin-top:6px}}
.lb{{margin:18px 0 8px;border:1px solid var(--ln);border-radius:14px;
background:#fff;overflow:hidden}}
.lbhead{{display:flex;justify-content:space-between;align-items:center;gap:16px;
padding:16px 20px;background:var(--soft);border-bottom:1px solid var(--ln)}}
.lbh{{font-size:18px;margin:0}}
.lbsub{{margin:4px 0 0;font-size:13px;color:var(--mut)}}
.lbcta{{flex:0 0 auto;font-size:13px;font-weight:600;color:#fff;
background:var(--ac);border-radius:8px;padding:8px 14px;text-decoration:none}}
.lbcta:hover{{filter:brightness(1.08)}}
.lblist{{max-height:232px;overflow-y:auto}}
.lbrow{{display:flex;align-items:center;gap:14px;padding:11px 20px;
border-bottom:1px solid var(--ln);text-decoration:none;color:var(--ink)}}
.lbrow:last-child{{border-bottom:none}}.lbrow:hover{{background:#f7f8fc}}
.lbrank{{width:20px;text-align:center;color:var(--mut);font-weight:600;
font-variant-numeric:tabular-nums}}
.lbav{{width:34px;height:34px;border-radius:50%;background:var(--soft);
object-fit:cover;flex:0 0 auto}}
.lbname{{flex:1 1 auto;font-weight:600;min-width:0;color:var(--ac)}}
.lbcrown{{margin-left:5px}}
.lbm{{display:flex;flex-direction:column;align-items:center;width:82px;
flex:0 0 auto}}
.lbm b{{font-size:17px;font-variant-numeric:tabular-nums}}
.lbml{{font-size:11px;color:var(--mut);margin-top:1px;white-space:nowrap}}
@media(max-width:680px){{.lbm:nth-child(n+5){{display:none}}.lbm{{width:64px}}}}
.how{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin:40px 0}}
.how .card{{border:1px solid var(--ln);border-radius:12px;padding:20px;
background:var(--soft)}}
.how .n{{display:inline-flex;width:26px;height:26px;border-radius:50%;
background:var(--ac);color:#fff;align-items:center;justify-content:center;
font-size:14px;font-weight:700;margin-bottom:10px}}
.how h3{{margin:.2rem 0;font-size:16px}}.how p{{margin:0;color:var(--mut);
font-size:14px}}
.legend{{display:flex;flex-wrap:wrap;gap:18px;margin:28px 0 4px;padding:14px 16px;
background:var(--soft);border:1px solid var(--ln);border-radius:10px;
font-size:13px;color:var(--mut)}}
.legend b{{color:var(--ink)}}
.legbreak{{flex-basis:100%}}
.collegend{{flex-basis:100%;border-top:1px solid var(--ln);padding-top:10px;
line-height:1.7}}
.dot{{display:inline-block;width:11px;height:11px;border-radius:50%;
vertical-align:-1px;margin-right:2px}}
.dot.ex{{background:var(--ex)}}.dot.ac{{background:var(--ac)}}
.dot.ho{{background:#fff;border:2px solid var(--ac)}}
.swatch{{display:inline-block;width:18px;height:11px;vertical-align:-1px;
margin-right:3px;background:#fffbe0;border-left:3px solid var(--ac)}}
h2.track{{font-size:24px;margin:48px 0 4px;padding-top:24px;
border-top:1px solid var(--ln);scroll-margin-top:16px}}
.tcount{{color:var(--mut);font-size:14px;font-weight:400}}
.plots{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
gap:16px;margin:14px 0 4px}}
.plot{{min-width:0;border:1px solid var(--ln);border-radius:12px;
background:#fff;padding:8px}}
.chartlegend{{display:flex;flex-wrap:wrap;gap:10px 20px;margin:10px 0 4px;
padding:12px 16px;background:var(--soft);border:1px solid var(--ln);
border-radius:10px;font-size:13px;color:var(--mut)}}
.chartlegend .ci{{display:inline-flex;align-items:center;gap:7px}}
.cdot{{width:12px;height:12px;border-radius:50%;flex:0 0 auto}}
/* full width (matching the panels above) with fixed, evenly distributed
   columns so the slack isn't dumped into one column as a stray gap. */
table.board{{border-collapse:collapse;width:100%;table-layout:fixed;
font-size:14px;margin:12px 0}}
.board th,.board td{{padding:.55rem .9rem;text-align:left;white-space:nowrap;
border-bottom:1px solid var(--ln)}}
.board th{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;
color:var(--mut);cursor:pointer;user-select:none;border-bottom:2px solid var(--ln)}}
.board th:hover{{color:var(--ink)}}.board td.num,.board th.num{{text-align:center;
font-variant-numeric:tabular-nums}}
.board td.auth{{white-space:normal}}
.hexwrap{{display:inline-flex;align-items:center;margin-left:8px}}
.hexmark{{color:var(--ac);vertical-align:-2px}}
.board tbody tr{{cursor:pointer}}.board tbody tr:hover{{background:#f6f3fb}}
.board tr.fr{{background:#fffbe0}}.board tr.fr td:first-child{{
box-shadow:inset 3px 0 0 var(--ac)}}
.board tr.fr:hover{{background:#fff6c4}}
.board tbody tr.xh,.board tbody tr.fr.xh{{background:#fef3c7}}
.board tbody tr.xh td:first-child{{box-shadow:inset 3px 0 0 #f59e0b}}
.typecell{{white-space:normal!important}}
.tchip{{display:inline-block;font-size:11px;line-height:1;padding:3px 7px;
margin:2px 4px 2px 0;border-radius:999px;background:var(--soft);color:var(--mut);
border:1px solid var(--ln);white-space:nowrap}}
.searchbar{{display:flex;align-items:center;gap:12px;margin:14px 0 8px}}
#boardsearch{{flex:1 1 0;min-width:0;font-size:14px;padding:10px 13px;
border:1px solid var(--ln);border-radius:10px;background:#fff;color:var(--ink);
font-family:inherit}}
#boardsearch:focus{{outline:none;border-color:var(--ac);
box-shadow:0 0 0 3px rgba(54,0,108,.15)}}
.searchcount{{font-size:13px;color:var(--mut);white-space:nowrap}}
.typepills{{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px}}
.typepill{{font-size:12px;padding:5px 11px;border-radius:999px;cursor:pointer;
border:1px solid var(--ln);background:#fff;color:var(--mut);font-family:inherit}}
.typepill:hover{{border-color:var(--ac);color:var(--ac)}}
.clearpill{{color:var(--mut)}}
.searchhelp{{font-size:12px;color:var(--mut);margin:0 0 14px;max-width:80ch}}
.searchhelp code{{background:var(--soft);padding:1px 5px;border-radius:4px;
font-size:11px}}
.plot circle.pt.xh{{stroke:#f59e0b;stroke-width:4;r:7}}
.plot circle.hit{{cursor:pointer}}
.star{{color:var(--ac);width:18px}}
.auth{{color:var(--mut);font-size:13px}}
.b{{display:inline-block;font-size:11px;font-weight:700;padding:1px 6px;
border-radius:5px;font-family:ui-monospace,monospace}}
.b.exact{{background:#d1fae5;color:var(--ex)}}.b.ub{{background:#eef2f7;
color:var(--mut)}}.b.corr{{background:#fef3c7;color:var(--corr)}}
footer.foot{{margin-top:72px;border-top:1px solid var(--ln);
background:linear-gradient(180deg,var(--soft),var(--bg));color:var(--mut);
font-size:14px}}
.footmain{{max-width:1080px;margin:0 auto;padding:34px 24px 26px;display:flex;
flex-wrap:wrap;gap:24px;justify-content:space-between;align-items:flex-start}}
.footbrand{{max-width:360px}}
.footbrand .fb{{display:flex;align-items:center;gap:12px;margin-bottom:8px}}
.footbrand .fb span{{font-size:18px;font-weight:700;color:var(--ink)}}
.footbrand p{{margin:0;color:var(--mut)}}
.footlinks{{display:flex;flex-wrap:wrap;gap:8px 22px;align-items:center}}
.footlinks a{{display:inline-flex;align-items:center;gap:7px;color:var(--mut);
font-weight:600}}
.footlinks a:hover{{color:var(--ac);text-decoration:none}}
.footlinks svg{{width:16px;height:16px}}
.footbar{{border-top:1px solid var(--ln);text-align:center;padding:16px;
color:var(--mut);font-size:13px}}
a{{color:var(--ac);text-decoration:none}}a:hover{{text-decoration:underline}}
code{{background:var(--soft);padding:1px 5px;border-radius:4px;font-size:.9em}}
.faq{{max-width:64ch;margin:22px 0;padding-bottom:18px;
border-bottom:1px solid var(--ln)}}
.faq h3{{font-size:17px;margin:0 0 6px}}
.faq p{{margin:0;color:var(--mut);line-height:1.6}}
.hit{{cursor:pointer}}
#tip{{position:fixed;pointer-events:none;z-index:60;background:#0f172a;
color:#fff;padding:7px 10px;border-radius:7px;font-size:12px;line-height:1.45;
white-space:pre-line;box-shadow:0 6px 20px rgba(2,6,23,.28);opacity:0;
transition:opacity .06s;max-width:300px}}
#tip.show{{opacity:1}}
/* detail page */
.back{{display:inline-block;margin:24px 0 0;font-size:14px}}
.codehead{{margin:8px 0 0}}.codehead .big{{font-size:32px;letter-spacing:-.5px}}
.params{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
gap:1px;background:var(--ln);border:1px solid var(--ln);border-radius:10px;
overflow:hidden;margin:20px 0}}
.params .cell{{background:#fff;padding:12px 14px}}
.params .l{{font-size:11px;text-transform:uppercase;letter-spacing:.04em;
color:var(--mut)}}.params .v{{font-size:20px;font-weight:700;margin-top:2px}}
section.blk{{margin:28px 0}}section.blk h3{{font-size:16px;margin:0 0 8px;
padding-bottom:6px;border-bottom:1px solid var(--ln)}}
.kv{{font-size:14px;margin:4px 0}}.kv b{{color:var(--mut);font-weight:600;
display:inline-block;min-width:120px}}
.share{{display:flex;flex-wrap:wrap;gap:10px}}
.sharebtn{{cursor:pointer;border:1px solid var(--ln);background:var(--soft);
color:var(--mut);border-radius:9px;width:40px;height:40px;padding:0;
display:inline-flex;align-items:center;justify-content:center;
text-decoration:none;line-height:0}}
.sharebtn:hover{{border-color:var(--ac);color:var(--ac)}}
.sharebtn svg{{display:block}}
.wit{{font-family:ui-monospace,monospace;font-size:12px;background:var(--soft);
border:1px solid var(--ln);border-radius:8px;padding:10px;
white-space:pre-wrap;word-break:break-word}}
details{{margin:8px 0}}summary{{cursor:pointer;color:var(--ac);font-size:14px}}
.cert-ok{{color:var(--ex);font-weight:600}}.cert-no{{color:var(--mut)}}
.ref{{display:flex;gap:16px;padding:16px 0;border-bottom:1px solid var(--ln);
font-size:15px;line-height:1.55;scroll-margin-top:16px}}
.ref:target{{background:var(--soft);border-radius:8px;padding:16px 12px}}
.refkey{{flex:0 0 auto;width:170px;font-family:ui-monospace,monospace;
font-size:12px;color:var(--ac);word-break:break-all}}
.refbody{{flex:1 1 0;min-width:0}}
.refauth{{color:var(--mut)}}
.reftitle{{font-style:italic}}
.refmeta{{color:var(--mut)}}
.refcited{{font-size:12px;color:var(--mut);margin-top:8px;
display:flex;flex-wrap:wrap;gap:6px;align-items:center}}
.refcited a{{font-family:ui-monospace,monospace;font-size:11px;
color:var(--mut);background:var(--soft);border:1px solid var(--ln);
border-radius:5px;padding:1px 6px;white-space:nowrap;text-decoration:none}}
.refcited a:hover{{color:var(--ac);border-color:var(--ac)}}
@media(max-width:680px){{.ref{{flex-direction:column;gap:4px}}
.refkey{{width:auto}}}}
@media(max-width:880px){{.how{{grid-template-columns:1fr}}}}
"""

JS = """
// Remember where the user was on the board when they open a code, so the
// detail page's "back to the board" link (and the browser back button) return
// to that spot rather than the top of the page.
document.addEventListener('click',e=>{
 if(e.target.closest('a[href^="codes/"],tr[data-href],circle.hit[data-code]'))
  sessionStorage.setItem('boardY', String(window.scrollY));
},true);
(function(){const y=sessionStorage.getItem('boardY');
 if(y!==null){sessionStorage.removeItem('boardY');
  requestAnimationFrame(()=>window.scrollTo(0, parseInt(y,10)));}})();
document.querySelectorAll('table.board').forEach(t=>{
 t.querySelectorAll('th[data-c]').forEach((th)=>{
  let asc=true;
  th.addEventListener('click',()=>{
   const c=th.dataset.c;
   const num=th.classList.contains('num')||th.hasAttribute('data-num');
   const rows=[...t.querySelectorAll('tbody tr')];
   rows.sort((a,b)=>{let x=a.dataset[c],y=b.dataset[c];
    if(num){x=parseFloat(x);y=parseFloat(y);return asc?x-y:y-x;}
    return asc?(''+x).localeCompare(y):(''+y).localeCompare(x);});
   asc=!asc; const tb=t.querySelector('tbody'); rows.forEach(r=>tb.appendChild(r));
  });
 });
});
document.querySelectorAll('tr[data-href]').forEach(r=>{
 r.addEventListener('click',()=>{location.href=r.dataset.href;});
});
// Cross-highlight a code's table row and its chart dot together. Global (not
// scoped to one section) because the charts and the table now live in separate
// parts of the page.
(function(){
 const mark=(code,on)=>document.querySelectorAll('[data-code="'+code+'"]')
  .forEach(el=>el.classList.toggle('xh',on));
 document.querySelectorAll('[data-code]').forEach(el=>{
  const code=el.dataset.code;
  el.addEventListener('mouseenter',()=>mark(code,true));
  el.addEventListener('mouseleave',()=>mark(code,false));
 });
})();
const tip=document.getElementById('tip');
if(tip)document.querySelectorAll('circle.hit').forEach(c=>{
 c.addEventListener('mouseenter',()=>{tip.textContent=c.dataset.tip;
  tip.classList.add('show');});
 c.addEventListener('mousemove',e=>{let x=e.clientX+14,y=e.clientY+14;
  if(x+310>innerWidth)x=e.clientX-tip.offsetWidth-14;
  tip.style.left=x+'px';tip.style.top=y+'px';});
 c.addEventListener('mouseleave',()=>tip.classList.remove('show'));
});
document.querySelectorAll('circle.hit[data-code]').forEach(c=>{
 c.addEventListener('click',()=>{location.href='codes/'+c.dataset.code+'.html';});
});
// Smart search over the unified board: space-separated terms, all must match.
// A term is either a comparison (n/k/d/w/eff with >= <= > < =) or free text
// matched against the code name, type, and authors. 'record' keeps frontier
// records. The landscape scatter hides points that the table filters out.
(function(){
 const board=document.getElementById('mainboard');
 const q=document.getElementById('boardsearch');
 if(!board||!q)return;
 const count=document.getElementById('boardcount');
 const rows=[...board.querySelectorAll('tbody tr')];
 const cmp=/^(n|k|d|w|eff)(>=|<=|>|<|=)(-?\\d+(?:\\.\\d+)?)$/;
 function term(r,t){
  const m=t.match(cmp);
  if(m){const x=parseFloat(r.dataset[m[1]]),v=parseFloat(m[3]);
   switch(m[2]){case'>=':return x>=v;case'<=':return x<=v;
    case'>':return x>v;case'<':return x<v;default:return x===v;}}
  if(t==='record'||t==='frontier')return r.dataset.record==='1';
  const hay=(r.dataset.name+' '+r.dataset.tracks+' '+r.dataset.auth).toLowerCase();
  return hay.indexOf(t)>=0;
 }
 function apply(){
  const toks=q.value.toLowerCase().trim().split(/\\s+/).filter(Boolean);
  const vis=new Set();let shown=0;
  rows.forEach(r=>{const ok=toks.every(t=>term(r,t));
   r.style.display=ok?'':'none';if(ok){shown++;vis.add(r.dataset.code);}});
  if(count)count.textContent=shown+(shown===rows.length?'':' of '+rows.length)+' codes';
  document.querySelectorAll('.plots svg.plot circle[data-code]').forEach(c=>{
   c.style.display=vis.has(c.dataset.code)?'':'none';});
 }
 q.addEventListener('input',apply);
 document.querySelectorAll('.typepill').forEach(p=>{
  p.addEventListener('click',()=>{q.value=p.dataset.q;apply();q.focus();});});
 apply();
})();
"""


def head(title, rel=""):
    return ("".join([
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        '<meta name=viewport content="width=device-width,initial-scale=1">',
        f"<title>{html.escape(title)}</title>",
        f'<link rel=icon type="image/svg+xml" href="{rel}favicon.svg">',
        '<link rel=preconnect href="https://fonts.googleapis.com">',
        '<link rel=preconnect href="https://fonts.gstatic.com" crossorigin>',
        '<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;'
        '600;700&family=Space+Grotesk:wght@500;700&family=Space+Mono:wght@400;'
        '700&display=swap" rel=stylesheet>',
        f"<style>{CSS}</style></head><body>"]))


def cert_info(slug):
    p = os.path.join(CERTS, slug + ".json")
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def heuristic_cert_info(slug):
    """Heuristic distance result (certs/heuristic/<slug>.json), if any. Carries a
    `verdict` of corroborated / refuted / inconclusive (see verify/heuristic_*)."""
    p = os.path.join(CERTS, "heuristic", slug + ".json")
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def load_entries():
    entries = []
    for p in sorted(glob.glob(os.path.join(ROOT, "codes", "*.json"))):
        slug = os.path.splitext(os.path.basename(p))[0]
        with open(p) as f:
            doc = json.load(f)
        rep = verify(doc)
        if not rep["ok"]:
            continue
        cert = cert_info(slug)
        hcert = heuristic_cert_info(slug)
        if cert and cert.get("d_exact"):
            tier = "exact"
        elif hcert and hcert.get("verdict") == "corroborated":
            tier = "corroborated"
        else:
            tier = "ub"
        n, k, d = doc["n"], doc["k"], doc["distance"]["d"]
        entries.append({
            "slug": slug, "name": doc["name"], "n": n, "k": k, "d": d,
            "eff": round(k * d * d / n, 3), "tier": tier,
            "w": rep["computed"].get("max_check_weight"),
            "tracks": doc["tracks"],
            "origin": doc["provenance"].get("origin", "submission"),
            "authors": ", ".join(doc["provenance"]["authors"]),
            "authors_list": doc["provenance"]["authors"],
            "construction": doc["provenance"].get("construction", ""),
            "doc": doc, "cert": cert, "hcert": hcert,
        })
    return entries


def pareto(te):
    front = set()
    for i, a in enumerate(te):
        if not any(i != j and b["n"] <= a["n"] and b["k"] >= a["k"]
                   and b["d"] >= a["d"] and (b["n"] < a["n"] or b["k"] > a["k"]
                                             or b["d"] > a["d"])
                   for j, b in enumerate(te)):
            front.add(i)
    return front


def _axis_step(hi):
    """A round tick step giving at most ~6 gridlines up to hi."""
    for s in (1, 2, 5, 10, 20, 50, 100, 200, 500):
        if hi / s <= 6:
            return s
    return 1000


def scatter(te, front, yacc, ylabel):
    """A landscape scatter of every code: x = n, y = yacc(e) (e.g. distance or
    kd^2/n). Two complementary views are shown side by side, so codes that
    coincide in one (e.g. same n and d but different k) separate in the other.
    Suppressed below a handful of distinct (n, y) points (nothing to show)."""
    if not te or len({(e["n"], round(yacc(e), 3)) for e in te}) < 4:
        return ""
    W, H = 520, 300
    pad_l, pad_r, pad_b, pad_t = 54, 12, 52, 22
    nhi = max(e["n"] for e in te) or 1
    yhi = max(yacc(e) for e in te) or 1

    def sx(n):
        return pad_l + n / nhi * (W - pad_l - pad_r)

    def sy(v):
        return H - pad_b - v / yhi * (H - pad_t - pad_b)

    grid = []
    xstep = max(1, round(nhi / 4 / 50) * 50 or 50)
    for gx in range(0, int(nhi) + 1, xstep):
        x = sx(gx)
        grid.append(f'<line x1="{x:.0f}" y1="{pad_t}" x2="{x:.0f}" y2="{H-pad_b}" '
                    f'stroke="#eef2f7"/><text x="{x:.0f}" y="{H-pad_b+18}" '
                    f'font-size="12" fill="#475569" text-anchor="middle">{gx}</text>')
    ystep = _axis_step(yhi)
    gy = 0
    while gy <= yhi + 1e-9:
        y = sy(gy)
        grid.append(f'<line x1="{pad_l}" y1="{y:.0f}" x2="{W-pad_r}" y2="{y:.0f}" '
                    f'stroke="#eef2f7"/><text x="{pad_l-8}" y="{y+4:.0f}" '
                    f'font-size="12" fill="#475569" text-anchor="end">{gy:g}</text>')
        gy += ystep

    pts = []
    for i, e in enumerate(te):
        f = i in front
        col = {"exact": EXACT, "corroborated": CORR}.get(e["tier"], ACCENT)
        r = 6 if f else 4
        fill = col if f else "#fff"
        _tlabel = {"exact": "exact", "corroborated": "corroborated"}.get(
            e["tier"], "upper bound")
        tip = (f'[[{e["n"]},{e["k"]},{e["d"]}]]  kd2/n={e["eff"]}\n'
               f'{_tlabel}{", record" if f else ""}')
        cx, cy = sx(e["n"]), sy(yacc(e))
        pts.append(f'<circle class=pt data-code="{e["slug"]}" cx="{cx:.1f}" '
                   f'cy="{cy:.1f}" r="{r}" fill="{fill}" '
                   f'stroke="{col}" stroke-width="2" pointer-events="none"/>')
        pts.append(f'<circle class=hit data-code="{e["slug"]}" cx="{cx:.1f}" '
                   f'cy="{cy:.1f}" r="12" '
                   f'fill="transparent" data-tip="{html.escape(tip)}"/>')
    x_mid = pad_l + (W - pad_l - pad_r) / 2
    y_mid = pad_t + (H - pad_t - pad_b) / 2
    return (f'<svg viewBox="0 0 {W} {H}" class="plot" role="img">'
            + "".join(grid)
            + f'<text x="{x_mid:.0f}" y="{H - 10}" font-size="13" fill="#334155" '
            f'text-anchor="middle">Physical Qubits (n)</text>'
            f'<text x="14" y="{y_mid:.0f}" font-size="13" fill="#334155" '
            f'text-anchor="middle" transform="rotate(-90 14 {y_mid:.0f})">{ylabel}</text>'
            + "".join(pts) + "</svg>")


def badge(tier):
    if tier == "exact":
        return '<span class="b exact">d =</span>'
    if tier == "corroborated":
        return ('<span class="b corr" title="heuristically corroborated: an '
                'independent search found nothing lighter">d &le;*</span>')
    return '<span class="b ub">d &le;</span>'


def mathfmt(s):
    """Light typographic math for the construction strings: render Python-style
    (x**3) and caret-style (x^-2) powers as superscripts. Laurent exponents can
    be negative. Variables are left in normal text on purpose (the strings mix
    in prose, so blanket italics would catch letters inside words)."""
    return re.sub(r"(?:\*\*|\^)(-?\d+)", r"<sup>\1</sup>", html.escape(s))


def authors_html(lst):
    """A GitHub handle is written with a leading '@' in the data and rendered as
    a profile link; anything else (a paper-author surname or citation string) is
    plain text. So '@vprusso' links, but 'Kitaev' does not."""
    out = []
    for a in lst:
        h = a.strip()
        if h.startswith("@") and re.fullmatch(r"@[A-Za-z0-9-]+", h):
            out.append(f'<a href="https://github.com/{h[1:]}">{h}</a>')
        else:
            out.append(html.escape(h))
    return ", ".join(out)


def detail_page(e):
    doc, cert = e["doc"], e["cert"]
    n, k, d = e["n"], e["k"], e["d"]
    P = [head(f"[[{n},{k},{d}]] · QEC Challenge", rel="../")]
    P.append('<div class=wrap>')
    P.append('<a class=back href="../index.html">&larr; back to the board</a>')
    P.append(f'<div class=codehead><span class="mono big">[[{n},{k},{d}]]</span> '
             f'{badge(e["tier"])}</div>')

    P.append('<div class=params>')
    params = [
        ("n", n, "physical qubits"),
        ("k", k, "logical qubits"),
        ("d", d, "distance (smallest undetectable error)"),
        ("kd&sup2;/n", e["eff"], "figure of merit, higher is better"),
        ("w", e["w"], "max check weight"),
    ]
    if "locality" in doc:
        loc = doc["locality"]
        params.append(("layers", loc.get("layers", "?"),
                       "physical layers (e.g. 2 for a flip-chip bilayer)"))
        if "interaction_radius" in loc:
            params.append(("radius", f'{loc["interaction_radius"]:.2f}',
                           "interaction radius: max check diameter in the layout"))
    for lab, val, tip in params:
        P.append(f'<div class=cell title="{html.escape(tip)}">'
                 f'<div class=l>{lab}</div><div class=v>{val}</div></div>')
    P.append('</div>')

    # share: a link back to this entry plus pre-filled posts
    url = f"{SITE_URL}/codes/{e['slug']}.html"
    msg = f"[[{n},{k},{d}]] quantum LDPC code on the QEC Challenge"
    q = urllib.parse.quote
    x_url = f"https://twitter.com/intent/tweet?text={q(msg)}&url={q(url)}"
    bsky_url = f"https://bsky.app/intent/compose?text={q(msg + ' ' + url)}"
    li_url = ("https://www.linkedin.com/sharing/share-offsite/?url="
              + q(url))
    P.append(
        '<section class=blk><h3>Share this result</h3>'
        '<div class=share>'
        f'<button class=sharebtn type=button data-copy="{html.escape(url)}" '
        f'aria-label="Copy link" title="Copy link">{LINK_ICON}</button>'
        f'<a class=sharebtn href="{html.escape(x_url)}" target=_blank '
        f'rel=noopener aria-label="Post on X" title="Post on X">{X_ICON}</a>'
        f'<a class=sharebtn href="{html.escape(bsky_url)}" target=_blank '
        f'rel=noopener aria-label="Share on Bluesky" title="Bluesky">'
        f'{BSKY_ICON}</a>'
        f'<a class=sharebtn href="{html.escape(li_url)}" target=_blank '
        f'rel=noopener aria-label="Share on LinkedIn" title="LinkedIn">'
        f'{LI_ICON}</a>'
        '</div></section>')

    # distance + certificate
    P.append('<section class=blk><h3>Distance</h3>')
    for side in ("X", "Z"):
        if side in doc["distance"]:
            sd = doc["distance"][side]
            wit = sd["witness"]
            P.append(f'<div class=kv><b>d_{side}</b> {sd["value"]} '
                     f'&middot; witness weight {len(wit)} '
                     f'({"claimed " + sd["confidence"]})</div>')
            P.append(f'<details><summary>witness operator (support, {len(wit)} '
                     f'qubits)</summary><div class=wit>{wit}</div></details>')
    if cert and cert.get("d_exact"):
        notes = "; ".join(f'{s}: {v["note"]}' for s, v in
                          cert.get("sides", {}).items())
        P.append(f'<div class=kv><b>certificate</b> '
                 f'<span class=cert-ok>exact, d = {d}</span> &middot; '
                 f'{html.escape(cert.get("solver",""))}</div>'
                 f'<div class=kv style="color:var(--mut)">{html.escape(notes)}</div>')
    else:
        P.append('<div class=kv><b>certificate</b> '
                 '<span class=cert-no>none yet &middot; distance stands as a '
                 'self-certified upper bound (d &le;)</span></div>')
    P.append('</section>')

    # construction / provenance
    pr = doc["provenance"]
    P.append('<section class=blk><h3>Construction &amp; provenance</h3>')
    P.append(f'<div class=kv><b>authors</b> {authors_html(pr["authors"])}</div>')
    P.append(f'<div class=kv><b>construction</b> {mathfmt(pr.get("construction",""))}</div>')
    if pr.get("references"):
        refs = [cite(r, rel="../") for r in pr["references"]]
        # A baseline IS the cited paper's code; a submission only builds on the
        # family it cites, so don't label its reference as if it were the source.
        lbl = "reference" if pr.get("origin") == "baseline" else "builds on"
        P.append(f'<div class=kv><b>{lbl}</b> {", ".join(refs)}</div>')
    if pr.get("date"):
        P.append(f'<div class=kv><b>date</b> {html.escape(pr["date"])}</div>')
    if pr.get("notes"):
        P.append(f'<div class=kv><b>notes</b> {html.escape(pr["notes"])}</div>')
    P.append(f'<div class=kv><b>tracks</b> {html.escape(", ".join(doc["tracks"]))}</div>')
    P.append('</section>')

    # parity checks
    X, Z = doc["checks"]["X"], doc["checks"]["Z"]
    P.append('<section class=blk><h3>Parity checks</h3>')
    P.append(f'<div class=kv><b>X-checks</b> {len(X)} &middot; '
             f'<b style="min-width:auto">Z-checks</b> {len(Z)}</div>')
    for nm, H in (("H_X", X), ("H_Z", Z)):
        body = "\n".join(str(s) for s in H)
        P.append(f'<details><summary>{nm} ({len(H)} checks, sparse supports)'
                 f'</summary><div class=wit>{body}</div></details>')
    P.append(f'<div class=kv style="margin-top:10px"><a href="{REPO}/codes/'
             f'{e["slug"]}.json">raw submission JSON</a></div>')
    P.append('</section>')

    P.append("<script>document.querySelectorAll('[data-copy]').forEach("
             "b=>b.addEventListener('click',()=>{navigator.clipboard"
             ".writeText(b.dataset.copy);const o=b.innerHTML;"
             "b.innerHTML='\\u2713';b.title='link copied';"
             "setTimeout(()=>{b.innerHTML=o;b.title='Copy link';},1400);}));"
             "</script>")
    P.append('</div></body></html>')
    return "\n".join(P)


def fmt_citation(e, extra=""):
    """One reference, formatted as HTML: bibtag, authors, title, venue/year,
    links, plus an optional trailing block (e.g. the citing codes)."""
    sn = e.get("author", "")
    authors = " and ".join(a.strip() for a in sn.split(" and ")) if sn else ""
    title = html.escape(e.get("title", e["key"]))
    bits = []
    pages = e.get("pages", "").replace("--", "-")
    if e.get("journal"):
        v = e["journal"]
        if e.get("volume"):
            v += f" {e['volume']}"
        if e.get("number"):
            v += f"({e['number']})"
        if pages:
            v += f":{pages}"
        bits.append(html.escape(v))
    elif e.get("booktitle"):
        v = f"In {e['booktitle']}"
        if pages:
            v += f", pp. {pages}"
        bits.append(html.escape(v))
    if e.get("year"):
        bits.append(html.escape(e["year"]))
    links = []
    if e.get("eprint"):
        links.append(f'<a href="https://arxiv.org/abs/{e["eprint"]}">'
                     f'arXiv:{html.escape(e["eprint"])}</a>')
    if e.get("doi"):
        links.append(f'<a href="https://doi.org/{html.escape(e["doi"])}">doi</a>')
    if e.get("url") and not e.get("eprint") and not e.get("doi"):
        host = re.sub(r"^https?://(www\.)?|/.*$", "", e["url"]) or "link"
        links.append(f'<a href="{html.escape(e["url"])}">{html.escape(host)}</a>')
    out = [f'<div class=ref id="{html.escape(e["key"])}">']
    out.append(f'<span class=refkey>{html.escape(e["key"])}</span>')
    out.append('<div class=refbody>')
    if authors:
        sep = "" if authors.endswith(".") else "."
        out.append(f'<span class=refauth>{html.escape(authors)}{sep}</span> ')
    out.append(f'<span class=reftitle>{title}.</span>')
    if bits:
        out.append(f' <span class=refmeta>{". ".join(bits)}.</span>')
    if links:
        out.append(f' {" &middot; ".join(links)}')
    out.append(extra)
    out.append('</div></div>')
    return "".join(out)


def references_page(entries):
    """Page listing every bib entry, with the codes that cite each one."""
    # which on-board codes cite each key
    citers = {e["key"]: [] for e in REFS}
    for ent in entries:
        for r in ent["doc"]["provenance"].get("references", []):
            k = resolve_ref(r)
            if k and ent["slug"] not in [c[0] for c in citers.get(k, [])]:
                citers.setdefault(k, []).append(
                    (ent["slug"], ent["n"], ent["k"], ent["d"]))
    P = [head("References | QEC Challenge", rel="")]
    P.append('<div class=wrap>')
    P.append('<a class=back href="index.html">&larr; back to the board</a>')
    P.append('<h1 style="margin:.4rem 0 0">References</h1>')
    P.append('<p style="color:var(--mut);max-width:60ch">Every paper and tool '
             'the challenge cites. Submissions reference an entry by its arXiv '
             'id or DOI; verified codes that cite each one are listed beneath '
             'it. The machine-readable source is '
             f'<a href="{REPO}/refs.bib">refs.bib</a>.</p>')
    for e in REFS:
        cs = citers.get(e["key"], [])
        extra = ""
        if cs:
            links = "".join(f'<a href="codes/{s}.html">[[{n},{k},{d}]]</a>'
                            for s, n, k, d in
                            sorted(cs, key=lambda c: (c[2], -c[3], c[1])))
            extra = (f'<div class=refcited><span>cited by {len(cs)}</span>'
                     f'{links}</div>')
        P.append(fmt_citation(e, extra))
    P.append('</div></body></html>')
    return "\n".join(P)



def progress_panel(entries, n_exact, best_eff):
    """The prominent stats bar at the top of the board: the headline numbers as
    big cards. This is the single home for the board's numbers (the hero carries
    none). The 'new codes' count is contributed (non-baseline) codes only."""
    n_base = sum(1 for e in entries if e["origin"] == "baseline")
    n_contrib = len(entries) - n_base
    metrics = [
        (str(n_contrib), "new codes",
         "new codes found and submitted through the challenge"),
        (str(n_base), "literature baselines",
         "published codes seeded as the bar to beat"),
        (str(n_exact), "certified exact",
         "distance proven exact by server-side certification (d =)"),
        (f"{best_eff:g}", "best kd&sup2;/n", ""),
    ]
    cards = "".join(f'<div class="stat-card{" hero" if i == 0 else ""}"'
                    f'{f" title=\"{t}\"" if t else ""}>'
                    f'<div class=v>{v}</div>'
                    f'<div class=l>{lab}</div></div>'
                    for i, (v, lab, t) in enumerate(metrics))
    return f'<section class=statsbar>{cards}</section>'


def contributors_panel(entries, tracks):
    """A leaderboard of who has found the codes on the board. Ranks GitHub-handle
    authors of contributed (non-baseline) codes by how many they have on the
    board, then by how many sit on a track frontier, then by best kd2/n. The
    seeded literature authors are not contributors and are excluded."""
    front_slugs = set()
    for idxs in tracks.values():
        te = [entries[i] for i in idxs]
        for j in pareto(te):
            front_slugs.add(te[j]["slug"])
    stats = {}
    for e in entries:
        if e["origin"] == "baseline":
            continue
        for a in e["authors_list"]:
            h = a.strip()
            if not (h.startswith("@") and re.fullmatch(r"@[A-Za-z0-9-]+", h)):
                continue
            s = stats.setdefault(h, {"codes": 0, "front": 0, "exact": 0,
                                     "eff": 0.0})
            s["codes"] += 1
            s["front"] += e["slug"] in front_slugs
            s["exact"] += e["tier"] == "exact"
            s["eff"] = max(s["eff"], e["eff"])
    if not stats:
        return ""
    order = sorted(stats.items(),
                   key=lambda kv: (-kv[1]["codes"], -kv[1]["front"],
                                   -kv[1]["eff"], kv[0]))
    n_codes = sum(1 for e in entries if e["origin"] != "baseline")

    def metric(v, lab):
        return (f'<span class=lbm><b>{v}</b>'
                f'<span class=lbml>{lab}</span></span>')

    rows = []
    for r, (h, s) in enumerate(order, 1):
        crown = ' <span class=lbcrown title="top contributor">&#128081;</span>' \
            if r == 1 else ''
        rows.append(
            f'<a class=lbrow href="https://github.com/{h[1:]}">'
            f'<span class=lbrank>{r}</span>'
            f'<img class=lbav loading=lazy alt="" '
            f'src="https://github.com/{h[1:]}.png?size=64">'
            f'<span class=lbname>{html.escape(h)}{crown}</span>'
            + metric(s["codes"], "codes")
            + metric(s["front"], "on frontier")
            + metric(s["exact"], "exact")
            + metric(f'{s["eff"]:g}', "best kd&sup2;/n")
            + '</a>')
    return ('<section class=lb id=leaderboard><div class=lbhead>'
            '<div><h2 class=lbh>Leaderboard</h2>'
            f'<p class=lbsub>{len(order)} contributor'
            f'{"" if len(order) == 1 else "s"} &middot; {n_codes} codes found '
            'through the challenge</p></div>'
            f'<a class=lbcta href="{REPO}/CONTRIBUTING.md">Add yours</a>'
            '</div>'
            f'<div class=lblist>{"".join(rows)}</div></section>')


FAQ = [
    ("What is a qLDPC code?",
     "A quantum low-density parity-check code. As in classical LDPC codes, the "
     "parity checks are sparse: each check involves only a few qubits and each "
     "qubit appears in only a few checks. It is a stabilizer code (here CSS), "
     "so it has two commuting sets of checks, X-type and Z-type. A code is "
     "summarized as [[n,k,d]]: n physical qubits encode k logical qubits, and "
     "the distance d is the lowest weight of an error that can go undetected."),
    ("Where are qLDPC codes useful?",
     "Fault-tolerant quantum computing. The surface code works but spends a "
     "large number of physical qubits per logical qubit. qLDPC codes can encode "
     "more logical qubits at higher distance for the same number of physical "
     "qubits, while keeping the checks sparse and low-weight so syndrome "
     "extraction stays manageable. They are a leading route to lowering the "
     "qubit overhead of error correction."),
    ("Why does this page exist?",
     "To collect the best known qLDPC codes in one place, with every entry's "
     "parameters checked automatically instead of taken on trust. The "
     "literature is scattered; this gathers codes, verifies them, and ranks "
     "them per track on a Pareto frontier, so it is easy to see the current "
     "state of the art and where there is room to do better."),
    ("What counts as a better code?",
     "Each track ranks codes on a Pareto frontier over (n, k, d). A submission "
     "earns a place by beating that frontier: fewer physical qubits n, more "
     "logical qubits k, or a higher distance d than the codes currently on it. "
     "The board holds the best we know of in each track so you know what to aim "
     "past; it is the bar to beat, not a catalog of every code."),
    ("Why is it hard to find good qLDPC codes?",
     "The checks have to commute (the CSS condition) and stay sparse, which "
     "constrains the construction. You want high k, high d, and low n at the "
     "same time, and those pull against each other. Computing the distance d is "
     "NP-hard, so even measuring how good a candidate is can be expensive. Good "
     "codes tend to come from algebraic constructions (bicycle, product, "
     "lifted) whose parameters are hard to predict, so improving on them is "
     "largely search."),
    ("What does “verified” mean here?",
     "CI runs a verifier on every submission. It recomputes n and k over GF(2), "
     "checks the CSS commutation and the check weights, and confirms the "
     "distance witness is a genuine nontrivial logical operator of the claimed "
     "weight. That certifies the distance as an upper bound (d &le;) with no "
     "trust required. A code shows d= (certified exact) only when an "
     "independent certificate proves no shorter logical operator exists."),
    ("What do d= and d&le; mean, and how is the distance found?",
     "Distance d is the weight of the lightest nontrivial logical operator. "
     "d&le; (upper bound) means a submission exhibits an explicit logical "
     "operator of that weight, found by a decoder-based search (BP+OSD random "
     "coset, or heuristics like QDistEvol); the verifier confirms it is a "
     "genuine logical, so the distance is at most that weight. d= (certified "
     "exact) means a server-side integer program has proven no lighter logical "
     "exists. Exact certification is NP-hard and does not scale, so large codes "
     "carry a tight upper bound while small and moderate codes are certified "
     "exact. A d&le; record is provisional: if the true distance turns out "
     "lower, the entry is corrected."),
    ("What do I get if I find a new code?",
     "Bragging rights, chiefly. Your code lands on the board under your GitHub "
     "handle with a permanent link you can wave around, and if it advances a "
     "track's frontier it earns the record star (&#9733;). This is an open "
     "community leaderboard, so the rewards are accolades, a citable verified "
     "record, and the quiet respect of the few people who know what a good "
     "kd&sup2;/n means. No prize money, sorry."),
    ("How do I submit?",
     "Add one JSON file under <code>codes/</code> following the schema and open "
     "a pull request; CI verifies it automatically. See "
     f"<a href=\"{REPO}/CONTRIBUTING.md\">CONTRIBUTING</a> and "
     f"<a href=\"{REPO}/schema/SCHEMA.md\">the schema</a>. The "
     "<a href=\"https://github.com/qLDPCOrg/qLDPC\">qLDPC library</a> is a "
     "convenient way to build a code and export its parity checks."),
]


def faq_page():
    P = [head("FAQ | QEC Challenge", rel="")]
    P.append('<div class=wrap>')
    P.append('<a class=back href="index.html">&larr; back to the board</a>')
    P.append('<h1 style="margin:.4rem 0 0">FAQ</h1>')
    for q, a in FAQ:
        P.append(f'<div class=faq><h3>{html.escape(q)}</h3><p>{a}</p></div>')
    P.append('</div></body></html>')
    return "\n".join(P)


# Compact chip label and a short search token for each track type.
TYPE_LABEL = {
    "bivariate bicycle (periodic)": "BB (periodic)",
    "generalized bicycle": "GB",
    "2d-local-bilayer": "2D-local",
}
TYPE_TERM = {
    "bivariate bicycle (periodic)": "bivariate",
    "generalized bicycle": "generalized",
    "2d-local-bilayer": "2d-local",
}


def type_label(t):
    return TYPE_LABEL.get(t, t)


def type_term(t):
    return TYPE_TERM.get(t, t)


def compute_records(entries, tracks):
    """Indices of codes that sit on the Pareto frontier of at least one of their
    tracks (over n, k, d). These are the 'records' (starred, shaded)."""
    record_in = {}
    for t, idxs in tracks.items():
        te = [entries[i] for i in idxs]
        for j in pareto(te):
            record_in.setdefault(te[j]["slug"], set()).add(t)
    return {i for i, e in enumerate(entries) if e["slug"] in record_in}


def board_controls(entries, tracks, records):
    """The board heading plus the search box, type-filter pills, and filter help.
    Lives above the charts so filtering and the landscape view stay together; the
    JS finds the table by id, so its position relative to the table is free."""
    pills = "".join(
        f'<button type=button class=typepill data-q="{html.escape(type_term(t))}" '
        f'title="filter to {html.escape(t)}">{html.escape(type_label(t))}</button>'
        for t in sorted(tracks))
    return ('<section id=board>'
            '<h2 class=track>Codes '
            f'<span class=tcount>&middot; {len(entries)} total, '
            f'{len(records)} records</span></h2>'
            '<div class=searchbar>'
            '<input id=boardsearch type=text autocomplete=off '
            'placeholder="search, e.g.  weight-6 k&gt;=10 d&gt;=8  or  '
            'eff&gt;5  or  farlab" aria-label="search codes">'
            '<span id=boardcount class=searchcount></span></div>'
            f'<div class=typepills>{pills}'
            '<button type=button class="typepill clearpill" data-q="">'
            'clear</button></div>'
            '<p class=searchhelp>Filter by typing terms (all must match): a '
            'type or author name, or a comparison on <b>n</b>, <b>k</b>, '
            '<b>d</b>, <b>w</b>, or <b>eff</b> (kd&sup2;/n), e.g. '
            '<code>k&gt;=10</code> <code>d&gt;8</code> <code>eff&gt;=5</code>. '
            'The word <code>record</code> keeps only frontier records.</p>'
            '</section>')


def charts_block(entries, records):
    """The two landscape scatters side by side (stacked on narrow screens) with a
    shared HTML legend below them. The legend is HTML, not drawn into the SVG, so
    it keeps real font sizes and reflows on mobile."""
    d_plot = scatter(entries, records, lambda e: e["d"], "Code Distance (d)")
    eff_plot = scatter(entries, records, lambda e: e["eff"], "kd²/n")
    if not d_plot and not eff_plot:
        return ""
    legend = (
        '<div class=chartlegend>'
        f'<span class=ci><span class=cdot style="background:{EXACT}"></span>'
        'Certified exact</span>'
        f'<span class=ci><span class=cdot style="background:{CORR}"></span>'
        'Corroborated</span>'
        f'<span class=ci><span class=cdot style="background:{ACCENT}"></span>'
        'Upper bound</span>'
        f'<span class=ci><span class=cdot style="background:{ACCENT}"></span>'
        'Filled = Pareto record</span>'
        '<span class=ci><span class=cdot '
        f'style="background:#fff;border:2px solid {ACCENT}"></span>'
        'Open = non-frontier</span>'
        '</div>')
    return f'<div class=plots>{d_plot}{eff_plot}</div>{legend}'


def board_table(entries, records):
    """The searchable, sortable table of every code, with the track type as a
    column of chips. Search and charts are rendered separately, above; this is
    the table itself."""
    def chips(e):
        return "".join(
            f'<span class=tchip title="{html.escape(t)}">'
            f'{html.escape(type_label(t))}</span>'
            for t in sorted(e["tracks"]))

    cols = ('<colgroup><col style="width:3%"><col style="width:16%">'
            '<col style="width:16%"><col style="width:7%"><col style="width:7%">'
            '<col style="width:9%"><col style="width:10%"><col style="width:6%">'
            '<col style="width:26%"></colgroup>')
    head = ('<thead><tr><th></th>'
            '<th data-c=codekey data-num title="the code, written [[n,k,d]]; '
            'sorts by n, then k, then d">code</th>'
            '<th data-c=type title="construction family / track">type</th>'
            '<th data-c=n class=num title="physical qubits">n</th>'
            '<th data-c=k class=num title="logical qubits">k</th>'
            '<th data-c=d class=num title="distance">d</th>'
            '<th data-c=eff class=num title="k&middot;d&sup2;/n, higher is better">'
            'kd&sup2;/n</th>'
            '<th data-c=w class=num title="max check weight">w</th>'
            '<th data-c=auth title="who submitted it">authors</th></tr></thead>')
    order = sorted(range(len(entries)),
                   key=lambda i: (-entries[i]["k"], -entries[i]["d"],
                                  entries[i]["n"]))
    rows = []
    for i in order:
        e = entries[i]
        fr = i in records
        ts = sorted(e["tracks"])
        rows.append(
            f'<tr class="{"fr" if fr else ""}" data-href="codes/{e["slug"]}.html" '
            f'data-code="{e["slug"]}" data-name="[[{e["n"]},{e["k"]},{e["d"]}]]" '
            f'data-n="{e["n"]}" data-k="{e["k"]}" data-d="{e["d"]}" '
            f'data-codekey="{e["n"]*1000000 + e["k"]*1000 + e["d"]}" '
            f'data-eff="{e["eff"]}" data-w="{e["w"]}" '
            f'data-type="{html.escape(", ".join(type_label(t) for t in ts))}" '
            f'data-tracks="{html.escape(" ".join(t.lower() for t in ts))}" '
            f'data-record="{1 if fr else 0}" '
            f'data-auth="{html.escape(e["authors"])}">'
            f'<td class=star title="{"record on its type frontier" if fr else ""}">'
            f'{"&#9733;" if fr else ""}</td>'
            f'<td><span class=mono>[[{e["n"]},{e["k"]},{e["d"]}]]</span>'
            + ('<span class=hexwrap title="found and submitted through the '
               f'challenge">{HEX_MARK}</span>'
               if e["origin"] != "baseline" else "")
            + f'</td><td class=typecell>{chips(e)}</td>'
            f'<td class=num>{e["n"]}</td><td class=num>{e["k"]}</td>'
            f'<td class=num>{badge(e["tier"])} {e["d"]}</td>'
            f'<td class=num>{e["eff"]}</td><td class=num>{e["w"]}</td>'
            f'<td class=auth>{authors_html(e["authors_list"])}</td></tr>')

    return (f'<table class=board id=mainboard>{cols}{head}'
            f'<tbody>{"".join(rows)}</tbody></table>')


def build():
    entries = load_entries()
    tracks = {}
    for i, e in enumerate(entries):
        for t in e["tracks"]:
            tracks.setdefault(t, []).append(i)
    n_exact = sum(1 for e in entries if e["tier"] == "exact")
    best_eff = max((e["eff"] for e in entries), default=0)
    records = compute_records(entries, tracks)

    P = [head("QEC Challenge")]
    P.append('<header class=hero><div class=wrap>'
             '<div class=brand>'
             '<span class=brandmark>'
             '<a href="https://unitary.foundation" '
             f'aria-label="Unitary Foundation">{UF_LOGO}</a>'
             '</span></div>'
             '<h1>QEC Challenge</h1>'
             '<p>Find better quantum LDPC codes. '
             '<a href="planar_code_challenge.pdf">Read the whitepaper.</a></p>'
             '<nav class=topnav>'
             '<a href="faq.html">FAQ</a>'
             f'<a href="{REPO}/CONTRIBUTING.md">How to contribute</a>'
             '<a href="#leaderboard">Leaderboard</a>'
             f'<a href="{REPO}/TRACKS.md">Tracks</a>'
             '<a href="references.html">References</a>'
             f'<a href="{REPO_ROOT}">{GH_ICON}GitHub</a>'
             '</nav>'
             '</div></header>')
    P.append('<div class=wrap>')
    P.append(progress_panel(entries, n_exact, best_eff))
    P.append(board_controls(entries, tracks, records))
    P.append(charts_block(entries, records))
    P.append(contributors_panel(entries, tracks))
    P.append('<div class=how>'
             '<div class=card><span class=n>1</span><h3>Build a code</h3>'
             '<p>A CSS qLDPC code, written as one JSON file with its parity '
             'checks and a distance witness.</p></div>'
             '<div class=card><span class=n>2</span><h3>Open a PR</h3>'
             '<p>Add it under <code>codes/</code>. CI runs the verifier on '
             'every submission automatically.</p></div>'
             '<div class=card><span class=n>3</span><h3>Climb the board</h3>'
             '<p>If it advances a track&rsquo;s frontier it is highlighted. '
             'Click any row for the witness, certificate, and checks.</p>'
             '</div></div>')
    P.append('<div class=legend>'
             '<span class=legbreak><span class=swatch></span>&#9733; '
             '<b>record</b> (shaded rows): on the Pareto frontier of at least '
             'one of its types, i.e. no other code of that type beats it on all '
             'of (n, k, d). Plain (unshaded) rows are dominated everywhere.</span>'
             '<span><span class="dot ex"></span> certified exact '
             '(<span class="b exact">d =</span>)</span>'
             '<span><span class="dot ac"></span> upper bound '
             '(<span class="b ub">d &le;</span>)</span>'
             f'<span><span class=hexwrap style="margin-left:0">{HEX_MARK}</span> '
             'found through the challenge (unmarked = literature baseline)</span>'
             '<span class=collegend><b>columns:</b> '
             '<b>n</b> physical qubits &middot; <b>k</b> logical qubits '
             '&middot; <b>d</b> distance (smallest undetectable error) '
             '&middot; <b>kd&sup2;/n</b> figure of merit, higher is better '
             '&middot; <b>w</b> max check weight</span>'
             '</div>')
    P.append(board_table(entries, records))
    P.append('</div>')  # close the main content wrap; footer is full-width
    P.append(
        '<footer class=foot><div class=footmain>'
        '<div class=footbrand><div class=fb>'
        f'<svg width=34 height=34 viewBox="0 0 64 64" aria-hidden="true">{MARK}'
        '</svg><span>QEC Challenge</span></div>'
        '<p>An open, automatically verified leaderboard for quantum '
        'low-density parity-check codes.</p></div>'
        '<nav class=footlinks>'
        f'<a href="{REPO_ROOT}">{GH_ICON}GitHub</a>'
        f'<a href="{REPO}/CONTRIBUTING.md">Contribute</a>'
        f'<a href="{REPO}/schema/SCHEMA.md">Schema</a>'
        f'<a href="{REPO}/TRACKS.md">Tracks</a>'
        '<a href="faq.html">FAQ</a>'
        '<a href="references.html">References</a>'
        '<a href="planar_code_challenge.pdf">Whitepaper</a>'
        '</nav></div>'
        '<div class=footbar>&copy; 2026 &middot; Built by '
        '<a href="https://unitary.foundation">Unitary Foundation</a> '
        f'&middot; <a href="{REPO}/LICENSE">Apache 2.0</a></div></footer>')
    P.append('<div id=tip></div>')
    P.append(f'<script>{JS}</script></body></html>')

    os.makedirs(os.path.join(DOCS, "codes"), exist_ok=True)
    # serve the raw static files on GitHub Pages without Jekyll processing
    open(os.path.join(DOCS, ".nojekyll"), "w").close()
    with open(os.path.join(DOCS, "index.html"), "w") as f:
        f.write("\n".join(P))
    with open(os.path.join(DOCS, "favicon.svg"), "w") as f:
        f.write(FAVICON)
    with open(os.path.join(DOCS, "references.html"), "w") as f:
        f.write(references_page(entries))
    with open(os.path.join(DOCS, "faq.html"), "w") as f:
        f.write(faq_page())
    slugs = {e["slug"] for e in entries}
    for e in entries:
        with open(os.path.join(DOCS, "codes", e["slug"] + ".html"), "w") as f:
            f.write(detail_page(e))
    # prune orphan detail pages left behind when a code is removed
    for f in glob.glob(os.path.join(DOCS, "codes", "*.html")):
        if os.path.splitext(os.path.basename(f))[0] not in slugs:
            os.remove(f)

    # machine-readable stats; the README badges (shields.io dynamic JSON) read
    # this file from the live site, so there is no committed badge image to fall
    # out of sync.
    stats = {"verified_codes": len(entries), "certified_exact": n_exact,
             "tracks": len(tracks), "best_kd2_over_n": best_eff}
    with open(os.path.join(DOCS, "stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    print(f"wrote docs/index.html + {len(entries)} detail pages + "
          f"references.html ({len(REFS)} refs), "
          f"{len(tracks)} tracks, {n_exact} certified exact")


if __name__ == "__main__":
    build()
