"""
Generate the static leaderboard site into docs/: an index (per-track Pareto
tables) plus one detail page per code under docs/codes/<slug>.html.

Pure Python, no framework. A code's displayed distance tier is earned, not
self-declared: it shows d= only when a server certificate exists in
certs/<slug>.json (d_exact), otherwise d<= (the witness upper bound the cheap
verifier confirmed). Detail pages expose the actual witness, certificate, and
parity checks so the verification is transparent.
"""

import collections
import glob
import html
import json
import math
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

# Plausible's per-site script URL is public configuration, not a secret.  Keep
# it here (rather than in a CI variable) so local and CI builds produce exactly
# the same committed pages.  The Plausible site ID is the path-qualified
# ``unitaryfoundation.github.io/qldpc-challenge`` project site.
PLAUSIBLE_SCRIPT_SRC = "https://plausible.io/js/pa-BZqEmTRv5VBwv3HYwVpoB.js"

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
.scoredefs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));
gap:14px;margin:12px 0 18px}}
.sdef{{border:1px solid var(--ln);border-radius:14px;background:#fff;
padding:16px 18px}}
.sdefhead{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
margin:0 0 9px}}
.sdeftitle{{font-weight:700;color:var(--ink);font-size:14px}}
.sdefformula{{font-size:15px;color:var(--ac);background:var(--soft);
padding:2px 9px;border-radius:7px;white-space:nowrap}}
.sdefbody{{margin:0;color:var(--mut);font-size:13.5px;line-height:1.6}}
.sgloss{{grid-column:1/-1;border:1px solid var(--ln);border-radius:12px;
background:var(--soft);padding:11px 16px;font-size:12.5px;color:var(--mut);
line-height:1.8}}
.sgloss b{{color:var(--ink)}}
.statsbar{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:14px;margin:28px 0 8px}}
.stat-card{{border:1px solid var(--ln);border-radius:14px;padding:18px 20px;
background:var(--soft)}}
.stat-card .v{{font-size:34px;font-weight:700;line-height:1.05;
font-variant-numeric:tabular-nums}}
.stat-card .l{{font-size:13px;color:var(--mut);margin-top:6px}}
.stat-card .sub{{font-size:12.5px;margin-top:5px;color:var(--mut)}}
.stat-card .sub a{{font-family:'Space Mono',ui-monospace,monospace;
color:var(--ink)}}
.lb{{margin:18px 0 8px;border:1px solid var(--ln);border-radius:14px;
background:#fff;overflow:hidden}}
.lbhead{{display:flex;justify-content:space-between;align-items:center;gap:16px;
flex-wrap:wrap;
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
max-width:580px;width:92%;box-shadow:0 20px 60px rgba(17,17,17,.25)}}
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
.codeblock pre{{margin:0;white-space:pre;overflow-x:auto}}
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
.lbnamewrap{{flex:1 1 auto;min-width:0;font-weight:600}}
.lbname{{color:var(--ac);text-decoration:none}}
.lbname:hover{{text-decoration:underline}}
.lbcrown{{margin-left:5px}}
.lbm{{display:flex;flex-direction:column;align-items:center;width:82px;
flex:0 0 auto;text-decoration:none;color:var(--ink)}}
a.lbm[href]:hover b{{text-decoration:underline;color:var(--ac)}}
/* a metric with no target (e.g. no eligible g at the active weight cap) is an
   anchor without an href, so it must not read as a link */
a.lbm:not([href]){{cursor:default}}
/* the heroes wrapper exists only so the weight slider can swap both cards at
   once; it must not become a flex item of its own inside .lbhead */
.lbheroes{{display:contents}}
/* One stop per integer weight. 120px is the widest track that still leaves the
   header on one row in BOTH metric modes (the "best g" card is the wider of
   the two); past that the hero wraps to a second line. Fine-grained aiming is
   covered by the arrow keys, which step exactly one weight, and by the value
   label, which always reads the live W. */
.lbwf .wfslider{{width:120px}}
.lbwf .wfval{{min-width:1.6em}}
.lbm b{{font-size:17px;font-variant-numeric:tabular-nums}}
.lbml{{font-size:11px;color:var(--mut);margin-top:1px;white-space:nowrap}}
.lbrow{{cursor:pointer}}
/* Leaderboard metric toggle (issue #356): each row and the hero carry both
   scores; the mode on the section picks which one is on show, and the crown
   follows whoever is rank 1 in the active ranking. */
.lb[data-mode=eff] .lbmgeo,.lb[data-mode=eff] .lbhgeo,
.lb[data-mode=eff] .lbsgeo,.lb[data-mode=geo] .lbmeff,
.lb[data-mode=geo] .lbheff,.lb[data-mode=geo] .lbseff{{display:none}}
.lbmnone b{{color:var(--mut);font-weight:400}}
.lbcrown{{display:none}}
.lbrow.lbtop .lbcrown{{display:inline}}
.qchip{{margin-left:12px;font:inherit;font-size:12.5px;border:1px solid #f59e0b;
background:#fef3c7;color:#92400e;border-radius:999px;padding:3px 11px;
cursor:pointer;vertical-align:3px}}
.qchip b{{font-weight:700}}
.qchip:hover{{background:#fde68a}}
.lbscore{{text-align:right;margin-right:14px}}
.lbscore .lbsv{{font-size:30px;font-weight:800;line-height:1;
font-variant-numeric:tabular-nums;color:var(--ink)}}
.lbscore .lbsl{{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
color:var(--mut)}}
.lbscore .lbsd{{font-size:11.5px;color:var(--mut);margin-top:2px}}
.lbscore .lbsd a{{color:var(--ac);text-decoration:none}}
.lbscore .lbsd a:hover{{text-decoration:underline}}
.rcbar{{display:flex;gap:14px;flex-wrap:wrap;margin:2px 0 10px}}
.rcgroup{{display:inline-flex;gap:4px;border:1px solid var(--ln);
border-radius:999px;padding:3px}}
.rcbtn,.ptbtn,.lbbtn{{border:0;background:none;font:inherit;font-size:12.5px;
color:var(--mut);padding:4px 11px;border-radius:999px;cursor:pointer}}
.rcbtn.active,.ptbtn.active,.lbbtn.active{{background:var(--ac);color:#fff}}
.rcbtn:hover:not(.active),.ptbtn:hover:not(.active){{background:var(--soft)}}
/* the leaderboard header already sits on --soft, so its pills lift to white */
.lbbtn:hover:not(.active){{background:#fff}}
.cmodal{{border:none;border-radius:14px;padding:0;max-width:520px;width:92vw;
box-shadow:0 24px 70px rgba(20,24,60,.35)}}
.cmodal::backdrop{{background:rgba(18,20,34,.45)}}
.cmhead{{display:flex;align-items:center;gap:12px;padding:16px 20px;
border-bottom:1px solid var(--ln)}}
.cmhead img{{width:40px;height:40px;border-radius:50%}}
.cmhead .cmh{{flex:1;font-weight:700}}
.cmhead a{{color:var(--ac);text-decoration:none}}
.cmhead a:hover{{text-decoration:underline}}
.cmstats{{display:flex;flex-wrap:wrap;gap:10px;padding:14px 20px}}
.cmstat{{flex:1 1 84px;border:1px solid var(--ln);border-radius:9px;
padding:9px 11px}}
.cmstat b{{display:block;font-size:18px;font-variant-numeric:tabular-nums}}
.cmstat span{{font-size:10.5px;color:var(--mut);letter-spacing:.06em;
text-transform:uppercase}}
.cmlist{{max-height:280px;overflow-y:auto;padding:0 20px 16px}}
.cmrow{{display:flex;justify-content:space-between;gap:10px;padding:7px 0;
border-top:1px dashed var(--ln);text-decoration:none;color:var(--ink);
font-size:13.5px}}
.cmrow:hover .cmname{{text-decoration:underline}}
.cmrow .cmname{{color:var(--ac);font-family:var(--mono,monospace)}}
.cmrow .cmeff{{font-variant-numeric:tabular-nums;color:var(--mut)}}
/* phones: show every metric column (codes/frontier/exact/kd2n) instead of
   hiding the right-hand ones. The list scrolls horizontally as one unit; rows
   share a min-width so the columns stay aligned row-to-row while scrolling. */
@media(max-width:680px){{.lbm{{width:64px}}
.lblist{{overflow-x:auto}}
.lbrow{{min-width:520px}}
.lbname{{min-width:96px}}}}
.how{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin:40px 0}}
.how .card{{border:1px solid var(--ln);border-radius:12px;padding:20px;
background:var(--soft);display:block;color:inherit;text-decoration:none}}
a.card{{transition:border-color .12s,transform .12s}}
a.card:hover{{border-color:var(--ac);transform:translateY(-2px)}}
a.card .arrow{{color:var(--ac);font-weight:700}}
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
gap:16px;margin:14px 0 4px;position:relative}}
.geotabs{{position:absolute;top:2px;right:2px;z-index:6;display:flex;gap:6px}}
/* The plots were position:sticky here (#273) so the point<->row hover
   highlight stayed visible while the table scrolled. But the opaque pinned
   plots covered the table and leaderboard whenever plots + legend + table
   outgrew the viewport (issue #302). The both-on-screen effect now comes from
   fitting the explorer to one viewport instead; see .explorer by .boardscroll. */
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
.gitem.ghide{{display:none}}
/* Reference surface/toric tilings render with the same shading in both the
   kd^2/n and g views; in the g view they are distinguished by sorting last
   (JS) and by their tooltip, not by a colour change, so the two views match. */
.ptbar{{display:flex;justify-content:flex-end;margin:0 0 8px}}
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
.ttab,.otog,.geotab{{flex:0 0 auto;font-size:13px;padding:6px 13px;border-radius:999px;
cursor:pointer;border:1px solid var(--ln);background:#fff;color:var(--mut);
font-family:inherit;white-space:nowrap}}
.geotab{{font-size:12px;padding:4px 11px}}
.ttab:hover,.otog:hover,.geotab:hover{{border-color:var(--ac);color:var(--ac)}}
.ttab.active,.otog.active,.geotab.active{{background:var(--ac);border-color:var(--ac);color:#fff}}
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
/* nowrap keeps the row one line; the table is table-layout:fixed, so without
   the clip a name wider than the column paints over the date cell (#407).
   models_compact() already shortens ensembles -- this bounds the single-name
   case too, at any font size. */
.board td.model{{color:var(--mut);font-size:13px;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}}
.nomodel{{color:#94a3b8;display:inline-flex;vertical-align:middle}}
.modelmark,.modelicon{{display:inline-flex;align-items:center;gap:5px;
vertical-align:middle}}
.board td.model .modelname{{font-size:13px;color:var(--ink);
overflow:hidden;text-overflow:ellipsis;min-width:0}}
.board td.model .modelmark{{max-width:100%}}
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
/* "Show all" reveal for the collapsed mobile card list (issue #336);
   desktop keeps the bounded scroll box and never needs it. */
.showall{{display:none}}
/* On screens tall enough to fit plots + legend + a useful slice of the table,
   size the explorer to exactly one viewport: plots and legend keep their
   natural height and the board's scroll box absorbs the remainder, so plots
   and table are on screen together (the row-hover -> point highlight from
   #273) without anything sliding underneath anything (issue #302). Shorter
   screens keep normal flow -- the plots scroll away and the 64vh box above
   applies -- so the flex column is never over-constrained into overlapping
   the leaderboard below. Width gate matches the card-layout breakpoint. */
@media(min-width:821px) and (min-height:800px){{
.explorer{{display:flex;flex-direction:column;max-height:100vh}}
.explorer>*{{flex:0 0 auto}}
.explorer .boardscroll{{flex:1 1 auto;min-height:240px;max-height:none}}}}
@media(max-width:1000px){{table.board{{table-layout:auto;min-width:820px}}}}
/* Narrow screens: rather than drop columns (and hide g, a headline metric)
   into a horizontal scroll, each row becomes a card so every field stays
   visible (issue #305, PR #312 review). The header is dropped; each cell
   carries its own label via data-label. */
@media(max-width:820px){{
.boardscroll{{max-height:none;overflow:visible;border:0;border-radius:0}}
table.board,.board tbody,.board tr,.board td{{display:block;width:auto}}
table.board{{min-width:0;font-size:13px;margin:12px 0}}
.board thead{{display:none}}
.board tr{{border:1px solid var(--ln);border-radius:12px;margin:0 0 10px;
padding:12px 14px 10px;background:var(--soft)}}
.board tr.fr{{border-color:var(--ac)}}
.showall{{display:block;width:100%;margin:2px 0 14px;padding:11px;
font:inherit;font-size:14px;font-weight:600;color:var(--ac);
background:var(--soft);border:1px solid var(--ln);border-radius:12px;
cursor:pointer}}
.board td{{display:flex;justify-content:space-between;align-items:baseline;
gap:16px;padding:3px 0;border:0;white-space:normal;text-align:right}}
.board td::before{{content:attr(data-label);color:var(--mut);flex:0 0 auto;
font-family:'Space Mono',ui-monospace,monospace;font-size:11px;
text-transform:uppercase;letter-spacing:.04em;text-align:left}}
.board td.num{{text-align:right}}
.board td.codecell{{justify-content:flex-start;padding:0 0 8px;margin:0 0 6px;
border-bottom:1px solid var(--ln);font-size:15px}}
.board td.codecell::before{{content:none}}
.board tr.fr td.codecell::after{{content:"\\2605";color:var(--ac);
margin-left:8px}}
.board td.star{{display:none}}
.board td.auth{{max-width:none}}
.board td.typecell{{flex-wrap:wrap}}
/* n, k, d are already printed inside the [[n,k,d]] name: drop their rows */
.board td.col-n,.board td.col-k,.board td.col-d{{display:none}}
/* date: small, in the card's top-right corner */
.board tr{{position:relative}}
.board td.date{{position:absolute;top:12px;right:14px;width:auto;padding:0;
font-size:11.5px;color:var(--mut)}}
.board td.date::before{{content:none}}
.board td.codecell{{padding-right:92px}}
/* kd2/n, g, w: a horizontal stat trio — big value, small label beneath
   (column-reverse puts the ::before label under the number) */
.board td.m3{{display:inline-flex;flex-direction:column-reverse;
align-items:center;justify-content:flex-start;gap:3px;width:32.8%;
padding:9px 0 5px;font-size:19px;font-weight:700;
font-variant-numeric:tabular-nums;text-align:center}}
.board td.m3::before{{font-size:10.5px}}
/* unlabeled rows: chips and byline speak for themselves */
.board td.typecell::before,.board td.auth::before,
.board td.model::before{{content:none}}
.board td.typecell{{justify-content:flex-start}}
/* bottom line: authors on the left, model on the right, one row */
.board td.auth{{display:inline-flex;width:57%;justify-content:flex-start;
text-align:left}}
.board td.model{{display:inline-flex;width:42%;justify-content:flex-end;
text-align:right}}}}
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
.notebody{{font-size:14px;line-height:1.55}}
.notebody h3,.notebody h4,.notebody h5{{margin:14px 0 6px}}
.notebody pre{{font-family:ui-monospace,monospace;font-size:12px;
background:var(--soft);border:1px solid var(--ln);border-radius:8px;
padding:10px;overflow-x:auto}}
.notebody code{{font-family:ui-monospace,monospace;font-size:12.5px;
background:var(--soft);padding:1px 4px;border-radius:4px}}
.notebody ul{{margin:6px 0 6px 20px}}
.layoutfig svg{{width:100%;max-width:560px;height:auto;display:block;
background:var(--soft);border:1px solid var(--ln);border-radius:10px}}
.lo-chk{{fill-opacity:.15;stroke-width:1.3;stroke-linejoin:round}}
.lo-x{{fill:{ACCENT};stroke:{ACCENT}}}
.lo-z{{fill:{EXACT};stroke:{EXACT};stroke-dasharray:5 3}}
.lo-q{{fill:var(--ink);stroke:#fff;stroke-width:1}}
.lo-q2{{fill:none;stroke:var(--ink);stroke-width:1.4}}
.lo-dense .lo-chk{{fill-opacity:.05;stroke-opacity:.35}}
.lofig .lo-chk{{cursor:pointer}}
.lofig .lo-q,.lofig .lo-q2,.lofig .lo-r,.lofig .lo-rt{{pointer-events:none}}
.lofig.lo-hover .lo-chk:not(.lo-cur){{fill-opacity:.04;stroke-opacity:.12}}
.lofig.lo-hover .lo-r,.lofig.lo-hover .lo-rt{{opacity:.15}}
.lofig .lo-chk.lo-cur{{fill-opacity:.3;stroke-opacity:1;stroke-width:2.2}}
.lofig.lo-hover .lo-q:not(.lo-mem),
.lofig.lo-hover .lo-q2:not(.lo-mem){{opacity:.18}}
.lofig .lo-q.lo-mem{{stroke:{ACCENT};stroke-width:2}}
.lo-r{{stroke:var(--ink);stroke-width:1.6;stroke-dasharray:6 4;fill:none}}
.lo-rt{{fill:var(--ink);font-size:13px;font-family:'Space Mono',monospace;
paint-order:stroke;stroke:var(--soft);stroke-width:3.5px}}
.lolegend{{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;
color:var(--mut);margin-top:8px;align-items:center}}
.lolegend .sw{{display:inline-block;width:11px;height:11px;border-radius:3px;
margin-right:5px;vertical-align:-1px;opacity:.55}}
.lolegend .dt{{display:inline-block;width:8px;height:8px;border-radius:50%;
background:var(--ink);margin-right:5px}}
.lolegend .rg{{display:inline-block;width:10px;height:10px;border-radius:50%;
border:1.5px solid var(--ink);margin-right:5px;vertical-align:-1px}}
details{{margin:8px 0}}summary{{cursor:pointer;color:var(--ac);font-size:14px}}
.cert-ok{{color:var(--ex);font-weight:600}}.cert-no{{color:var(--mut)}}
.ref{{display:flex;gap:16px;padding:16px 0;border-bottom:1px solid var(--ln);
font-size:15px;line-height:1.55;scroll-margin-top:16px}}
.ref:target{{background:var(--soft);border-radius:8px;padding:16px 12px}}
.refkey{{flex:0 0 auto;width:170px;font-family:ui-monospace,monospace;
font-size:12px;color:var(--ac);word-break:break-all;text-decoration:none}}
a.refkey:hover{{text-decoration:underline}}
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
.latest{{margin:40px 0 0}}
.latestlist{{list-style:none;margin:10px 0 0;padding:0;
border:1px solid var(--ln);border-radius:12px;overflow:hidden}}
.latestlist li{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;
padding:9px 14px;border-top:1px solid var(--ln);font-size:13.5px}}
.latestlist li:first-child{{border-top:0}}
.latestlist .lnkd{{font-size:13.5px;white-space:nowrap}}
.latestlist .lstar{{color:var(--ac);margin-left:-6px}}
.latestlist .lfam{{color:var(--mut)}}
.latestlist .lwho{{color:var(--fg);font-variant-numeric:tabular-nums}}
.latestlist .lorig{{font-size:11px;padding:2px 7px;border-radius:999px;
border:1px solid var(--ln);color:var(--mut)}}
.latestlist .lorig.literature{{background:#eef2ff;color:#3730a3;
border-color:#c7d2fe}}
.latestlist .ldate{{margin-left:auto;color:var(--mut);
font-variant-numeric:tabular-nums;white-space:nowrap}}
@media(max-width:560px){{.latestlist .ldate{{margin-left:0}}}}
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
// Delegated so it survives the record chart re-rendering its own circles.
const tip=document.getElementById('tip');
if(tip){
 document.addEventListener('mouseover',e=>{
  const c=e.target.closest('.hit[data-tip]');if(!c)return;
  tip.textContent=c.getAttribute('data-tip');tip.classList.add('show');});
 document.addEventListener('mousemove',e=>{
  if(!tip.classList.contains('show'))return;
  let x=e.clientX+14,y=e.clientY+14;
  if(x+310>innerWidth)x=e.clientX-tip.offsetWidth-14;
  tip.style.left=x+'px';tip.style.top=y+'px';});
 document.addEventListener('mouseout',e=>{
  if(e.target.closest('.hit[data-tip]'))tip.classList.remove('show');});
}
document.addEventListener('click',e=>{
 const c=e.target.closest('.hit[data-code]');
 if(c)location.href='codes/'+c.getAttribute('data-code')+'.html';});
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
 // Phones render the rows as cards in normal page flow (no bounded scroll
 // box), so the full list buried the leaderboard below it (issue #336): show
 // the first few and a "Show all" button. The cap lives inside apply(), not
 // CSS, because filtering toggles inline display and sorting re-appends rows;
 // a static nth-child cap would hide matches and survive reorders.
 const showall=document.getElementById('showall');
 const cardsmq=matchMedia('(max-width:820px)');
 const CARDCAP=10;
 let allcards=false;
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
 // layout toggle (top right of the charts): '' = all, 'with' = only codes
 // with a verified layout (f defined), 'without' = only codes with none.
 // Clicking the active button clears it back to 'all'.
 let geoMode='';
 const cmp=/^(n|k|d|w|eff|f|g|geo)(>=|<=|>|<|=)(-?\\d+(?:\\.\\d+)?)$/;
 function term(r,t){
  const m=t.match(cmp);
  if(m){const key=(m[1]==='f'||m[1]==='g')?'geo':m[1];
   const x=parseFloat(r.dataset[key]),v=parseFloat(m[3]);
   if(key==='geo'&&x<0)return false;
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
    &&(geoMode===''||(geoMode==='with')===(+r.dataset.geo>=0))
    &&(!litOn||r.dataset.origin==='literature')&&toks.every(t=>term(r,t));
   r.style.display=ok?'':'none';if(ok){shown++;vis.add(r.dataset.code);}});
  // Collapse only the unfiltered mobile card list; any narrowing shows every
  // match (some may sit past the cap). Walk current DOM order, not the static
  // rows array, so a sorted board collapses to its first cards, not its
  // original ones. Chart dots key off vis, so capped cards stay plotted.
  const capped=showall&&cardsmq.matches&&!allcards&&shown===rows.length;
  if(capped){let ci=0;board.querySelectorAll('tbody tr').forEach(r=>{
   if(r.style.display===''&&++ci>CARDCAP)r.style.display='none';});}
  if(showall)showall.style.display=capped?'':'none';
  if(count)count.textContent=shown+(shown===rows.length?'':' of '+rows.length)+' codes';
  var chip=document.getElementById('qchip');
  if(chip){var f=q.value.trim();
   chip.style.display=f?'':'none';
   if(f)chip.innerHTML='filtered: '+f.replace(/</g,'&lt;')+' <b>&times; clear</b>';}
  document.querySelectorAll('.plots svg.plot circle[data-code]').forEach(c=>{
   c.style.display=vis.has(c.dataset.code)?'':'none';});
  // 'with layout' swaps the efficiency chart from kd^2/n to f (issue #276)
  const pe=document.getElementById('ploteff'),pg=document.getElementById('plotgeo');
  if(pe&&pg){const g=(geoMode==='with');
   pg.style.display=g?'':'none';pe.style.display=g?'none':'';}
 }
 function clearall(){q.value='';
  document.querySelectorAll('.ttab').forEach(t=>
   t.classList.toggle('active',t.dataset.q==='')); resetsliders();apply();}
 var chipEl=document.getElementById('qchip');
 if(chipEl)chipEl.addEventListener('click',clearall);
 var clrEl=document.getElementById('clearfilters');
 if(clrEl)clrEl.addEventListener('click',clearall);
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
  if(lit)lit.classList.remove('active');
  geoMode='';document.querySelectorAll('.geotab').forEach(x=>
   x.classList.remove('active'));}
 // Primary-tracks grid: a cell's code-count chip filters the table to that
 // (locality x weight) cell and scrolls it into view.
 document.querySelectorAll('[data-cell]').forEach(b=>{
  b.addEventListener('click',()=>{
   document.querySelectorAll('.ttab').forEach(t=>t.classList.remove('active'));
   resetsliders();q.value='cell:'+b.dataset.cell;apply();
   const bd=document.getElementById('board');
   if(bd)bd.scrollIntoView({behavior:'smooth'});});});
 if(lit)lit.addEventListener('click',()=>{lit.classList.toggle('active');apply();});
 document.querySelectorAll('.geotab').forEach(g=>{
  g.addEventListener('click',()=>{
   geoMode=(geoMode===g.dataset.geo)?'':g.dataset.geo;
   document.querySelectorAll('.geotab').forEach(x=>
    x.classList.toggle('active',x.dataset.geo===geoMode));
   apply();});});
 if(wlo&&whi){wlo.addEventListener('input',()=>{wpaint();apply();});
  whi.addEventListener('input',()=>{wpaint();apply();});wpaint();}
 if(dlo&&dhi){dlo.addEventListener('input',()=>{dpaint();apply();});
  dhi.addEventListener('input',()=>{dpaint();apply();});dpaint();}
 if(nlo&&nhi){nlo.addEventListener('input',()=>{npaint();apply();});
  nhi.addEventListener('input',()=>{npaint();apply();});npaint();}
 if(klo&&khi){klo.addEventListener('input',()=>{kpaint();apply();});
  khi.addEventListener('input',()=>{kpaint();apply();});kpaint();}
 // ?q=... deep-links a search (used by the contributor leaderboard counts).
 const uq=new URLSearchParams(location.search).get('q');
 if(uq){q.value=uq;
  document.querySelectorAll('.ttab').forEach(t=>
   t.classList.toggle('active', t.dataset.q===uq));
  const bd=document.getElementById('board');
  if(bd)bd.scrollIntoView();}
 if(showall)showall.addEventListener('click',()=>{allcards=true;apply();});
 // Crossing the card-layout breakpoint must re-run the cap: rows hidden by it
 // would otherwise stay hidden as desktop table rows (and vice versa).
 if(cardsmq.addEventListener)cardsmq.addEventListener('change',apply);
 apply();
})();

"""


def plausible_snippet(custom_properties=None):
    """Plausible's cookie-free tracker plus conservative site-wide options.

    The properties describe public page content, never a visitor.  Encoding the
    options as JSON and escaping ``<`` keeps values safe inside an inline script
    even if a future submission-controlled label contains HTML-like text.
    """
    options = {"outboundLinks": True, "fileDownloads": True}
    if custom_properties:
        options["customProperties"] = custom_properties
    encoded = json.dumps(options, sort_keys=True, separators=(",", ":"))
    encoded = encoded.replace("<", "\\u003c")
    return (
        '<!-- Privacy-friendly analytics by Plausible -->'
        f'<script async src="{html.escape(PLAUSIBLE_SCRIPT_SRC, quote=True)}">'
        '</script><script>'
        'window.plausible=window.plausible||function(){'
        '(plausible.q=plausible.q||[]).push(arguments)},'
        'plausible.init=plausible.init||function(i){plausible.o=i||{}};'
        f'plausible.init({encoded})</script>')


def check_analytics_coverage():
    """Fail the build if a generated HTML page omits or duplicates tracking."""
    marker = PLAUSIBLE_SCRIPT_SRC
    failures = []
    for path in glob.glob(os.path.join(DOCS, "**", "*.html"), recursive=True):
        with open(path) as f:
            count = f.read().count(marker)
        if count != 1:
            failures.append(f"{os.path.relpath(path, ROOT)} ({count} snippets)")
    if failures:
        raise RuntimeError("invalid Plausible coverage: " + ", ".join(failures))


def head(title, rel="", page_properties=None):
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
        f'<link rel=stylesheet href="{rel}style.css">',
        plausible_snippet(page_properties),
        '</head><body>']))


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


# Geometric efficiency (issue #276): f = 4 k d^2 / (n rho^2 r^4), the BPT
# ratio priced by the layout it comes with -- r is the measured interaction
# radius (max check diameter, Euclidean, in units of the unit qubit spacing)
# and rho the layer count (the capacity charge rho^2 is the unique exponent
# that makes re-packaging a layout into layers score-neutral). The constant 4
# = (sqrt(2))^4 normalizes the planar surface code (r = sqrt(2), rho = 1) to
# exactly 1. Defined for any honest layout accepted by the verifier; the
# locality caps decide the leaderboard cell, not score eligibility. A code
# without a layout has no f -- that is a certification status, not a claim
# that the code is an expander.
# D = 2 only: the schema accepts planar coordinates; other D are reserved.
GEO_MIN_D = 3   # headline eligibility: d = 2 tilings (a [[4,2,2]] block on
                # one plaquette scores g = 2) beat the surface code trivially,
                # so the headline requires d >= GEO_MIN_D. All KNOWN d = 3..4
                # codes with honest layouts sit far below 1 (Steane 0.32), but
                # no theorem caps that band; raise this (or implement the
                # d_min(w, rho) rule) if a small-d packing exploit shows up.


def geo_reference(e):
    """True for the seeded surface/toric/Steane tilings: the codes g is
    normalized against. They are shown as the g = 1 ceiling rather than raced,
    since a race that includes them freezes at their 1997 publication date.
    Origin matters as much as family here: a topological code SUBMITTED to the
    challenge is a contender, not the reference (issue #376)."""
    return e["family"] == "topological" and e["origin"] == "baseline"


def geo_score(doc, n, k, d, locality_class):
    """(f, r, rho) for a verifier-accepted layout, else (None, None, None).
    r is recomputed exactly from the stored coordinates (the report's value
    is rounded for display)."""
    if "locality" not in doc:
        return None, None, None
    loc = doc["locality"]
    coords = [tuple(c) for c in loc["coordinates"]]
    r = max((max(math.dist(coords[a], coords[b]) for a in sup for b in sup)
             for sup in doc["checks"]["X"] + doc["checks"]["Z"] if sup),
            default=0.0)
    if r <= 0:
        return None, None, None
    rho = loc.get("layers", 1)
    return 4.0 * k * d * d / (n * rho * rho * r ** 4), r, rho


def _model_str(m):
    """provenance.model may be a single name or a list (an ensemble of models);
    the rest of the site treats it as one display string."""
    if isinstance(m, (list, tuple)):
        return ", ".join(str(x) for x in m)
    return m or ""


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
        loc_cls = rep["computed"].get("locality_class", "unrestricted")
        geo, geo_r, geo_rho = geo_score(doc, n, k, d, loc_cls)
        entries.append({
            "slug": slug, "name": doc["name"], "n": n, "k": k, "d": d,
            "eff": round(k * d * d / n, 3), "tier": tier,
            "geo": round(geo, 4) if geo is not None else None,
            "geo_r": round(geo_r, 4) if geo_r is not None else None,
            "geo_rho": geo_rho,
            "w": rep["computed"].get("max_check_weight"),
            "family": doc.get("family", "other"),
            "locality_class": loc_cls,
            "weight_class": rep["computed"].get("weight_class", "weight-9plus"),
            "origin": doc["provenance"].get("origin", "submission"),
            "novelty": doc["provenance"].get("novelty", "unknown"),
            "authors": ", ".join(doc["provenance"]["authors"]),
            "authors_list": doc["provenance"]["authors"],
            "model": _model_str(doc["provenance"].get("model", "")),
            "date": doc["provenance"].get("date", ""),
            "construction": doc["provenance"].get("construction", ""),
            "note_md": load_note(slug),
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
        _geo = f'  g={e["geo"]:.3g}' if e["geo"] is not None else ""
        tip = (f'[[{e["n"]},{e["k"]},{e["d"]}]]  kd2/n={e["eff"]}{_geo}\n'
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


def md_to_html(md):
    """Render the deliberately small markdown subset allowed in research notes
    and fieldnotes (headings, bold, inline code, fenced code, lists, links,
    paragraphs). Everything is HTML-escaped first, so a note can never inject
    markup; anything outside the subset renders as literal text."""
    out, in_code, in_list, para = [], False, False, []

    def flush_para():
        if para:
            out.append("<p>" + " ".join(para) + "</p>")
            para.clear()

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def inline(s):
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                   r'<a href="\2">\1</a>', s)
        return s

    for line in md.splitlines():
        if line.strip().startswith("```"):
            flush_para(); close_list()
            out.append("<pre>" if not in_code else "</pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        m = re.match(r"(#{1,4})\s+(.*)", line)
        if m:
            flush_para(); close_list()
            lvl = min(len(m.group(1)) + 2, 5)   # note h1 -> page h3
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            continue
        if re.match(r"\s*[-*]\s+", line):
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + inline(re.sub(r"\s*[-*]\s+", "", line, count=1))
                       + "</li>")
            continue
        if not line.strip():
            flush_para(); close_list()
            continue
        para.append(inline(line.strip()))
    flush_para(); close_list()
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


NOTE_CAP = 10 * 1024


def load_note(slug):
    """The research note staged beside a submission: notes/<slug>.md.
    Absent file -> None (notes are requested, not yet mandatory)."""
    p = os.path.join(ROOT, "notes", slug + ".md")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        md = f.read()
    if len(md.encode()) > NOTE_CAP:
        print(f"  warning: notes/{slug}.md exceeds {NOTE_CAP} bytes; "
              f"truncating on render")
        md = md.encode()[:NOTE_CAP].decode(errors="ignore")
    return md


def load_fieldnotes():
    """fieldnotes/*.md with a minimal front-matter block (title/date/author/
    model/topics). Malformed front matter degrades to filename-derived
    metadata rather than failing the build."""
    notes = []
    for p in sorted(glob.glob(os.path.join(ROOT, "fieldnotes", "*.md"))):
        base = os.path.basename(p)
        if base.upper() == "README.MD":
            continue
        with open(p) as f:
            raw = f.read()
        meta = {"title": os.path.splitext(base)[0], "date": "", "author": "",
                "model": "", "topics": ""}
        body = raw
        m = re.match(r"\s*---\n(.*?)\n---\n(.*)", raw, re.S)
        if m:
            body = m.group(2)
            for line in m.group(1).splitlines():
                kv = re.match(r"(\w+)\s*:\s*(.*)", line)
                if kv and kv.group(1) in meta:
                    meta[kv.group(1)] = kv.group(2).strip().strip('"')
        if not meta["date"]:
            dm = re.match(r"(\d{4}-\d{2}-\d{2})", base)
            meta["date"] = dm.group(1) if dm else ""
        notes.append({**meta, "file": base, "md": body})
    return notes


def research_log_page(entries, fieldnotes):
    """docs/research-log.html: every submission note and fieldnote, newest
    first — the board's shared record of what was tried, what worked, and
    what is known not to work."""
    items = []
    for e in entries:
        if e.get("note_md"):
            items.append({
                "date": e["date"], "kind": "submission note",
                "title": f'[[{e["n"]},{e["k"]},{e["d"]}]] — {e["slug"]}',
                "link": f'codes/{e["slug"]}.html',
                "src": f'{REPO}/notes/{e["slug"]}.md',
                "author": e["authors"], "model": e["model"],
                "md": e["note_md"]})
    for fn in fieldnotes:
        items.append({
            "date": fn["date"], "kind": "fieldnote", "title": fn["title"],
            "link": None, "src": f'{REPO}/fieldnotes/{fn["file"]}',
            "author": fn["author"], "model": fn["model"], "md": fn["md"]})
    items.sort(key=lambda i: i["date"], reverse=True)

    P = [head("Research log · QEC Challenge",
              page_properties={"page_type": "research_log"})]
    P.append('<div class=wrap>')
    P.append('<a class=back href="index.html">&larr; back to the board</a>')
    P.append('<h1>Research log</h1>')
    P.append(
        '<p class=sub>The search behind the board: every submission ships a '
        'public research note (how the code was found, what was swept, what '
        'collapsed), and negative results land as stand-alone '
        f'<a href="{REPO}/fieldnotes">fieldnotes</a>. Newest first. '
        f'See <a href="{REPO}/notes">notes/</a> for the contract.</p>')
    if not items:
        P.append('<p class=sub>No notes yet.</p>')
    for i, it in enumerate(items):
        title = (f'<a href="{it["link"]}">{html.escape(it["title"])}</a>'
                 if it["link"] else html.escape(it["title"]))
        byline = " &middot; ".join(x for x in (
            html.escape(it["date"]), html.escape(it["kind"]),
            authors_html([a.strip() for a in it["author"].split(",")])
            if it["author"] else "",
            html.escape(it["model"])) if x)
        P.append(f'<section class=blk><h3>{title}</h3>'
                 f'<div class=kv style="color:var(--mut)">{byline}</div>'
                 f'<details {"open" if i < 3 else ""}>'
                 f'<summary>note</summary>'
                 f'<div class=notebody>{md_to_html(it["md"])}</div>'
                 f'<div class=kv><a href="{it["src"]}">raw markdown</a></div>'
                 f'</details></section>')
    P.append('</div></body></html>')
    return "\n".join(P)


def sci_int(v):
    """Compact trial-count display: exact powers of ten as 10<sup>e</sup>,
    everything else as m×10<sup>e</sup> to two significant figures, small
    numbers verbatim. The budget a witness survived is evidence (issue #611),
    so it is shown, not buried."""
    v = int(v)
    if v < 10000:
        return str(v)
    e = len(str(v)) - 1
    m = v / 10 ** e
    ms = f"{m:.1f}".rstrip("0").rstrip(".")
    if ms == "1":
        return f'10<sup>{e}</sup>'
    return f'{ms}&times;10<sup>{e}</sup>'


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


def model_parts(model):
    """The individual models behind a display string. An ensemble reaches the
    site either as a JSON list (joined with ', ' by _model_str) or, for the
    older free-text entries, as one string with ' + ' between the names."""
    parts = [p.strip() for p in re.split(r"\s*\+\s*|\s*,\s*", model or "")]
    return [p for p in parts if p]


def models_compact(model):
    """Compact model display for the board, the same bargain authors_compact
    strikes: one line per row. A single model renders in full; an ensemble
    shows the first name and a '+N' badge. The full list is on the detail page
    and in the cell's hover title. Without this an ensemble overruns the fixed
    column width and paints over the date column (issue #407)."""
    parts = model_parts(model)
    if not parts:
        return ""
    if len(parts) == 1:
        return html.escape(parts[0])
    return (f'{html.escape(parts[0])} '
            f'<span class=etal>+{len(parts) - 1}</span>')


def layout_svg(doc):
    """Inline SVG of a verified 2D layout (issue #289): qubit sites, one
    translucent polygon per check, and the qubit pair attaining the measured
    interaction radius. Returns figure+legend HTML, or None when the code has
    no usable layout. Mirrors the verifier's reading of the layout (checks
    drawn over `locality.coordinates`); it draws what the class was earned
    from, never a prettified abstraction."""
    loc = doc.get("locality")
    if not loc or "coordinates" not in loc:
        return None
    try:
        coords = [(float(c[0]), float(c[1])) for c in loc["coordinates"]]
    except (TypeError, ValueError, IndexError):
        return None
    if len(coords) != doc["n"]:
        return None
    X, Z = doc["checks"]["X"], doc["checks"]["Z"]
    selfdual = sorted(map(sorted, X)) == sorted(map(sorted, Z))
    groups = [("lo-x", X)] + ([] if selfdual else [("lo-z", Z)])

    # scale: coordinate units -> px, clamped so tiny codes don't balloon and
    # large ones stay legible; y flipped (SVG y grows downward)
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    w_u = max(xs) - min(xs) or 1.0
    h_u = max(ys) - min(ys) or 1.0
    S = min(84.0, max(24.0, 560.0 / max(w_u, h_u)))
    pad = 26.0
    W = w_u * S + 2 * pad
    H = h_u * S + 2 * pad

    def T(p):
        return (round((p[0] - min(xs)) * S + pad, 1),
                round(H - ((p[1] - min(ys)) * S + pad), 1))

    # the pair attaining the interaction radius (the verifier's r)
    r_best, r_pair = 0.0, None
    for sup in X + Z:
        for i, a in enumerate(sup):
            for b in sup[i + 1:]:
                dd = math.dist(coords[a], coords[b])
                if dd > r_best:
                    r_best, r_pair = dd, (coords[a], coords[b])

    # dense boards (many overlapping checks) drop the fill so structure stays
    # readable; the class is on the root and CSS does the rest
    dense = " lo-dense" if len(X) + len(Z) > 80 else ""
    parts = [f'<svg viewBox="0 0 {round(W)} {round(H)}" role="img" '
             f'class="lofig{dense}" '
             f'aria-label="verified 2D layout: {doc["n"]} qubit sites and '
             f'{len(X) + len(Z)} checks">']
    # site index for the hover interaction: a check names the sites its qubits
    # occupy (data-sites) and every dot names its own site (data-s), so a
    # click/hover can isolate one check's qubits without any geometry at
    # runtime
    site_ids = {}
    for p in coords:
        site_ids.setdefault(p, len(site_ids))
    for cls, checks in groups:
        for sup in checks:
            pts = [coords[q] for q in sup]
            sids = " ".join(str(s) for s in
                            sorted({site_ids[coords[q]] for q in sup}))
            if len(pts) < 2:
                continue
            if len(pts) == 2:
                (x1, y1), (x2, y2) = map(T, pts)
                parts.append(f'<line class="lo-chk {cls}" data-sites="{sids}" '
                             f'x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
                continue
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            ordered = sorted(pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
            body = " ".join(f"{x},{y}" for x, y in map(T, ordered))
            parts.append(f'<polygon class="lo-chk {cls}" data-sites="{sids}" '
                         f'points="{body}"/>')
    # sites: a dot per site, a ring where layers stack more than one qubit
    mult = collections.Counter(coords)
    rq = round(min(6.0, max(2.6, S * 0.11)), 1)
    stacked = False
    for site, m in mult.items():
        x, y = T(site)
        sid = site_ids[site]
        if m > 1:
            stacked = True
            parts.append(f'<circle class=lo-q2 data-s="{sid}" '
                         f'cx="{x}" cy="{y}" r="{rq + 3.2}"/>')
        parts.append(f'<circle class=lo-q data-s="{sid}" '
                     f'cx="{x}" cy="{y}" r="{rq}"/>')
    # the radius pair goes on top: on dense boards it is the one thing the
    # reader must still be able to find
    if r_pair:
        (x1, y1), (x2, y2) = map(T, r_pair)
        parts.append(f'<line class=lo-r x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
        tx, ty = (x1 + x2) / 2, (y1 + y2) / 2
        anchor = "start" if tx < W / 2 else "end"
        dx = 10 if anchor == "start" else -10
        parts.append(f'<text class=lo-rt x="{round(tx + dx, 1)}" '
                     f'y="{round(ty - 8, 1)}" text-anchor="{anchor}">'
                     f'r = {r_best:.4g}</text>')
    parts.append('</svg>')

    legend = ['<div class=lolegend>']
    if selfdual:
        legend.append(f'<span><span class=sw style="background:{ACCENT}">'
                      '</span>check (X = Z, self-dual)</span>')
    else:
        legend.append(f'<span><span class=sw style="background:{ACCENT}">'
                      '</span>X check</span>')
        legend.append(f'<span><span class=sw style="background:{EXACT}">'
                      '</span>Z check</span>')
    legend.append(f'<span><span class=dt></span>qubit site ({len(mult)})</span>')
    if stacked:
        legend.append('<span><span class=rg></span>2 qubits stacked '
                      f'({loc.get("layers", max(mult.values()))} layers)</span>')
    legend.append('<span>dashed: the pair setting the interaction radius</span>')
    legend.append('<span>hover a check to isolate its qubits; click to pin '
                  '&mdash; repeated clicks cycle through overlapping checks; '
                  'click empty space to release</span>')
    legend.append('</div>')
    return '<div class=layoutfig>' + "".join(parts) + "".join(legend) + '</div>'


def detail_page(e):
    doc, cert = e["doc"], e["cert"]
    n, k, d = e["n"], e["k"], e["d"]
    P = [head(
        f"[[{n},{k},{d}]] · QEC Challenge", rel="../",
        page_properties={
            "page_type": "code_detail",
            "code_tier": e["tier"],
            "code_origin": e["origin"],
            "code_family": e["family"],
            "locality_class": e["locality_class"],
            "weight_class": e["weight_class"],
        })]
    P.append('<div class=wrap>')
    P.append('<a class=back href="../index.html">&larr; back to the board</a>')
    P.append(f'<div class=codehead><span class="mono big">[[{n},{k},{d}]]</span> '
             f'{badge(e["tier"])}</div>')

    P.append('<div class=params>')
    params = [
        ("n", n, "physical qubits"),
        ("k", k, "logical qubits"),
        ("d", d, "distance (smallest undetectable error)"),
        ("kd&sup2;/n", e["eff"], "operational efficiency (BPT ratio), compared within a track at comparable n"),
        ("w", e["w"], "max check weight"),
    ]
    if e.get("geo") is not None:
        params.append(("g", f'{e["geo"]:.3g}',
                       "geometric efficiency 4kd²/(nρ²r⁴) "
                       "from the verified layout; surface code = 1"
                       + ("" if e["tier"] == "exact"
                          else "; inherits the upper-bound distance tier")))
        params.append(("r", e["geo_r"],
                       "measured interaction radius: the largest check "
                       "diameter in the layout, in units of the qubit spacing"))
    if "locality" in doc:
        loc = doc["locality"]
        params.append(("layers", loc.get("layers", 1),
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
            wp = sd.get("witness_provenance")
            if wp:
                parts = ['witness found by '
                         + authors_html(wp["found_by"])]
                if wp.get("tool"):
                    parts.append(html.escape(wp["tool"]))
                parts.append(f'found at {sci_int(wp["found_at_samples"])} '
                             'trials')
                if wp.get("survived_samples"):
                    parts.append('survived '
                                 f'{sci_int(wp["survived_samples"])} trials')
                parts.append(html.escape(wp["date"]))
                P.append('<div class=kv style="color:var(--mut)">'
                         + " &middot; ".join(parts) + '</div>')
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

    # verified 2D layout (issue #289): draw the layout the locality class was
    # earned from, not just its numbers
    fig = layout_svg(doc)
    if fig:
        P.append('<section class=blk><h3>Verified 2D layout</h3>')
        P.append('<div class=kv style="color:var(--mut)">as measured by the '
                 'verifier: every check drawn over the submitted coordinates; '
                 'the interaction radius is the longest dashed pair</div>')
        P.append(fig)
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

    # research note: how the code was found (notes/<slug>.md, staged with the
    # submission PR — see notes/README.md for the contract)
    if e.get("note_md"):
        P.append('<section class=blk><h3>How this code was found</h3>'
                 '<div class=kv style="color:var(--mut)">the research note '
                 'submitted with this code &middot; '
                 f'<a href="{REPO}/notes/{e["slug"]}.md">raw markdown</a> '
                 '&middot; <a href="../research-log.html">all notes</a></div>'
                 f'<div class=notebody>{md_to_html(e["note_md"])}</div>'
                 '</section>')
    else:
        P.append('<section class=blk><h3>How this code was found</h3>'
                 '<div class=kv style="color:var(--mut)">no research note was '
                 'staged with this submission &mdash; notes are requested for '
                 f'new submissions (<a href="{REPO}/notes">notes/README.md</a>)'
                 '</div></section>')

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
             "plausible('Result Link Copied');"
             "b.innerHTML='\\u2713';b.title='link copied';"
             "setTimeout(()=>{b.innerHTML=o;b.title='Copy link';},1400);}));"
             # layout figure: hover a check to isolate its member qubits
             # (membership is corner-hood, which overlapping polygons obscure);
             # click pins the selection for touch devices
             "document.querySelectorAll('.lofig').forEach(svg=>{"
             "const dots={};"
             "svg.querySelectorAll('[data-s]').forEach(d=>{"
             "(dots[d.dataset.s]=dots[d.dataset.s]||[]).push(d);});"
             "let pin=null;"
             "const clear=()=>{svg.classList.remove('lo-hover');"
             "svg.querySelectorAll('.lo-cur,.lo-mem').forEach("
             "e=>e.classList.remove('lo-cur','lo-mem'));};"
             "const show=el=>{clear();svg.classList.add('lo-hover');"
             "el.classList.add('lo-cur');"
             "el.dataset.sites.split(' ').forEach(s=>"
             "(dots[s]||[]).forEach(d=>d.classList.add('lo-mem')));};"
             "svg.querySelectorAll('.lo-chk').forEach(el=>{"
             "el.addEventListener('mouseenter',()=>{if(!pin)show(el);});"
             "el.addEventListener('mouseleave',()=>{if(!pin)clear();});"
             # click cycles through ALL checks under the cursor (topmost
             # first), so a polygon buried under later-drawn ones is still
             # reachable; click empty space to release
             "el.addEventListener('click',e=>{e.stopPropagation();"
             "const stack=document.elementsFromPoint(e.clientX,e.clientY)"
             ".filter(x=>x.classList&&x.classList.contains('lo-chk')"
             "&&svg.contains(x));"
             "if(!stack.length)return;"
             "const i=pin?stack.indexOf(pin):-1;"
             "pin=stack[(i+1)%stack.length];show(pin);});});"
             "svg.addEventListener('click',()=>{if(pin){pin=null;clear();}});"
             "});"
             "</script>")
    P.append('</div></body></html>')
    return "\n".join(P)


def ref_target(e):
    """Best canonical URL for a reference: the journal posting (a real DOI)
    if there is one, else the arXiv abstract, else the arXiv DOI, else whatever
    resource the entry points at (url). None if the entry links nowhere."""
    doi = e.get("doi", "")
    is_arxiv_doi = doi.lower().startswith("10.48550/arxiv")
    if doi and not is_arxiv_doi:
        return f'https://doi.org/{doi}'
    if e.get("eprint"):
        return f'https://arxiv.org/abs/{e["eprint"]}'
    if doi:
        return f'https://doi.org/{doi}'
    if e.get("url"):
        return e["url"]
    m = re.search(r'https?://[^\s}]+', e.get("howpublished", ""))
    if m:
        return m.group(0)
    return None


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
    tgt = ref_target(e)
    key_html = html.escape(e["key"])
    if tgt:
        out.append(f'<a class=refkey href="{html.escape(tgt)}">{key_html}</a>')
    else:
        out.append(f'<span class=refkey>{key_html}</span>')
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
    P = [head("References | QEC Challenge", rel="",
              page_properties={"page_type": "references"})]
    P.append('<div class=wrap>')
    P.append('<a class=back href="index.html">&larr; back to the board</a>')
    P.append('<h1 style="margin:.4rem 0 0">References</h1>')
    P.append('<p style="color:var(--mut);max-width:60ch">Every paper and tool '
             'the challenge cites. Submissions reference an entry by its arXiv '
             'id or DOI; verified codes that cite each one are listed beneath '
             'it. The machine-readable source is '
             f'<a href="{REPO}/refs.bib">refs.bib</a>.</p>')
    for e in sorted(REFS, key=lambda e: e["key"].lower()):
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



def progress_panel(entries, best_eff_e, best_geo_e):
    """The prominent stats bar at the top of the board: the headline numbers as
    big cards. This is the single home for the board's numbers (the hero carries
    none). The contributed count is non-baseline codes only; it is not a novelty
    claim. best_eff_e / best_geo_e are the entries ACHIEVING the two headline
    efficiencies (geo: among eligible codes -- verified layout, d >= GEO_MIN_D);
    each card names its code so the parameters behind the number are visible."""
    n_base = sum(1 for e in entries if e["origin"] == "baseline")
    n_contrib = len(entries) - n_base

    def by_line(e, geo=False):
        """The achieving code, linked: [[n,k,d]] plus the layout facts that
        enter the score."""
        if e is None:
            return ""
        extra = (f" &middot; r={e['geo_r']:g} &middot; &rho;={e['geo_rho']}"
                 if geo else f" &middot; w={e['w']}")
        return (f'<div class=sub><a href="codes/{e["slug"]}.html">'
                f'[[{e["n"]},{e["k"]},{e["d"]}]]</a>{extra}</div>')

    # g and kd^2/n are both monotone in d, so an upper-bound distance makes both
    # of them upper bounds. Marking only g implied the other was firmer than it
    # is; the distance column already carries the one d <= that governs both.
    geo_v = "&middot;" if best_geo_e is None else f"{best_geo_e['geo']:.3g}"
    best_eff = best_eff_e["eff"] if best_eff_e else 0
    metrics = [
        (str(n_contrib), "submitted codes",
         "codes submitted through the challenge; not necessarily novel parameter sets"),
        (str(n_base), "literature baselines",
         "published codes seeded as the bar to beat"),
        (f"{best_eff:g}" + by_line(best_eff_e), "best operational efficiency",
         "Best kd^2/n on the board (surface code = 1). Full definition below."),
        (geo_v + by_line(best_geo_e, geo=True), "best geometric efficiency",
         "Best geometric efficiency g among codes with a verified layout "
         "(surface code = 1). Full definition below."),
    ]
    cards = "".join(f'<div class="stat-card"'
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
    excluded.

    A toggle re-ranks the same contributors by best geometric efficiency g
    (issue #356). Both orderings are computed here and carried on each row as
    data-erank / data-grank, so the client only has to reorder -- the two
    comparators cannot drift apart. g eligibility matches the headline card
    (verified layout, d >= GEO_MIN_D); contributors without an eligible code
    show a dot and sort last, which is the honest reading: no layout shipped,
    so no geometric claim.

    A weight slider restricts every ranking to the codes of check weight <= W,
    snapping to the same caps as the primary-track weight cells. kd^2/n climbs
    with check weight (it is a per-cell figure, not a global one -- TRACKS.md),
    so an uncapped headline quietly rewards whoever worked the highest-weight
    region; the slider makes the cap you are reading explicit. Each cap is
    ranked here and shipped precomputed, like the metric toggle."""

    def geo_disp(g, tier):
        """Same 3-significant-digit display as the headline card and the board.
        No d <= marker: kd^2/n inherits the distance tier exactly as g does, so
        marking g alone read as if the other were the firmer number."""
        return "&middot;" if g is None else f"{g:.3g}"

    front_slugs = {entries[i]["slug"] for i in compute_records(entries)}

    def collect(cap):
        """Per-contributor stats over the codes with check weight <= cap
        (cap None = no cap, the whole board). Returns
        (stats, eff_order, geo_order, n_codes, n_geo)."""
        stats = {}
        for e in entries:
            if e["origin"] == "baseline":
                continue
            if cap is not None and (e["w"] is None or e["w"] > cap):
                continue
            for a in e["authors_list"]:
                h = a.strip()
                if not (h.startswith("@") and re.fullmatch(r"@[A-Za-z0-9-]+", h)):
                    continue
                s = stats.setdefault(h.casefold(),
                                     {"codes": 0, "front": 0, "exact": 0,
                                      "eff": 0.0, "slug": None, "handle": h,
                                      "geo": None, "geo_slug": None,
                                      "geo_tier": None, "list": []})
                s["codes"] += 1
                s["front"] += e["slug"] in front_slugs
                s["exact"] += e["tier"] == "exact"
                s["list"].append({"name": f'[[{e["n"]},{e["k"]},{e["d"]}]]',
                                  "slug": e["slug"], "eff": e["eff"],
                                  "geo": (geo_disp(e["geo"], e["tier"])
                                          if e["geo"] is not None else None),
                                  "w": e["w"], "date": e["date"],
                                  "front": e["slug"] in front_slugs})
                if e["eff"] > s["eff"]:
                    s["eff"] = e["eff"]
                    s["slug"] = e["slug"]   # the code achieving the best kd^2/n
                if (e["geo"] is not None and e["d"] >= GEO_MIN_D
                        and (s["geo"] is None or e["geo"] > s["geo"])):
                    s["geo"] = e["geo"]
                    s["geo_slug"] = e["slug"]
                    s["geo_tier"] = e["tier"]
        eff_order = sorted(stats.items(),
                           key=lambda kv: (-kv[1]["eff"], -kv[1]["front"],
                                           -kv[1]["codes"], kv[1]["handle"]))
        # the g ordering: contributors with no eligible g fall to the bottom
        geo_order = sorted(stats.items(),
                           key=lambda kv: (kv[1]["geo"] is None,
                                           -(kv[1]["geo"] or 0.0),
                                           -kv[1]["front"], -kv[1]["codes"],
                                           kv[1]["handle"]))
        n_geo = sum(1 for s in stats.values() if s["geo"] is not None)
        n_codes = sum(1 for e in entries
                      if e["origin"] != "baseline"
                      and (cap is None
                           or (e["w"] is not None and e["w"] <= cap)))
        return stats, eff_order, geo_order, n_codes, n_geo

    # The uncapped board is what the rows are rendered from, so every
    # contributor has a DOM row for the slider to show or hide.
    stats, order, geo_order, n_codes, n_geo = collect(None)
    if not stats:
        return ""
    grank = {k: i for i, (k, _) in enumerate(geo_order, 1)}

    def metric(v, lab, href=None, tip="", cls=""):
        # Always an anchor, with href only when there is a target: the weight
        # slider can give a contributor a best-g code at one cap and none at
        # another, and an <a> can gain or lose an href where a <span> could not.
        body = f'<b>{v}</b><span class=lbml>{lab}</span>'
        k = f"lbm {cls}".strip()
        h = f' href="{href}"' if href else ""
        return f'<a class="{k}"{h} title="{html.escape(tip)}">{body}</a>'

    rows = []
    for r, (key, s) in enumerate(order, 1):
        h = s["handle"]
        # identity links to the GitHub profile; the counts deep-link the board
        # filtered to this handle; the best-score numbers link to that code.
        qh = html.escape(f"?q={h}")
        gtip = (f"{h}'s best geometric efficiency; the code achieving it"
                if s["geo"] is not None else
                f"{h} has no code with a verifier-accepted layout and "
                f"d >= {GEO_MIN_D}, so no g")
        rows.append(
            f'<div class="lbrow{" lbtop" if r == 1 else ""}" '
            f'data-h="{html.escape(h)}" '
            f'data-erank="{r}" data-grank="{grank[key]}">'
            f'<span class=lbrank>{r}</span>'
            f'<img class=lbav loading=lazy alt="" '
            f'src="https://github.com/{h[1:]}.png?size=64">'
            f'<span class=lbnamewrap><a class=lbname '
            f'href="https://github.com/{h[1:]}" title="GitHub profile">'
            f'{html.escape(h)}</a>'
            ' <span class=lbcrown title="top contributor">&#128081;</span>'
            '</span>'
            + metric(s["codes"], "codes", qh, f"all {h} codes on the board",
                     cls="lbmcodes")
            + metric(s["front"], "on frontier",
                     html.escape(f"?q={h} record"), f"{h} frontier codes",
                     cls="lbmfront")
            + metric(s["exact"], "exact", qh, f"all {h} codes on the board",
                     cls="lbmexact")
            + metric(f'{s["eff"]:g}', "best kd&sup2;/n",
                     f'codes/{s["slug"]}.html' if s["slug"] else None,
                     "the code achieving this", cls="lbmeff")
            + metric(geo_disp(s["geo"], s["geo_tier"]), "best g",
                     f'codes/{s["geo_slug"]}.html' if s["geo_slug"] else None,
                     gtip, cls="lbmgeo" + ("" if s["geo"] is not None
                                           else " lbmnone"))
            + '</div>')
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
        'plausible("Submission Command Copied");'
        'var o=c.textContent;c.textContent="copied";'
        'setTimeout(function(){c.textContent=o;},1200);});})();</script>'
        '</dialog>')
    # ecdsa.fail-style headline: the best score among contributed codes, with
    # the code and holder it belongs to. One per metric; the toggle shows the
    # one matching the active ranking.
    by_slug = {e["slug"]: e for e in entries}

    def hero_card(holder, slug, value, extra, label, cls):
        be = by_slug.get(slug)
        if be is None:
            return ""
        dmark = "d=" if be["tier"] == "exact" else "d&le;"
        return (f'<div class="lbscore {cls}"><div class=lbsl>{label}</div>'
                f'<div class=lbsv>{value}</div>'
                f'<div class=lbsd><a href="codes/{be["slug"]}.html">'
                f'[[{be["n"]},{be["k"]},{be["d"]}]]</a> &middot; '
                f'{dmark}{be["d"]} &middot; {extra} &middot; '
                f'{html.escape(holder)}</div></div>')

    def heroes(od, gd):
        """The two headline cards for a ranking: best kd^2/n and best g."""
        h = ""
        if od:
            b = od[0][1]
            be = by_slug.get(b["slug"])
            h = hero_card(b["handle"], b["slug"], f'{b["eff"]:g}',
                          f'w={be["w"]}' if be else "",
                          "best kd&sup2;/n", "lbheff")
        if gd and gd[0][1]["geo"] is not None:
            gb = gd[0][1]
            ge = by_slug.get(gb["geo_slug"])
            h += hero_card(
                gb["handle"], gb["geo_slug"],
                geo_disp(gb["geo"], gb["geo_tier"]),
                f'r={ge["geo_r"]:g} &middot; &rho;={ge["geo_rho"]}' if ge else "",
                "best g", "lbhgeo")
        return h

    def subs_html(nk, nc, ng):
        return (f'<span class=lbseff>{nk} contributor'
                f'{"" if nk == 1 else "s"} &middot; {nc} code'
                f'{"" if nc == 1 else "s"} submitted through the challenge</span>'
                f'<span class=lbsgeo>{ng} of {nk} contributor'
                f'{"" if nk == 1 else "s"} have a code with a verified '
                f'layout and d &ge; {GEO_MIN_D}</span>')

    hero = heroes(order, geo_order)
    # One ranking per integer check weight W. Position W ranks each contributor
    # using only their codes of weight <= W, so the nesting the track cells use
    # holds here too: a weight-4 code still competes at every W above it.
    # Without this the headline collapses every weight cell and rewards whoever
    # mined the highest-weight region, since kd^2/n climbs with w (TRACKS.md:
    # kd^2/n is compared within a cell, not globally).
    #
    # The range is the board's own [min w, max w]: below the minimum every
    # ranking is empty, so a slider starting at 0 would only offer dead travel.
    #
    # Every W is ranked in Python and shipped precomputed, for the same reason
    # the eff/g toggle is: the client applies a ranking, never computes one, so
    # the two cannot drift apart. Rankings are deduplicated because leader-at-W
    # is a max over a growing set and so is a step function of W -- consecutive
    # weights usually share a ranking, and only the distinct ones are shipped.
    cw = [e["w"] for e in entries
          if e["origin"] != "baseline" and e["w"] is not None]
    wmin, wmax = (min(cw), max(cw)) if cw else (0, 0)
    lbw, lbidx, seen = {}, [], {}
    for cap in range(wmin, wmax + 1):
        st, od, gd, nc, ng = (
            (stats, order, geo_order, n_codes, n_geo) if cap >= wmax
            else collect(cap))
        er = {k: i for i, (k, _) in enumerate(od, 1)}
        gr = {k: i for i, (k, _) in enumerate(gd, 1)}
        payload = {
            "m": {s["handle"]: {
                "codes": s["codes"], "front": s["front"], "exact": s["exact"],
                "eff": f'{s["eff"]:g}', "effSlug": s["slug"],
                "geo": geo_disp(s["geo"], s["geo_tier"]),
                "geoSlug": s["geo_slug"],
                "erank": er[key2], "grank": gr[key2]}
                for key2, s in st.items()},
            "hero": heroes(od, gd),
            "subs": subs_html(len(od), nc, ng),
        }
        sig = json.dumps(payload, sort_keys=True)
        if sig not in seen:
            seen[sig] = str(len(lbw))
            lbw[seen[sig]] = payload
        lbidx.append(seen[sig])
    # Contributor modal: row click opens a summary card; inner links still
    # navigate (profile, filtered board, code pages).
    cdata = json.dumps({s["handle"]: {
        "codes": s["codes"], "front": s["front"], "exact": s["exact"],
        "eff": s["eff"], "geo": geo_disp(s["geo"], s["geo_tier"]),
        "list": sorted(s["list"], key=lambda c: -c["eff"])}
        for _, s in order})
    cmodal = (
        '<dialog id=cmodal class=cmodal>'
        '<div class=cmhead><img id=cmav alt="">'
        '<span class=cmh id=cmh></span>'
        '<a id=cmgh href="#" target=_blank rel=noopener>View profile</a>'
        '<form method=dialog><button class=modalx aria-label="close">'
        '&times;</button></form></div>'
        '<div class=cmstats id=cmstats></div>'
        '<div class=cmlist id=cmlist></div>'
        '</dialog>'
        f'<script id=cmdata type="application/json">{cdata}</script>'
        '<script>(function(){'
        'var D=JSON.parse(document.getElementById("cmdata").textContent);'
        'var dlg=document.getElementById("cmodal");if(!dlg)return;'
        'dlg.addEventListener("click",function(e){if(e.target===dlg)dlg.close();});'
        'document.querySelectorAll(".lbrow[data-h]").forEach(function(r){'
        'r.addEventListener("click",function(e){'
        'if(e.target.closest("a"))return;'
        'var h=r.dataset.h,s=D[h];if(!s)return;'
        'document.getElementById("cmav").src="https://github.com/"+h.slice(1)+".png?size=80";'
        'document.getElementById("cmh").textContent=h;'
        'var g=document.getElementById("cmgh");g.href="https://github.com/"+h.slice(1);'
        'document.getElementById("cmstats").innerHTML='
        '[["codes",s.codes],["on frontier",s.front],["exact",s.exact],'
        '["best kd\\u00b2/n",s.eff],["best g",s.geo]].map(function(p){'
        'return "<div class=cmstat><b>"+p[1]+"</b><span>"+p[0]+"</span></div>";'
        '}).join("");'
        'document.getElementById("cmlist").innerHTML=s.list.map(function(c){'
        'return "<a class=cmrow href=\\"codes/"+c.slug+".html\\">"'
        '+"<span class=cmname>"+c.name+(c.front?" \\u2605":"")+"</span>"'
        '+"<span class=cmeff>"+c.eff+" \\u00b7 w="+c.w'
        '+(c.geo!=null?" \\u00b7 g="+c.geo:"")+" \\u00b7 "+c.date+"</span></a>";'
        '}).join("");'
        'dlg.showModal();});});})();</script>')
    # metric toggle (issue #356): same contributors, ranked by the other score.
    toggle = ('<span class=rcgroup>'
              '<button type=button class="lbbtn active" data-lb=eff '
              'title="rank contributors by their best operational efficiency '
              'kd&sup2;/n">kd&sup2;/n</button>'
              '<button type=button class=lbbtn data-lb=geo '
              'title="rank contributors by their best geometric efficiency g. '
              'Needs a code with a verifier-accepted layout and d &ge; '
              f'{GEO_MIN_D}">g</button></span>')
    # Single-handle weight slider over the raw check weight, one step per
    # integer W from the board's lightest code to its heaviest.
    wslider = (
        '<span class="wfilter lbwf" title="rank contributors using only their '
        'codes of check weight &le; W. Nested, like the track cells: a '
        'weight-4 code still competes at every W above it.">'
        '<span class=wflabel>weight &le;</span>'
        '<span class=wfslider>'
        '<span class=wftrack></span><span class=wffill id=lbwfill></span>'
        f'<input type=range id=lbwrange class=wfrange min={wmin} max={wmax} '
        f'value={wmax} step=1 aria-label="maximum check weight">'
        '</span>'
        f'<span class=wfval id=lbwval>{wmax}</span>'
        '</span>')
    subs = f'<p class=lbsub id=lbsub>{subs_html(len(order), n_codes, n_geo)}</p>'
    # Reordering only: both rankings are server-computed (data-erank /
    # data-grank), so this cannot disagree with the Python comparators.
    # Reordering and value swapping only: every (weight cap x metric) ranking is
    # server-computed, so this cannot disagree with the Python comparators.
    lbdata = json.dumps({"wmin": wmin, "wmax": wmax, "idx": lbidx, "b": lbw})
    lbjs = ('<script id=lbwdata type="application/json">' + lbdata + '</script>'
            '<script>(function(){'
            'var sec=document.getElementById("leaderboard");if(!sec)return;'
            'var D=JSON.parse(document.getElementById("lbwdata").textContent);'
            'var WMIN=D.wmin,WMAX=D.wmax,SPAN=(WMAX-WMIN)||1;'
            'var list=sec.querySelector(".lblist");'
            'var rows=[].slice.call(list.querySelectorAll(".lbrow"));'
            'var heroes=document.getElementById("lbheroes");'
            'var subs=document.getElementById("lbsub");'
            'var rng=document.getElementById("lbwrange");'
            'var fill=document.getElementById("lbwfill");'
            'var val=document.getElementById("lbwval");'
            'var mode="eff";'
            # wcap() reads the live input on every apply, never a cached index:
            # a browser restoring the range on reload would otherwise leave the
            # label and the ranking disagreeing with the thumb.
            'function wcap(){var v=rng?+rng.value:WMAX;'
            'return Math.min(WMAX,Math.max(WMIN,v||WMIN));}'
            'function put(r,sel,v,slug){var el=r.querySelector(sel);'
            'if(!el)return;el.querySelector("b").innerHTML=v;'
            'if(slug===undefined)return;'
            'if(slug){el.setAttribute("href","codes/"+slug+".html");}'
            'else{el.removeAttribute("href");}'
            'el.classList.toggle("lbmnone",!slug);}'
            'function apply(){'
            'var w=wcap(),b=D.b[D.idx[w-WMIN]],m=b.m,'
            'key=mode==="geo"?"grank":"erank";'
            'var vis=[];'
            'rows.forEach(function(r){var s=m[r.dataset.h];'
            'if(!s){r.style.display="none";r.classList.remove("lbtop");return;}'
            'r.style.display="";'
            'put(r,".lbmcodes",s.codes);put(r,".lbmfront",s.front);'
            'put(r,".lbmexact",s.exact);'
            'put(r,".lbmeff",s.eff,s.effSlug);'
            'put(r,".lbmgeo",s.geo,s.geoSlug);'
            'r.dataset.erank=s.erank;r.dataset.grank=s.grank;vis.push(r);});'
            'vis.sort(function(a,c){'
            'return (+a.dataset[key])-(+c.dataset[key]);})'
            '.forEach(function(r,i){'
            'r.querySelector(".lbrank").textContent=i+1;'
            'r.classList.toggle("lbtop",i===0);list.appendChild(r);});'
            'if(heroes)heroes.innerHTML=b.hero;'
            'if(subs)subs.innerHTML=b.subs;'
            'sec.dataset.mode=mode;'
            'if(val)val.textContent=w;'
            'if(fill)fill.style.width=((w-WMIN)/SPAN*100)+"%";}'
            'if(rng)rng.addEventListener("input",apply);'
            'sec.querySelectorAll(".lbbtn").forEach(function(b){'
            'b.addEventListener("click",function(){'
            'sec.querySelectorAll(".lbbtn").forEach(function(x){'
            'x.classList.remove("active");});'
            'b.classList.add("active");mode=b.dataset.lb;apply();});});'
            'apply();'
            '})();</script>')
    return ('<section class=lb id=leaderboard data-mode=eff>'
            '<div class=lbhead>'
            f'<div><h2 class=lbh>Leaderboard</h2>{subs}</div>'
            + wslider + toggle
            + f'<span class=lbheroes id=lbheroes>{hero}</span>'
            + '</div>'
            f'<div class=lblist>{"".join(rows)}</div>'
            + modal + cmodal + lbjs +
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
    P = [head("FAQ | QEC Challenge", rel="",
              page_properties={"page_type": "faq"})]
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


# Client-side re-renderer for the record-progress chart: modes (record / all
# submissions / by model), log/lin scale, and time windows. The server-rendered
# SVG stays as the initial view and no-JS fallback. Plain string (no f-string)
# so braces stay literal.
_RC_JS = """<script>(function(){
var D=JSON.parse(document.getElementById('rcdata').textContent);
var S=JSON.parse(document.getElementById('rcseries').textContent);
var plot=document.getElementById('rcplot');if(!plot)return;
var init=plot.innerHTML, leg=document.getElementById('rclegend'), legInit=leg.innerHTML;
var MC=['#6d28d9','#0369a1','#b45309','#15803d','#be185d','#475569'];
var st={m:'record',s:'log',w:'all',y:'eff'};
function mv(r){return st.y==='geo'?r.geo:r.eff;}
function days(t){return Date.parse(t)/864e5;}
function windowed(){
 if(st.w==='all')return D.slice();
 var now=Math.max.apply(null,D.map(function(r){return days(r.t);}));
 return D.filter(function(r){return now-days(r.t)<=+st.w;});
}
function runbest(rows){
 rows=rows.slice().sort(function(a,b){return a.t<b.t?-1:a.t>b.t?1:mv(a)-mv(b);});
 var best=0,out=[];
 rows.forEach(function(r){if(mv(r)>best){best=mv(r);out.push(r);}});
 return out;
}
function draw(){
 if(st.m==='record'&&st.s==='log'&&st.w==='all'&&st.y==='eff'){plot.innerHTML=init;leg.innerHTML=legInit;return;}
 var W=1040,H=300,pl=64,pr=(st.m==='model'?182:118),pb=30,pt=14;
 var data=windowed(); if(st.m!=='record')data=data.filter(function(r){return r.sub;});
 // f view: the seeded surface/toric reference tilings ARE the f=1 ceiling;
 // keeping them in the record race would freeze it at 1997. They become a
 // dashed reference line instead, and the series show everyone else's climb.
 // r.ref is set by geo_reference() -- family AND baseline origin, so a
 // submitted topological code still races (issue #376).
 if(st.y==='geo')data=data.filter(function(r){return r.geo!=null&&!r.ref;});
 var series=[];
 if(st.m==='record'){
  S.forEach(function(s){series.push({lab:s[0],col:s[2],step:true,
   rows:runbest(data.filter(function(r){return r.w<=s[1];}))});});
 }else if(st.m==='model'){
  var by={},disp={};data.forEach(function(r){var k=r.model.toLowerCase();
   if(!disp[k])disp[k]=r.model;(by[k]=by[k]||[]).push(r);});
  var names=Object.keys(by).sort(function(a,b){return by[b].length-by[a].length;}).slice(0,6);
  names.forEach(function(nm,i){series.push({lab:disp[nm],col:MC[i%MC.length],step:true,rows:runbest(by[nm])});});
 }else{series.push({lab:'submissions',col:'#6d28d9',step:false,rows:data.slice()});}
 series=series.filter(function(s){return s.rows.length;});
 if(!series.length){plot.innerHTML='<div style="padding:40px;color:#64748b">no data in this window</div>';leg.innerHTML='';return;}
 var pts=[];series.forEach(function(s){pts=pts.concat(s.rows);});
 var xs={},xn=0;
 if(st.m==='all'){
  var t0=Math.min.apply(null,pts.map(function(r){return days(r.t);}));
  var t1=Math.max.apply(null,pts.map(function(r){return days(r.t);}));
  if(t1-t0<1)t1=t0+1;
  var fx=function(r){return pl+(days(r.t)-t0)/(t1-t0)*(W-pl-pr);};
 }else{
  var seen={},u=[];pts.slice().sort(function(a,b){return a.t<b.t?-1:1;})
   .forEach(function(r){if(!seen[r.slug]){seen[r.slug]=1;u.push(r.slug);}});
  u.forEach(function(sl,i){xs[sl]=i;});xn=u.length;
  var fx=function(r){return pl+(xs[r.slug]/Math.max(1,xn-1))*(W-pl-pr);};
 }
 var ymax=Math.max.apply(null,pts.map(mv));
 var ymin=Math.min.apply(null,pts.map(mv));
 // f view: the y range always includes the f=1 surface-code ceiling
 var yceil=(st.y==='geo')?Math.max(ymax,1):ymax;
 var fy;
 if(st.s==='log'){
  if(st.y==='geo'){
   // f spans decades BELOW 1, so the log floor is the data minimum, not 1
   var glo=Math.log10(Math.max(ymin,1e-6))-0.08,ghi=Math.log10(yceil)+0.08;
   if(ghi-glo<1e-9)ghi=glo+1;
   fy=function(v){return H-pb-((Math.log10(Math.max(v,1e-9))-glo)/(ghi-glo))*(H-pt-pb);};
  }else{var yhi=Math.log10(ymax)*1.06||1;
   fy=function(v){return H-pb-(Math.log10(Math.max(v,1))/yhi)*(H-pt-pb);};}
 }else{fy=function(v){return H-pb-(v/(yceil*1.08))*(H-pt-pb);};}
 var ylab=st.y==='geo'?'Geometric Efficiency (g)':'Code Efficiency (kd&#178;/n)';
 var g='<text transform="translate(14 '+((pt+H-pb)/2)+') rotate(-90)" font-size="12.5" fill="#475569" text-anchor="middle">'+ylab+'</text>';
 var ticks=st.s==='log'?(st.y==='geo'?[0.001,0.002,0.005,0.01,0.02,0.05,0.1,0.2,0.5,1]:[1,2,5,10,20,50,100,200,500]):
  (function(){var s=Math.pow(10,Math.floor(Math.log10(ymax)))/2,o=[];
   for(var v=0;v<=ymax*1.05;v+=s)if(v>0)o.push(Math.round(v*1000)/1000);return o.slice(0,8);})();
 ticks.forEach(function(t){if(t>yceil*1.15||(st.y==='geo'&&st.s==='log'&&t<ymin/1.15))return;var y=fy(t);
  g+='<line x1="'+pl+'" y1="'+y+'" x2="'+(W-pr)+'" y2="'+y+'" stroke="#eef2f7"/>'
   +'<text x="'+(pl-7)+'" y="'+y+'" font-size="12" fill="#475569" text-anchor="end" dy="4">'+t+'</text>';});
 if(st.y==='geo'){var yr=fy(1);
  g+='<line x1="'+pl+'" y1="'+yr+'" x2="'+(W-pr)+'" y2="'+yr+'" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="6 5"/>'
   +'<text x="'+(pl+6)+'" y="'+(yr-6)+'" font-size="11.5" fill="#64748b">surface code = 1 (the ceiling to beat)</text>';}
 var srt=pts.slice().sort(function(a,b){return a.t<b.t?-1:1;});
 var span=days(srt[srt.length-1].t)-days(srt[0].t);
 var lseen={},cand=[];
 srt.forEach(function(r){var lab=span>730?r.t.slice(0,4):r.t.slice(0,7);
  if(!lseen[lab]){lseen[lab]=1;cand.push({x:fx(r),lab:lab});}});
 var lastx=-1e9;
 cand.forEach(function(c){if(c.x-lastx<62)return;lastx=c.x;
  g+='<line x1="'+c.x+'" y1="'+(H-pb)+'" x2="'+c.x+'" y2="'+(H-pb+5)+'" stroke="#cbd5e1"/>'
   +'<text x="'+c.x+'" y="'+(H-pb+19)+'" font-size="12" fill="#475569" text-anchor="middle">'+c.lab+'</text>';});
 var body='',ends='',endlist=[];
 series.forEach(function(s){
  var P=s.rows.map(function(r){return[fx(r),fy(mv(r)),r];});
  if(s.step&&P.length){var d='M'+P[0][0]+' '+P[0][1];
   for(var i=1;i<P.length;i++)d+=' H'+P[i][0]+' V'+P[i][1];
   d+=' H'+(W-pr);
   body+='<path d="'+d+'" fill="none" stroke="'+s.col+'" stroke-width="2" stroke-linejoin="round"/>';
   var le=s.rows[s.rows.length-1];
   endlist.push({y:fy(mv(le)),lab:s.lab,eff:mv(le)});}
  P.forEach(function(p){var r=p[2];
   var tp=('[['+r.n+','+r.k+','+r.d+']] · w='+r.w+' · kd²/n='+r.eff+(r.geo!=null?' · g='+r.geo:'')+' · '+r.t+' · '+r.model).replace(/"/g,'&quot;');
   body+='<circle cx="'+p[0]+'" cy="'+p[1]+'" r="'+(s.step?4:3.4)+'" fill="'+(s.step?'#fff':s.col)+'" fill-opacity="'+(s.step?1:0.55)+'" stroke="'+s.col+'" stroke-width="'+(s.step?2:0)+'" pointer-events="none"/>'
    +'<circle class=hit data-code="'+r.slug+'" data-tip="'+tp+'" cx="'+p[0]+'" cy="'+p[1]+'" r="9" fill="transparent"/>';});
 });
 endlist.sort(function(a,b){return a.y-b.y;});
 for(var i=1;i<endlist.length;i++)if(endlist[i].y-endlist[i-1].y<15)endlist[i].y=endlist[i-1].y+15;
 endlist.forEach(function(e){var lab=e.lab.length>18?e.lab.slice(0,17)+'…':e.lab;
  ends+='<text x="'+(W-pr+8)+'" y="'+e.y+'" dy="4" font-size="12" fill="#334155">'+lab+' &#183; <tspan font-weight="700">'+e.eff+'</tspan></text>';});
 plot.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto">'+g+body+ends+'</svg>';
 leg.innerHTML=series.map(function(s){return '<span class=ci><span class=cdot style="background:'+s.col+'"></span>'+s.lab+'</span>';}).join('')
  +(st.y==='geo'?'<span class=ci title="the surface/toric reference codes sit at the conjectured f ceiling and are drawn as the dashed line, not raced">&#8213; surface code = 1</span>':'');
}
document.querySelectorAll('.rcbtn').forEach(function(b){
 b.addEventListener('click',function(){
  var k=b.dataset.m?'m':(b.dataset.s?'s':(b.dataset.y?'y':'w'));
  st[k]=b.dataset.m||b.dataset.s||b.dataset.y||b.dataset.w;
  b.parentElement.querySelectorAll('.rcbtn').forEach(function(x){x.classList.remove('active');});
  b.classList.add('active');draw();});});
})();</script>"""


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
    # Year labels sit at the first record EVENT of each year, and the x axis is
    # indexed by event rather than by time. Early years contribute one or two
    # events each, so their labels land a few pixels apart and overprint each
    # other ("1996 1997 2019 2022 2023" ran together). Emit a label only when it
    # clears the previous one, and drop the tick with it so a suppressed year
    # leaves no orphan mark. The most recent year is forced: it is the one a
    # reader looks for, and it is the likeliest to be crowded out by the year
    # before it once entries start landing weekly.
    YEAR_GAP = 34          # ~4 digits at 12px plus breathing room
    year_first = {}
    for i, (date, _, _) in enumerate(union):
        year_first.setdefault(date[:4], i)
    picks, last_x = [], -1e9
    for yr, i in sorted(year_first.items()):
        if sx(i) - last_x >= YEAR_GAP:
            picks.append((yr, i))
            last_x = sx(i)
    if year_first:
        newest = max(year_first)
        if newest not in dict(picks):
            picks = [p for p in picks if sx(p[1]) < sx(year_first[newest]) - YEAR_GAP]
            picks.append((newest, year_first[newest]))
    for yr, i in picks:
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
        f'{html.escape(lab)}</span>'
        for lab, col, evs in series if evs)
    # Data + client-side renderer for the alternate views (all submissions,
    # per-model) and the scale/window controls; the server-rendered SVG above
    # stays as the no-JS fallback and the initial view.
    data = [{"t": e["date"], "eff": e["eff"], "geo": e["geo"], "n": e["n"],
             "k": e["k"], "d": e["d"], "w": e["w"], "slug": e["slug"],
             "model": (e["model"] or "human"),
             "ref": geo_reference(e),
             "sub": e["origin"] != "baseline"}
            for e in entries if e["date"]]
    rcjson = json.dumps(data)
    rcseries = json.dumps([[lab, cap, col] for lab, cap, col in RC_SERIES])
    controls = (
        '<div class=rcbar>'
        '<span class=rcgroup>'
        '<button class="rcbtn active" data-m=record>Record</button>'
        '<button class=rcbtn data-m=all>All submissions</button>'
        '<button class=rcbtn data-m=model>By model</button></span>'
        '<span class=rcgroup>'
        '<button class="rcbtn active" data-s=log>Log</button>'
        '<button class=rcbtn data-s=lin>Lin</button></span>'
        '<span class=rcgroup>'
        '<button class="rcbtn active" data-w=all>All</button>'
        '<button class=rcbtn data-w=90>90D</button>'
        '<button class=rcbtn data-w=30>30D</button></span>'
        # metric toggle (issue #276), pinned to the right end of the bar: f is
        # defined only for codes that ship a verified layout, so that view
        # restricts to them.
        '<span class=rcgroup style="margin-left:auto">'
        '<button class="rcbtn active" data-y=eff '
        'title="operational efficiency kd&sup2;/n">kd&sup2;/n</button>'
        '<button class=rcbtn data-y=geo title="geometric efficiency '
        'g = 4kd&sup2;/(n&rho;&sup2;r&#8308;); only codes with a verified '
        'layout">g</button></span>'
        '</div>')
    return ('<section class=rcwrap id=progress>'
            '<h2 class=track>Record progress</h2>'
            + controls +
            f'<div class=plot id=rcplot><svg viewBox="0 0 {W} {H}" role="img" '
            'style="width:100%;height:auto" '
            'aria-label="Running best kd^2/n per weight class over record '
            f'events">{"".join(grid)}{"".join(paths)}{"".join(dots)}'
            f'{"".join(ends)}</svg></div>'
            f'<div class=chartlegend id=rclegend>{legend}'
            '<span class=ci title="board-relative: among the seeded literature '
            'baselines and challenge entries listed here">&#9675; new record'
            '</span></div>'
            f'<script id=rcdata type="application/json">{rcjson}</script>'
            f'<script id=rcseries type="application/json">{rcseries}</script>'
            + _RC_JS +
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
            # the kd^2/n <-> g toggle shows each cell's top 3 by the active
            # metric, so emit exactly the union of both metrics' top 3 (some
            # frontiers run to 100+ co-leaders; emitting them all bloats the
            # page by ~20% for items that can never become visible)
            by_geo = sorted((i for i in ranked
                             if entries[i]["geo"] is not None
                             and not geo_reference(entries[i])),
                            key=lambda i: -entries[i]["geo"])
            keep = set(ranked[:topn]) | set(by_geo[:topn])
            ranked = [i for i in ranked if i in keep]
            def gitem(i, pos):
                e = entries[i]
                geo = e["geo"]
                # no d <= marker: kd^2/n carries the same tier and shows none
                geod = "" if geo is None else f"{geo:.3g}"
                # the seeded surface/toric/Steane tilings ARE the g = 1
                # ceiling (same convention as the record chart); in g mode
                # they rank below every submission, dimmed, as the reference
                ref = geo_reference(e)
                return (
                    f'<a class="gitem{" ghide" if pos >= topn else ""}" '
                    f'href="codes/{e["slug"]}.html" '
                    f'title="{html.escape(e["name"])}'
                    f'{" — reference tiling: the ceiling g is normalized to, not raced" if ref else ""}" '
                    f'data-eff="{e["eff"]}" data-effd="{e["eff"]:g}" '
                    f'data-geo="{"" if geo is None else geo}" '
                    f'data-geod="{geod}"{" data-ref=1" if ref else ""}>'
                    f'{badge(e["tier"])}'
                    f'<span class=gcode>[[{e["n"]},{e["k"]},{e["d"]}]]</span>'
                    f'<span class=geff>{e["eff"]:g}</span></a>')
            items = "".join(gitem(i, pos) for pos, i in enumerate(ranked))
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
            'Each cell lists its Pareto frontier, ranked by the selected score '
            '(kd&sup2;/n, or geometric efficiency g for codes with a verified '
            'layout). The code count filters the table below to that cell. '
            'Membership nests: a tighter cell&rsquo;s codes also compete in the '
            'looser ones. In the g view, the seeded surface/toric tilings are '
            'not raced; they set the ceiling g is normalized to '
            '(surface code = 1) and appear dimmed below the ranking.</p>'
            '<div class=ptbar><span class=rcgroup>'
            '<button type=button class="ptbtn active" data-pt=eff '
            'title="rank cells by operational efficiency kd&sup2;/n">'
            'kd&sup2;/n</button>'
            '<button type=button class=ptbtn data-pt=geo '
            'title="rank cells by geometric efficiency g. The seeded '
            'surface/toric tilings are the ceiling g is normalized to and are '
            'shown dimmed below the race; codes without a verified layout '
            'show &middot; and sort last">g</button>'
            '</span></div>'
            f'<div class=ptscroll><table class=grid>{head}'
            f'{"".join(body)}</table></div>'
            # the toggle re-ranks every cell by the chosen metric and shows its
            # top 3; members without a g sort last and display a dot
            '<script>(function(){'
            'var grid=document.querySelector(".ptgrid");if(!grid)return;'
            'function apply(m){'
            'grid.classList.toggle("pt-geo",m==="geo");'
            'grid.querySelectorAll("td.gcell").forEach(function(td){'
            'var items=[].slice.call(td.querySelectorAll(".gitem"));'
            'function sv(el){var v=parseFloat(el.dataset[m]);'
            'if(isNaN(v))return -2e9;'
            'if(m==="geo"&&el.dataset.ref)return v-1e9;'
            'return v;}'
            'items.sort(function(a,b){return sv(b)-sv(a);});'
            'items.forEach(function(el,i){'
            'el.classList.toggle("ghide",i>=3);'
            'el.querySelector(".geff").innerHTML='
            'el.dataset[m+"d"]||"&middot;";'
            'td.appendChild(el);});});}'
            'grid.querySelectorAll(".ptbtn").forEach(function(b){'
            'b.addEventListener("click",function(){'
            'grid.querySelectorAll(".ptbtn").forEach('
            'function(x){x.classList.remove("active");});'
            'b.classList.add("active");apply(b.dataset.pt);});});'
            '})();</script></section>')


def latest_codes_panel(entries, records, limit=10):
    """A 'recently added' strip (issue #308): the newest codes by submission
    date, newest first, so a visitor can see the board is live. Each row links
    to the code page and is starred if it currently holds a cell record."""
    rec_slugs = {entries[i]["slug"] for i in records}
    dated = [e for e in entries if e.get("date")]
    dated.sort(key=lambda e: (e["date"], e["slug"]), reverse=True)
    rows = []
    for e in dated[:limit]:
        star = ('<span class=lstar title="holds a cell record">&#9733;</span>'
                if e["slug"] in rec_slugs else '')
        # authors_compact, not html.escape on the joined string: this panel was
        # the one place a handle rendered as inert text while the same handle
        # linked to its profile everywhere else. It also collapses a long
        # literature author list to "Surname et al." so the row stays one line.
        who = authors_compact(e["authors_list"])
        origin = ('literature' if e["origin"] == "literature" else 'submission')
        rows.append(
            f'<li><a class="mono lnkd" href="codes/{e["slug"]}.html">'
            f'[[{e["n"]},{e["k"]},{e["d"]}]]</a>{star}'
            f'<span class=lfam>{html.escape(family_label(e["family"]))}</span>'
            f'<span class=lwho>{who}</span>'
            f'<span class="lorig {origin}">{origin}</span>'
            f'<span class=ldate>{html.escape(e["date"])}</span></li>')
    if not rows:
        return ""
    return ('<section class=latest><h2 class=track>Recently added '
            f'<span class=tcount>&middot; last {min(limit, len(dated))} by '
            'submission date</span></h2>'
            f'<ol class=latestlist>{"".join(rows)}</ol></section>')


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
            f'{len(records)} records</span>'
            '<button id=qchip class=qchip style="display:none" type=button '
            'title="an active search filter is hiding rows; click to clear">'
            '</button></h2>'
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
            f'<div class=filterrow>{wslider}{dslider}{nslider}{kslider}'
            '<button type=button id=clearfilters class=otog '
            'title="reset search, sliders, and every active filter">'
            'clear filters</button></div>'
            '<p class=searchhelp>Type terms (all must match): a family, author, '
            'or a comparison like <code>k&gt;=10</code> <code>d&gt;8</code> '
            '<code>eff&gt;=5</code> <code>g&gt;=0.1</code>; <code>record</code> '
            'keeps only frontier rows; <code>literature</code> / '
            '<code>submitted</code> filter by origin; <code>with-layout</code> '
            '/ <code>no-layout</code> filter by layout status.</p>'
            '</section>')


def charts_block(entries, records):
    """The two landscape scatters side by side (stacked on narrow screens) with a
    shared HTML legend below them. The legend is HTML, not drawn into the SVG, so
    it keeps real font sizes and reflows on mobile."""
    d_plot = scatter(entries, records, lambda e: e["d"], "Code Distance (d)")
    eff_plot = scatter(entries, records, lambda e: e["eff"], "kd²/n")
    # A second version of the efficiency scatter with y = f, only the codes
    # that ship a layout. The "with layout" toggle swaps it in for the kd^2/n
    # view (issue #276); both are rendered statically, JS flips display.
    geo_idx = [i for i, e in enumerate(entries) if e["geo"] is not None]
    f_plot = scatter([entries[i] for i in geo_idx],
                     {j for j, i in enumerate(geo_idx) if i in records},
                     lambda e: e["geo"], "g (geometric efficiency)")
    if eff_plot:
        eff_plot = eff_plot.replace('<svg ', '<svg id=ploteff ', 1)
    if f_plot:
        f_plot = f_plot.replace(
            '<svg ', '<svg id=plotgeo style="display:none" ', 1)
    if not d_plot and not eff_plot:
        return ""
    # layout toggle, top right of the charts (issue #276). "no layout" is a
    # certification status -- such codes may still be local, nobody proved it
    # -- so the label is neutral rather than "expander".
    toggle = (
        '<div class=geotabs role=group aria-label="filter by layout status">'
        '<button type=button class=geotab data-geo=with '
        'title="only codes with a verifier-accepted 2D layout; the efficiency '
        'chart switches from kd&sup2;/n to the geometric efficiency g">'
        'with layout</button>'
        '<button type=button class=geotab data-geo=without '
        'title="only codes without a verified layout; locality may exist but '
        'is uncertified (not necessarily expander codes)">no layout</button>'
        '</div>')
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
    return (f'<div class=plots>{toggle}{d_plot}{eff_plot}{f_plot}</div>'
            f'{xlabel}{legend}')


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
            '<col style="width:6%"><col style="width:7%"><col style="width:7%">'
            '<col style="width:5%">'
            '<col style="width:15%"><col style="width:14%">'
            '<col style="width:9%"></colgroup>')
    head = ('<thead><tr><th></th>'
            '<th data-c=codekey data-num title="the code, written [[n,k,d]]; '
            'sorts by n, then k, then d">code</th>'
            '<th data-c=type class=col-type title="construction family / track">'
            'type</th>'
            '<th data-c=n class="num col-n" title="physical qubits">n</th>'
            '<th data-c=k class="num col-k" title="logical qubits">k</th>'
            '<th data-c=d class="num col-d" title="distance">d</th>'
            '<th data-c=eff class=num title="operational efficiency '
            'k&middot;d&sup2;/n, higher is better">kd&sup2;/n</th>'
            '<th data-c=geo class=num title="geometric efficiency '
            'g = 4kd&sup2;/(n&rho;&sup2;r&#8308;), priced by the verified '
            'layout&rsquo;s interaction radius r and layers &rho;; surface '
            'code = 1; &middot; = no verified layout">g</th>'
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
            "with-layout" if e["geo"] is not None else "no-layout",
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
            f'data-eff="{e["eff"]}" data-w="{e["w"]}" '
            f'data-geo="{e["geo"] if e["geo"] is not None else -1}" '
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
            + f'</td><td class="typecell col-type" data-label="type">{chips(e)}</td>'
            f'<td class="num col-n" data-label="n">{e["n"]}</td>'
            f'<td class="num col-k" data-label="k">{e["k"]}</td>'
            f'<td class="num col-d" data-label="d">{badge(e["tier"])} {e["d"]}</td>'
            f'<td class="num m3" data-label="kd&sup2;/n">{e["eff"]}</td>'
            + (f'<td class="num m3" data-label="g" title="r = {e["geo_r"]}, {e["geo_rho"]} '
               f'layer{"s" if e["geo_rho"] != 1 else ""}'
               f'{"; inherits the upper-bound distance tier" if e["tier"] != "exact" else ""}">'
               f'{e["geo"]:.3g}</td>'
               if e["geo"] is not None else
               '<td class="num m3" data-label="g" title="no verified layout; geometric '
               'efficiency undefined (not necessarily an expander code)">&middot;</td>')
            + f'<td class="num m3" data-label="w">{e["w"]}</td>'
            f'<td class="auth col-auth" data-label="authors" '
            f'title="{html.escape(e["authors"])}">'
            f'{authors_compact(e["authors_list"])}</td>'
            '<td class=model data-label="model">'
            + (f'<span class=modelmark title="{html.escape(e["model"])}">'
               f'{CLAUDE_MARK if e["model"].startswith("Claude") else ""}'
               f'<span class=modelname>{models_compact(e["model"])}</span>'
               f'</span>'
               if e["model"]
               else f'<span class=nomodel title="classical construction, no AI '
                    f'model">{HUMAN_MARK}</span>')
            + '</td>'
            f'<td class=date data-label="date">{html.escape(e["date"]) if e["date"] else "&middot;"}</td></tr>')

    return (f'<div class=boardscroll><table class=board id=mainboard>{cols}{head}'
            f'<tbody>{"".join(rows)}</tbody></table></div>'
            f'<button id=showall class=showall type=button>'
            f'Show all {len(rows)} codes</button>')


def not_found_page():
    """Project-aware GitHub Pages 404, including Plausible's special event."""
    base_path = urllib.parse.urlparse(SITE_URL).path.rstrip("/") + "/"
    P = [head("Page not found · QEC Challenge", rel=base_path,
              page_properties={"page_type": "not_found"})]
    P.append('<div class=wrap style="padding-top:64px">'
             '<div class="mono big">404</div>'
             '<h1>Page not found</h1>'
             '<p>The requested QEC Challenge page does not exist.</p>'
             f'<a class=back href="{base_path}">&larr; back to the board</a>'
             '</div>')
    # A 404 is diagnostic rather than visitor engagement, so it must not turn
    # an otherwise bounced visit into an engaged one.
    P.append('<script>plausible("404",{interactive:false})</script>'
             '</body></html>')
    return "\n".join(P)


def build():
    entries = load_entries()
    n_exact = sum(1 for e in entries if e["tier"] == "exact")
    best_eff = max((e["eff"] for e in entries), default=0)
    best_eff_e = max(entries, key=lambda e: (e["eff"], -e["n"]), default=None)
    geo_pool = [e for e in entries
                if e["geo"] is not None and e["d"] >= GEO_MIN_D]
    best_geo_e = max(geo_pool, key=lambda e: (e["geo"], -e["n"]),
                     default=None)
    records = compute_records(entries)

    P = [head("QEC Challenge",
              page_properties={"page_type": "leaderboard"})]
    P.append('<header class=hero>' + HERO_FLOW + '<div class=wrap>'
             '<div class=brand>'
             '<span class=brandmark>'
             '<a href="https://unitary.foundation" '
             f'aria-label="Unitary Foundation">{UF_LOGO}</a>'
             '</span>'
             '<button class="lbcta herocta" type=button '
             'onclick="(function(){var d=document.getElementById('
             '&quot;participate&quot;);if(d&&d.showModal){d.showModal();'
             'plausible(&quot;Participate Opened&quot;,{props:{location:'
             '&quot;hero&quot;}});}})()">Participate</button>'
             '</div>'
             '<h1>QEC Challenge</h1>'
             '<p>Find better quantum LDPC codes. '
             '<a href="whitepaper.html">Read the whitepaper.</a></p>'
             '<nav class=topnav>'
             '<a href="faq.html">FAQ</a>'
             '<a href="research-log.html">Research log</a>'
             '<a href="references.html">References</a>'
             f'<a href="{REPO_ROOT}">{GH_ICON}GitHub</a>'
             '</nav>'
             '</div></header>')
    P.append('<div class=wrap>')
    P.append(progress_panel(entries, best_eff_e, best_geo_e))
    # plain-sight definitions of the two headline scores (issue #276 review:
    # tooltips are invisible on mobile and undiscoverable in general)
    P.append(
        '<section class=scoredefs>'
        '<div class=sdef><div class=sdefhead>'
        '<span class=sdeftitle>Operational efficiency</span>'
        '<span class="mono sdefformula">kd&sup2;/n</span></div>'
        '<p class=sdefbody>The Bravyi&ndash;Poulin&ndash;Terhal ratio, '
        'normalized so the surface code sits at 1. Bounded for 2D-local and '
        'bounded-weight codes; grows with n for high-rate codes, so it is '
        'compared within tracks, not as a global record.</p></div>'
        '<div class=sdef><div class=sdefhead>'
        '<span class=sdeftitle>Geometric efficiency</span>'
        '<span class="mono sdefformula">g = 4kd&sup2;/(n&rho;&sup2;r&#8308;)</span>'
        '</div>'
        '<p class=sdefbody>The same ratio priced by the layout the code ships '
        'with, normalized so the planar surface code scores exactly 1. Computed '
        'only for codes with a verifier-accepted layout; an upper-bound distance '
        f'makes g an upper bound, and the headline requires d &ge; {GEO_MIN_D}.'
        '</p></div>'
        '<div class=sgloss><b>n</b> physical qubits &middot; '
        '<b>k</b> logical qubits &middot; <b>d</b> code distance (smallest '
        'undetectable error) &middot; <b>w</b> max check weight &middot; '
        '<b>r</b> interaction radius: the largest check diameter in the '
        'layout, in units of the minimum qubit spacing &middot; '
        '<b>&rho;</b> qubit layers per site (2 = flip-chip bilayer; charged '
        'as &rho;&sup2; so stacking must earn its density)</div>'
        '</section>')
    P.append(record_chart(entries))
    P.append(primary_tracks_grid(entries, records))
    P.append('<div class=how>'
             f'<a class=card href="{REPO_ROOT}/blob/main/CONTRIBUTING.md">'
             '<span class=n>1</span><h3>Build a code</h3>'
             '<p>A CSS qLDPC code, written as one JSON file with its parity '
             'checks and a distance witness. <span class=arrow>&rarr;</span></p>'
             '</a>'
             f'<a class=card href="{REPO_ROOT}/pulls">'
             '<span class=n>2</span><h3>Open a PR</h3>'
             '<p>Add it under <code>codes/</code>. CI runs the verifier on '
             'every submission automatically. <span class=arrow>&rarr;</span></p>'
             '</a>'
             '<a class=card href="#board">'
             '<span class=n>3</span><h3>Climb the board</h3>'
             '<p>If it advances a track&rsquo;s frontier it is highlighted. '
             'Click any row for the witness, certificate, and checks. '
             '<span class=arrow>&rarr;</span></p>'
             '</a></div>')
    P.append(latest_codes_panel(entries, records))
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
             '&middot; <b>kd&sup2;/n</b> operational efficiency (per track) '
             '&middot; <b>g</b> geometric efficiency 4kd&sup2;/(n&rho;&sup2;'
             'r&#8308;), priced by the layout&rsquo;s radius r and layers '
             '&rho; (surface code = 1; &middot; = no verified layout) '
             '&middot; <b>w</b> max check weight</span>'
             '</div>')
    P.append(board_table(entries, records))
    P.append('</div>')  # close explorer (the viewport-fitted plots+table column)
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
        '<a href="research-log.html">Research log</a>'
        '<a href="references.html">References</a>'
        '<a href="qec_challenge.pdf">Whitepaper</a>'
        '</nav></div>'
        '<div class=footbar>&copy; 2026 &middot; Built by '
        '<a href="https://unitary.foundation">Unitary Foundation</a> '
        f'&middot; <a href="{REPO}/LICENSE">Apache 2.0</a> '
        '&middot; Cookie-free analytics by '
        '<a href="https://plausible.io">Plausible</a></div></footer>')
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
    with open(os.path.join(DOCS, "research-log.html"), "w") as f:
        f.write(research_log_page(entries, load_fieldnotes()))
    with open(os.path.join(DOCS, "404.html"), "w") as f:
        f.write(not_found_page())
    # Wrapper so the whitepaper opens with the site favicon and a proper tab
    # title (a raw PDF tab shows the browser's PDF-viewer icon instead).
    with open(os.path.join(DOCS, "whitepaper.html"), "w") as f:
        f.write(
            '<!doctype html><html lang=en><head><meta charset=utf-8>'
            '<meta name=viewport content="width=device-width,initial-scale=1">'
            '<title>The QEC Challenge whitepaper</title>'
            '<link rel=icon type="image/svg+xml" href="favicon.svg">'
            + plausible_snippet({"page_type": "whitepaper"}) +
            '<style>html,body{margin:0;height:100%}'
            'embed{width:100%;height:100%}</style></head><body>'
            '<embed src="qec_challenge.pdf" type="application/pdf">'
            '</body></html>')
    slugs = {e["slug"] for e in entries}
    for e in entries:
        with open(os.path.join(DOCS, "codes", e["slug"] + ".html"), "w") as f:
            f.write(detail_page(e))
    # prune orphan detail pages left behind when a code is removed
    for f in glob.glob(os.path.join(DOCS, "codes", "*.html")):
        if os.path.splitext(os.path.basename(f))[0] not in slugs:
            os.remove(f)
    check_analytics_coverage()

    # machine-readable stats; the README badges (shields.io dynamic JSON) read
    # this file from the live site, so there is no committed badge image to fall
    # out of sync.
    n_cells = len(cells_by_key(entries))
    stats = {"verified_codes": len(entries), "certified_exact": n_exact,
             "tracks": n_cells, "best_kd2_over_n": best_eff,
             "best_geometric_efficiency":
                 best_geo_e["geo"] if best_geo_e else None}
    with open(os.path.join(DOCS, "stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    print(f"wrote docs/index.html + {len(entries)} detail pages + "
          f"references.html ({len(REFS)} refs), "
          f"{n_cells} primary-track cells, {n_exact} certified exact")


if __name__ == "__main__":
    build()
