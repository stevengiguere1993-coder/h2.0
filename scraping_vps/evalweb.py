"""Scraper EvalWeb (rôle d'évaluation MTL) via Playwright.

Le portail montreal.ca/role-evaluation-fonciere a un flow stateful
4 étapes avec JavaScript et CSRF. Avec Playwright on automatise un
vrai navigateur Chromium qui exécute la JS — bypass complet.

Flow :
1. Goto /role-evaluation-fonciere (page options)
2. Click radio « Par matricule »
3. Click « Suivant » → page form 6 sous-champs
4. Fill 6 inputs (Division/Secteur/Emplacement/Cav/Bâtiment/Local)
5. Click « Rechercher » → page liste
6. Click le matricule cible → page Résultat détaillé
7. Parse la section « 2. Propriétaire »
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

from playwright.async_api import Browser, Page

log = logging.getLogger(__name__)

NEW_PORTAL_PUBLIC = "https://montreal.ca/role-evaluation-fonciere"

# Labels propriétaire dans le HTML rendu
_OWNER_LABELS = (
    ("name", ("Nom",)),
    ("statut", (
        "Statut aux fins d'imposition scolaire", "Statut",
    )),
    ("postal_address", ("Adresse postale",)),
    ("inscription_date", (
        "Date d'inscription au rôle", "Date d'inscription",
    )),
    ("conditions", (
        "Conditions particulières d'inscription",
        "Conditions particulières",
    )),
)


def decompose_matricule(matricule: str) -> Optional[dict]:
    """0135-23-0549-2-000-0000 → 6 sous-champs."""
    parts = matricule.strip().split("-")
    if len(parts) != 6:
        return None
    div, sec, emp, cav, bat, loc = parts
    if not (
        len(div) == 4 and len(sec) == 2 and len(emp) == 4
        and len(cav) == 1 and len(bat) == 3 and len(loc) == 4
    ):
        return None
    return {
        "division": div, "secteur": sec, "emplacement": emp,
        "cav": cav, "batiment": bat, "local": loc,
    }


async def scrape_owners_via_browser(
    browser: Browser, matricule: str
) -> Tuple[List[dict], Optional[str]]:
    """Lance Playwright et fait le flow 4 étapes.

    Retourne (owners, raw_text). `raw_text` rempli en cas d'erreur
    de parsing pour debug.
    """
    parts = decompose_matricule(matricule)
    if parts is None:
        raise ValueError(f"Matricule invalide : {matricule!r}")

    context = await browser.new_context(
        locale="fr-CA",
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
    )
    page = await context.new_page()
    page.set_default_timeout(30_000)

    async def _snap(label: str) -> None:
        try:
            path = f"/tmp/evalweb-step-{matricule}-{label}.png"
            await page.screenshot(path=path, full_page=True)
            html_len = len(await page.content())
            log.info(
                "STEP[%s] url=%s html_len=%d screenshot=%s",
                label, page.url, html_len, path,
            )
        except Exception as exc:
            log.warning("STEP[%s] snap fail: %s", label, exc)

    try:
        # Étape 1 : page d'accueil. networkidle attend que toutes
        # les requêtes finissent (React hydrate, fonts chargent…).
        log.info("EvalWeb : goto %s", NEW_PORTAL_PUBLIC)
        await page.goto(
            NEW_PORTAL_PUBLIC, wait_until="networkidle", timeout=30_000
        )
        # Sécurité supplémentaire : laisse 2s à React pour hydrater
        # les event listeners.
        await page.wait_for_timeout(2_000)
        await _snap("01-home")

        # Étape 2 : sélectionne « Par matricule » + Suivant
        await _click_par_matricule(page)
        await page.wait_for_timeout(500)
        await _snap("02-radio-checked")
        await _click_suivant(page)
        await page.wait_for_load_state("networkidle", timeout=15_000)
        await page.wait_for_timeout(1_500)
        await _snap("03-after-suivant")

        # Étape 3 : remplit les 6 sous-champs + Rechercher
        await _fill_matricule_form(page, parts)
        await page.wait_for_timeout(500)
        await _snap("04-form-filled")
        await _click_rechercher(page)
        await page.wait_for_load_state("networkidle", timeout=15_000)
        await page.wait_for_timeout(1_500)
        await _snap("05-after-rechercher")

        # Étape 4 : si on tombe sur la liste, click le bon matricule
        await _click_matricule_in_list(page, matricule)
        await page.wait_for_load_state("networkidle", timeout=10_000)
        await page.wait_for_timeout(1_000)
        await _snap("06-final")

        html = await page.content()
        owners = parse_owners_from_html(html)
        if owners:
            log.info(
                "EvalWeb : %d proprios extraits pour %s",
                len(owners),
                matricule,
            )
            return owners, None
        # Si rien extrait, retourne le HTML pour debug + sauve un
        # screenshot dans /tmp pour inspection ultérieure.
        try:
            screenshot_path = f"/tmp/evalweb-fail-{matricule}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            log.warning(
                "EvalWeb : 0 owners trouvés. Screenshot : %s. URL: %s",
                screenshot_path,
                page.url,
            )
        except Exception:
            pass
        return [], html[:8000]
    finally:
        await context.close()


async def _click_par_matricule(page: Page) -> None:
    """Sélectionne le radio « Par matricule ».

    Sur cette React SPA, cliquer sur le label ne suffit pas — il
    faut faire un .check() sur l'input radio pour que React
    enregistre le change. On essaie plusieurs stratégies.
    """
    # Stratégie 1 : trouve la label puis check via l'attribut `for`.
    try:
        label = page.locator("label:has-text('Par matricule')").first
        for_attr = await label.get_attribute("for")
        if for_attr:
            radio = page.locator(f"#{for_attr}")
            await radio.check(force=True, timeout=5_000)
            checked = await radio.is_checked()
            if checked:
                log.info(
                    "  → 'Par matricule' coché via #%s",
                    for_attr,
                )
                return
    except Exception as exc:
        log.debug("  label[for] → %s", exc)

    # Stratégie 2 : page.get_by_label() + .check()
    try:
        await page.get_by_label("Par matricule").first.check(
            force=True, timeout=5_000
        )
        log.info("  → 'Par matricule' coché via get_by_label")
        return
    except Exception as exc:
        log.debug("  get_by_label → %s", exc)

    # Stratégie 3 : input radio par value
    for selector in (
        "input[type='radio'][value='matricule']",
        "input[type='radio'][value='Par matricule']",
        "input[type='radio'][name*='option']",
    ):
        try:
            radio = page.locator(selector).first
            await radio.check(force=True, timeout=3_000)
            if await radio.is_checked():
                log.info(
                    "  → 'Par matricule' coché via %s", selector
                )
                return
        except Exception:
            continue

    # Stratégie 4 : click direct sur la label (peut suffire dans
    # certains cas où le radio n'a pas d'id)
    try:
        await page.locator(
            "label:has-text('Par matricule')"
        ).first.click(timeout=3_000)
        log.info("  → 'Par matricule' cliqué via label")
        return
    except Exception:
        pass

    raise RuntimeError("Bouton « Par matricule » introuvable")


async def _click_suivant(page: Page) -> None:
    try:
        await page.get_by_role("button", name="Suivant").first.click(
            timeout=5_000
        )
        log.info("  → 'Suivant' cliqué via get_by_role")
        return
    except Exception:
        pass
    for selector in (
        "button:has-text('Suivant')",
        "input[type='submit'][value='Suivant']",
        "text=Suivant",
    ):
        try:
            await page.locator(selector).first.click(timeout=3_000)
            log.info("  → 'Suivant' cliqué via %s", selector)
            return
        except Exception:
            continue
    raise RuntimeError("Bouton « Suivant » introuvable")


async def _fill_matricule_form(page: Page, parts: dict) -> None:
    """Remplit les 6 inputs du form Recherche par matricule.

    Les noms exacts des champs varient — on essaie label + name.
    """
    mapping = {
        "division": parts["division"],
        "secteur": parts["secteur"],
        "emplacement": parts["emplacement"],
        "cav": parts["cav"],
        "batiment": parts["batiment"],
        "local": parts["local"],
    }
    labels_fr = {
        "division": "Division",
        "secteur": "Secteur",
        "emplacement": "Emplacement",
        "cav": "Cav",
        "batiment": "Bâtiment",
        "local": "Local",
    }
    for key, value in mapping.items():
        filled = False
        for selector in (
            f"input[name='{key}']",
            f"input[name='{key.capitalize()}']",
            f"input[id='{key}']",
            f"input[aria-label*='{labels_fr[key]}' i]",
        ):
            try:
                loc = page.locator(selector).first
                await loc.fill(value, timeout=2_000)
                filled = True
                break
            except Exception:
                continue
        if not filled:
            # Fallback : trouve le label puis l'input qui suit
            try:
                label = page.locator(
                    f"text={labels_fr[key]}"
                ).first
                # Le input est typiquement le 1er input frère
                await label.locator(
                    "xpath=following::input[1]"
                ).fill(value, timeout=2_000)
                filled = True
            except Exception:
                pass
        if not filled:
            raise RuntimeError(
                f"Champ {labels_fr[key]} introuvable"
            )


async def _click_rechercher(page: Page) -> None:
    try:
        await page.get_by_role(
            "button", name="Rechercher"
        ).first.click(timeout=5_000)
        log.info("  → 'Rechercher' cliqué via get_by_role")
        return
    except Exception:
        pass
    for selector in (
        "button:has-text('Rechercher')",
        "input[type='submit'][value='Rechercher']",
        "text=Rechercher",
    ):
        try:
            await page.locator(selector).first.click(timeout=3_000)
            log.info("  → 'Rechercher' cliqué via %s", selector)
            return
        except Exception:
            continue
    raise RuntimeError("Bouton « Rechercher » introuvable")


async def _click_matricule_in_list(page: Page, matricule: str) -> None:
    """Sur la page Liste, clique le lien dont le texte contient
    le matricule cible. Si on tombe direct sur la fiche (cas 1
    seul résultat), on saute cette étape."""
    # Si la page contient déjà « 2. Propriétaire », pas besoin
    content = await page.content()
    if "2. Propriétaire" in content or "Propriétaire" in content:
        return
    # Sinon, click le matricule dans la liste
    for selector in (
        f"a:has-text('{matricule}')",
        f"text={matricule}",
    ):
        try:
            await page.locator(selector).first.click(timeout=3_000)
            await page.wait_for_load_state("domcontentloaded")
            return
        except Exception:
            continue
    # Dernière chance : cherche le lien qui contient les premiers
    # chiffres du matricule
    short = matricule[:8]
    try:
        await page.locator(f"a:has-text('{short}')").first.click(
            timeout=3_000
        )
    except Exception:
        log.warning(
            "Impossible de cliquer le matricule dans la liste, "
            "on tente de parser ce qui est affiché."
        )


# ============== Parser HTML → owners ==============


def parse_owners_from_html(html: str) -> List[dict]:
    """Parse la section Propriétaire du HTML rendu. Tolère
    plusieurs structures."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    # Cherche la section Propriétaire
    idx = text.lower().find("propriétaire")
    if idx > 0:
        text = text[idx:]
    # Coupe avant les sections suivantes
    for stop in (
        "Caractéristiques",
        "Évaluation",
        "Valeurs au rôle",
        "Imposition",
        "Identification",
    ):
        cut = text.find(stop)
        if cut > 0:
            text = text[:cut]

    lines = [
        line.strip().rstrip(":").strip()
        for line in text.split("\n")
        if line.strip()
    ]

    owners: List[dict] = []
    current: dict = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        match_key: Optional[str] = None
        for key, syns in _OWNER_LABELS:
            if any(line.lower() == s.lower() for s in syns):
                match_key = key
                break
        if match_key:
            val = lines[i + 1] if i + 1 < len(lines) else ""
            if match_key == "name" and "name" in current:
                owners.append(current)
                current = {}
            current[match_key] = val
            i += 2
        else:
            i += 1
    if current.get("name"):
        owners.append(current)
    return [o for o in owners if o.get("name")]
