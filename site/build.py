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
from qldpc_verify import file_size_error, verify

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
# logo node), near-black surfaces. Green is kept as the functional tier
# signal (certified exact) for chart and badge legibility.
ACCENT = "#36006c"        # UF deep purple (links, accents, stars) — reads on white
HILITE = "#ffff00"        # UF signature yellow (highlight node, hero glow, records)
EXACT = "#059669"         # certified-exact green, on light backgrounds
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

# Decorative flow-line layer for the hero background, drifting trails along smooth
# ribbons (opt-in via ?bg=1; CSS animates dashoffset, off under reduced-motion).
HERO_FLOW = (
    '<svg class=heroflow viewBox="0 0 1200 360" '
    'preserveAspectRatio="xMidYMid slice" aria-hidden="true">'
    '<path d="M-60,90 C250,20 450,260 760,150 S1160,40 1300,120"/>'
    '<path d="M-60,205 C200,300 500,80 790,225 S1110,265 1300,180"/>'
    '<path d="M-60,300 C300,180 520,360 820,255 S1130,120 1300,300"/>'
    '<path d="M-60,40 C220,140 480,-20 760,90 S1090,180 1300,50"/>'
    '<path d="M-60,260 C280,360 540,200 800,320 S1190,220 1300,260"/>'
    '</svg>')

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
# code as submitted through the challenge, the way the star flags the frontier.
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

# a person glyph, shown in the model column for classical (human) constructions
# that were not produced by an AI model.
HUMAN_MARK = (
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" '
    'fill="none" stroke="currentColor" stroke-width="1.4" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="8" cy="5" r="2.6"/>'
    '<path d="M2.8 14c0-3 2.4-4.6 5.2-4.6S13.2 11 13.2 14"/></svg>')

# Claude mark (the sunburst), shown in the model column for codes a contributor
# reports were produced with Claude. Official brand mark, in brand coral.
CLAUDE_MARK = (
    '<svg class=modelicon viewBox="0 0 24 24" width="15" height="15" '
    'role="img" aria-label="Claude"><title>Claude</title>'
    '<path fill="#D97757" d="m4.7144 15.9555 4.7174-2.6471.079-.2307-.079-.1275'
    'h-.2307l-.7893-.0486-2.6956-.0729-2.3375-.0971-2.2646-.1214-.5707-.1215'
    '-.5343-.7042.0546-.3522.4797-.3218.686.0608 1.5179.1032 2.2767.1578 1.6514'
    '.0972 2.4468.255h.3886l.0546-.1579-.1336-.0971-.1032-.0972L6.973 9.8356'
    'l-2.55-1.6879-1.3356-.9714-.7225-.4918-.3643-.4614-.1578-1.0078.6557-.7225'
    '.8803.0607.2246.0607.8925.686 1.9064 1.4754 2.4893 1.8336.3643.3035.1457'
    '-.1032.0182-.0728-.164-.2733-1.3539-2.4467-1.445-2.4893-.6435-1.032-.17'
    '-.6194c-.0607-.255-.1032-.4674-.1032-.7285L6.287.1335 6.6997 0l.9957.1336'
    '.419.3642.6192 1.4147 1.0018 2.2282 1.5543 3.0296.4553.8985.2429.8318.091'
    '.255h.1579v-.1457l.1275-1.706.2368-2.0947.2307-2.6957.0789-.7589.3764'
    '-.9107.7468-.4918.5828.2793.4797.686-.0668.4433-.2853 1.8517-.5586 2.9021'
    '-.3643 1.9429h.2125l.2429-.2429.9835-1.3053 1.6514-2.0643.7286-.8196.85'
    '-.9046.5464-.4311h1.0321l.759 1.1293-.34 1.1657-1.0625 1.3478-.8804 1.1414'
    '-1.2628 1.7-.7893 1.36.0729.1093.1882-.0183 2.8535-.607 1.5421-.2794 1.8396'
    '-.3157.8318.3886.091.3946-.3278.8075-1.967.4857-2.3072.4614-3.4364.8136'
    '-.0425.0304.0486.0607 1.5482.1457.6618.0364h1.621l3.0175.2247.7892.522'
    '.4736.6376-.079.4857-1.2142.6193-1.6393-.3886-3.825-.9107-1.3113-.3279h'
    '-.1822v.1093l1.0929 1.0686 2.0035 1.8092 2.5075 2.3314.1275.5768-.3218'
    '.4554-.34-.0486-2.2039-1.6575-.85-.7468-1.9246-1.621h-.1275v.17l.4432'
    '.6496 2.3436 3.5214.1214 1.0807-.17.3521-.6071.2125-.6679-.1214-1.3721'
    '-1.9246L14.38 17.959l-1.1414-1.9428-.1397.079-.674 7.2552-.3156.3703'
    '-.7286.2793-.6071-.4614-.3218-.7468.3218-1.4753.3886-1.9246.3157-1.53'
    '.2853-1.9004.17-.6314-.0121-.0425-.1397.0182-1.4328 1.9672-2.1796 2.9446'
    '-1.7243 1.8456-.4128.164-.7164-.3704.0667-.6618.4008-.5889 2.386-3.0357'
    ' 1.4389-1.882.929-1.0868-.0062-.1579h-.0546l-6.3385 4.1164-1.1293.1457'
    '-.4857-.4554.0608-.7467.2307-.2429 1.9064-1.3114Z"/></svg>')


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
--exb:{GREEN_BRIGHT};--dark:{DARK};--bg:#fff;--soft:#f8fafc}}
*{{box-sizing:border-box}}
/* Unitary Foundation type stack: Manrope for body and page-level headings
   (H1/H2, per UF homepage), Space Grotesk for in-container display text,
   Space Mono for code. Loaded from Google Fonts in head(). */
body{{font-family:'Manrope',system-ui,-apple-system,sans-serif;
color:var(--ink);margin:0;background:var(--bg);line-height:1.55}}
h1,h2{{font-family:'Manrope',system-ui,sans-serif;letter-spacing:-.01em}}
h3,.codehead .big,.lbh,.ph{{font-family:'Space Grotesk',
'Manrope',system-ui,sans-serif;letter-spacing:-.01em}}
.mono{{font-family:'Space Mono',ui-monospace,'SF Mono',Menlo,monospace;
font-weight:700}}
.wrap{{max-width:1080px;margin:0 auto;padding:0 24px}}
header.hero{{background:
radial-gradient(115% 130% at 50% -25%,rgba(255,255,0,.18),transparent 60%),
repeating-linear-gradient(0deg,transparent 0 27px,rgba(255,255,255,.05) 27px 28px),
repeating-linear-gradient(90deg,transparent 0 27px,rgba(255,255,255,.05) 27px 28px),
var(--dark);color:#fff;padding:54px 0 50px;
position:relative;overflow:hidden;
border-bottom:4px solid {HILITE}}}
header.hero>.wrap{{position:relative;z-index:1}}
.heroflow{{position:absolute;inset:0;width:100%;height:100%;z-index:0;
pointer-events:none}}
.heroflow path{{fill:none;stroke:{HILITE};stroke-width:1.5;opacity:.10;
stroke-linecap:round;stroke-dasharray:130 420;
animation:flowtrail 15s linear infinite}}
.heroflow path:nth-child(2){{opacity:.07;animation-duration:21s;animation-delay:-4s}}
.heroflow path:nth-child(3){{opacity:.08;animation-duration:26s;animation-delay:-9s}}
.heroflow path:nth-child(4){{opacity:.06;animation-duration:18s;animation-delay:-2s}}
.heroflow path:nth-child(5){{opacity:.05;animation-duration:30s;animation-delay:-13s}}
@keyframes flowtrail{{to{{stroke-dashoffset:-1100}}}}
@media (prefers-reduced-motion:reduce){{.heroflow path{{animation:none;opacity:.06}}}}
.brand{{display:flex;align-items:center;justify-content:space-between;
gap:16px;margin:0 0 18px}}
.brandmark{{display:flex;align-items:center;gap:16px}}
.brand .brandmark svg{{flex:0 0 auto}}
.uflogo{{height:38px;width:auto;display:block;
filter:drop-shadow(0 4px 14px rgba(0,0,0,.35))}}
.ghlink{{display:inline-flex;align-items:center;gap:8px;color:#fff;
font-family:'Space Mono',ui-monospace,monospace;
text-decoration:none;font-size:14px;font-weight:700;
border:1px solid rgba(255,255,255,.28);border-radius:9px;padding:8px 14px;
background:rgba(255,255,255,.08)}}
.ghlink:hover{{background:rgba(255,255,255,.18)}}
header.hero h1{{font-size:clamp(30px,6vw,44px);margin:0;letter-spacing:-1px}}
header.hero h1 a{{color:#fff}}
header.hero p{{font-size:18px;max-width:640px;margin:0;color:#e4e4e7}}
header.hero p a{{color:{HILITE};text-decoration:underline}}
header.hero p a:hover{{background:{HILITE};color:#111;text-decoration:none}}
.topnav{{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}}
.topnav a{{display:inline-flex;align-items:center;gap:7px;color:#e4e4e7;
font-family:'Space Mono',ui-monospace,monospace;
font-size:14px;font-weight:700;padding:7px 14px;
border:1px solid rgba(255,255,255,.18);border-radius:8px;
background:rgba(255,255,255,.06)}}
.topnav a:hover{{background:{HILITE};color:#111;border-color:{HILITE}}}
.stats{{display:flex;gap:40px;margin-top:30px;flex-wrap:wrap}}
.stat .v{{font-size:30px;font-weight:700;
font-family:'Space Mono',ui-monospace,monospace}}
.stat .l{{color:#c7d2fe;font-size:13px;
text-transform:uppercase;letter-spacing:.05em}}
.statsbar{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:14px;margin:28px 0 8px}}
.stat-card{{border:1px solid var(--ln);border-radius:14px;padding:18px 20px;
background:var(--soft)}}
.stat-card.hero{{border-color:var(--ac);background:#fffbe0}}
.stat-card .v{{font-size:34px;font-weight:700;line-height:1.05;
font-family:'Space Mono',ui-monospace,monospace}}
.stat-card.hero .v{{color:var(--ac)}}
.stat-card .l{{font-size:13px;color:var(--mut);margin-top:6px}}
.lb{{margin:18px 0 8px;border:1px solid var(--ln);border-radius:14px;
background:#fff;overflow:hidden}}
.lbhead{{display:flex;justify-content:space-between;align-items:center;gap:16px;
padding:16px 20px;background:var(--soft);border-bottom:1px solid var(--ln)}}
.lbh{{font-size:16px;margin:0;font-family:'Space Mono',ui-monospace,monospace;
text-transform:uppercase;letter-spacing:.03em}}
.lbsub{{margin:4px 0 0;font-size:13px;color:var(--mut)}}
.lbcta{{flex:0 0 auto;font-size:13px;font-weight:700;color:#fff;
font-family:'Space Mono',ui-monospace,monospace;
background:var(--ac);border:none;border-radius:8px;padding:8px 14px;
text-decoration:none;cursor:pointer;transition:background .15s}}
.lbcta:hover{{background:#5b21b6}}
.herocta{{padding:9px 16px;font-size:14px;
box-shadow:0 4px 14px rgba(0,0,0,.35)}}
.modal{{position:relative;border:none;border-radius:14px;padding:22px 24px;
max-width:520px;width:92%;box-shadow:0 20px 60px rgba(17,17,17,.25)}}
.modal::backdrop{{background:rgba(17,17,17,.45)}}
.modalx{{position:absolute;top:10px;right:12px;border:none;background:none;
font-size:24px;line-height:1;color:var(--mut);cursor:pointer}}
.modalh{{margin:0 0 2px;font-size:20px}}
.modalsub{{margin:0 0 14px;color:var(--mut);font-size:14px}}
.codeblock{{background:var(--dark);border-radius:10px;padding:12px 14px 14px}}
/* header row holds the copy button so it never overlaps the commands */
.cbbar{{display:flex;justify-content:flex-end;margin-bottom:6px}}
/* the pre is the horizontal scroller; each command stays on its own line
   (no wrap) so a long clone URL can't bleed into the next command */
.codeblock pre{{margin:0;overflow-x:auto}}
.codeblock code{{display:block;color:#e4e4e7;font-size:13px;line-height:1.7;
white-space:pre;background:none;padding:0;border:none}}
.codeblock ::selection{{background:#4f46e5;color:#fff}}
.codeblock .cmt{{color:#8a8f98;background:none}}
.copybtn{{border:1px solid #3a3f4a;
background:#1c2230;color:#cbd5e1;font-size:12px;padding:3px 8px;
border-radius:6px;cursor:pointer}}
.modalfoot{{margin:12px 0 0;font-size:13px;color:var(--mut)}}
.modalfoot a{{color:var(--ac)}}
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
/* phones: show every metric column (codes/frontier/exact/kd2n) instead of
   hiding the right-hand ones. The list scrolls horizontally as one unit; rows
   share a min-width so the columns stay aligned row-to-row while scrolling. */
@media(max-width:680px){{.lbm{{width:64px}}
.lblist{{overflow-x:auto}}
.lbrow{{min-width:520px}}
.lbname{{min-width:96px}}}}
.how{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin:40px 0}}
.how .card{{border:1px solid var(--ln);border-radius:12px;padding:20px;
background:var(--soft)}}
.how .n{{display:inline-flex;width:26px;height:26px;border-radius:50%;
background:var(--ac);color:#fff;align-items:center;justify-content:center;
font-size:14px;font-weight:700;margin-bottom:10px;
font-family:'Space Mono',ui-monospace,monospace}}
.how h3{{margin:.2rem 0;font-size:14px;
font-family:'Space Mono',ui-monospace,monospace;
text-transform:uppercase;letter-spacing:.03em}}
.how p{{margin:0;color:var(--mut);
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
.plotx{{text-align:center;font-size:13px;color:#334155;margin:2px 0 0}}
.cdot{{width:12px;height:12px;border-radius:50%;flex:0 0 auto}}
/* Record-progress chart: running best kd^2/n per weight class over record
   events (ecdsa.fail-style). One full-width panel; the SVG scales down. */
.rcwrap{{margin:26px 0 4px}}
.rcwrap .plot{{padding:10px 12px 6px}}
.rcsub{{font-size:13px;color:var(--mut);margin:2px 0 10px;max-width:760px}}
/* phones: scroll the wide chart instead of scaling its text away */
@media(max-width:680px){{.rcwrap .plot{{overflow-x:auto;
-webkit-overflow-scrolling:touch}}
.rcwrap svg{{min-width:760px}}}}
/* full width (matching the panels above) with fixed, evenly distributed
   columns so the slack isn't dumped into one column as a stray gap. */
table.board{{border-collapse:collapse;width:100%;table-layout:fixed;
font-size:14px;margin:12px 0}}
.board th,.board td{{padding:.55rem .9rem;text-align:left;white-space:nowrap;
border-bottom:1px solid var(--ln)}}
.board th{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;
font-family:'Space Mono',ui-monospace,monospace;
color:var(--mut);cursor:pointer;user-select:none;border-bottom:2px solid var(--ln)}}
/* Header stays visible while the rows scroll inside the bounded board box; it
   pins to the top of that scroll container. box-shadow stands in for the bottom
   border, which a collapsed table drops from a sticky cell. */
.board thead th{{position:sticky;top:0;z-index:3;
background:var(--bg);box-shadow:0 2px 0 var(--ln)}}
.board th:hover{{color:var(--ink)}}.board td.num,.board th.num{{text-align:center;
font-variant-numeric:tabular-nums}}
.board td.auth{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
max-width:220px}}
.etal{{color:var(--mut)}}
.hexwrap{{display:inline-flex;align-items:center;margin-left:8px}}
.hexmark{{color:var(--ac);vertical-align:-2px}}
.novelty{{display:inline-block;margin-left:7px;font-size:10px;line-height:1;
padding:3px 6px;border-radius:5px;background:#fef3c7;color:#92400e;
border:1px solid #fde68a;vertical-align:2px;white-space:nowrap}}
.board tbody tr{{cursor:pointer}}.board tbody tr:hover{{background:#f6f3fb}}
.board tr.fr{{background:#fffbe0}}.board tr.fr td:first-child{{
box-shadow:inset 3px 0 0 var(--ac)}}
.board tr.fr:hover{{background:#fff6c4}}
.board tbody tr.xh,.board tbody tr.fr.xh{{background:#fef3c7}}
.board tbody tr.xh td:first-child{{box-shadow:inset 3px 0 0 #f59e0b}}
.typecell{{white-space:normal!important;line-height:1.7}}
.codecell{{white-space:normal!important;line-height:1.7}}
.tchip{{display:inline-block;font-size:11px;line-height:1.25;padding:3px 7px;
margin:2px 4px 2px 0;border-radius:999px;background:var(--soft);color:var(--mut);
border:1px solid var(--ln);white-space:normal}}
.tchip.loc{{background:#eef2ff;color:#3730a3;border-color:#c7d2fe}}
/* Primary-tracks grid (locality x weight). */
.ptgrid{{margin:8px 0 4px}}
.ptsub{{font-size:13px;color:var(--mut);margin:2px 0 12px;max-width:760px}}
.ptscroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
table.grid{{border-collapse:collapse;font-size:13px;margin:0 auto}}
table.grid th,table.grid td{{border:1px solid var(--ln);padding:8px 12px;
text-align:left;vertical-align:top}}
table.grid thead th,table.grid tr:first-child th{{background:var(--soft);
font-weight:700;color:var(--ink);white-space:nowrap;font-size:12px;
font-family:'Space Mono',ui-monospace,monospace;text-transform:uppercase}}
.grow{{background:var(--soft);font-weight:700;color:var(--ink);
white-space:nowrap;font-size:12px;
font-family:'Space Mono',ui-monospace,monospace;text-transform:uppercase}}
.gcorner{{background:var(--soft)}}
.gcell{{min-width:158px}}
.gcount{{font-size:11px;color:var(--mut);background:none;border:0;padding:0;
margin:0 0 5px;cursor:pointer;font-family:inherit;text-align:left;display:block}}
.gcount:hover{{color:var(--ac);text-decoration:underline}}
.gitem{{display:flex;align-items:center;gap:6px;text-decoration:none;
padding:3px 0;color:var(--ink)}}
.gitem+.gitem{{border-top:1px dashed var(--ln)}}
.gitem:hover .gcode{{text-decoration:underline}}
.gcode{{font-family:'Space Mono',ui-monospace,monospace;font-size:12px;
color:var(--ac);font-weight:700;flex:1 1 auto}}
.gitem .geff{{font-size:11px;color:var(--mut);font-variant-numeric:tabular-nums}}
.gempty{{background:repeating-linear-gradient(45deg,#fafafa 0 6px,#fff 6px 12px)}}
.searchbar{{display:flex;align-items:center;gap:12px;margin:14px 0 8px}}
#boardsearch{{flex:1 1 0;min-width:0;font-size:14px;padding:10px 13px;
border:1px solid var(--ln);border-radius:10px;background:#fff;color:var(--ink);
font-family:inherit}}
#boardsearch:focus{{outline:none;border-color:var(--ac);
box-shadow:0 0 0 3px rgba(54,0,108,.15)}}
.searchcount{{font-size:13px;color:var(--mut);white-space:nowrap}}
/* Track tabs (OpenRouter-rankings style): a horizontal strip for picking the
   view; the active tab is filled. Scrolls horizontally on narrow screens. */
.tracktabs{{display:flex;gap:6px;margin:6px 0 10px;overflow-x:auto;
-webkit-overflow-scrolling:touch;scrollbar-width:none}}
.tracktabs::-webkit-scrollbar{{display:none}}
.ttab,.otog{{flex:0 0 auto;font-size:13px;padding:6px 13px;border-radius:999px;
cursor:pointer;border:1px solid var(--ln);background:#fff;color:var(--mut);
font-family:inherit;white-space:nowrap}}
.ttab:hover,.otog:hover{{border-color:var(--ac);color:var(--ac)}}
.ttab.active,.otog.active{{background:var(--ac);border-color:var(--ac);color:#fff}}
.filterrow{{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px;align-items:center}}
.searchhelp{{font-size:12px;color:var(--mut);margin:0 0 14px}}
.searchhelp code{{background:var(--soft);padding:1px 5px;border-radius:4px;
font-size:11px}}
/* Weight range slider, styled as a filter pill that sits inline with the type
   pills. Two overlapping range inputs share one visual track; the native track
   is full height and transparent so each 16px thumb stays centred on the line
   (rather than riding above it as a top-aligned thumb would). */
.wfilter{{display:inline-flex;align-items:center;gap:9px;
border:1px solid var(--ln);border-radius:999px;padding:4px 12px;background:#fff;
font-size:12px;color:var(--mut)}}
.wflabel{{font-weight:600;color:var(--ink);white-space:nowrap}}
.wfslider{{position:relative;width:118px;height:16px;flex:0 0 auto}}
.wftrack,.wffill{{position:absolute;top:50%;height:4px;
transform:translateY(-50%);border-radius:3px}}
.wftrack{{left:0;right:0;background:var(--ln)}}
.wffill{{background:var(--ac)}}
.wfrange{{position:absolute;top:0;left:0;width:100%;height:16px;margin:0;
background:none;pointer-events:none;-webkit-appearance:none;appearance:none}}
#whi,#dhi,#nhi,#khi{{z-index:2}}
.wfrange::-webkit-slider-runnable-track{{-webkit-appearance:none;background:none;
height:16px}}
.wfrange::-webkit-slider-thumb{{-webkit-appearance:none;pointer-events:auto;
width:16px;height:16px;border-radius:50%;background:#fff;border:2px solid var(--ac);
cursor:pointer;box-shadow:0 1px 2px rgba(17,17,17,.25)}}
.wfrange::-moz-range-track{{background:none;height:16px}}
.wfrange::-moz-range-thumb{{pointer-events:auto;width:16px;height:16px;
border-radius:50%;background:#fff;border:2px solid var(--ac);cursor:pointer;
box-shadow:0 1px 2px rgba(17,17,17,.25)}}
.wfval{{font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:700;
color:var(--ink);min-width:2.4em;text-align:right}}
.plot circle.pt.xh{{stroke:#f59e0b;stroke-width:4;r:7}}
.plot circle.hit{{cursor:pointer}}
.star{{color:var(--ac);width:18px}}
.auth{{color:var(--mut);font-size:13px}}
.board td.date{{color:var(--mut);font-size:13px;white-space:nowrap}}
.board td.model{{color:var(--mut);font-size:13px;white-space:nowrap}}
.nomodel{{color:#94a3b8;display:inline-flex;vertical-align:middle}}
.modelmark,.modelicon{{display:inline-flex;align-items:center;gap:5px;
vertical-align:middle}}
.board td.model .modelname{{font-size:13px;color:var(--ink)}}
/* Let the wide board scroll instead of crushing columns, and progressively
   drop the secondary metadata columns (model, then date) on smaller screens.
   Under the breakpoints the table sizes to content so freed space redistributes
   cleanly. */
/* The table is a bounded, internally scrolling box so the board stays compact
   instead of running the full length of the page. Its header pins to the top of
   this box (thead is position:sticky) while the rows scroll under it, and the
   plots sit just above it, both on screen at once, so the row-hover -> point
   highlight stays usable. overflow:auto also carries the horizontal scroll on
   narrow screens (where the table sets its own min-width). */
.boardscroll{{max-height:64vh;overflow:auto;-webkit-overflow-scrolling:touch;
border:1px solid var(--ln);border-radius:12px}}
@media(max-width:880px){{table.board{{table-layout:auto;min-width:600px}}
.board .model{{display:none}}}}
@media(max-width:680px){{.board .date{{display:none}}}}
/* phones: the board was cut off in a horizontal scroll with the scored columns
   (kd2/n, w) off-screen. n, k and d are already printed inside the [[n,k,d]]
   code name, and type/authors live on each row's detail page, so drop those
   columns here and let the four that matter (code, kd2/n, w, plus the record
   star) fit the viewport with no sideways scroll. */
@media(max-width:620px){{
.board .col-type,.board .col-n,.board .col-k,.board .col-d,
.board .col-auth{{display:none}}
table.board{{min-width:0;font-size:13px}}
.board th,.board td{{padding:.5rem .45rem;white-space:normal}}
.board td.auth{{max-width:none}}}}
/* phones: reclaim horizontal space and shrink oversized headers */
@media(max-width:560px){{.wrap{{padding:0 14px}}
header.hero{{padding:34px 0 30px}}
.statsbar{{grid-template-columns:repeat(2,1fr);gap:10px}}
.stat-card{{padding:14px 16px}}.stat-card .v{{font-size:27px}}}}
.claimed{{color:var(--mut);font-size:12px;font-style:italic}}
.b{{display:inline-block;font-size:11px;font-weight:700;padding:1px 6px;
border-radius:5px;font-family:ui-monospace,monospace}}
.b.exact{{background:#d1fae5;color:var(--ex)}}.b.ub{{background:#eef2f7;
color:var(--mut)}}
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
 // Hovering a chart point brings its table row into view by scrolling ONLY the
 // bounded table box, never the page, and only when the row is outside the box's
 // visible area, so a sweep over points never jumps the page.
 const reveal=code=>{
  const r=document.querySelector('tr[data-code="'+code+'"]');
  if(!r||r.offsetParent===null)return;
  const box=r.closest('.boardscroll');
  if(!box)return;
  const br=box.getBoundingClientRect(),rr=r.getBoundingClientRect();
  if(rr.top<br.top||rr.bottom>br.bottom)
   box.scrollTop+=(rr.top-br.top)-(box.clientHeight-rr.height)/2;
 };
 document.querySelectorAll('[data-code]').forEach(el=>{
  const code=el.dataset.code;
  const isPoint=el.tagName.toLowerCase()==='circle';
  el.addEventListener('mouseenter',()=>{mark(code,true); if(isPoint)reveal(code);});
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
 const wlo=document.getElementById('wlo'),whi=document.getElementById('whi');
 const wfill=document.getElementById('wffill'),wval=document.getElementById('wfval');
 const WMIN=wlo?+wlo.min:0,WMAX=wlo?+wlo.max:0,wspan=(WMAX-WMIN)||1;
 const dlo=document.getElementById('dlo'),dhi=document.getElementById('dhi');
 const dfill=document.getElementById('dffill'),dval=document.getElementById('dfval');
 const DMIN=dlo?+dlo.min:0,DMAX=dlo?+dlo.max:0,dspan=(DMAX-DMIN)||1;
 const nlo=document.getElementById('nlo'),nhi=document.getElementById('nhi');
 const nfill=document.getElementById('nffill'),nval=document.getElementById('nfval');
 const NMIN=nlo?+nlo.min:0,NMAX=nlo?+nlo.max:0,nspan=(NMAX-NMIN)||1;
 const klo=document.getElementById('klo'),khi=document.getElementById('khi');
 const kfill=document.getElementById('kffill'),kval=document.getElementById('kfval');
 const KMIN=klo?+klo.min:0,KMAX=klo?+klo.max:0,kspan=(KMAX-KMIN)||1;
 const lit=document.getElementById('littoggle');
 const cmp=/^(n|k|d|w|effw|eff)(>=|<=|>|<|=)(-?\\d+(?:\\.\\d+)?)$/;
 function term(r,t){
  const m=t.match(cmp);
  if(m){const x=parseFloat(r.dataset[m[1]]),v=parseFloat(m[3]);
   switch(m[2]){case'>=':return x>=v;case'<=':return x<=v;
    case'>':return x>v;case'<':return x<v;default:return x===v;}}
  if(t==='record'||t==='frontier')return r.dataset.record==='1';
  // cell:<locality>~<weight> keeps only the members of one primary-track cell,
  // honoring nesting via the row's precomputed data-cells list.
  if(t.slice(0,5)==='cell:')return (' '+(r.dataset.cells||'')+' ').indexOf(' '+t.slice(5)+' ')>=0;
  const hay=(r.dataset.name+' '+r.dataset.tracks+' '+r.dataset.auth+' '+(r.dataset.model||'')+' '+(r.dataset.date||'')).toLowerCase();
  return hay.indexOf(t)>=0;
 }
 // dual-handle weight slider: bounds are the lower/upper of the two handles
 // (taken symmetrically so the handles may cross without sticking).
 function wbounds(){if(!wlo||!whi)return[-Infinity,Infinity];
  return[Math.min(+wlo.value,+whi.value),Math.max(+wlo.value,+whi.value)];}
 function wpaint(){const b=wbounds();
  if(wfill){wfill.style.left=((b[0]-WMIN)/wspan*100)+'%';
   wfill.style.width=((b[1]-b[0])/wspan*100)+'%';}
  if(wval)wval.textContent=(b[0]===b[1])?(''+b[0]):(b[0]+'\\u2013'+b[1]);}
 function dbounds(){if(!dlo||!dhi)return[-Infinity,Infinity];
  return[Math.min(+dlo.value,+dhi.value),Math.max(+dlo.value,+dhi.value)];}
 function dpaint(){const b=dbounds();
  if(dfill){dfill.style.left=((b[0]-DMIN)/dspan*100)+'%';
   dfill.style.width=((b[1]-b[0])/dspan*100)+'%';}
  if(dval)dval.textContent=(b[0]===b[1])?(''+b[0]):(b[0]+'\\u2013'+b[1]);}
 function nbounds(){if(!nlo||!nhi)return[-Infinity,Infinity];
  return[Math.min(+nlo.value,+nhi.value),Math.max(+nlo.value,+nhi.value)];}
 function npaint(){const b=nbounds();
  if(nfill){nfill.style.left=((b[0]-NMIN)/nspan*100)+'%';
   nfill.style.width=((b[1]-b[0])/nspan*100)+'%';}
  if(nval)nval.textContent=(b[0]===b[1])?(''+b[0]):(b[0]+'\\u2013'+b[1]);}
 function kbounds(){if(!klo||!khi)return[-Infinity,Infinity];
  return[Math.min(+klo.value,+khi.value),Math.max(+klo.value,+khi.value)];}
 function kpaint(){const b=kbounds();
  if(kfill){kfill.style.left=((b[0]-KMIN)/kspan*100)+'%';
   kfill.style.width=((b[1]-b[0])/kspan*100)+'%';}
  if(kval)kval.textContent=(b[0]===b[1])?(''+b[0]):(b[0]+'\\u2013'+b[1]);}
 function apply(){
  const toks=q.value.toLowerCase().trim().split(/\\s+/).filter(Boolean);
  const wb=wbounds(),db=dbounds(),nb=nbounds(),kb=kbounds();
  const litOn=lit&&lit.classList.contains('active');
  const vis=new Set();let shown=0;
  rows.forEach(r=>{const w=+r.dataset.w,d=+r.dataset.d,nn=+r.dataset.n,kk=+r.dataset.k;
   const ok=(w>=wb[0]&&w<=wb[1])&&(d>=db[0]&&d<=db[1])
    &&(nn>=nb[0]&&nn<=nb[1])&&(kk>=kb[0]&&kk<=kb[1])
    &&(!litOn||r.dataset.origin==='literature')&&toks.every(t=>term(r,t));
   r.style.display=ok?'':'none';if(ok){shown++;vis.add(r.dataset.code);}});
  if(count)count.textContent=shown+(shown===rows.length?'':' of '+rows.length)+' codes';
  document.querySelectorAll('.plots svg.plot circle[data-code]').forEach(c=>{
   c.style.display=vis.has(c.dataset.code)?'':'none';});
 }
 // typing syncs the active tab (the one whose filter term matches, else none).
 q.addEventListener('input',()=>{
  document.querySelectorAll('.ttab').forEach(t=>
   t.classList.toggle('active', t.dataset.q===q.value.trim()));
  apply();});
 document.querySelectorAll('.ttab').forEach(p=>{
  p.addEventListener('click',()=>{
   document.querySelectorAll('.ttab').forEach(t=>t.classList.remove('active'));
   p.classList.add('active');
   q.value=p.dataset.q;
   // the All tab (empty filter) also resets every range slider.
   if(p.dataset.q===''){resetsliders();}
   apply();});});
 function resetsliders(){
  if(wlo&&whi){wlo.value=WMIN;whi.value=WMAX;wpaint();}
  if(dlo&&dhi){dlo.value=DMIN;dhi.value=DMAX;dpaint();}
  if(nlo&&nhi){nlo.value=NMIN;nhi.value=NMAX;npaint();}
  if(klo&&khi){klo.value=KMIN;khi.value=KMAX;kpaint();}
  if(lit)lit.classList.remove('active');}
 // Primary-tracks grid: a cell's code-count chip filters the table to that
 // (locality x weight) cell and scrolls it into view.
 document.querySelectorAll('[data-cell]').forEach(b=>{
  b.addEventListener('click',()=>{
   document.querySelectorAll('.ttab').forEach(t=>t.classList.remove('active'));
   resetsliders();q.value='cell:'+b.dataset.cell;apply();
   const bd=document.getElementById('board');
   if(bd)bd.scrollIntoView({behavior:'smooth'});});});
 if(lit)lit.addEventListener('click',()=>{lit.classList.toggle('active');apply();});
 if(wlo&&whi){wlo.addEventListener('input',()=>{wpaint();apply();});
  whi.addEventListener('input',()=>{wpaint();apply();});wpaint();}
 if(dlo&&dhi){dlo.addEventListener('input',()=>{dpaint();apply();});
  dhi.addEventListener('input',()=>{dpaint();apply();});dpaint();}
 if(nlo&&nhi){nlo.addEventListener('input',()=>{npaint();apply();});
  nhi.addEventListener('input',()=>{npaint();apply();});npaint();}
 if(klo&&khi){klo.addEventListener('input',()=>{kpaint();apply();});
  khi.addEventListener('input',()=>{kpaint();apply();});kpaint();}
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
        f'<link rel=stylesheet href="{rel}style.css"></head><body>']))


def cert_info(slug):
    p = os.path.join(CERTS, slug + ".json")
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def cert_consistent(cert, doc):
    """An exact certificate may only be honored if it agrees with the code's
    current distance (overall and per side). Guards against a stale cert left
    behind when a code's distance is edited without re-certifying."""
    dist = doc["distance"]
    if cert.get("d") is not None and cert["d"] != dist["d"]:
        return False
    sides = cert.get("sides") or {}
    for side in ("X", "Z"):
        cv = (sides.get(side) or {}).get("value")
        dv = (dist.get(side) or {}).get("value")
        if cv is not None and dv is not None and cv != dv:
            return False
    return True


def load_entries():
    entries = []
    for p in sorted(glob.glob(os.path.join(ROOT, "codes", "*.json"))):
        slug = os.path.splitext(os.path.basename(p))[0]
        ferr = file_size_error(p)
        if ferr:
            print(f"  warning: {slug}: {ferr}; skipping")
            continue
        with open(p) as f:
            doc = json.load(f)
        rep = verify(doc)   # site render: structural checks only, refutation is a CI/cron job
        if not rep["ok"]:
            continue
        earned = rep["earned_distance"].get("d")
        if not earned:
            print(f"  warning: {slug}: no earned distance; skipping board entry")
            continue
        cert = cert_info(slug)
        if cert and cert.get("d_exact") and cert_consistent(cert, doc):
            tier = "exact"
        else:
            if cert and cert.get("d_exact"):
                # cert claims exact but disagrees with the code's current distance
                # (e.g. the code was edited without re-certifying); do not honor it.
                print(f"  warning: {slug}: exact cert disagrees with the code's "
                      f"distance; not labeling it d= (re-run verify/certify.py)")
            tier = "ub"
        n, k, d = doc["n"], doc["k"], earned["value"]
        w = rep["computed"].get("max_check_weight")
        entries.append({
            "slug": slug, "name": doc["name"], "n": n, "k": k, "d": d,
            "eff": round(k * d * d / n, 3), "tier": tier,
            "w": w,
            # Weight-aware sort key (issue #165): kd^2/n divided by w^2 to
            # charge for check weight. A heuristic penalty, not a BPT saturation
            # ratio -- it borrows the large-D check-weight exponent but keeps
            # d^2, so it is not dimensionally consistent (the consistent metric
            # is the locality score f, issue #168). Display-only.
            "effw": round(k * d * d / (n * w * w), 3) if w else None,
            "family": doc.get("family", "other"),
            "locality_class": rep["computed"].get("locality_class", "unrestricted"),
            "weight_class": rep["computed"].get("weight_class", "weight-9plus"),
            "origin": doc["provenance"].get("origin", "submission"),
            "novelty": doc["provenance"].get("novelty", "unknown"),
            "authors": ", ".join(doc["provenance"]["authors"]),
            "authors_list": doc["provenance"]["authors"],
            "model": doc["provenance"].get("model", ""),
            "date": doc["provenance"].get("date", ""),
            "construction": doc["provenance"].get("construction", ""),
            "doc": doc, "cert": cert,
        })
    return entries


def pareto(te):
    """Pareto frontier over (n, k, d, w): a code is on it when no other code
    beats it on all four axes (n and w lower-is-better, k and d higher-is-
    better) with at least one strict. Check weight w is a ranking axis now that
    it is a plain code property rather than a track."""
    front = set()
    for i, a in enumerate(te):
        if not any(i != j and b["n"] <= a["n"] and b["k"] >= a["k"]
                   and b["d"] >= a["d"] and b["w"] <= a["w"]
                   and (b["n"] < a["n"] or b["k"] > a["k"]
                        or b["d"] > a["d"] or b["w"] < a["w"])
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
    W, H = 520, 274
    # x-axis label is shared below both plots, so the bottom pad only needs room
    # for the tick numbers (drawn at H-pad_b+18), not a per-plot axis title.
    pad_l, pad_r, pad_b, pad_t = 54, 12, 26, 22
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
        col = EXACT if e["tier"] == "exact" else ACCENT
        r = 6 if f else 4
        fill = col if f else "#fff"
        _tlabel = "exact" if e["tier"] == "exact" else "upper bound"
        tip = (f'[[{e["n"]},{e["k"]},{e["d"]}]]  kd2/n={e["eff"]}\n'
               f'{_tlabel}{", record" if f else ""}')
        cx, cy = sx(e["n"]), sy(yacc(e))
        pts.append(f'<circle class=pt data-code="{e["slug"]}" cx="{cx:.1f}" '
                   f'cy="{cy:.1f}" r="{r}" fill="{fill}" '
                   f'stroke="{col}" stroke-width="2" pointer-events="none"/>')
        pts.append(f'<circle class=hit data-code="{e["slug"]}" cx="{cx:.1f}" '
                   f'cy="{cy:.1f}" r="12" '
                   f'fill="transparent" data-tip="{html.escape(tip)}"/>')
    y_mid = pad_t + (H - pad_t - pad_b) / 2
    return (f'<svg viewBox="0 0 {W} {H}" class="plot" role="img">'
            + "".join(grid)
            + f'<text x="14" y="{y_mid:.0f}" font-size="13" fill="#334155" '
            f'text-anchor="middle" transform="rotate(-90 14 {y_mid:.0f})">{ylabel}</text>'
            + "".join(pts) + "</svg>")


def badge(tier):
    if tier == "exact":
        return '<span class="b exact">d =</span>'
    return ('<span class="b ub" title="verified upper bound: an explicit '
            'logical of this weight, and independent refutation searches '
            'found nothing lighter">d &le;</span>')


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
    return " and ".join(out)


def authors_compact(lst):
    """Compact author display for the board so every row is one line: GitHub
    handles (short) and single authors render in full; multi-author literature
    collapses to 'Surname et al.'. The full list is on the detail page and in
    the cell's hover title."""
    if len(lst) == 1 or all(a.strip().startswith("@") for a in lst):
        return authors_html(lst)
    surname = html.escape(lst[0].split(",")[0].strip())
    return f'{surname} <span class=etal>et al.</span>'


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
        ("kd&sup2;/n", e["eff"], "encoding-efficiency ratio (BPT), compared within a track at comparable n"),
        ("kd&sup2;/nw&sup2;", e["effw"] if e["effw"] is not None else "n/a",
         "weight-aware sort key: kd²/n divided by w² to charge for check "
         "weight (issue #165, a heuristic; the dimensionally consistent metric "
         "is the locality score f, issue #168); display-only"),
        ("w", e["w"], "max check weight"),
    ]
    if "locality" in doc:
        loc = doc["locality"]
        params.append(("layers", loc.get("layers", "?"),
                       "physical layers (e.g. 2 for a flip-chip bilayer)"))
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
    if pr.get("origin") == "baseline":
        provenance_status = "literature baseline"
    else:
        provenance_status = "submitted through the challenge"
    P.append(f'<div class=kv><b>provenance</b> {provenance_status}</div>')
    if pr.get("origin") != "baseline":
        P.append(f'<div class=kv><b>novelty</b> '
                 f'{html.escape(novelty_label(pr.get("novelty", "unknown")))}</div>')
    P.append(f'<div class=kv><b>construction</b> {mathfmt(pr.get("construction",""))}</div>')
    if pr.get("model"):
        mark = f'{CLAUDE_MARK} ' if pr["model"].startswith("Claude") else ""
        P.append('<div class=kv><b>model</b> '
                 f'<span class=modelmark>{mark}</span>{html.escape(pr["model"])} '
                 '<span class=claimed>(claimed, not verified)</span></div>')
    elif pr.get("origin") == "baseline":
        P.append('<div class=kv><b>model</b> '
                 '<span class=claimed>classical construction (no AI model)</span>'
                 '</div>')
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
    P.append('<div class=kv><b>family</b> '
             f'{html.escape(family_label(e["family"]))} '
             '<span class=claimed>(a tag, not a ranking)</span></div>')
    P.append('<div class=kv><b>locality</b> '
             f'{html.escape(LOCALITY_LABEL[e["locality_class"]])} '
             '<span class=claimed>(computed from the layout)</span></div>')
    P.append('<div class=kv><b>weight class</b> '
             f'{html.escape(WEIGHT_LABEL.get(e["weight_class"], "weight > 8"))} '
             '<span class=claimed>(computed)</span></div>')
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
    none). The contributed count is non-baseline codes only; it is not a novelty
    claim."""
    n_base = sum(1 for e in entries if e["origin"] == "baseline")
    n_contrib = len(entries) - n_base
    metrics = [
        (str(n_contrib), "submitted codes",
         "codes submitted through the challenge; not necessarily novel parameter sets"),
        (str(n_base), "literature baselines",
         "published codes seeded as the bar to beat"),
        (str(n_exact), "certified exact",
         "distance proven exact by server-side certification (d =)"),
        (f"{best_eff:g}", "best kd&sup2;/n on the board",
         "kd^2/n is the Bravyi-Poulin-Terhal saturation ratio. It is bounded and "
         "meaningful for 2D-local / bounded-weight codes at comparable n, but "
         "grows with n for high-rate codes, so it is compared within tracks, not "
         "as a global record. This is the best among the codes on this board."),
    ]
    cards = "".join(f'<div class="stat-card{" hero" if i == 0 else ""}"'
                    f'{f" title=\"{t}\"" if t else ""}>'
                    f'<div class=v>{v}</div>'
                    f'<div class=l>{lab}</div></div>'
                    for i, (v, lab, t) in enumerate(metrics))
    return f'<section class=statsbar>{cards}</section>'


def contributors_panel(entries):
    """A leaderboard of who submitted the codes on the board. Ranks GitHub-handle
    authors of contributed (non-baseline) codes by the best kd2/n among their
    codes, then by how many sit on a track frontier, then by how many they have
    on the board. The seeded literature authors are not contributors and are
    excluded."""
    front_slugs = {entries[i]["slug"] for i in compute_records(entries)}
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
                   key=lambda kv: (-kv[1]["eff"], -kv[1]["front"],
                                   -kv[1]["codes"], kv[0]))
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
    cmd = (f"git clone {REPO_ROOT}\n"
           "cd qldpc-challenge\n"
           "./qldpc submit mycode.npz --authors @you")
    modal = (
        '<dialog id=participate class=modal>'
        '<form method=dialog><button class=modalx autofocus aria-label="close">'
        '&times;</button></form>'
        '<h3 class=modalh>Participate</h3>'
        '<p class=modalsub>Run it yourself, or point a coding agent at it.</p>'
        '<div class=codeblock>'
        '<div class=cbbar>'
        f'<button class=copybtn type=button data-copy="{html.escape(cmd)}">'
        'copy</button></div>'
        f'<pre><code>git clone {REPO_ROOT}\n'
        'cd qldpc-challenge\n'
        '<span class=cmt># bring your H_X / H_Z as mycode.npz (keys hx, hz)'
        '</span>\n'
        './qldpc submit mycode.npz --authors @you</code></pre></div>'
        '<p class=modalfoot>It finds the distance witness, runs the verifier, '
        'and opens the PR for you.</p>'
        '<p class=modalfoot>Have an LLM or coding agent? '
        f'<a href="{REPO}/CONTRIBUTING.md#contribute-with-an-llm">Paste the '
        'research prompt</a> and it runs the whole loop. '
        f'<a href="{REPO}/CONTRIBUTING.md">Full guide</a></p>'
        '<script>(function(){var d=document.getElementById("participate");'
        'if(!d)return;'
        'd.addEventListener("click",function(e){if(e.target===d)d.close();});'
        'var c=d.querySelector(".copybtn");if(c)c.addEventListener("click",'
        'function(){navigator.clipboard.writeText(c.dataset.copy);'
        'var o=c.textContent;c.textContent="copied";'
        'setTimeout(function(){c.textContent=o;},1200);});})();</script>'
        '</dialog>')
    return ('<section class=lb id=leaderboard><div class=lbhead>'
            '<div><h2 class=lbh>Leaderboard</h2>'
            f'<p class=lbsub>{len(order)} contributor'
            f'{"" if len(order) == 1 else "s"} &middot; {n_codes} codes submitted '
            'through the challenge</p></div>'
            '<button class=lbcta type=button onclick="document.getElementById('
            '&quot;participate&quot;).showModal()">Participate</button>'
            '</div>'
            f'<div class=lblist>{"".join(rows)}</div>'
            + modal +
            '</section>')


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
     "To collect qLDPC codes in one place, with every entry's "
     "parameters checked automatically instead of taken on trust. The "
     "literature is scattered; this gathers codes, verifies them, and ranks "
     "them per track on a Pareto frontier, so it is easy to see this board's "
     "frontier and where there is room to do better. The frontier is "
     "board-relative: it reflects the codes seeded and submitted here, not an "
     "exhaustive snapshot of the literature."),
    ("What counts as a better code?",
     "The primary tracks are a computed grid of locality class by check-weight "
     "class. Within each cell, codes rank on a Pareto frontier over (n, k, d, w): "
     "a submission earns a record by beating that cell&rsquo;s frontier with "
     "fewer physical qubits n, more logical qubits k, higher distance d, or lower "
     "check weight. Tighter cells nest into looser ones, so a strong 2D-local "
     "low-weight code also competes on the looser boards. The board holds the "
     "best we know of so you know what to aim past."),
    ("How are a code&rsquo;s tracks decided?",
     "You do not pick them. The verifier computes each code&rsquo;s locality "
     "class (single, bilayer, or unrestricted, derived from the layout) and its "
     "weight class (from the max check weight), so track membership cannot be "
     "gamed by relabeling. The construction family (bivariate bicycle, "
     "generalized bicycle, 2BGA, tile, and so on) is a separate self-declared "
     "tag, used only as a filter and never for ranking, because it cannot be "
     "recovered from the parity-check matrix."),
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
    ("What do d= and d≤ mean, and how is the distance found?",
     "Distance d is the weight of the lightest nontrivial logical operator. "
     "There are two confidence levels. d&le; (upper bound) means a submission "
     "exhibits an explicit logical operator of that weight, found by a "
     "decoder-based search (BP+OSD random coset, or heuristics like QDistEvol); "
     "the verifier confirms it is a genuine logical, so the distance is at most "
     "that weight. The claim is also refutation-tested: independent searches "
     "(deep randomized information-set and BP+OSD passes at submission time, "
     "plus weekly fresh-seed sweeps of the whole board) try to find something "
     "lighter, which is evidence but not a proof. d= (certified exact) means a "
     "server-side integer program has proven no lighter logical exists. Exact "
     "certification is NP-hard and does not scale, so large codes carry a tight "
     "upper bound while small and moderate codes are certified exact. A d&le; "
     "record is provisional: if the true distance turns out lower, the entry "
     "is corrected."),
    ("What does kd&sup2;/n mean, and is bigger always better?",
     "It is an encoding-efficiency ratio: logical qubits times distance squared, "
     "per physical qubit. It comes from the Bravyi-Poulin-Terhal bound, which "
     "says a 2D-local code obeys kd&sup2; &le; O(n), so under a locality or "
     "bounded-check-weight constraint kd&sup2;/n is bounded and measures how "
     "close a code gets to that ceiling (the surface code sits near 1). It is "
     "not a global record to chase: for high-rate codes with k and d both "
     "growing like n, kd&sup2;/n grows like n&sup2; without bound, so a large "
     "code trivially scores higher (the cited large-block codes reach the "
     "hundreds). So kd&sup2;/n is compared within a track, among codes of "
     "comparable size and check weight, not across the whole field. The "
     "headline number is the best among the codes on this board."),
    ("What is the kd&sup2;/nw&sup2; column?",
     "A weight-aware sort key: the efficiency kd&sup2;/n divided by w&sup2; to "
     "charge for check weight, which plain kd&sup2;/n ignores (a code can raise "
     "kd&sup2;/n just by using heavier checks). The w&sup2; is a heuristic "
     "penalty, not a saturation ratio. It takes the check-weight exponent from "
     "the large-dimension limit of the Bravyi-Poulin-Terhal tradeoff "
     "(w<sup>2+2/(D-1)</sup>, which is w&sup4; at D=2 and falls to w&sup2; as D "
     "grows) but keeps d&sup2;, so it is not dimensionally consistent: the "
     "consistent quantity is the locality score f, which fixes one dimension "
     "and needs a layout (see docs/locality-score.md and issue #168). Its job "
     "here is to reorder the sort so lighter-weight codes surface: a lighter "
     "code can overtake a heavier one that scored higher on plain kd&sup2;/n. "
     "It is display-only; records, cells, and frontiers still rank by "
     "kd&sup2;/n."),
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
     f"<a href=\"{REPO}/schema/SCHEMA.md\">the schema</a>."),
]


def faq_page():
    P = [head("FAQ | QEC Challenge", rel="")]
    P.append('<div class=wrap>')
    P.append('<a class=back href="index.html">&larr; back to the board</a>')
    P.append('<h1 style="margin:.4rem 0 0">FAQ</h1>')
    for q, a in FAQ:
        question = html.escape(html.unescape(q))
        P.append(f'<div class=faq><h3>{question}</h3><p>{a}</p></div>')
    P.append('</div></body></html>')
    return "\n".join(P)


# Layer-1 primary tracks: two nested, computed axes (locality and check weight).
# Membership is derived from H and the layout, never self-declared. A code in a
# tighter class also belongs to the looser ones (the grid nests).
LOCALITY_ORDER = ["local-2d-single", "local-2d-bilayer", "unrestricted"]
WEIGHT_ORDER = ["weight-4", "weight-6", "weight-8", "weight-any"]  # caps 4,6,8,inf
LOCALITY_LABEL = {"local-2d-single": "2D-local single",
                  "local-2d-bilayer": "2D-local bilayer",
                  "unrestricted": "unrestricted"}
WEIGHT_LABEL = {"weight-4": "weight ≤ 4", "weight-6": "weight ≤ 6",
                "weight-8": "weight ≤ 8", "weight-any": "any weight"}

# Layer-2 family tags (filterable, never ranked).
FAMILY_LABEL = {
    "bivariate-bicycle": "bivariate bicycle",
    "generalized-bicycle": "generalized bicycle",
    "2bga-coset": "2BGA coset",
    "hypergraph-product": "hypergraph product",
    "lifted-product": "lifted product",
    "balanced-product": "balanced product",
    "quantum-tanner": "quantum Tanner",
    "tile": "tile",
    "topological": "topological",
    "other": "other",
}


# A short, distinctive search token per family, used by the filter pills.
FAMILY_TERM = {
    "bivariate-bicycle": "bivariate", "generalized-bicycle": "generalized",
    "2bga-coset": "2bga", "hypergraph-product": "hypergraph",
    "lifted-product": "lifted", "balanced-product": "balanced",
    "quantum-tanner": "tanner", "tile": "tile", "topological": "topological",
    "other": "other",
}


def family_label(f):
    return FAMILY_LABEL.get(f, f)


NOVELTY_LABEL = {
    "known_parameters": "known parameter set; see provenance notes",
    "new_parameters": "new parameter set claimed by submitter",
    "unknown": "novelty not audited",
}


def novelty_label(v):
    return NOVELTY_LABEL.get(v, NOVELTY_LABEL["unknown"])


def locality_members(cls):
    """The locality boards a code of this class qualifies for (tighter nests into
    looser): single -> single/bilayer/unrestricted, etc."""
    i = LOCALITY_ORDER.index(cls) if cls in LOCALITY_ORDER else len(LOCALITY_ORDER) - 1
    return LOCALITY_ORDER[i:]


def weight_members(wc):
    """The weight boards a code qualifies for, from its tightest weight class."""
    start = {"weight-4": 0, "weight-6": 1, "weight-8": 2}.get(wc, 3)
    return WEIGHT_ORDER[start:]


def cells(e):
    """Every (locality, weight) primary-track cell this code belongs to."""
    return [(L, W) for L in locality_members(e["locality_class"])
            for W in weight_members(e["weight_class"])]


def cells_by_key(entries):
    """Map each populated (locality, weight) cell to the indices of its members."""
    by_cell = {}
    for i, e in enumerate(entries):
        for cell in cells(e):
            by_cell.setdefault(cell, []).append(i)
    return by_cell


def compute_records(entries):
    """Indices of codes on a Pareto frontier (over n, k, d, w) of any primary-track
    cell they belong to, or of the global frontier. These are the records (starred,
    shaded): a record is a within-cell claim, so a code only stars where no other
    code in the SAME computed cell beats it."""
    records = set()
    for idxs in cells_by_key(entries).values():
        te = [entries[i] for i in idxs]
        for j in pareto(te):
            records.add(idxs[j])
    for j in pareto(entries):
        records.add(j)
    return records


def cell_frontier_ranked(entries, idxs):
    """Indices of a cell's Pareto frontier, ranked leader-first by kd^2/n, then
    d, then k (higher better), then n (lower better). Ties on kd^2/n no longer
    pick an arbitrary single leader; the whole frontier is returned in order so
    co-leaders and the runner-up are visible."""
    te = [entries[i] for i in idxs]
    front = pareto(te)
    return sorted((idxs[j] for j in front),
                  key=lambda i: (-entries[i]["eff"], -entries[i]["d"],
                                 -entries[i]["k"], entries[i]["n"]))


RC_SERIES = [                       # label, weight cap, series color
    ("w ≤ 6", 6, "#b45309"),   # validated categorical trio (amber /
    ("w ≤ 8", 8, "#0369a1"),   # blue / violet): lightness band, chroma,
    ("any w", 10**9, "#6d28d9"),    # CVD separation and contrast all pass
]


def record_chart(entries):
    """Record progress, ecdsa.fail-style: the running best kd^2/n per check-
    weight class (classes nest, so a light-check record competes upward). The
    x axis is record EVENTS in date order, not elapsed time: literature seeds
    span decades while challenge entries land weekly, so a linear time axis
    would crush the interesting part into a sliver. y is log-scale (the
    running best spans two orders of magnitude)."""
    import math

    def running_best(cap):
        evs = sorted(((e["date"], e["eff"], e) for e in entries
                      if e["date"] and e["w"] <= cap),
                     key=lambda t: (t[0], t[1]))
        best, out = 0.0, []
        for date, eff, e in evs:
            if eff > best:
                best = eff
                out.append((date, eff, e))
        return out

    series = [(lab, col, running_best(cap)) for lab, cap, col in RC_SERIES]
    if not any(evs for _, _, evs in series):
        return ""
    # Union of record events (deduped by slug) in date order = the x axis.
    seen, union = set(), []
    for _, _, evs in series:
        for date, eff, e in evs:
            if e["slug"] not in seen:
                seen.add(e["slug"])
                union.append((date, eff, e["slug"]))
    union.sort()
    xof = {slug: i for i, (_, _, slug) in enumerate(union)}
    W, H = 1040, 300
    pad_l, pad_r, pad_b, pad_t = 64, 118, 30, 14
    ymax = max(eff for _, _, evs in series for _, eff, _ in evs)
    ylo, yhi = 0.0, math.log10(ymax) * 1.06

    def sx(i):
        return pad_l + (i / max(1, len(union) - 1)) * (W - pad_l - pad_r)

    def sy(v):
        f = (math.log10(max(v, 1.0)) - ylo) / (yhi - ylo)
        return H - pad_b - f * (H - pad_t - pad_b)

    grid, labels = [], []
    ymid = (pad_t + H - pad_b) / 2
    grid.append(f'<text transform="translate(14 {ymid:.0f}) rotate(-90)" '
                'font-size="12.5" fill="#475569" text-anchor="middle">'
                'Code Efficiency (kd&#178;/n)</text>')
    for tick in (1, 2, 5, 10, 20, 50, 100):
        if tick > ymax * 1.15:
            break
        y = sy(tick)
        grid.append(f'<line x1="{pad_l}" y1="{y:.0f}" x2="{W-pad_r}" '
                    f'y2="{y:.0f}" stroke="#eef2f7"/>'
                    f'<text x="{pad_l-7}" y="{y:.0f}" font-size="12" '
                    f'fill="#475569" text-anchor="end" dy="4">{tick}</text>')
    year_seen = set()
    for i, (date, _, _) in enumerate(union):
        yr = date[:4]
        if yr not in year_seen:
            year_seen.add(yr)
            grid.append(f'<text x="{sx(i):.0f}" y="{H-pad_b+19}" '
                        f'font-size="12" fill="#475569" '
                        f'text-anchor="middle">{yr}</text>'
                        f'<line x1="{sx(i):.0f}" y1="{H-pad_b}" '
                        f'x2="{sx(i):.0f}" y2="{H-pad_b+5}" stroke="#cbd5e1"/>')
    paths, dots, ends = [], [], []
    for lab, col, evs in series:
        if not evs:
            continue
        pts = [(sx(xof[e["slug"]]), sy(eff)) for _, eff, e in evs]
        d = f'M{pts[0][0]:.1f} {pts[0][1]:.1f}'
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            d += f' H{x1:.1f} V{y1:.1f}'
        d += f' H{W-pad_r}'
        paths.append(f'<path d="{d}" fill="none" stroke="{col}" '
                     'stroke-width="2" stroke-linejoin="round"/>')
        for (date, eff, e), (x, y) in zip(evs, pts):
            tip = (f'[[{e["n"]},{e["k"]},{e["d"]}]] · w={e["w"]} · '
                   f'kd²/n = {e["eff"]} · {date} · {lab} record')
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" '
                        f'fill="#fff" stroke="{col}" stroke-width="2" '
                        'pointer-events="none"/>')
            dots.append(f'<circle class=hit data-code="{e["slug"]}" '
                        f'cx="{x:.1f}" cy="{y:.1f}" r="11" fill="transparent" '
                        f'data-tip="{html.escape(tip)}"/>')
        _, last_eff, last_e = evs[-1]
        ends.append(f'<text x="{W-pad_r+8}" y="{sy(last_eff):.0f}" dy="4" '
                    f'font-size="12.5" fill="#334155">{lab} · '
                    f'<tspan font-weight="700">{last_eff:g}</tspan></text>')
    legend = "".join(
        f'<span class=ci><span class=cdot style="background:{col}"></span>'
        f'best kd&sup2;/n, {html.escape(lab)}</span>'
        for lab, col, evs in series if evs)
    return ('<section class=rcwrap id=progress>'
            '<h2 class=track>Record progress</h2>'
            f'<div class=plot><svg viewBox="0 0 {W} {H}" role="img" '
            'style="width:100%;height:auto" '
            'aria-label="Running best kd^2/n per weight class over record '
            f'events">{"".join(grid)}{"".join(paths)}{"".join(dots)}'
            f'{"".join(ends)}</svg></div>'
            f'<div class=chartlegend>{legend}'
            '<span class=ci>&#9675; a new record on this board (seeded '
            'literature + challenge entries)</span></div>'
            '</section>')


def primary_tracks_grid(entries, records):
    """The Layer-1 primary tracks: the computed locality x check-weight grid. Each
    populated cell is a board; membership is derived from H and the layout (never
    self-declared) and nests, so a tighter cell's codes also compete in the looser
    ones. Each cell lists its Pareto frontier (best kd^2/n first) with a distance-
    confidence badge; the count and the 'see all' link filter the table below to
    that exact cell, so the runner-up and the rest of the ranking are one click
    away."""
    by_cell = cells_by_key(entries)
    if not by_cell:
        return ""
    head = ('<tr><th class=gcorner></th>'
            + "".join(f'<th>{html.escape(WEIGHT_LABEL[w])}</th>'
                      for w in WEIGHT_ORDER) + '</tr>')
    body = []
    topn = 3
    for L in LOCALITY_ORDER:
        cellshtml = []
        for W in WEIGHT_ORDER:
            idxs = by_cell.get((L, W), [])
            if not idxs:
                cellshtml.append('<td class=gempty></td>')
                continue
            key = f"{L}~{W}"
            ranked = cell_frontier_ranked(entries, idxs)
            items = "".join(
                f'<a class=gitem href="codes/{entries[i]["slug"]}.html" '
                f'title="{html.escape(entries[i]["name"])}">'
                f'{badge(entries[i]["tier"])}'
                f'<span class=gcode>[[{entries[i]["n"]},{entries[i]["k"]},'
                f'{entries[i]["d"]}]]</span>'
                f'<span class=geff>{entries[i]["eff"]:g}</span></a>'
                for i in ranked[:topn])
            n = len(idxs)
            count = (f'<button type=button class=gcount data-cell="{key}" '
                     f'title="filter the table below to this cell">'
                     f'{n} code{"s" if n != 1 else ""}</button>')
            cellshtml.append(f'<td class=gcell>{count}{items}</td>')
        body.append(f'<tr><th class=grow>{html.escape(LOCALITY_LABEL[L])}</th>'
                    + "".join(cellshtml) + '</tr>')
    return ('<section class=ptgrid><h2 class=track>Primary tracks</h2>'
            '<p class=ptsub>Computed grid of locality &times; check weight, '
            'derived from <code>H</code> and the layout, not self-declared. '
            'Each cell lists its Pareto frontier, best kd&sup2;/n first; the '
            'code count filters the table below to that cell, so the runner-up '
            'and the rest of the ranking are one click away. '
            'Membership nests: a tighter cell&rsquo;s codes also compete in the '
            'looser ones.</p>'
            f'<div class=ptscroll><table class=grid>{head}'
            f'{"".join(body)}</table></div></section>')


def board_controls(entries, records):
    """The board heading plus the search box, filter pills, and filter help. Lives
    above the charts so filtering and the landscape view stay together; the JS
    finds the table by id, so its position relative to the table is free. Filters:
    a 2D-local pill (locality is computed), a family-tag pill per family present,
    and the check-weight slider."""
    # A tab strip (All + 2D-local + one per family) for picking the view, in the
    # OpenRouter rankings style. Each tab filters the table and charts; the active
    # tab is highlighted. The strip scrolls horizontally on narrow screens.
    tabs = ('<button type=button class="ttab active" data-q="" '
            'title="all codes">All</button>')
    if any(e["locality_class"] != "unrestricted" for e in entries):
        tabs += ('<button type=button class=ttab data-q="2d-local" '
                 'title="2D-local codes">2D-local</button>')
    families = sorted({e["family"] for e in entries})
    tabs += "".join(
        f'<button type=button class=ttab data-q="{html.escape(FAMILY_TERM.get(f, f))}" '
        f'title="the {html.escape(family_label(f))} family">'
        f'{html.escape(family_label(f))}</button>'
        for f in families)
    weights = [e["w"] for e in entries if e["w"] is not None]
    wmin, wmax = (min(weights), max(weights)) if weights else (0, 0)
    # Dual-handle range slider over the check weight w, styled as a pill so it
    # sits inline with the type-filter pills as one filter group. Two overlapping
    # range inputs share one visual track; replaces the old weight-N filter tags.
    wslider = (
        '<span class=wfilter title="filter by maximum check weight w">'
        '<span class=wflabel>weight</span>'
        '<span class=wfslider>'
        '<span class=wftrack></span><span class=wffill id=wffill></span>'
        f'<input type=range id=wlo class=wfrange min={wmin} max={wmax} '
        f'value={wmin} step=1 aria-label="minimum check weight">'
        f'<input type=range id=whi class=wfrange min={wmin} max={wmax} '
        f'value={wmax} step=1 aria-label="maximum check weight">'
        '</span>'
        f'<span class=wfval id=wfval>{wmin}&ndash;{wmax}</span>'
        '</span>')
    dists = [e["d"] for e in entries]
    dmin, dmax = (min(dists), max(dists)) if dists else (0, 0)
    # Same dual-handle range slider over the code distance d.
    dslider = (
        '<span class=wfilter title="filter by code distance d">'
        '<span class=wflabel>distance</span>'
        '<span class=wfslider>'
        '<span class=wftrack></span><span class=wffill id=dffill></span>'
        f'<input type=range id=dlo class=wfrange min={dmin} max={dmax} '
        f'value={dmin} step=1 aria-label="minimum distance">'
        f'<input type=range id=dhi class=wfrange min={dmin} max={dmax} '
        f'value={dmax} step=1 aria-label="maximum distance">'
        '</span>'
        f'<span class=wfval id=dfval>{dmin}&ndash;{dmax}</span>'
        '</span>')

    def rslider(label, pre, lo, hi, what):
        # dual-handle range slider; the generated ids ({pre}lo/{pre}hi/{pre}ffill/
        # {pre}fval) follow the same convention the JS wires up for w and d.
        return (
            f'<span class=wfilter title="filter by {what}">'
            f'<span class=wflabel>{label}</span>'
            '<span class=wfslider>'
            f'<span class=wftrack></span><span class=wffill id={pre}ffill></span>'
            f'<input type=range id={pre}lo class=wfrange min={lo} max={hi} '
            f'value={lo} step=1 aria-label="minimum {what}">'
            f'<input type=range id={pre}hi class=wfrange min={lo} max={hi} '
            f'value={hi} step=1 aria-label="maximum {what}">'
            '</span>'
            f'<span class=wfval id={pre}fval>{lo}&ndash;{hi}</span>'
            '</span>')

    ns = [e["n"] for e in entries]
    ks = [e["k"] for e in entries]
    nmin, nmax = (min(ns), max(ns)) if ns else (0, 0)
    kmin, kmax = (min(ks), max(ks)) if ks else (0, 0)
    nslider = rslider("n", "n", nmin, nmax, "physical qubits n")
    kslider = rslider("k", "k", kmin, kmax, "logical qubits k")
    return ('<section id=board>'
            '<h2 class=track>Codes '
            f'<span class=tcount>&middot; {len(entries)} total, '
            f'{len(records)} records</span></h2>'
            '<div class=searchbar>'
            '<input id=boardsearch type=text autocomplete=off '
            'placeholder="search, e.g.  w&lt;=6 k&gt;=10 d&gt;=8  or  '
            'eff&gt;5" aria-label="search codes">'
            '<span id=boardcount class=searchcount></span></div>'
            f'<nav class=tracktabs>{tabs}'
            '<button type=button id=littoggle class=otog '
            'title="show only literature baselines (codes seeded from '
            'published papers, not submitted through the challenge)">'
            'literature</button></nav>'
            f'<div class=filterrow>{wslider}{dslider}{nslider}{kslider}</div>'
            '<p class=searchhelp>Type terms (all must match): a family, author, '
            'or a comparison like <code>k&gt;=10</code> <code>d&gt;8</code> '
            '<code>eff&gt;=5</code>; <code>record</code> keeps only frontier '
            'rows; <code>literature</code> / <code>submitted</code> filter '
            'by origin.</p>'
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
        f'<span class=ci><span class=cdot style="background:{ACCENT}"></span>'
        'Upper bound</span>'
        '<span class=ci><span class=cdot style="background:#475569"></span>'
        'Filled = Pareto record</span>'
        '<span class=ci><span class=cdot '
        'style="background:#fff;border:2px solid #475569"></span>'
        'Open = non-frontier</span>'
        '</div>')
    xlabel = '<div class=plotx>Physical Qubits (n)</div>'
    return f'<div class=plots>{d_plot}{eff_plot}</div>{xlabel}{legend}'


def board_table(entries, records):
    """The searchable, sortable table of every code, with the track type as a
    column of chips. Search and charts are rendered separately, above; this is
    the table itself."""
    def chips(e):
        out = [f'<span class=tchip title="construction family (a tag, not a '
               f'ranking)">{html.escape(family_label(e["family"]))}</span>']
        if e["locality_class"] != "unrestricted":
            out.append('<span class="tchip loc" title="computed locality class">'
                       f'{html.escape(LOCALITY_LABEL[e["locality_class"]])}</span>')
        return "".join(out)

    cols = ('<colgroup><col style="width:3%"><col style="width:12%">'
            '<col style="width:12%"><col style="width:5%"><col style="width:5%">'
            '<col style="width:6%"><col style="width:7%"><col style="width:8%">'
            '<col style="width:5%"><col style="width:14%"><col style="width:14%">'
            '<col style="width:9%"></colgroup>')
    head = ('<thead><tr><th></th>'
            '<th data-c=codekey data-num title="the code, written [[n,k,d]]; '
            'sorts by n, then k, then d">code</th>'
            '<th data-c=type class=col-type title="construction family / track">'
            'type</th>'
            '<th data-c=n class="num col-n" title="physical qubits">n</th>'
            '<th data-c=k class="num col-k" title="logical qubits">k</th>'
            '<th data-c=d class="num col-d" title="distance">d</th>'
            '<th data-c=eff class=num title="k&middot;d&sup2;/n, higher is better">'
            'kd&sup2;/n</th>'
            '<th data-c=effw class=num title="weight-aware sort key: kd&sup2;/n '
            'divided by w&sup2; to charge for check weight (issue #165, a '
            'heuristic; the layout-based locality score f is the consistent '
            'one, issue #168). Display-only; records and cells still rank by '
            'kd&sup2;/n.">kd&sup2;/nw&sup2;</th>'
            '<th data-c=w class=num title="max check weight">w</th>'
            '<th data-c=auth class=col-auth title="who submitted it">authors</th>'
            '<th class=model data-c=model title="claimed model that produced '
            'the code (self-reported, not verified); person icon = classical '
            'construction, no AI model">model</th>'
            '<th class=date data-c=date title="publication date for literature, '
            'submission date for contributions">date</th></tr></thead>')
    # Default ordering: the headline kd^2/n efficiency, highest first, with
    # (k, d, n) as tiebreakers. Clicking a header re-sorts from here.
    order = sorted(range(len(entries)),
                   key=lambda i: (-entries[i]["eff"], -entries[i]["k"],
                                  -entries[i]["d"], entries[i]["n"]))
    rows = []
    for i in order:
        e = entries[i]
        fr = i in records
        # searchable terms (family + computed locality/weight class) so the
        # filter pills, which set the search box, can match a row.
        search_terms = " ".join([
            e["family"], family_label(e["family"]),
            FAMILY_TERM.get(e["family"], ""),
            e["locality_class"], e["weight_class"], e["novelty"],
            "2d-local" if e["locality_class"] != "unrestricted" else "",
            "literature" if e["origin"] == "baseline" else "submitted",
        ]).lower()
        # every (locality x weight) cell this code competes in, so the grid's
        # cell links can filter with nesting (a weight-4 code shows in weight-6/8
        # cells too), which the raw w slider cannot express.
        cell_keys = " ".join(f"{L}~{W}" for (L, W) in cells(e))
        novelty = (
            '<span class=novelty title="known parameter set in the literature; '
            'this entry may still improve weight or construction details">'
            'known params</span>'
            if e["novelty"] == "known_parameters" else "")
        rows.append(
            f'<tr class="{"fr" if fr else ""}" data-href="codes/{e["slug"]}.html" '
            f'data-code="{e["slug"]}" data-name="[[{e["n"]},{e["k"]},{e["d"]}]]" '
            f'data-n="{e["n"]}" data-k="{e["k"]}" data-d="{e["d"]}" '
            f'data-codekey="{e["n"]*1000000 + e["k"]*1000 + e["d"]}" '
            f'data-eff="{e["eff"]}" '
            f'data-effw="{e["effw"] if e["effw"] is not None else 0}" '
            f'data-w="{e["w"]}" '
            f'data-tracks="{html.escape(search_terms)}" '
            f'data-cells="{html.escape(cell_keys)}" '
            f'data-record="{1 if fr else 0}" '
            f'data-origin="{"literature" if e["origin"] == "baseline" else "submitted"}" '
            f'data-model="{html.escape(e["model"].lower())}" '
            f'data-date="{html.escape(e["date"])}" '
            f'data-auth="{html.escape(e["authors"])}">'
            f'<td class=star title="{"record: Pareto-best in a computed cell among listed codes (board-relative, not a literature record)" if fr else ""}">'
            f'{"&#9733;" if fr else ""}</td>'
            f'<td class=codecell><span class=mono>[[{e["n"]},{e["k"]},{e["d"]}]]</span>'
            + ('<span class=hexwrap title="submitted through the challenge; '
               f'not a novelty claim">{HEX_MARK}</span>'
               if e["origin"] != "baseline" else "")
            + novelty
            + f'</td><td class="typecell col-type">{chips(e)}</td>'
            f'<td class="num col-n">{e["n"]}</td>'
            f'<td class="num col-k">{e["k"]}</td>'
            f'<td class="num col-d">{badge(e["tier"])} {e["d"]}</td>'
            f'<td class=num>{e["eff"]}</td>'
            f'<td class=num title="kd&sup2;/(n&middot;w&sup2;)">'
            f'{e["effw"] if e["effw"] is not None else "n/a"}</td>'
            f'<td class=num>{e["w"]}</td>'
            f'<td class="auth col-auth" title="{html.escape(e["authors"])}">'
            f'{authors_compact(e["authors_list"])}</td>'
            '<td class=model>'
            + (f'<span class=modelmark title="{html.escape(e["model"])}">'
               f'{CLAUDE_MARK if e["model"].startswith("Claude") else ""}'
               f'<span class=modelname>{html.escape(e["model"])}</span></span>'
               if e["model"]
               else f'<span class=nomodel title="classical construction, no AI '
                    f'model">{HUMAN_MARK}</span>')
            + '</td>'
            f'<td class=date>{html.escape(e["date"]) if e["date"] else "&middot;"}</td></tr>')

    return (f'<div class=boardscroll><table class=board id=mainboard>{cols}{head}'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def build():
    entries = load_entries()
    n_exact = sum(1 for e in entries if e["tier"] == "exact")
    best_eff = max((e["eff"] for e in entries), default=0)
    records = compute_records(entries)

    P = [head("QEC Challenge")]
    P.append('<header class=hero>' + HERO_FLOW + '<div class=wrap>'
             '<div class=brand>'
             '<span class=brandmark>'
             '<a href="https://unitary.foundation" '
             f'aria-label="Unitary Foundation">{UF_LOGO}</a>'
             '</span>'
             '<button class="lbcta herocta" type=button '
             'onclick="(function(){var d=document.getElementById('
             '&quot;participate&quot;);if(d&&d.showModal)d.showModal();})()">Participate</button>'
             '</div>'
             '<h1>QEC Challenge</h1>'
             '<p>Find better quantum LDPC codes. '
             '<a href="qec_challenge.pdf">Read the whitepaper.</a></p>'
             '<nav class=topnav>'
             '<a href="faq.html">FAQ</a>'
             '<a href="references.html">References</a>'
             f'<a href="{REPO_ROOT}">{GH_ICON}GitHub</a>'
             '</nav>'
             '</div></header>')
    P.append('<div class=wrap>')
    P.append(progress_panel(entries, n_exact, best_eff))
    P.append(record_chart(entries))
    P.append(primary_tracks_grid(entries, records))
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
    P.append(board_controls(entries, records))
    P.append('<div class=explorer>')
    P.append(charts_block(entries, records))
    P.append('<div class=legend>'
             '<span class=legbreak><span class=swatch></span>&#9733; '
             '<b>record</b> (shaded rows): Pareto-best on (n, k, d) within at '
             'least one computed cell, among the codes listed here. It is a '
             'board-relative marker, not a claim against the wider literature; '
             'a code the literature beats may still be seeded.</span>'
             '<span><span class="dot ex"></span> certified exact '
             '(<span class="b exact">d =</span>)</span>'
             '<span><span class="dot ac"></span> upper bound '
             '(<span class="b ub">d &le;</span>): a verified logical of that '
             'weight; independent refutation searches found nothing lighter, '
             'but it is not a proof</span>'
             f'<span><span class=hexwrap style="margin-left:0">{HEX_MARK}</span> '
             'submitted through the challenge (not a novelty claim; '
             'unmarked = literature baseline)</span>'
             '<span><span class=novelty style="margin-left:0">known params</span> '
             'parameter set exists in the literature; see provenance notes</span>'
             '<span class=collegend><b>columns:</b> '
             '<b>n</b> physical qubits &middot; <b>k</b> logical qubits '
             '&middot; <b>d</b> distance (smallest undetectable error) '
             '&middot; <b>kd&sup2;/n</b> encoding efficiency (per track) '
             '&middot; <b>w</b> max check weight</span>'
             '</div>')
    P.append(board_table(entries, records))
    P.append('</div>')  # close explorer (bounds the sticky plots)
    P.append(contributors_panel(entries))  # leaderboard sits below the table
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
        '<a href="qec_challenge.pdf">Whitepaper</a>'
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
    with open(os.path.join(DOCS, "style.css"), "w") as f:
        f.write(CSS)
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
    n_cells = len(cells_by_key(entries))
    stats = {"verified_codes": len(entries), "certified_exact": n_exact,
             "tracks": n_cells, "best_kd2_over_n": best_eff}
    with open(os.path.join(DOCS, "stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    print(f"wrote docs/index.html + {len(entries)} detail pages + "
          f"references.html ({len(REFS)} refs), "
          f"{n_cells} primary-track cells, {n_exact} certified exact")


if __name__ == "__main__":
    build()
