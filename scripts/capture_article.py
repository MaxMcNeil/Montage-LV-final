#!/usr/bin/env python3
"""Capture PROPRE d'un article de presse (pour « Préparer les médias »), avec un vrai navigateur (Chromium) :
  1. ouvre la page comme un lecteur normal (France, français) ;
  2. FERME la fenêtre des cookies / du consentement (« Accepter », « Tout accepter », « Continuer sans accepter »…),
     y compris quand elle est dans un cadre (Didomi, OneTrust, Sirdata, Quantcast…) ;
  3. retire ce qui reste collé par-dessus (bandeaux, fenêtres, fonds grisés) ;
  4. photographie le haut de l'article (titre, chapô, photo) en 1280 x 1500.

  python3 scripts/capture_article.py <url> <sortie.jpg>
Code 0 : capture faite. Code 1 : impossible (le workflow essaie alors les autres moyens).
La vérification « page d'erreur / page bloquée » est faite ensuite par le workflow (lecture du texte de l'image)."""
from __future__ import annotations

import re
import sys

ACCEPT = re.compile(r"^\s*(tout accepter|accepter( et fermer| & fermer| tout)?|j'?accepte|ok|d'accord|"
                    r"accept( all)?|agree|i agree|continuer sans accepter|refuser( et fermer)?|tout refuser)\s*$", re.I)

CLEAN_JS = r"""
() => {
  const kill = el => { try { el.remove(); } catch (e) {} };
  // fenêtres et bandeaux de consentement connus
  document.querySelectorAll('[id*="didomi"],[class*="didomi"],[id*="onetrust"],[class*="onetrust"],'
    + '[id*="sp_message"],[class*="sp_message"],[id*="qc-cmp"],[class*="qc-cmp"],[id*="cmp"],[class*="cmp-"],'
    + '[id*="cookie"],[class*="cookie"],[id*="consent"],[class*="consent"],[id*="gdpr"],[class*="gdpr"],'
    + '[class*="paywall"],[id*="paywall"],[class*="newsletter-popup"],[aria-modal="true"]').forEach(kill);
  // tout ce qui est fixé par-dessus la page et couvre une grande surface (fenêtres, fonds grisés)
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if ((s.position === 'fixed' || s.position === 'sticky') && parseInt(s.zIndex || '0') > 10) {
      const r = el.getBoundingClientRect();
      if (r.width * r.height > 0.15 * innerWidth * innerHeight) kill(el);
    }
  }
  for (const el of [document.documentElement, document.body]) {
    el.style.setProperty('overflow', 'auto', 'important');
    el.style.setProperty('position', 'static', 'important');
  }
}
"""


def click_consent(page) -> bool:
    for fr in [page.main_frame] + page.frames:
        try:
            for b in fr.query_selector_all("button, a[role=button], [role=button], input[type=button]"):
                t = (b.inner_text() or b.get_attribute("value") or "").strip()
                if t and len(t) < 40 and ACCEPT.match(t) and b.is_visible():
                    b.click(timeout=3000)
                    page.wait_for_timeout(1200)
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    url, out = sys.argv[1], sys.argv[2]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright absent")
        return 1
    try:
        with sync_playwright() as p:
            br = p.chromium.launch()
            ctx = br.new_context(viewport={"width": 1280, "height": 1500}, locale="fr-FR", timezone_id="Europe/Paris",
                                 user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like "
                                            "Gecko) Chrome/130.0 Safari/537.36")
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            for _ in range(2):                       # parfois deux fenêtres l'une après l'autre
                if not click_consent(page):
                    break
            page.evaluate(CLEAN_JS)
            page.wait_for_timeout(800)
            page.evaluate("() => window.scrollTo(0, 0)")
            page.screenshot(path=out, type="jpeg", quality=88, clip={"x": 0, "y": 0, "width": 1280, "height": 1500})
            br.close()
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"capture impossible : {type(e).__name__}: {str(e)[:200]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
