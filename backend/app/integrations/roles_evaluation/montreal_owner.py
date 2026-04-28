"""Scraper EvalWeb — rôle d'évaluation Ville de Montréal.

Le CSV bulk de la Ville n'inclut pas les propriétaires (vie privée
au niveau du dataset agrégé). Mais l'app web EvalWeb les affiche
publiquement par propriété. On scrape à la demande pour enrichir
un lead Prospection avec les vrais propriétaires (souvent des
personnes physiques que REQ ne couvre pas).

Stratégie :
- Ouvre une session httpx, GET la page de recherche (récupère
  viewState JSF), POST le matricule, parse la page de résultat.
- Cache le résultat dans `MontrealPropertyUnit.owners_json`
  (TTL effectif = jamais re-scrappé sauf force_refresh).
- Best-effort : si la page change de structure ou le site rejette,
  on retourne un message clair pour que l'utilisateur fasse le
  lookup manuel via le bouton externe.

⚠ La structure HTML d'EvalWeb peut évoluer. Les sélecteurs et URLs
ci-dessous sont basés sur la version Avril 2026. Si le scraping
échoue, vérifier dans `EVALWEB_SEARCH_URL` et `_parse_owners()`.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

EVALWEB_BASE = "https://servicesenligne2.ville.montreal.qc.ca/sel/evalweb"
EVALWEB_SEARCH_URL = f"{EVALWEB_BASE}/index"

# ⚠ Le legacy EvalWeb (servicesenligne2) est officiellement
# déprécié — la Ville le redirige vers une page d'erreur 404 maintenant.
# On le garde comme fallback ultime au cas où ça revienne, mais
# le scraper compte essentiellement sur le nouveau portail montreal.ca.

# Nouveau portail montreal.ca (mis en place 2024-2025). Direct deep
# link par matricule, sans JSF — beaucoup plus fiable que le legacy.
NEW_PORTAL_URL = (
    "https://montreal.ca/role-evaluation-fonciere/recherche"
)
NEW_PORTAL_DETAIL = (
    "https://montreal.ca/role-evaluation-fonciere/{matricule}"
)
# Lien grand public à montrer dans l'UI quand le scraper auto échoue.
NEW_PORTAL_PUBLIC = "https://montreal.ca/role-evaluation-fonciere"

# UA navigateur — certains WAF de la Ville bloquent les UA Python.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Timeout réseau : on veut fail-fast pour éviter de tenir le proxy
# Render trop longtemps (limite 100s, plus le user attend, plus le
# UX se dégrade). 5s par requête, max 4-5 essais → ~20s total.
TIMEOUT = httpx.Timeout(5.0, connect=3.0)


class EvalWebOwner(dict):
    """Dict-like {name, statut, postal_address, inscription_date,
    conditions}. Hérite de dict pour serialization JSON triviale."""


class EvalWebError(Exception):
    """Échec de scraping. Le message est destiné à l'utilisateur."""


async def scrape_owners(matricule: str) -> List[dict]:
    """Récupère les propriétaires d'une unité d'évaluation par
    matricule (ex: « 0135-23-0549-2-000-0000 »).

    Stratégie multi-niveaux (du plus moderne au plus legacy) :
    1. Nouveau portail montreal.ca (deep link direct par matricule)
    2. Legacy EvalWeb JSF (viewState + POST)
    3. Si tout échoue → EvalWebError avec message clair

    Lève `EvalWebError` si rien ne marche.
    """
    matricule_clean = matricule.strip()
    if not _is_valid_matricule(matricule_clean):
        raise EvalWebError(
            f"Format de matricule invalide : {matricule_clean!r}"
        )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
    }

    # Tentative #1 : nouveau portail montreal.ca avec deep link
    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=TIMEOUT,
            follow_redirects=True,
        ) as client:
            owners = await _try_new_portal(client, matricule_clean)
            if owners:
                return owners
    except Exception as exc:
        log.debug("New portal failed: %s", exc)

    # Tentative #2 : legacy EvalWeb JSF
    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=TIMEOUT,
            follow_redirects=True,
            cookies=httpx.Cookies(),
        ) as client:
            owners = await _try_legacy_jsf(client, matricule_clean)
            if owners:
                return owners
    except Exception as exc:
        log.debug("Legacy JSF failed: %s", exc)

    # Tout a échoué — le portail montreal.ca a un flow stateful 4
    # étapes avec CSRF tokens probablement, qu'on ne peut pas
    # reproduire fiablement sans navigateur headless (Playwright).
    # Le user passe au paste manuel — 30s + auto-enrichissement
    # REQ + Canada411 = aussi efficace en pratique.
    raise EvalWebError(
        "Le scraper auto n'arrive pas à passer le flow stateful du "
        "portail montreal.ca. Utilise « Saisir manuellement → » : "
        "ouvre EvalWeb, fais la recherche par matricule, copie la "
        "section Propriétaire et colle ici. Le système enrichit "
        "ensuite automatiquement avec REQ + Canada411."
    )


async def _try_new_portal(
    client: httpx.AsyncClient, matricule: str
) -> Optional[List[dict]]:
    """Tente le portail moderne montreal.ca/role-evaluation-fonciere.

    Le portail nécessite un flow stateful en 3 étapes :
    1. GET /role-evaluation-fonciere → page choix (4 options)
    2. POST option=matricule + Suivant → page form 6 champs
    3. POST des 6 sous-champs (Division/Secteur/Emplacement/Cav/
       Bâtiment/Local) + Rechercher → page résultat

    Sans Playwright, on tente plusieurs patterns POST courants. Si
    rien ne marche, on lève vers le fallback paste manuel.
    """
    matricule_no_dash = matricule.replace("-", "")
    parts = _decompose_matricule(matricule)

    # Variante #1 : deep links éventuels (au cas où). On limite à
    # 4 candidats pour rester rapide (5s × 4 = 20s max).
    deep_link_candidates = [
        f"{NEW_PORTAL_PUBLIC}/matricule/liste/resultat?matricule={matricule}",
        NEW_PORTAL_DETAIL.format(matricule=matricule),
        f"{NEW_PORTAL_URL}?matricule={matricule}",
        f"{NEW_PORTAL_PUBLIC}?matricule={matricule}",
    ]
    for url in deep_link_candidates:
        try:
            r = await client.get(url)
            if r.status_code != 200 or len(r.text) < 1000:
                continue
            if "Propriétaire" not in r.text:
                continue
            owners = _parse_owners(r.text)
            if owners:
                log.info(
                    "EvalWeb : succès deep link (%s, %d owners)",
                    url,
                    len(owners),
                )
                return owners
        except httpx.HTTPError:
            continue

    # Variante #2 : flow multi-step complet (4 étapes en réalité)
    if not parts:
        return None
    try:
        # Étape 1 : GET la page d'accueil pour cookies de session
        await client.get(NEW_PORTAL_PUBLIC)
        # Étape 2 : POST option=matricule (page choix → page form)
        for option_name in ("optionRecherche", "option", "type"):
            await client.post(
                NEW_PORTAL_PUBLIC,
                data={option_name: "matricule"},
            )
        # Étape 3 : POST des 6 sous-champs (form Recherche → liste)
        form_data = {
            "division": parts["division"],
            "secteur": parts["secteur"],
            "emplacement": parts["emplacement"],
            "cav": parts["cav"],
            "batiment": parts["batiment"],
            "local": parts["local"],
            "Division": parts["division"],
            "Secteur": parts["secteur"],
            "Emplacement": parts["emplacement"],
            "Cav": parts["cav"],
            "Batiment": parts["batiment"],
            "Local": parts["local"],
            "matricule": matricule,
            "rechercher": "Rechercher",
        }
        list_response_text: Optional[str] = None
        for endpoint in (
            f"{NEW_PORTAL_PUBLIC}/matricule/liste",
            f"{NEW_PORTAL_PUBLIC}/recherche/matricule",
            f"{NEW_PORTAL_PUBLIC}/recherche",
            NEW_PORTAL_PUBLIC,
        ):
            try:
                r2 = await client.post(endpoint, data=form_data)
                if r2.status_code != 200 or len(r2.text) < 1000:
                    continue
                # Si on tombe direct sur une page Propriétaire, c'est
                # gagné (cas où le portail saute la liste pour 1 seul
                # résultat).
                if "Propriétaire" in r2.text:
                    owners = _parse_owners(r2.text)
                    if owners:
                        log.info(
                            "EvalWeb : succès direct étape 3 (%s, %d owners)",
                            endpoint,
                            len(owners),
                        )
                        return owners
                # Sinon, c'est probablement la page « Liste des
                # matricules » → on doit cliquer sur le matricule
                # qui matche pour aller au Résultat détaillé.
                if (
                    "Liste des matricules" in r2.text
                    or "Sélectionnez un numéro" in r2.text
                ):
                    list_response_text = r2.text
                    break
            except httpx.HTTPError:
                continue

        # Étape 4 : si on a la liste, trouve le lien du matricule
        # qui correspond et le suit pour le Résultat détaillé.
        if list_response_text:
            soup = BeautifulSoup(list_response_text, "html.parser")
            target = matricule  # clé de match
            target_clean = target.replace("-", "")
            chosen_url: Optional[str] = None
            # On cherche tous les <a> qui contiennent ce matricule
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                text = a.get_text(" ", strip=True)
                blob = f"{href} {text}"
                if (
                    target in blob
                    or target_clean in blob.replace("-", "")
                ):
                    chosen_url = (
                        href
                        if href.startswith("http")
                        else f"https://montreal.ca{href}"
                    )
                    break
            if chosen_url:
                try:
                    r3 = await client.get(chosen_url)
                    if r3.status_code == 200 and "Propriétaire" in r3.text:
                        owners = _parse_owners(r3.text)
                        if owners:
                            log.info(
                                "EvalWeb : succès étape 4 — Résultat détaillé "
                                "(%s, %d owners)",
                                chosen_url,
                                len(owners),
                            )
                            return owners
                except httpx.HTTPError:
                    pass
    except httpx.HTTPError:
        pass

    return None


def _decompose_matricule(matricule: str) -> Optional[dict]:
    """Décompose un matricule type « 0135-23-0549-2-000-0000 » en
    ses 6 composantes Division/Secteur/Emplacement/Cav/Bâtiment/Local.
    Format obligatoire imposé par le portail montreal.ca."""
    parts = matricule.split("-")
    if len(parts) != 6:
        return None
    division, secteur, emplacement, cav, batiment, local = parts
    if not (
        len(division) == 4
        and len(secteur) == 2
        and len(emplacement) == 4
        and len(cav) == 1
        and len(batiment) == 3
        and len(local) == 4
    ):
        return None
    return {
        "division": division,
        "secteur": secteur,
        "emplacement": emplacement,
        "cav": cav,
        "batiment": batiment,
        "local": local,
    }


async def _try_legacy_jsf(
    client: httpx.AsyncClient, matricule: str
) -> Optional[List[dict]]:
    """Legacy : JSF avec viewState. Plus fragile, gardé en fallback."""
    try:
        resp = await client.get(EVALWEB_SEARCH_URL)
        resp.raise_for_status()
        view_state = _extract_view_state(resp.text)
        if not view_state:
            return None
        search_data = {
            "javax.faces.ViewState": view_state,
            "form:matricule": matricule,
            "form:rechercher": "Rechercher",
        }
        resp = await client.post(
            EVALWEB_SEARCH_URL, data=search_data
        )
        resp.raise_for_status()
        owners = _parse_owners(resp.text)
        if owners:
            log.info(
                "EvalWeb : succès via legacy JSF (%d owners)",
                len(owners),
            )
            return owners
    except httpx.HTTPError:
        pass
    return None


_MATRICULE_RE = re.compile(r"^\d{4}-\d{2}-\d{4}-\d-\d{3}-\d{4}$")


def _is_valid_matricule(s: str) -> bool:
    """Le matricule MATRICULE83 a un format précis : 0135-23-0549-2-000-0000."""
    return bool(_MATRICULE_RE.match(s))


def _extract_view_state(html: str) -> Optional[str]:
    """JSF embarque le viewState dans un input caché. On le grep
    directement plutôt que parser tout le DOM (plus robuste si la
    page est partielle)."""
    m = re.search(
        r'name=["\']javax\.faces\.ViewState["\'][^>]*value=["\']([^"\']+)',
        html,
    )
    if m:
        return m.group(1)
    # Variation : value vient avant name.
    m = re.search(
        r'value=["\']([^"\']+)["\'][^>]*name=["\']javax\.faces\.ViewState["\']',
        html,
    )
    return m.group(1) if m else None


# Labels qu'on cherche dans le HTML, dans l'ordre où ils apparaissent
# pour chaque propriétaire. La page EvalWeb les affiche comme
# « <label>: <value> » ou en table HTML.
_OWNER_LABELS = (
    ("name", ("Nom",)),
    (
        "statut",
        ("Statut aux fins d'imposition scolaire", "Statut"),
    ),
    ("postal_address", ("Adresse postale",)),
    (
        "inscription_date",
        ("Date d'inscription au rôle", "Date d'inscription"),
    ),
    (
        "conditions",
        (
            "Conditions particulières d'inscription",
            "Conditions particulières",
        ),
    ),
)


def parse_owners_from_text(text: str) -> List[dict]:
    """Extrait la liste des propriétaires depuis un texte plat
    contenant la section « Propriétaire » d'EvalWeb.

    Sert pour le fallback « collage manuel » : l'utilisateur copie
    la section depuis le site de la Ville et la colle dans le modal.
    Tolère les espaces multiples, tabulations, retours de ligne
    variés.
    """
    return _parse_owners_text(text)


def _parse_owners_text(section_text: str) -> List[dict]:
    """Parse la section propriétaire depuis du texte brut.

    Approche : on tokenize en lignes label/value alternant. Un label
    suivi d'une ligne devient une paire. Les blocs qui commencent
    par « Nom » ouvrent un nouveau propriétaire.
    """
    # On coupe au prochain gros titre (« Caractéristiques »,
    # « Évaluation »…) pour ne pas inclure la suite.
    for stop in (
        "Caractéristiques",
        "Évaluation",
        "Valeurs au rôle",
        "Imposition",
        "Identification",
    ):
        cut = section_text.find(stop)
        if cut > 0:
            section_text = section_text[:cut]

    lines = [
        line.strip().rstrip(":").strip()
        for line in section_text.split("\n")
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


def _parse_owners(html: str) -> List[dict]:
    """Extrait la section « Propriétaire » d'une page HTML EvalWeb.

    Convertit en texte plat via BeautifulSoup puis délègue au parser
    de texte. Cherche d'abord la section « Propriétaire » dans la
    page, sinon utilise toute la page (best-effort).
    """
    soup = BeautifulSoup(html, "html.parser")

    # On limite à la section qui contient le mot « Propriétaire ».
    # Si on ne le trouve pas, on tombe sur la page complète.
    section_text = soup.get_text("\n", strip=True)
    idx = section_text.lower().find("propriétaire")
    if idx > 0:
        section_text = section_text[idx:]

    return _parse_owners_text(section_text)
