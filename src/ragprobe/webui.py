"""Shared web chrome so every generated page wears the same skin.

The landing page, the security report, the quality report and the dashboard are
rendered by separate modules, but a visitor moves between them and expects one
product, not four. This module is the single source of that shared shell: the
sticky top navigation bar (gradient mark, cross-page links, theme toggle), the
scroll-reveal and count-up animations, and the little script that drives both.

Everything is plain strings with no external assets, so it stays inside the
"self-contained, offline, no CDN" rule the rest of the site follows. The CSS
resolves its colours through fallback chains (``--panel`` or ``--surface`` …) so
it drops into any of the pages whatever they happen to call their tokens.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple

# The links every sub-page shows, in one fixed order. (page-id, href, label)
SITE_LINKS: Sequence[Tuple[str, str, str]] = (
    ("overview", "index.html", "Overview"),
    ("security", "security.html", "Security"),
    ("dashboard", "dashboard.html", "Dashboard"),
    ("report", "report.html", "Report"),
)


def _esc(text: object) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def top_nav(active: str, repo_url: str,
            links: Optional[Iterable[Tuple[str, str, str]]] = None,
            toggle: bool = True) -> str:
    """The sticky top bar, identical in look across every page.

    ``active`` is the page-id of the current page so its link reads as selected.
    ``toggle`` draws the theme button; pages that already own a theme control
    (the dashboard) pass ``False`` so there is only one.
    """
    items = []
    for page_id, href, label in (links if links is not None else SITE_LINKS):
        cls = ' class="on"' if page_id == active else ""
        items.append(f'<a href="{_esc(href)}"{cls}>{_esc(label)}</a>')
    items.append(f'<a href="{_esc(repo_url)}" class="ext">GitHub</a>')
    tg = (
        '<button class="rptg" id="tg" type="button" aria-label="Toggle light or dark theme">'
        '<svg class="moon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>'
        '<svg class="sun" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4.5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2 2M17 17l2 2M4.9 19.1l2-2M17 7l2-2" stroke-linecap="round"/></svg>'
        "</button>"
    ) if toggle else ""
    return (
        '<nav class="rpnav"><div class="rpnav-in">'
        '<a class="rplogo" href="index.html"><span class="rpmark">R</span>RAGProbe</a>'
        '<span class="rplinks">' + "".join(items) + "</span>"
        + tg + "</div></nav>"
    )


# The shell styles. Colours come through fallback chains so one block fits every
# page regardless of whether it names its surface --panel or --surface, etc.
NAV_CSS = """
.rpnav{--_bg:var(--bg,#07090d);--_panel:var(--panel,var(--surface,#0e1219));--_bd:var(--border,#1c2430);--_bd2:var(--border-2,var(--border,#273243));--_ink:var(--ink,var(--text,#eef2f8));--_muted:var(--muted,var(--text-dim,#9aa6b6));--_acc:var(--accent,#ff5a1f);--_acc2:var(--accent-2,var(--accent,#ffb547));--_glow:var(--glow,rgba(255,90,31,.35));position:sticky;top:0;z-index:60;backdrop-filter:blur(12px);background:color-mix(in srgb,var(--_bg) 74%,transparent);border-bottom:1px solid var(--_bd)}
.rpnav-in{max-width:1120px;margin:0 auto;padding:0 20px;display:flex;align-items:center;gap:18px;height:62px}
.rplogo{display:flex;align-items:center;gap:10px;font-weight:800;font-size:17px;color:var(--_ink);text-decoration:none;letter-spacing:-.02em}
.rpmark{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--_acc),var(--_acc2));color:#0a0a0a;display:grid;place-items:center;font-weight:900;font-size:16px;box-shadow:0 0 24px -4px var(--_glow)}
.rplinks{margin-left:auto;display:flex;gap:2px;flex-wrap:wrap;justify-content:flex-end}
.rplinks a{padding:8px 13px;border-radius:9px;color:var(--_muted);font-weight:500;font-size:14.5px;text-decoration:none;transition:background .15s,color .15s}
.rplinks a:hover{background:var(--_panel);color:var(--_ink)}
.rplinks a.on{color:var(--_acc);background:color-mix(in srgb,var(--_acc) 12%,transparent)}
.rplinks a.ext::after{content:"\\2197";font-size:11px;opacity:.6;margin-left:3px}
.rptg{width:36px;height:36px;border-radius:10px;border:1px solid var(--_bd2);background:var(--_panel);color:var(--_ink);cursor:pointer;display:grid;place-items:center;flex:none}
.rptg:hover{border-color:var(--_acc);color:var(--_acc)}
:root[data-theme="light"] .rptg .moon{display:none}:root:not([data-theme="light"]) .rptg .sun{display:none}
@media(max-width:560px){.rplinks a{padding:7px 9px;font-size:13px}.rpnav-in{gap:10px}}
"""

# Tiny head script: restore the saved theme before first paint, so a light-theme
# visitor never sees a dark flash. The full wiring lives in CHROME_JS at body end.
THEME_BOOT = ("(function(){try{var t=localStorage.getItem('ragprobe-theme');"
              "if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();")

# Scroll-reveal + count-up. Elements tagged .reveal rise in as they enter view;
# a number tagged data-count ticks up to its value once revealed.
REVEAL_CSS = """
@media (prefers-reduced-motion:reduce){.reveal{opacity:1!important;transform:none!important}}
.reveal{opacity:0;transform:translateY(22px);transition:opacity .7s cubic-bezier(.2,.7,.2,1),transform .7s cubic-bezier(.2,.7,.2,1)}
.reveal.in{opacity:1;transform:none}
"""

# One script run on every page: restore the saved theme, wire the toggle, play
# the reveal/count-up as sections scroll into view.
CHROME_JS = """
(function(){
  try{var t=localStorage.getItem('ragprobe-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}
  var tg=document.getElementById('tg');
  if(tg)tg.addEventListener('click',function(){
    var n=document.documentElement.getAttribute('data-theme')!=='light'?'light':'dark';
    document.documentElement.setAttribute('data-theme',n);
    try{localStorage.setItem('ragprobe-theme',n);}catch(e){}});
  function count(el){var to=+el.getAttribute('data-count'),suf=el.getAttribute('data-suffix')||'',t0=null,d=1100;
    function s(ts){t0=t0||ts;var p=Math.min((ts-t0)/d,1);el.textContent=Math.round(p*to)+suf;if(p<1)requestAnimationFrame(s);}
    requestAnimationFrame(s);}
  var reduce=false;try{reduce=window.matchMedia('(prefers-reduced-motion:reduce)').matches;}catch(e){}
  var targets=document.querySelectorAll('.reveal');
  if(reduce||!('IntersectionObserver'in window)){
    Array.prototype.forEach.call(targets,function(el){el.classList.add('in');});
    Array.prototype.forEach.call(document.querySelectorAll('[data-count]'),function(el){el.textContent=el.getAttribute('data-count')+(el.getAttribute('data-suffix')||'');});
    return;}
  var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){
    e.target.classList.add('in');
    Array.prototype.forEach.call(e.target.querySelectorAll('[data-count]'),count);
    io.unobserve(e.target);}});},{threshold:.15});
  Array.prototype.forEach.call(targets,function(el){io.observe(el);});
})();
"""
