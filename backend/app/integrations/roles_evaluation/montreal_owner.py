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

# UA navigateur — certains WAF de la Ville bloquent les UA Python.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Timeout réseau : EvalWeb est parfois lent (legacy JSF).
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class EvalWebOwner(dict):
    """Dict-like {name, statut, postal_address, inscription_date,
    conditions}. Hérite de dict pour serialization JSON triviale."""


class EvalWebError(Exception):
    """Échec de scraping. Le message est destiné à l'utilisateur."""


async def scrape_owners(matricule: str) -> List[dict]:
    """Récupère les propriétaires d'une unité d'évaluation par
    matricule (ex: « 0135-23-0549-2-000-0000 »).

    Retourne une liste de dicts (peut être vide si pas de
    propriétaire trouvé — rare). Lève `EvalWebError` si le scraping
    échoue (site down, format changé, captcha, etc.).
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
    }

    async with httpx.AsyncClient(
        headers=headers,
        timeout=TIMEOUT,
        follow_redirects=True,
        # Garde les cookies de session JSF.
        cookies=httpx.Cookies(),
    ) as client:
        try:
            # Étape 1 : GET la page de recherche pour récupérer le
            # viewState JSF (jeton CSRF).
            resp = await client.get(EVALWEB_SEARCH_URL)
            resp.raise_for_status()
            view_state = _extract_view_state(resp.text)
            if not view_state:
                raise EvalWebError(
                    "Page EvalWeb chargée mais viewState introuvable "
                    "(structure HTML modifiée ?)."
                )

            # Étape 2 : POST le matricule. La forme exacte des champs
            # dépend de la version JSF — on tente le pattern le plus
            # courant. Si EvalWeb passe à une nouvelle structure,
            # ajuster ici.
            search_data = {
                "javax.faces.ViewState": view_state,
                "form:matricule": matricule_clean,
                "form:rechercher": "Rechercher",
            }
            resp = await client.post(
                EVALWEB_SEARCH_URL, data=search_data
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise EvalWebError(
                f"Erreur réseau EvalWeb : {exc}"
            ) from exc

        owners = _parse_owners(resp.text)
        if not owners:
            # Soit le matricule n'existe pas, soit la structure HTML
            # a changé. On laisse l'utilisateur faire le lookup manuel.
            raise EvalWebError(
                "Aucun propriétaire trouvé. Le matricule peut être "
                "invalide, ou la structure de la page EvalWeb a changé. "
                "Lookup manuel : "
                f"{EVALWEB_SEARCH_URL}?matricule={matricule_clean}"
            )

        return owners


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


def _parse_owners(html: str) -> List[dict]:
    """Extrait la section « Propriétaire » de la page EvalWeb.

    Approche : on cherche tous les blocs commençant par un label
    « Nom » et on récupère les champs suivants jusqu'au prochain
    « Nom » (séparateur de propriétaire). Robuste aux variations
    de mise en page (table vs div) parce qu'on travaille sur le
    texte plat de la section.
    """
    soup = BeautifulSoup(html, "html.parser")

    # On limite la recherche à la section qui contient le mot
    # « Propriétaire » (sous-titre H2/H3 typique sur EvalWeb).
    # Si on ne le trouve pas, on tombe sur la page complète (best-effort).
    section_text = soup.get_text("\n", strip=True)
    idx = section_text.lower().find("propriétaire")
    if idx > 0:
        section_text = section_text[idx:]
    # On coupe au prochain gros titre (« Caractéristiques »,
    # « Évaluation », « Imposition ») pour ne pas inclure la suite.
    for stop in (
        "Caractéristiques",
        "Évaluation",
        "Valeurs au rôle",
        "Imposition",
    ):
        cut = section_text.find(stop)
        if cut > 0:
            section_text = section_text[:cut]

    # Liste des labels qu'on reconnaît (à plat).
    all_labels: List[str] = []
    for _key, syns in _OWNER_LABELS:
        all_labels.extend(syns)

    # Tokenize en lignes label/value alternant. Un label suivi d'une
    # ligne devient une paire.
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
        # Détection d'un label (insensible à la casse).
        match_key: Optional[str] = None
        for key, syns in _OWNER_LABELS:
            if any(line.lower() == s.lower() for s in syns):
                match_key = key
                break
        if match_key:
            # La valeur est sur la ligne suivante.
            val = lines[i + 1] if i + 1 < len(lines) else ""
            # Si match_key == "name" et qu'on avait déjà un nom, on
            # ferme l'owner précédent.
            if match_key == "name" and "name" in current:
                owners.append(current)
                current = {}
            current[match_key] = val
            i += 2
        else:
            i += 1

    if current.get("name"):
        owners.append(current)

    # Nettoyage final : on garde uniquement les owners avec un nom.
    return [o for o in owners if o.get("name")]
