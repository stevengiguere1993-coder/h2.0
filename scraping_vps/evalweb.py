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
import random
import re
from typing import List, Optional, Tuple


def _humanish(low: int, high: int) -> int:
    """Renvoie un délai aléatoire entre low et high ms — humanise
    les actions pour ne pas avoir de motif robotique parfait."""
    return random.randint(low, high)

from playwright.async_api import Browser, Page

try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None

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

    # Stealth DÉSACTIVÉ : avec headless=False + Xvfb on n'a plus
    # besoin (Chrome headed score reCAPTCHA naturellement haut), et
    # stealth peut au contraire casser grecaptcha.execute() (les
    # propriétés patchées créent des incohérences détectées par
    # reCAPTCHA et le token n'est pas généré).
    # if stealth_async is not None:
    #     await stealth_async(page)

    # Capture les console errors pour voir si reCAPTCHA plante
    def _on_console(msg) -> None:
        if msg.type in ("error", "warning"):
            text = msg.text[:300]
            if "recaptcha" in text.lower() or "captcha" in text.lower():
                log.warning("CONSOLE[%s] %s", msg.type, text)

    page.on("console", _on_console)

    # Capture toutes les requêtes pour debug — on filtre celles qui
    # touchent montreal.ca / api.montreal.ca pour voir où le form est posté.
    def _on_request(req) -> None:
        url = req.url
        if (
            "montreal.ca" in url
            and "google" not in url
            and req.method != "GET"
        ):
            body = req.post_data or ""
            log.info("REQ[%s] %s body=%s", req.method, url, body[:500])

    def _on_response(resp) -> None:
        url = resp.url
        if (
            "montreal.ca" in url
            and "google" not in url
            and resp.request.method != "GET"
        ):
            location = resp.headers.get("location", "")
            log.info(
                "RESP[%s %d] %s location=%s",
                resp.request.method, resp.status, url, location,
            )

    page.on("request", _on_request)
    page.on("response", _on_response)

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
        # Le fill prend déjà ~10s humanisés, donc plus besoin
        # de mouvements souris artificiels avant submit.
        await _fill_matricule_form(page, parts)
        # Pause "vérification" comme un user qui relit ses chiffres
        await page.wait_for_timeout(_humanish(1_200, 2_000))
        await _snap("04-form-filled")
        # Avant de cliquer, vérifie que TOUS les inputs ont la bonne
        # valeur (Radix UI peut avoir une valeur stale).
        try:
            current_values = await page.evaluate("""
                () => {
                    const inputs = document.querySelectorAll('input[name]');
                    const out = {};
                    inputs.forEach(i => out[i.name] = i.value);
                    return out;
                }
            """)
            log.info("PRE-SUBMIT VALUES: %s", current_values)
        except Exception as exc:
            log.warning("Dump values failed: %s", exc)
        # Bouge la souris vers le bouton Rechercher (fluide, ~400ms)
        # puis pause "réflexion" puis clic. Reproduit ce qu'un user
        # fait : visualiser le bouton, hover, cliquer.
        try:
            btn = page.locator("button[type='submit']").first
            box = await btn.bounding_box()
            if box:
                target_x = box["x"] + box["width"] / 2
                target_y = box["y"] + box["height"] / 2
                await page.mouse.move(target_x, target_y, steps=25)
            await page.wait_for_timeout(_humanish(400, 800))
            await btn.click()
            log.info("  → 'Rechercher' cliqué (humanisé)")
        except Exception as exc:
            log.warning("Click humanisé failed (%s), fallback", exc)
            await _click_rechercher(page)
        # Au lieu de networkidle (qui peut retourner trop vite),
        # attend que l'URL change OU 8s
        try:
            await page.wait_for_url(
                lambda u: u != "https://montreal.ca/role-evaluation-fonciere/matricule",
                timeout=8_000,
            )
            log.info("URL changed after Rechercher → %s", page.url)
        except Exception:
            log.warning("URL inchangée après Rechercher (%s)", page.url)
        await page.wait_for_load_state("networkidle", timeout=10_000)
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
    # Les name HTML sont en anglais sur cette SPA Next.js,
    # mais on garde le label FR pour fallback xpath.
    mapping = {
        "division": parts["division"],
        "sector": parts["secteur"],
        "location": parts["emplacement"],
        "cav": parts["cav"],
        "building": parts["batiment"],
        "local": parts["local"],
    }
    labels_fr = {
        "division": "Division",
        "sector": "Secteur",
        "location": "Emplacement",
        "cav": "Cav",
        "building": "Bâtiment",
        "local": "Local",
    }
    # D'abord, dump tous les inputs visibles pour debug
    try:
        inputs_info = await page.evaluate("""
            () => Array.from(document.querySelectorAll('input')).map(i => ({
                name: i.name, id: i.id, type: i.type,
                placeholder: i.placeholder,
                ariaLabel: i.getAttribute('aria-label'),
                maxLength: i.maxLength,
                visible: i.offsetParent !== null,
            }))
        """)
        log.info("FORM INPUTS: %s", inputs_info)
    except Exception as exc:
        log.warning("Dump inputs failed: %s", exc)

    # Pause initiale "lecture du matricule" — un vrai user prend
    # 1-2s à regarder son matricule avant de commencer.
    await page.wait_for_timeout(_humanish(1_200, 1_800))

    for idx, (key, value) in enumerate(mapping.items()):
        selector = f"input[name='{key}']"
        try:
            loc = page.locator(selector).first
            # Bouge la souris vers le champ avant de cliquer
            # (humain pas téléporté). steps=15 pour un mouvement
            # fluide sur ~300ms.
            box = await loc.bounding_box()
            if box:
                target_x = box["x"] + box["width"] / 2
                target_y = box["y"] + box["height"] / 2
                await page.mouse.move(target_x, target_y, steps=15)
            # Clic + petit délai (réflex humain)
            await loc.click(timeout=2_000)
            await page.wait_for_timeout(_humanish(150, 350))
            await loc.fill("", timeout=1_000)
            # Frappe à ~150ms par caractère (vitesse user moyen
            # qui lit son matricule). delay=180 ± variation
            await loc.type(
                value,
                delay=_humanish(140, 220),
                timeout=5_000,
            )
            await page.wait_for_timeout(_humanish(200, 400))
            await loc.press("Tab")
            actual = await loc.input_value()
            if actual == value:
                log.info("  ✓ %s='%s'", key, value)
            else:
                log.warning(
                    "  ✗ %s='%s' (input_value='%s')",
                    key, value, actual,
                )
            # Pause inter-champs (un user regarde le prochain digit)
            await page.wait_for_timeout(_humanish(300, 600))
        except Exception as exc:
            log.warning("  ✗ %s='%s' (%s)", key, value, exc)


async def _click_rechercher(page: Page) -> None:
    # Dump tous les boutons visibles pour debug
    try:
        buttons_info = await page.evaluate("""
            () => Array.from(document.querySelectorAll('button')).map(b => ({
                text: b.innerText.trim().slice(0, 50),
                type: b.type, disabled: b.disabled,
                ariaLabel: b.getAttribute('aria-label'),
                visible: b.offsetParent !== null,
            })).filter(b => b.visible)
        """)
        log.info("BUTTONS: %s", buttons_info)
    except Exception as exc:
        log.warning("Dump buttons failed: %s", exc)

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
