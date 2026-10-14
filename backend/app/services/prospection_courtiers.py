"""Registre des courtiers — logique métier (Prospection, Phil 2026-10-14).

Plan de match de Phil : « regarder sur Centris toutes les 20 logements et
plus à vendre, aller chercher le contact du courtier, me construire une
liste des courtiers qui vendent des gros parcs, et leur envoyer un
courriel personnalisé : qui on est, ce qu'on achète, peut-être une
rétribution supplémentaire — une façon de se faire remarquer. »

Ce module :
  • ``scan`` : construit / met à jour le registre depuis ce que Kratos
    connaît déjà (annonces Centris reçues par l'extension, fiches
    d'analyse avec un courtier) et, si le VPS de scraping répond, depuis
    la liste Centris « immeuble résidentiel 6+ » (détail des annonces ≥
    seuil pour lire le courtier) ;
  • ``parser_courtier_html`` : lecture best-effort du bloc courtier d'une
    page Centris (nom, agence, téléphone, courriel) ;
  • ``rendre`` : gabarit de courriel avec variables {{prenom}}, {{agence}},
    {{adresse}}… ;
  • ``envoyer_presentation`` : envoi par Microsoft 365 + journal + audit.

Réglages (Paramètres → Prospection → Courtiers) dans
``AutomationSetting("prospection_courtiers")``. Rien ne part sans un clic
humain : aucun cron n'appelle l'envoi.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prospection_courtier import (
    COURTIER_STATUTS,
    ProspectionCourtier,
    ProspectionCourtierAnnonce,
    ProspectionCourtierContact,
)

log = logging.getLogger(__name__)

CONFIG_KEY = "prospection_courtiers"


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite rend des datetimes naïfs pour DateTime(timezone=True) :
    on les considère UTC pour pouvoir les comparer."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

#: Gabarit par défaut du courriel de présentation (modifiable dans
#: Paramètres). Variables : {{prenom}}, {{nom}}, {{agence}}, {{adresse}},
#: {{ville}}, {{nb_logements}}, {{prix}}, {{seuil}}, {{signature}}.
GABARIT_SUJET_DEFAUT = (
    "Acheteur actif pour vos immeubles de {{seuil}} logements et plus"
)
GABARIT_CORPS_DEFAUT = """<p>Bonjour {{prenom}},</p>
<p>Je me présente : Philippe Meuser, d'Horizon Services Immobiliers (MGV Investissements). Nous achetons des immeubles multirésidentiels de {{seuil}} logements et plus dans la grande région de Montréal, en particulier ceux qui ont un potentiel d'optimisation (loyers sous le marché, travaux à faire, gestion à reprendre).</p>
<p>J'ai vu votre inscription au {{adresse}} ({{nb_logements}} logements) et je voulais surtout que vous sachiez que nous sommes des acheteurs sérieux et rapides : financement en place, équipe de construction interne, décisions en quelques jours.</p>
<p>Si vous avez des immeubles de cette taille, en inscription ou hors marché, nous aimerions les voir en premier. Nous sommes ouverts à une rétribution additionnelle pour le courtier qui nous amène un dossier qui se conclut, dans le respect des règles de l'OACIQ.</p>
<p>Au plaisir d'échanger,</p>
<p>{{signature}}</p>"""
SIGNATURE_DEFAUT = (
    "Philippe Meuser<br/>Horizon Services Immobiliers — MGV Investissements"
)

DEFAUTS: dict[str, Any] = {
    "seuil_logements": 20,
    "pages_centris": 5,
    "max_details_par_scan": 40,
    "relance_jours": 14,
    "sujet": GABARIT_SUJET_DEFAUT,
    "corps_html": GABARIT_CORPS_DEFAUT,
    "signature": SIGNATURE_DEFAUT,
    "from_email": "",
    "from_name": "Philippe Meuser — Horizon Services Immobiliers",
    "reply_to": "",
}


async def charger_config() -> dict[str, Any]:
    """Réglages du registre (Paramètres), complétés par les défauts."""
    from app.services.automation_state import get_automation_config

    return fusionner_config(await get_automation_config(CONFIG_KEY))


def fusionner_config(cfg: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Config brute (telle qu'enregistrée) → config complète : les clés
    vides ou absentes prennent la valeur par défaut, les nombres sont
    bornés."""
    out = dict(DEFAUTS)
    for k, v in (cfg or {}).items():
        if v is not None and v != "":
            out[k] = v
    try:
        out["seuil_logements"] = max(1, int(out["seuil_logements"]))
        out["pages_centris"] = max(1, min(10, int(out["pages_centris"])))
        out["max_details_par_scan"] = max(0, int(out["max_details_par_scan"]))
        out["relance_jours"] = max(1, int(out["relance_jours"]))
    except (TypeError, ValueError):
        pass
    return out


# ─── Normalisation / dédoublonnage ───────────────────────────────────


def _sans_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    )


def normaliser_cle(nom: str) -> str:
    """Clé de dédoublonnage d'un courtier : nom sans accents, minuscules,
    ponctuation et titres retirés, espaces simples."""
    s = _sans_accents(nom or "").lower()
    s = re.sub(r"\b(courtier|immobilier|residentiel|commercial|agree|inc\.?|m\.|mme|me)\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_TITRES_FIN_RE = re.compile(
    r"\s*[,\-–]?\s*\b(?:courtiers?(?:\s+immobiliers?)?(?:\s+(?:r[ée]sidentiel(?:\s+et\s+commercial)?"
    r"|commercial|agr[ée]{2}))?|c\.?i\.?(?:r|c)?\.?|inc\.?)\s*$",
    re.IGNORECASE,
)


def nettoyer_nom(nom: str) -> tuple[str, Optional[str]]:
    """Nom tel que lu sur une fiche → (nom affiché, agence déduite).
    « François Courval Courtier » → (« François Courval », None) ;
    « Denis Gallico (Immo Alliances) » → (« Denis Gallico », « Immo Alliances ») ;
    « Rosibel Martinez inc. » → (« Rosibel Martinez », None)."""
    s = re.sub(r"\s+", " ", (nom or "").strip())
    agence: Optional[str] = None
    m = re.match(r"^(.*?)\s*\(([^()]{2,120})\)\s*$", s)
    if m and m.group(1).strip():
        s, agence = m.group(1).strip(), m.group(2).strip()
    for _ in range(3):
        s2 = _TITRES_FIN_RE.sub("", s).strip(" ,-–")
        if s2 == s or len(s2) < 3:
            break
        s = s2
    return (s or (nom or "").strip()), agence


def prenom_de(nom: str) -> str:
    parts = [p for p in re.split(r"\s+", (nom or "").strip()) if p]
    return parts[0].capitalize() if parts else ""


_TEL_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_MAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
_AGENCE_MOTS = (
    "re/max", "remax", "royal lepage", "sutton", "proprio direct",
    "via capitale", "century 21", "keller williams", "engel", "exp ",
    "agence immobili", "immobilier inc", "courtage", "realty", "realties",
    "groupe", "equipe", "équipe",
)


def _courriel_valide(c: Optional[str]) -> Optional[str]:
    if not c:
        return None
    m = _MAIL_RE.search(c)
    if not m:
        return None
    v = m.group(0).strip().lower()
    if v.endswith("@centris.ca") or "noreply" in v or "no-reply" in v:
        return None
    return v


def _telephone_propre(t: Optional[str]) -> Optional[str]:
    if not t:
        return None
    m = _TEL_RE.search(t)
    if not m:
        return None
    chiffres = re.sub(r"\D", "", m.group(0))
    if len(chiffres) == 11 and chiffres.startswith("1"):
        chiffres = chiffres[1:]
    if len(chiffres) != 10:
        return None
    # Plan de numérotation nord-américain : indicatif régional et central
    # commencent par 2-9 (écarte « 055-… », « 329-093-… » lus de travers).
    if chiffres[0] not in "23456789" or chiffres[3] not in "23456789":
        return None
    return f"{chiffres[0:3]}-{chiffres[3:6]}-{chiffres[6:]}"


def separer_contact(contact: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """``courtier_contact`` d'une fiche d'analyse = texte libre (courriel
    et/ou téléphone) → (courriel, téléphone)."""
    return _courriel_valide(contact), _telephone_propre(contact)


def parser_courtier_html(html: str, nom_connu: Optional[str] = None) -> dict:
    """Lecture best-effort du bloc courtier d'une page Centris rendue.
    Retourne {nom, agence, telephone, courriel} (None si absent)."""
    out: dict[str, Optional[str]] = {
        "nom": nom_connu, "agence": None, "telephone": None, "courriel": None,
    }
    if not html:
        return out
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:  # noqa: BLE001
        return out
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001
        return out
    blocs = soup.select(
        '[class*="broker"], [class*="courtier"], [itemtype*="RealEstateAgent"]'
    )
    # Fragments de texte du bloc courtier (un par élément), sinon la page.
    fragments: list[str] = []
    for b in blocs[:6]:
        fragments.extend(s.strip() for s in b.stripped_strings if s.strip())
    if not fragments:
        fragments = [s.strip() for s in soup.stripped_strings if s.strip()][:400]
    texte = " ".join(fragments)[:6000]
    if not out["nom"]:
        el = soup.select_one(
            ".broker-info__name, .broker__name, [data-broker], "
            '[class*="broker"] h1, [class*="broker"] h2, [class*="broker"] h3'
        )
        if el:
            out["nom"] = el.get_text(" ", strip=True)[:255] or None
    # Agence : premier fragment qui contient un mot d'enseigne connue.
    for frag in fragments:
        f_min = frag.lower()
        if any(m in f_min for m in _AGENCE_MOTS) and 3 < len(frag) < 120:
            out["agence"] = frag
            break
    out["telephone"] = _telephone_propre(texte)
    # Courriel : seulement un courriel « humain » (pas Centris).
    for m in _MAIL_RE.finditer(texte):
        c = _courriel_valide(m.group(0))
        if c:
            out["courriel"] = c
            break
    return out


_UNITES_RES = (
    re.compile(r"nombre\s+d['’]unit[ée]s\D{0,60}?(\d{1,4})", re.IGNORECASE),
    re.compile(r"r[ée]sidentiel(?:le)?s?\s*\(\s*(\d{1,4})\s*\)", re.IGNORECASE),
    re.compile(r"(\d{1,4})\s*unit[ée]s\s+r[ée]sidentielles", re.IGNORECASE),
    re.compile(r"(\d{1,4})\s*(?:logements|unit[ée]s)\b", re.IGNORECASE),
)


_PLEX_URL_RE = re.compile(
    r"centris\.ca/(?:fr|en)/(duplex|triplex|quadruplex|quintuplex|maison|condo|"
    r"terrain|chalet|commercial|propriete-commerciale|bureau|local|"
    r"batisse-commerciale|immeuble-commercial|local-commercial|"
    r"terrain-commercial|entreprise|industriel|batisse-industrielle|"
    r"fermette|ferme|stationnement)[~/-]",
    re.IGNORECASE,
)
_PLEX_TAILLES = {"duplex": 2, "triplex": 3, "quadruplex": 4, "quintuplex": 5}


def taille_depuis_url(url: str) -> Optional[int]:
    """Le type Centris est dans l'URL (/fr/quadruplex~a-vendre~…) : taille
    connue sans ouvrir la fiche pour les plex (2 à 5), 0 pour une maison,
    un condo, un terrain ou un commerce (jamais un parc de logements),
    None si inconnu (immeuble-a-revenus…)."""
    m = _PLEX_URL_RE.search(url or "")
    if not m:
        return None
    return _PLEX_TAILLES.get(m.group(1).lower(), 0)


def parser_fiche_html(html: str) -> dict:
    """Lecture best-effort d'une fiche Centris rendue : nombre d'unités,
    adresse, ville. Retourne {nb_units, adresse, ville} (None si absent).
    Les vignettes de la liste « Multifamilial » ne donnent pas la taille :
    c'est ici qu'on l'apprend."""
    out: dict[str, Any] = {"nb_units": None, "adresse": None, "ville": None}
    if not html:
        return out
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001
        return out
    texte = soup.get_text(" ", strip=True)
    for rx in _UNITES_RES:
        m = rx.search(texte)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 2000:
                out["nb_units"] = n
                break
    el = soup.select_one(
        '[itemprop="address"], h2[itemprop="address"], .address, h2.pt-1'
    )
    if el:
        complet = " ".join(el.get_text(" ", strip=True).split())
        if complet:
            out["adresse"] = complet[:500]
            parts = [p.strip() for p in complet.split(",") if p.strip()]
            if len(parts) >= 3:
                out["ville"] = re.sub(r"\s*\(.*\)\s*$", "", parts[2])[:120] or None
            elif len(parts) == 2:
                out["ville"] = re.sub(r"\s*\(.*\)\s*$", "", parts[1])[:120] or None
    return out


# ─── Upserts ─────────────────────────────────────────────────────────


async def upsert_courtier(
    db: AsyncSession,
    *,
    nom: str,
    agence: Optional[str] = None,
    courriel: Optional[str] = None,
    telephone: Optional[str] = None,
    source: str = "manuel",
    vu_le: Optional[datetime] = None,
    secteur: Optional[str] = None,
) -> tuple[Optional[ProspectionCourtier], bool]:
    """Crée ou complète la fiche d'un courtier (clé = nom normalisé). Ne
    remplace jamais une coordonnée déjà saisie par une coordonnée vide.
    Retourne (courtier, créé)."""
    nom_brut = (nom or "").strip()
    nom, agence_deduite = nettoyer_nom(nom_brut)
    agence = agence or agence_deduite
    cle = normaliser_cle(nom)
    cle_brute = normaliser_cle(nom_brut)
    if not cle or len(cle) < 3:
        return None, False
    vu_le = _aware(vu_le) or datetime.now(timezone.utc)
    # Une ligne créée avant le nettoyage des noms porte la clé « brute » :
    # on la retrouve aussi et on la met au propre (pas de doublon).
    candidats = (
        await db.execute(
            select(ProspectionCourtier).where(
                ProspectionCourtier.cle_dedup.in_({cle, cle_brute})
            )
        )
    ).scalars().all()
    existant = next((c for c in candidats if c.cle_dedup == cle), None) or (
        candidats[0] if candidats else None
    )
    courriel = _courriel_valide(courriel)
    telephone = _telephone_propre(telephone)
    if existant is not None:
        if existant.cle_dedup != cle and not any(c.cle_dedup == cle for c in candidats):
            existant.cle_dedup = cle
        nom_existant_propre, agence_existante = nettoyer_nom(existant.nom)
        if nom_existant_propre != existant.nom:
            existant.nom = nom_existant_propre[:255]
            if agence_existante and not existant.agence:
                existant.agence = agence_existante[:255]
        if existant.telephone and _telephone_propre(existant.telephone) is None:
            existant.telephone = None  # numéro impossible lu de travers
        if agence and not existant.agence:
            existant.agence = agence[:255]
        if courriel and not existant.courriel:
            existant.courriel = courriel
        if telephone and not existant.telephone:
            existant.telephone = telephone
        if secteur and not existant.secteur:
            existant.secteur = secteur[:255]
        dernier = _aware(existant.dernier_vu_le)
        if dernier is None or vu_le > dernier:
            existant.dernier_vu_le = vu_le
        premier = _aware(existant.premier_vu_le)
        if premier is None or vu_le < premier:
            existant.premier_vu_le = vu_le
        return existant, False
    c = ProspectionCourtier(
        nom=nom[:255],
        agence=(agence or None) and agence[:255],
        courriel=courriel,
        telephone=telephone,
        secteur=(secteur or None) and secteur[:255],
        source=source if source in ("centris", "extension", "analyse", "manuel") else "manuel",
        statut="a_contacter",
        cle_dedup=cle,
        premier_vu_le=vu_le,
        dernier_vu_le=vu_le,
    )
    db.add(c)
    await db.flush()
    return c, True


async def lier_annonce(
    db: AsyncSession,
    courtier: ProspectionCourtier,
    *,
    source_url: str,
    mls_id: Optional[str] = None,
    adresse: Optional[str] = None,
    ville: Optional[str] = None,
    nb_units: Optional[int] = None,
    prix: Optional[float] = None,
    centris_listing_id: Optional[int] = None,
    lead_analysis_id: Optional[int] = None,
    vue_le: Optional[datetime] = None,
    active: bool = True,
) -> tuple[ProspectionCourtierAnnonce, bool]:
    """Rattache une annonce au courtier (une ligne par URL)."""
    # La clé d'unicité est (courtier, URL) telle que STOCKÉE : on normalise
    # avant de chercher, sinon une URL > 500 car. est insérée tronquée puis
    # jamais retrouvée (doublon → IntegrityError au scan suivant).
    source_url = (source_url or "").strip()[:500]
    if not source_url:
        raise ValueError("source_url vide")
    vue_le = _aware(vue_le) or datetime.now(timezone.utc)
    existante = (
        await db.execute(
            select(ProspectionCourtierAnnonce).where(
                ProspectionCourtierAnnonce.courtier_id == courtier.id,
                ProspectionCourtierAnnonce.source_url == source_url,
            )
        )
    ).scalar_one_or_none()
    if existante is not None:
        if prix:
            existante.prix = prix
        if nb_units:
            existante.nb_units = nb_units
        if adresse and not existante.adresse:
            existante.adresse = adresse[:500]
        existante.vue_le = vue_le
        existante.active = active
        if centris_listing_id and not existante.centris_listing_id:
            existante.centris_listing_id = centris_listing_id
        if lead_analysis_id and not existante.lead_analysis_id:
            existante.lead_analysis_id = lead_analysis_id
        return existante, False
    a = ProspectionCourtierAnnonce(
        courtier_id=courtier.id,
        centris_listing_id=centris_listing_id,
        lead_analysis_id=lead_analysis_id,
        mls_id=(mls_id or None) and str(mls_id)[:16],
        source_url=source_url,
        adresse=(adresse or None) and adresse[:500],
        ville=(ville or None) and ville[:120],
        nb_units=nb_units,
        prix=prix,
        vue_le=vue_le,
        active=active,
    )
    db.add(a)
    await db.flush()
    return a, True


# ─── Scan ────────────────────────────────────────────────────────────


async def scan(
    db: AsyncSession,
    *,
    config: dict[str, Any],
    utiliser_vps: bool = True,
    progres: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Construit / met à jour le registre. Trois sources, dans l'ordre :
    1. annonces Centris déjà en base (extension / imports) avec un nom de
       courtier et ≥ seuil logements ;
    2. fiches d'analyse Kratos qui ont un courtier ;
    3. (si le VPS répond) la liste Centris « immeuble résidentiel 6+ » :
       nouvelles annonces enregistrées, puis détail des annonces ≥ seuil
       sans courtier pour lire son nom / téléphone / courriel.
    Retourne un rapport chiffré ; ne lève pas pour une source en panne."""
    from app.models.centris_listing import CentrisListing
    from app.models.lead_analysis import LeadAnalysis

    seuil = int(config.get("seuil_logements") or 20)
    rapport: dict[str, Any] = {
        "seuil_logements": seuil,
        "courtiers_crees": 0,
        "courtiers_mis_a_jour": 0,
        "annonces_liees": 0,
        "annonces_centris_examinees": 0,
        "analyses_examinees": 0,
        "vps_utilise": False,
        "vps_annonces_lues": 0,
        "vps_sans_taille": 0,
        "vps_details_lus": 0,
        "vps_sous_seuil": 0,
        "vps_sans_courtier": 0,
        "vps_exemples": [],
        "erreurs": [],
    }

    def _dire(msg: str) -> None:
        if progres:
            try:
                progres(msg)
            except Exception:  # noqa: BLE001
                pass

    async def _compter(courtier, cree: bool) -> None:
        if cree:
            rapport["courtiers_crees"] += 1
        else:
            rapport["courtiers_mis_a_jour"] += 1

    # 1. Annonces Centris en base ------------------------------------
    _dire("Annonces Centris déjà connues…")
    annonces = (
        await db.execute(
            select(CentrisListing).where(
                CentrisListing.nb_units >= seuil,
                CentrisListing.broker_name.is_not(None),
            )
        )
    ).scalars().all()
    for L in annonces:
        rapport["annonces_centris_examinees"] += 1
        try:
            # SAVEPOINT : une annonce cassée n'annule pas le scan.
            async with db.begin_nested():
                courtier, cree = await upsert_courtier(
                    db,
                    nom=L.broker_name or "",
                    telephone=L.broker_phone,
                    source="extension",
                    vu_le=L.last_seen_at or L.first_seen_at,
                    secteur=L.city,
                )
                if courtier is None:
                    continue
                await _compter(courtier, cree)
                _, liee = await lier_annonce(
                    db, courtier,
                    source_url=L.source_url, mls_id=L.mls_id, adresse=L.address,
                    ville=L.city, nb_units=L.nb_units,
                    prix=float(L.price) if L.price is not None else None,
                    centris_listing_id=L.id, vue_le=L.last_seen_at or L.first_seen_at,
                    active=L.delisted_at is None,
                )
                rapport["annonces_liees"] += int(liee)
        except Exception as exc:  # noqa: BLE001
            log.warning("scan courtiers : annonce %s ignorée", L.id, exc_info=True)
            rapport["erreurs"].append(
                f"Annonce Centris #{L.id} ignorée : {type(exc).__name__}: {str(exc)[:120]}"
            )

    # 2. Fiches d'analyse avec un courtier ---------------------------
    _dire("Fiches d'analyse avec un courtier…")
    fiches = (
        await db.execute(
            select(LeadAnalysis).where(
                LeadAnalysis.courtier_nom.is_not(None),
                LeadAnalysis.courtier_nom != "",
            )
        )
    ).scalars().all()
    for f in fiches:
        rapport["analyses_examinees"] += 1
        try:
            # SAVEPOINT : une fiche cassée n'annule pas le scan.
            async with db.begin_nested():
                courriel, tel = separer_contact(f.courtier_contact)
                courtier, cree = await upsert_courtier(
                    db, nom=f.courtier_nom or "", courriel=courriel, telephone=tel,
                    source="analyse", vu_le=getattr(f, "created_at", None),
                    secteur=f.city,
                )
                if courtier is None:
                    continue
                await _compter(courtier, cree)
                url = None
                for u in re.split(r"[\s,;]+", f.source_urls or ""):
                    if u.startswith("http"):
                        url = u
                        break
                _, liee = await lier_annonce(
                    db, courtier,
                    source_url=url or f"analyse:{f.id}", adresse=f.address,
                    ville=f.city, nb_units=f.nb_logements,
                    prix=float(f.asking_price) if f.asking_price is not None else None,
                    lead_analysis_id=f.id, vue_le=getattr(f, "created_at", None),
                )
                rapport["annonces_liees"] += int(liee)
        except Exception as exc:  # noqa: BLE001
            log.warning("scan courtiers : fiche %s ignorée", f.id, exc_info=True)
            rapport["erreurs"].append(
                f"Fiche d'analyse #{f.id} ({f.courtier_nom}) ignorée : "
                f"{type(exc).__name__}: {str(exc)[:120]}"
            )

    # Enregistrement progressif : ce qui est fait est fait, même si le
    # serveur redémarre pendant la (longue) lecture des fiches Centris.
    await db.commit()

    # 3. VPS : liste Centris 6+ puis détails ≥ seuil -------------------
    if utiliser_vps:
        try:
            from app.integrations import scraping_proxy
            from app.integrations.centris.scraper import upsert_listings

            if scraping_proxy.vps_available():
                _dire("Centris (VPS) : liste des immeubles résidentiels 6+…")
                reponse = await scraping_proxy.scrape_centris_search_complet(
                    category="immeuble_residentiel_6_plus",
                    max_pages=int(config.get("pages_centris") or 5),
                ) or {}
                listings = list(reponse.get("listings") or [])
                diagnostic = reponse.get("diagnostic") or {}
                rapport["vps_utilise"] = True
                if not listings:
                    rapport["vps_diagnostic"] = diagnostic or None
                    precision = ""
                    if diagnostic.get("captcha"):
                        precision = " Le VPS a vu une page de vérification anti-robot (captcha)."
                    elif diagnostic.get("title"):
                        precision = f" Titre de la page vue : « {diagnostic['title']} »."
                    rapport["erreurs"].append(
                        "Centris (VPS) : le VPS a répondu mais n'a lu aucune annonce "
                        "sur la liste « immeuble résidentiel 6+ » — Centris bloque "
                        "probablement le robot ou la page a changé." + precision
                        + " Le registre se nourrit alors des annonces reçues par "
                        "l'extension et des fiches d'analyse."
                    )
                if listings:
                    rapport["vps_annonces_lues"] = len(listings)
                    # Taille connue par l'URL (plex 2-5, maison, condo…) :
                    # enregistrée tout de suite, la fiche ne sera jamais ouverte.
                    for L in listings:
                        if not L.get("nb_units"):
                            t_url = taille_depuis_url(L.get("source_url") or "")
                            if t_url:
                                L["nb_units"] = int(t_url)
                    try:
                        # SAVEPOINT : une annonce impossible à enregistrer
                        # n'empêche pas la lecture des fiches.
                        async with db.begin_nested():
                            await upsert_listings(
                                db, listings, "immeuble_residentiel_6_plus"
                            )
                    except Exception as exc:  # noqa: BLE001
                        log.warning("scan courtiers : upsert Centris en échec", exc_info=True)
                        rapport["erreurs"].append(
                            "Centris (VPS) : annonces lues mais non enregistrées dans "
                            f"centris_listings ({type(exc).__name__}: {str(exc)[:120]})."
                        )
                    # Détail des annonces ≥ seuil OU de taille inconnue (les
                    # vignettes « Multifamilial » ne donnent pas le nombre
                    # d'unités) — sauf celles déjà lues (courtier connu ou
                    # taille connue sous le seuil).
                    rapport["vps_sans_taille"] = sum(
                        1 for L in listings if not L.get("nb_units")
                    )
                    rapport["vps_exemples"] = [
                        {
                            "url": L.get("source_url"),
                            "nb_units": L.get("nb_units"),
                            "prix": L.get("price"),
                        }
                        for L in listings[:3]
                    ]
                    candidats = []
                    for L in listings:
                        if not L.get("source_url"):
                            continue
                        taille = L.get("nb_units") or taille_depuis_url(L["source_url"])
                        if taille is not None and int(taille) < seuil:
                            # Plex / maison / condo : taille connue par l'URL,
                            # pas la peine d'ouvrir la fiche (~35 s chacune).
                            rapport["vps_sous_seuil"] += 1
                            if not L.get("nb_units") and taille:
                                L["nb_units"] = int(taille)
                            continue
                        candidats.append(L)
                    maxd = int(config.get("max_details_par_scan") or 40)
                    ouverts = 0
                    for L in candidats:
                        if ouverts >= maxd:
                            break
                        url = L["source_url"]
                        row = (
                            await db.execute(
                                select(CentrisListing).where(
                                    CentrisListing.source_url == url
                                )
                            )
                        ).scalar_one_or_none()
                        if row is not None and (
                            row.broker_name
                            or (row.nb_units is not None and row.nb_units < seuil)
                        ):
                            continue
                        ouverts += 1
                        _dire(f"Centris (VPS) : fiche {ouverts}/{min(maxd, len(candidats))} — {url}")
                        try:
                            detail = await scraping_proxy.scrape_centris_detail(
                                url, timeout_s=90.0
                            )
                        except Exception as exc:  # noqa: BLE001
                            rapport["erreurs"].append(f"détail {url} : {exc}")
                            continue
                        if not detail:
                            continue
                        rapport["vps_details_lus"] += 1
                        html_fiche = detail.get("html") or ""
                        info = parser_courtier_html(html_fiche, detail.get("broker_name"))
                        fiche = parser_fiche_html(html_fiche)
                        nb_units = (
                            detail.get("nb_units") or fiche.get("nb_units")
                            or L.get("nb_units") or (row.nb_units if row is not None else None)
                        )
                        adresse = detail.get("address") or fiche.get("adresse") or L.get("address")
                        ville = detail.get("city") or fiche.get("ville") or L.get("city")
                        try:
                            async with db.begin_nested():
                                if row is not None:
                                    if info.get("nom") and not row.broker_name:
                                        row.broker_name = info["nom"][:255]
                                    if info.get("telephone") and not row.broker_phone:
                                        row.broker_phone = info["telephone"]
                                    if nb_units and not row.nb_units:
                                        row.nb_units = int(nb_units)
                                    if adresse and not row.address:
                                        row.address = str(adresse)[:500]
                                    if ville and not row.city:
                                        row.city = str(ville)[:120]
                                if not info.get("nom"):
                                    rapport["vps_sans_courtier"] += 1
                                    continue
                                if not nb_units or int(nb_units) < seuil:
                                    rapport["vps_sous_seuil"] += 1
                                    continue
                                courtier, cree = await upsert_courtier(
                                    db, nom=info["nom"], agence=info.get("agence"),
                                    courriel=info.get("courriel"),
                                    telephone=info.get("telephone"), source="centris",
                                    secteur=(ville or (row.city if row is not None else None)),
                                )
                                if courtier is None:
                                    continue
                                await _compter(courtier, cree)
                                _, liee = await lier_annonce(
                                    db, courtier, source_url=url, mls_id=L.get("mls_id"),
                                    adresse=adresse, ville=ville, nb_units=int(nb_units),
                                    prix=L.get("price") or detail.get("price"),
                                    centris_listing_id=(row.id if row is not None else None),
                                )
                                rapport["annonces_liees"] += int(liee)
                        except Exception as exc:  # noqa: BLE001
                            rapport["erreurs"].append(
                                f"Centris {url} : {type(exc).__name__}: {str(exc)[:120]}"
                            )
                        await db.commit()  # fiche par fiche : rien n'est perdu
            else:
                rapport["erreurs"].append(
                    "VPS de scraping non configuré : Centris non lu (les annonces "
                    "arrivent par l'extension et les fiches d'analyse)."
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("scan courtiers : Centris VPS en échec", exc_info=True)
            rapport["erreurs"].append(f"Centris (VPS) : {exc}")

    await db.flush()
    return rapport


# ─── Gabarit et envoi ────────────────────────────────────────────────


_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")


def rendre(gabarit: str, ctx: dict[str, Any]) -> str:
    """Remplace {{variable}} par sa valeur (vide si inconnue)."""
    def _sub(m: re.Match) -> str:
        v = ctx.get(m.group(1))
        return "" if v is None else str(v)
    return _VAR_RE.sub(_sub, gabarit or "")


def _fmt_prix(p: Optional[float]) -> str:
    if p is None:
        return ""
    try:
        return f"{int(round(float(p))):,}".replace(",", " ") + " $"
    except (TypeError, ValueError):
        return ""


def contexte_courtier(
    courtier: ProspectionCourtier,
    annonce: Optional[ProspectionCourtierAnnonce],
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "prenom": prenom_de(courtier.nom),
        "nom": courtier.nom,
        "agence": courtier.agence or "",
        "adresse": (annonce.adresse if annonce and annonce.adresse else "votre immeuble"),
        "ville": (annonce.ville if annonce and annonce.ville else ""),
        "nb_logements": (annonce.nb_units if annonce and annonce.nb_units else ""),
        "prix": _fmt_prix(float(annonce.prix)) if annonce and annonce.prix is not None else "",
        "seuil": config.get("seuil_logements", 20),
        "signature": config.get("signature") or SIGNATURE_DEFAUT,
    }


async def meilleure_annonce(
    db: AsyncSession, courtier: ProspectionCourtier
) -> Optional[ProspectionCourtierAnnonce]:
    """L'annonce à citer dans le courriel : active la plus grosse, sinon
    la plus récente."""
    rows = (
        await db.execute(
            select(ProspectionCourtierAnnonce).where(
                ProspectionCourtierAnnonce.courtier_id == courtier.id
            )
        )
    ).scalars().all()
    if not rows:
        return None
    actives = [a for a in rows if a.active] or list(rows)
    actives.sort(
        key=lambda a: (
            (a.nb_units or 0),
            _aware(a.vue_le) or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    return actives[0]


async def envoyer_presentation(
    db: AsyncSession,
    *,
    user,
    courtier: ProspectionCourtier,
    sujet: str,
    corps_html: str,
    config: dict[str, Any],
    annonce: Optional[ProspectionCourtierAnnonce] = None,
) -> dict[str, Any]:
    """Envoie le courriel de présentation à UN courtier (Microsoft 365),
    journalise le contact, passe le statut à « contacté » et pose la date
    de relance. Retourne {ok, erreur}. N'appelle pas commit."""
    from app.integrations.email_graph import get_mailer
    from app.services.audit import log_action

    if not courtier.courriel:
        return {"ok": False, "erreur": "Aucun courriel sur la fiche du courtier."}
    mailer = get_mailer()
    if not mailer.ready:
        return {"ok": False, "erreur": "Mailer Microsoft 365 non configuré."}
    ctx = contexte_courtier(courtier, annonce, config)
    sujet_r = rendre(sujet, ctx)
    corps_r = rendre(corps_html, ctx)
    from_email = (config.get("from_email") or "").strip() or None
    from_name = (config.get("from_name") or "").strip() or None
    reply_to = (config.get("reply_to") or "").strip() or None
    try:
        await mailer.send(
            to=[courtier.courriel],
            subject=sujet_r,
            html_body=corps_r,
            from_email=from_email,
            from_name=from_name,
            reply_to=reply_to or from_email,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("envoi courtier %s échoué", courtier.id, exc_info=True)
        return {"ok": False, "erreur": f"{type(exc).__name__}: {str(exc)[:200]}"}
    maintenant = datetime.now(timezone.utc)
    db.add(
        ProspectionCourtierContact(
            courtier_id=courtier.id,
            annonce_id=annonce.id if annonce else None,
            date=maintenant,
            canal="courriel",
            direction="sortant",
            sujet=sujet_r[:255],
            contenu=corps_r,
            auteur_email=getattr(user, "email", None),
        )
    )
    if courtier.statut == "a_contacter":
        courtier.statut = "contacte"
    courtier.dernier_contact_le = maintenant
    courtier.prochaine_relance_le = (
        maintenant + timedelta(days=int(config.get("relance_jours") or 14))
    ).date()
    await log_action(
        db, user=user, action="prospection.courtier.courriel_envoye",
        entity_type="prospection_courtier", entity_id=courtier.id,
        details={"to": courtier.courriel, "sujet": sujet_r},
    )
    await db.flush()
    return {"ok": True, "erreur": None}


EXEMPLE_COURTIER = SimpleNamespace(
    nom="Jean Tremblay", agence="RE/MAX Exemple", courriel=None,
)
EXEMPLE_ANNONCE = SimpleNamespace(
    adresse="1234, rue de l'Exemple", ville="Montréal", nb_units=24,
    prix=4_950_000, id=None,
)


async def envoyer_test(
    *, vers: str, sujet: str, corps_html: str, config: dict[str, Any]
) -> dict[str, Any]:
    """Envoie le gabarit rendu avec un courtier d'EXEMPLE à l'adresse
    donnée (pour se relire). Aucune fiche touchée, aucun journal."""
    from app.integrations.email_graph import get_mailer

    vers = _courriel_valide(vers) or ""
    if not vers:
        return {"ok": False, "erreur": "Adresse de test invalide."}
    mailer = get_mailer()
    if not mailer.ready:
        return {"ok": False, "erreur": "Mailer Microsoft 365 non configuré."}
    ctx = contexte_courtier(EXEMPLE_COURTIER, EXEMPLE_ANNONCE, config)  # type: ignore[arg-type]
    from_email = (config.get("from_email") or "").strip() or None
    try:
        await mailer.send(
            to=[vers],
            subject="[TEST] " + rendre(sujet, ctx),
            html_body=rendre(corps_html, ctx),
            from_email=from_email,
            from_name=(config.get("from_name") or "").strip() or None,
            reply_to=(config.get("reply_to") or "").strip() or from_email,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erreur": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {"ok": True, "erreur": None}


def statut_valide(s: Optional[str]) -> bool:
    return s in COURTIER_STATUTS


__all__ = [
    "CONFIG_KEY",
    "DEFAUTS",
    "charger_config",
    "fusionner_config",
    "normaliser_cle",
    "nettoyer_nom",
    "prenom_de",
    "separer_contact",
    "parser_courtier_html",
    "parser_fiche_html",
    "taille_depuis_url",
    "upsert_courtier",
    "lier_annonce",
    "scan",
    "rendre",
    "contexte_courtier",
    "meilleure_annonce",
    "envoyer_presentation",
    "envoyer_test",
    "statut_valide",
]
