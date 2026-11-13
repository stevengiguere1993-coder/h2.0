"""Tableau des dossiers suivis en rencontres (2026-11-13).

Steven : « j'aimerais avoir un tableau de vue d'ensemble des différents
dossiers en cours que nous discutons lors des rencontres » — choix « tout
automatique », avec une IA qui liste et élimine les doublons.

Fonctionnement :

1. **Analyse d'une rencontre** (``analyser_rencontre``) : l'IA reçoit la
   rencontre (résumés, décisions, actions, extrait du transcript), la
   liste des dossiers EXISTANTS et les consignes du dirigeant ; elle
   rend les dossiers touchés, rattachés à un dossier connu (``dossier_id``)
   avant d'en créer un nouveau. Chaque dossier touché reçoit une MENTION
   (l'historique). Réanalyser une rencontre remplace ses mentions. Une
   rencontre est « à analyser » tant que l'empreinte de son contenu
   (``Rencontre.dossiers_empreinte``) ne correspond pas. Sans IA ou IA
   en panne : rien n'est écrit, la rencontre reste à analyser.
2. **État d'un dossier** (``recalculer``) : statut, dernier état,
   prochaine action et dernière discussion viennent de sa mention la
   plus récente. Une modification à la main tient jusqu'à ce qu'une
   rencontre plus récente reparle du dossier ; un titre, un responsable
   ou une entreprise saisis à la main ne sont jamais réécrits.
3. **Doublons** (``verifier_doublons``) : même titre (mots distinctifs)
   → fusion d'office ; puis l'IA compare tous les dossiers : « certain »
   ET au moins un mot distinctif commun → fusion d'office, sinon paire
   PROPOSÉE. Une fusion est douce (``fusionne_dans_id``) et se défait
   (``defusionner``) ; une paire « gardée séparée » n'est plus jamais
   proposée ni fusionnée.

Les gardes d'accès (page « entreprises.rencontres ») sont faites par les
routes (``endpoints/rencontre_dossiers.py``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select

from app.integrations.ai import complete, is_configured
from app.models.entreprise import Entreprise
from app.models.rencontre import Rencontre, RencontreSection
from app.models.rencontre_dossier import (
    STATUTS_DOSSIER,
    DossierStatut,
    RencontreDossier,
    RencontreDossierDoublon,
    RencontreDossierMention,
)
from app.services.rencontre_ai import _parse_ai_json
from app.services.rencontre_consignes import bloc_consignes
from app.services.rencontre_recherche import mots_cles, normaliser

log = logging.getLogger(__name__)

#: Un dossier ouvert dont on n'a pas reparlé depuis ce nombre de jours
#: est signalé « oublié ».
JOURS_OUBLI = 21
#: Dossiers existants montrés à l'IA au maximum.
MAX_DOSSIERS_IA = 150
#: Taille du contenu d'une rencontre envoyé à l'IA (caractères).
MAX_CONTENU_IA = 26_000
#: Rencontres analysées par passe (un appel à l'IA chacune).
LOT_ANALYSE = 3
#: Passes au plus dans une course de fond (300 rencontres).
MAX_PASSES_FOND = 100
#: Après ce nombre de rencontres ratées dans une passe, l'IA est tenue
#: pour en panne : inutile d'insister.
MAX_RATEES_PAR_PASSE = 2

LIBELLES_STATUT = {
    "en_cours": "En cours",
    "en_attente": "En attente",
    "bloque": "Bloqué",
    "regle": "Réglé",
}

#: Une seule analyse / passe de doublons à la fois par processus.
_verrou = asyncio.Lock()
_taches_fond: set[asyncio.Task] = set()
#: Bilan de la dernière course de fond, pour l'écran (par processus).
_etat_fond: dict = {
    "analysees": 0,
    "restantes": None,
    "echecs": 0,
    "ia_absente": False,
    "termine_le": None,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aujourdhui() -> date:
    """Jour de Montréal."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Toronto")).date()
    except Exception:  # noqa: BLE001
        return _now().date()


def _txt(v: Any, maxi: Optional[int] = None) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("null", "none", "n/a", "aucun", "aucune"):
        return None
    return s[:maxi] if maxi else s


def _liste_json(brut: Optional[str]) -> list:
    if not brut:
        return []
    try:
        v = json.loads(brut)
    except Exception:  # noqa: BLE001
        return []
    return v if isinstance(v, list) else []


def _liste_txt(v: Any, maxi: int = 12) -> list[str]:
    if not isinstance(v, list):
        return []
    out = [t for t in (_txt(x, 500) for x in v) if t]
    return out[:maxi]


#: Ce que l'IA écrit pour un dossier dont la rencontre n'a PAS parlé
#: (« n'a pas été abordé », « non discuté », « aucune mention »…), sur un
#: texte passé par ``normaliser``. « Pas discuté AVEC le banquier » est un
#: vrai état de dossier, pas une remarque sur la rencontre.
_RE_NON_ABORDE = re.compile(
    r"\bpas (?:encore |vraiment |du tout )?ete "
    r"(?:re)?(?:abordee?s?|discutee?s?|mentionnee?s?|evoquee?s?)\b(?! avec\b)"
    r"|\bpas (?:encore )?ete question\b"
    r"|\bnon (?:abordee?s?|discutee?s?|mentionnee?s?|evoquee?s?)\b"
    r"|\baucune (?:mention|discussion)\b"
    r"|\bpas (?:fait l objet|de mention)\b"
)
_RE_PHRASES = re.compile(r"(?<=[.!?…])\s+")
_RE_OPPOSITION = re.compile(
    r"\s*[,;]?\s+(?:mais|cependant|toutefois|par contre|en revanche)\s+",
    re.IGNORECASE,
)


def _non_aborde(texte: str) -> bool:
    return bool(_RE_NON_ABORDE.search(normaliser(texte)))


def sans_non_aborde(texte: Optional[str]) -> Optional[str]:
    """Retire d'un texte de l'IA ce qui dit seulement qu'un point « n'a
    pas été abordé » : une rencontre qui ne parle pas d'un dossier ne
    change pas son état. D'une phrase mixte (« Les portes arrivent
    mercredi, mais les électros n'ont pas été abordés. ») reste la partie
    qui dit quelque chose. ``None`` s'il ne reste rien."""
    if not texte:
        return None
    gardees: list[str] = []
    for phrase in _RE_PHRASES.split(texte.strip()):
        if not phrase:
            continue
        if not _non_aborde(phrase):
            gardees.append(phrase)
            continue
        bouts = [
            b.strip(" ,;.") for b in _RE_OPPOSITION.split(phrase) if b.strip(" ,;.")
        ]
        if len(bouts) < 2:
            continue
        reste = [b for b in bouts if not _non_aborde(b)]
        if reste:
            morceau = ", ".join(reste)
            gardees.append(morceau[0].upper() + morceau[1:] + ".")
    return " ".join(gardees) or None


# ── Titres : clé de comparaison ─────────────────────────────────────


def cle_titre(titre: str) -> frozenset[str]:
    """Mots distinctifs d'un titre (accents, pluriels et mots vides
    près) — deux titres de même clé désignent le même dossier."""
    return frozenset(mots_cles(titre or "", maximum=12))


def alias_de(d: RencontreDossier) -> list[str]:
    return [a for a in _liste_json(d.alias_json) if isinstance(a, str) and a]


def _ajoute_alias(d: RencontreDossier, *noms: Optional[str]) -> None:
    actuels = alias_de(d)
    vus = {normaliser(a) for a in actuels} | {normaliser(d.titre or "")}
    for n in noms:
        n = _txt(n, 255)
        if n and normaliser(n) not in vus:
            actuels.append(n)
            vus.add(normaliser(n))
    d.alias_json = json.dumps(actuels[:30], ensure_ascii=False) if actuels else None


def _cles(d: RencontreDossier) -> list[frozenset[str]]:
    """Clés du titre et des alias (non vides)."""
    out = [cle_titre(d.titre)]
    out += [cle_titre(a) for a in alias_de(d)]
    return [c for c in out if c]


def _mots(d: RencontreDossier) -> set[str]:
    """Tous les mots distinctifs du dossier (titre, alias, contexte)."""
    m: set[str] = set()
    for c in _cles(d):
        m |= c
    m |= cle_titre(d.contexte or "")
    return m


def _entreprises_compatibles(a: RencontreDossier, b: RencontreDossier) -> bool:
    return (
        a.entreprise_id is None
        or b.entreprise_id is None
        or a.entreprise_id == b.entreprise_id
    )


def _manuels(d: RencontreDossier) -> set[str]:
    return {x for x in _liste_json(d.champs_manuels_json) if isinstance(x, str)}


def _paire(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


# ── Lecture ─────────────────────────────────────────────────────────


async def dossiers_actifs(db) -> list[RencontreDossier]:
    """Dossiers non fusionnés dans un autre."""
    rows = (
        await db.execute(
            select(RencontreDossier)
            .where(RencontreDossier.fusionne_dans_id.is_(None))
            .order_by(RencontreDossier.id.asc())
        )
    ).scalars().all()
    return list(rows)


async def racine(db, d: RencontreDossier) -> RencontreDossier:
    """Le dossier vivant au bout de la chaîne de fusions."""
    vus = {d.id}
    while d.fusionne_dans_id is not None:
        suivant = await db.get(RencontreDossier, d.fusionne_dans_id)
        if suivant is None or suivant.id in vus:
            break
        vus.add(suivant.id)
        d = suivant
    return d


def _date_rencontre(r: Rencontre) -> date:
    if r.meeting_date:
        return r.meeting_date
    if r.created_at:
        return r.created_at.date()
    return _aujourdhui()


async def _mentions_avec_rencontre(
    db, dossier_id: int
) -> list[tuple[RencontreDossierMention, Rencontre]]:
    rows = (
        await db.execute(
            select(RencontreDossierMention, Rencontre)
            .join(Rencontre, Rencontre.id == RencontreDossierMention.rencontre_id)
            .where(RencontreDossierMention.dossier_id == dossier_id)
        )
    ).all()
    paires = [(m, r) for m, r in rows]
    paires.sort(key=lambda p: (_date_rencontre(p[1]), p[1].id, p[0].id))
    return paires


# ── État d'un dossier ───────────────────────────────────────────────


async def recalculer(db, d: RencontreDossier) -> None:
    """Remet l'état du dossier d'après ses mentions (la plus récente
    fait foi), sans toucher à ce qui a été saisi à la main."""
    paires = await _mentions_avec_rencontre(db, d.id)
    if not paires:
        d.derniere_discussion = None
        return
    derniere, r_dern = paires[-1]
    jour = _date_rencontre(r_dern)
    d.derniere_discussion = jour
    manuels = _manuels(d)
    if "responsable" not in manuels:
        for m, _r in reversed(paires):
            if m.responsable:
                d.responsable = m.responsable
                break
    # Une modification manuelle de l'état tient tant qu'aucune rencontre
    # plus récente ne reparle du dossier.
    if d.etat_manuel_le is not None and jour <= d.etat_manuel_le.date():
        return
    d.etat_manuel_le = None
    if derniere.statut in STATUTS_DOSSIER:
        d.statut = derniere.statut
    d.dernier_etat = derniere.etat or derniere.resume or d.dernier_etat
    if d.statut == DossierStatut.REGLE.value:
        d.prochaine_action = derniere.prochaine_action
        d.echeance = derniere.echeance
        d.echeance_date = derniere.echeance_date
        return
    for m, _r in reversed(paires):
        if m.prochaine_action:
            d.prochaine_action = m.prochaine_action
            d.echeance = m.echeance
            d.echeance_date = m.echeance_date
            break
    else:
        d.prochaine_action = None
        d.echeance = None
        d.echeance_date = None


# ── Analyse d'une rencontre ─────────────────────────────────────────


def _resume_section(s: RencontreSection) -> dict:
    if not s.ai_summary_json:
        return {}
    try:
        v = json.loads(s.ai_summary_json)
    except Exception:  # noqa: BLE001
        return {}
    return v if isinstance(v, dict) else {}


def contenu_pour_ia(r: Rencontre, sections: list[RencontreSection]) -> str:
    """Texte de la rencontre donné à l'IA : résumés structurés d'abord
    (fiables), transcript ensuite dans la place qui reste."""
    blocs: list[str] = []
    if (r.global_summary or "").strip():
        blocs.append("### Résumé global\n" + r.global_summary.strip()[:8000])
    if (r.notes or "").strip():
        blocs.append("### Notes\n" + r.notes.strip()[:2000])
    sections = sorted(sections, key=lambda x: (x.position, x.id))
    for s in sections:
        res = _resume_section(s)
        lignes: list[str] = []
        if _txt(res.get("summary")):
            lignes.append("Résumé : " + _txt(res.get("summary")))
        for cle, lib in (
            ("decisions", "Décisions"),
            ("open_questions", "Questions en suspens"),
            ("risks", "Risques"),
        ):
            items = _liste_txt(res.get(cle), 30)
            if items:
                lignes.append(f"{lib} : " + " ; ".join(items))
        actions = []
        for a in res.get("action_items") or []:
            if isinstance(a, dict) and _txt(a.get("title")):
                bout = _txt(a.get("title"))
                if _txt(a.get("owner")):
                    bout += f" (responsable : {_txt(a.get('owner'))})"
                if _txt(a.get("due")):
                    bout += f" (échéance : {_txt(a.get('due'))})"
                actions.append(bout)
        if actions:
            lignes.append("Actions : " + " ; ".join(actions))
        if lignes:
            blocs.append(f"### Section « {s.title} »\n" + "\n".join(lignes))
    texte = "\n\n".join(blocs)
    reste = MAX_CONTENU_IA - len(texte)
    transcripts = [
        (s.title, (s.transcript or "").strip()) for s in sections
    ]
    transcripts = [(t, x) for t, x in transcripts if x]
    if transcripts and reste > 1500:
        part = max(1000, reste // len(transcripts))
        for titre, x in transcripts:
            texte += f"\n\n### Transcript « {titre} »\n" + x[:part]
    return texte.strip()


def empreinte(r: Rencontre, sections: list[RencontreSection]) -> str:
    """Empreinte du contenu utile à l'analyse des dossiers."""
    h = hashlib.sha256()
    for bout in (
        r.title or "",
        r.meeting_date.isoformat() if r.meeting_date else "",
        r.global_summary or "",
        r.notes or "",
        r.entreprise_ids_json or "",
    ):
        h.update(bout.encode("utf-8"))
        h.update(b"\x00")
    for s in sorted(sections, key=lambda x: (x.position, x.id)):
        for bout in (s.title or "", s.transcript or "", s.ai_summary_json or ""):
            h.update(bout.encode("utf-8"))
            h.update(b"\x00")
    return h.hexdigest()


PROMPT_DOSSIERS = """Tu tiens le TABLEAU DES DOSSIERS d'un dirigeant qui \
gère plusieurs entreprises (construction, immobilier locatif, \
développement). Un DOSSIER est un sujet qui se suit d'une rencontre à \
l'autre jusqu'à ce qu'il soit réglé : un achat (« Camion »), un problème \
(« Factures Amazon non classées »), un chantier ou un immeuble \
(« Électros Adam »), une démarche (« Rencontre ingénieur 1660 \
Saint-Clément »), une embauche, un financement.

On te donne UNE rencontre et la liste des dossiers DÉJÀ suivis. Rends \
SEULEMENT les dossiers dont cette rencontre a réellement parlé.

## Règles
- La liste des dossiers déjà suivis sert UNIQUEMENT à rattacher. Un \
dossier existant dont cette rencontre ne dit rien n'est PAS rendu : ne \
le rends jamais pour écrire « non abordé », « pas discuté » ou « rien de \
nouveau ». Dans `resume` et `etat`, écris ce qui a été DIT, jamais ce \
qui n'a pas été abordé.
- RATTACHE D'ABORD : si le sujet correspond à un dossier existant (même \
chose dite autrement, autre orthographe, nom approximatif), mets son \
`dossier_id`. Ne crée un nouveau dossier (`dossier_id`: null) que si \
aucun existant ne convient. Jamais deux entrées pour le même sujet.
- Un dossier a une suite : n'en crée PAS pour une simple information, \
l'horaire de la semaine, une anecdote ou une tâche ponctuelle sans \
lendemain. Regroupe les petites tâches sous le dossier qu'elles servent.
- `titre` : 2 à 6 mots, stable dans le temps, sans date ni verbe \
(« Camion », pas « Recherche du camion mercredi »). Pour un dossier \
existant, redonne son titre tel quel.
- `statut` : "en_cours" (on y travaille), "en_attente" (on attend \
quelqu'un d'autre ou une date), "bloque" (rien n'avance, problème), \
"regle" (terminé, décidé pour de bon).
- `resume` : ce que CETTE rencontre a dit du dossier (2 à 4 phrases). \
`etat` : où en est le dossier APRÈS cette rencontre (1 à 2 phrases).
- `prochaine_action` : la prochaine chose à faire, avec qui la fait. \
`echeance` : telle que dite ; `echeance_date` : AAAA-MM-JJ seulement si \
elle se déduit sûrement de la date de la rencontre, sinon null.
- `entreprise` : nom EXACT pris dans la liste fournie, sinon null. \
`contexte` : l'immeuble ou le projet visé, sinon null.
- N'invente rien. Les transcripts sont bruités (dictée) : reconstitue \
le sens, garde « [à vérifier] » quand le texte le porte.
- Respecte les consignes du dirigeant quand il y en a.

## Sortie : JSON STRICT, rien d'autre
{"dossiers": [{"dossier_id": 12, "titre": "…", "entreprise": null, \
"contexte": null, "responsable": "…", "statut": "en_cours", \
"resume": "…", "etat": "…", "prochaine_action": "…", "echeance": null, \
"echeance_date": null, "decisions": ["…"], \
"actions": [{"title": "…", "owner": "…", "due": null}], \
"questions": ["…"]}]}
Aucun dossier dans la rencontre : {"dossiers": []}."""


def _ligne_dossier(d: RencontreDossier, noms_ent: dict[int, str]) -> str:
    bouts = [f"#{d.id} — {d.titre}"]
    al = alias_de(d)
    if al:
        bouts.append("aussi appelé : " + ", ".join(al[:4]))
    if d.entreprise_id and noms_ent.get(d.entreprise_id):
        bouts.append("entreprise : " + noms_ent[d.entreprise_id])
    if d.contexte:
        bouts.append("contexte : " + d.contexte)
    bouts.append("statut : " + d.statut)
    if d.dernier_etat:
        bouts.append("état : " + " ".join(d.dernier_etat.split())[:160])
    return "- " + " · ".join(bouts)


def _statut(v: Any) -> str:
    s = normaliser(_txt(v) or "").replace(" ", "_")
    if s in STATUTS_DOSSIER:
        return s
    if s.startswith("regl") or s in ("termine", "ferme", "fait", "clos"):
        return "regle"
    if s.startswith("bloq"):
        return "bloque"
    if "attente" in s:
        return "en_attente"
    return "en_cours"


def _date_iso(v: Any) -> Optional[date]:
    s = _txt(v)
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:  # noqa: BLE001
        return None


def _entreprise_id(
    nom: Optional[str], entreprises: list[Entreprise]
) -> Optional[int]:
    if not nom:
        return None
    n = normaliser(nom).strip()
    if not n:
        return None
    for e in entreprises:
        if normaliser(e.name or "").strip() == n:
            return e.id
    cle = cle_titre(nom)
    if cle:
        trouves = [e for e in entreprises if cle_titre(e.name or "") == cle]
        if len(trouves) == 1:
            return trouves[0].id
    return None


def _ids_entreprises(r: Rencontre) -> list[int]:
    out = []
    for x in _liste_json(r.entreprise_ids_json):
        try:
            out.append(int(x))
        except Exception:  # noqa: BLE001
            continue
    return out


def trouver_local(
    titre: str, entreprise_id: Optional[int], actifs: list[RencontreDossier]
) -> Optional[RencontreDossier]:
    """Dossier existant de même titre (ou alias), entreprise compatible."""
    cle = cle_titre(titre)
    if not cle:
        return None
    for d in actifs:
        if cle in _cles(d) and (
            entreprise_id is None
            or d.entreprise_id is None
            or d.entreprise_id == entreprise_id
        ):
            return d
    return None


async def _retirer_mentions(db, rencontre_id: int) -> set[int]:
    """Supprime les mentions d'une rencontre ; rend les dossiers touchés."""
    anciens = (
        await db.execute(
            select(RencontreDossierMention.dossier_id).where(
                RencontreDossierMention.rencontre_id == rencontre_id
            )
        )
    ).scalars().all()
    if anciens:
        await db.execute(
            delete(RencontreDossierMention).where(
                RencontreDossierMention.rencontre_id == rencontre_id
            )
        )
    return set(anciens)


async def supprimer(db, d: RencontreDossier) -> None:
    """Supprime un dossier avec ses mentions et ses paires de doublons
    (explicite : ne dépend pas des cascades de la base)."""
    await db.execute(
        delete(RencontreDossierMention).where(
            RencontreDossierMention.dossier_id == d.id
        )
    )
    await db.execute(
        delete(RencontreDossierDoublon).where(
            (RencontreDossierDoublon.dossier_a_id == d.id)
            | (RencontreDossierDoublon.dossier_b_id == d.id)
        )
    )
    await db.delete(d)
    await db.flush()


async def _nettoyer_orphelins(db, ids: set[int]) -> int:
    """Supprime les dossiers détectés par l'IA qui n'ont plus aucune
    mention, jamais retouchés à la main et dans lesquels rien n'a été
    fusionné."""
    retires = 0
    for did in ids:
        d = await db.get(RencontreDossier, did)
        if d is None or d.source != "ia" or d.fusionne_dans_id is not None:
            continue
        if _manuels(d) or d.etat_manuel_le is not None:
            continue
        nb = (
            await db.execute(
                select(func.count(RencontreDossierMention.id)).where(
                    RencontreDossierMention.dossier_id == did
                )
            )
        ).scalar_one()
        if nb:
            continue
        absorbes = (
            await db.execute(
                select(func.count(RencontreDossier.id)).where(
                    RencontreDossier.fusionne_dans_id == did
                )
            )
        ).scalar_one()
        if absorbes:
            continue
        await supprimer(db, d)
        retires += 1
    return retires


async def appliquer_analyse(
    db,
    r: Rencontre,
    items: list,
    *,
    entreprises: Optional[list[Entreprise]] = None,
) -> dict:
    """Écrit le résultat de l'IA pour UNE rencontre : remplace ses
    mentions, rattache ou crée les dossiers, recalcule leur état."""
    if entreprises is None:
        entreprises = list((await db.execute(select(Entreprise))).scalars().all())
    touches = await _retirer_mentions(db, r.id)
    actifs = await dossiers_actifs(db)
    par_id = {d.id: d for d in actifs}
    ents_r = _ids_entreprises(r)
    ent_defaut = ents_r[0] if len(ents_r) == 1 else None
    crees = 0
    non_abordes = 0
    mentions: dict[int, RencontreDossierMention] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        titre = _txt(item.get("titre"), 255)
        if not titre:
            continue
        resume_brut = _txt(item.get("resume"), 4000)
        etat_brut = _txt(item.get("etat"), 2000)
        resume = sans_non_aborde(resume_brut)
        etat = sans_non_aborde(etat_brut)
        if (resume_brut or etat_brut) and not (resume or etat):
            # L'IA a rendu un dossier pour dire que la rencontre n'en a
            # pas parlé : pas de mention, son état ne bouge pas.
            non_abordes += 1
            continue
        ent_id = _entreprise_id(_txt(item.get("entreprise")), entreprises)
        d: Optional[RencontreDossier] = None
        brut_id = item.get("dossier_id")
        try:
            did = int(brut_id) if brut_id is not None else None
        except Exception:  # noqa: BLE001
            did = None
        if did is not None:
            d = par_id.get(did)
            if d is None:
                # Dossier fusionné entre-temps : suit la fusion.
                ancien = await db.get(RencontreDossier, did)
                if ancien is not None:
                    d = par_id.get((await racine(db, ancien)).id)
        if d is None:
            d = trouver_local(titre, ent_id or ent_defaut, actifs)
        if d is None:
            d = RencontreDossier(
                titre=titre,
                statut=_statut(item.get("statut")),
                entreprise_id=ent_id or ent_defaut,
                contexte=_txt(item.get("contexte"), 255),
                source="ia",
            )
            db.add(d)
            await db.flush()
            actifs.append(d)
            par_id[d.id] = d
            crees += 1
        else:
            _ajoute_alias(d, titre)
            manuels = _manuels(d)
            if d.entreprise_id is None and "entreprise_id" not in manuels:
                d.entreprise_id = ent_id or ent_defaut
            if not d.contexte and "contexte" not in manuels:
                d.contexte = _txt(item.get("contexte"), 255)

        actions = []
        for a in item.get("actions") or []:
            if isinstance(a, dict) and _txt(a.get("title")):
                actions.append(
                    {
                        "title": _txt(a.get("title"), 255),
                        "owner": _txt(a.get("owner"), 120),
                        "due": _txt(a.get("due"), 120),
                    }
                )
        decisions = _liste_txt(item.get("decisions"))
        questions = _liste_txt(item.get("questions"))
        m = mentions.get(d.id)
        if m is None:
            m = RencontreDossierMention(
                dossier_id=d.id,
                rencontre_id=r.id,
                resume=resume,
                etat=etat,
                statut=_statut(item.get("statut")),
                responsable=_txt(item.get("responsable"), 255),
                prochaine_action=_txt(item.get("prochaine_action"), 2000),
                echeance=_txt(item.get("echeance"), 255),
                echeance_date=_date_iso(item.get("echeance_date")),
                decisions_json=json.dumps(decisions, ensure_ascii=False),
                actions_json=json.dumps(actions[:20], ensure_ascii=False),
                questions_json=json.dumps(questions, ensure_ascii=False),
            )
            db.add(m)
            mentions[d.id] = m
        else:
            # L'IA a rendu deux entrées pour le même dossier : on les joint.
            m.resume = " ".join(x for x in (m.resume, resume) if x)[:4000] or None
            m.etat = etat or m.etat
            m.statut = _statut(item.get("statut"))
            m.responsable = m.responsable or _txt(item.get("responsable"), 255)
            m.prochaine_action = (
                _txt(item.get("prochaine_action"), 2000) or m.prochaine_action
            )
            m.echeance = _txt(item.get("echeance"), 255) or m.echeance
            m.echeance_date = _date_iso(item.get("echeance_date")) or m.echeance_date
            m.decisions_json = json.dumps(
                (_liste_json(m.decisions_json) + decisions)[:12], ensure_ascii=False
            )
            m.actions_json = json.dumps(
                (_liste_json(m.actions_json) + actions)[:20], ensure_ascii=False
            )
            m.questions_json = json.dumps(
                (_liste_json(m.questions_json) + questions)[:12], ensure_ascii=False
            )
        touches.add(d.id)

    await db.flush()
    for did in touches:
        d = await db.get(RencontreDossier, did)
        if d is not None:
            await recalculer(db, d)
    await db.flush()
    retires = await _nettoyer_orphelins(db, touches - set(mentions))
    return {
        "dossiers_touches": len(mentions),
        "dossiers_crees": crees,
        "dossiers_retires": retires,
        "non_abordes": non_abordes,
    }


async def analyser_rencontre(
    db,
    r: Rencontre,
    sections: Optional[list[RencontreSection]] = None,
    *,
    forcer: bool = False,
) -> dict:
    """Met le tableau des dossiers à jour pour UNE rencontre."""
    if sections is None:
        sections = list(
            (
                await db.execute(
                    select(RencontreSection).where(
                        RencontreSection.rencontre_id == r.id
                    )
                )
            ).scalars().all()
        )
    emp = empreinte(r, sections)
    if not forcer and r.dossiers_empreinte == emp:
        return {"rencontre_id": r.id, "statut": "a_jour"}
    contenu = contenu_pour_ia(r, sections)
    if not contenu:
        touches = await _retirer_mentions(db, r.id)
        for did in touches:
            d = await db.get(RencontreDossier, did)
            if d is not None:
                await recalculer(db, d)
        await _nettoyer_orphelins(db, touches)
        r.dossiers_empreinte = emp
        await db.flush()
        return {"rencontre_id": r.id, "statut": "vide"}
    if not is_configured():
        return {"rencontre_id": r.id, "statut": "ia_absente"}

    entreprises = list((await db.execute(select(Entreprise))).scalars().all())
    noms_ent = {e.id: e.name for e in entreprises}
    actifs = await dossiers_actifs(db)
    actifs_tries = sorted(
        actifs,
        key=lambda d: (d.derniere_discussion or date.min, d.id),
        reverse=True,
    )[:MAX_DOSSIERS_IA]
    ents_r = [noms_ent[i] for i in _ids_entreprises(r) if noms_ent.get(i)]
    prompt = (
        await bloc_consignes(db, "dossiers")
        + "## Entreprises du dirigeant\n"
        + (", ".join(sorted(n for n in noms_ent.values() if n)) or "(aucune)")
        + "\n\n## Dossiers déjà suivis\n"
        + (
            "\n".join(_ligne_dossier(d, noms_ent) for d in actifs_tries)
            or "(aucun pour l'instant)"
        )
        + "\n\n## Rencontre à analyser\n"
        + f"Titre : {r.title}\n"
        + f"Date : {_date_rencontre(r).isoformat()}\n"
        + (f"Participants : {r.attendees}\n" if r.attendees else "")
        + (f"Entreprises visées : {', '.join(ents_r)}\n" if ents_r else "")
        + "\n"
        + contenu
        + "\n\nRends le JSON."
    )
    try:
        res = await complete(
            prompt=prompt,
            system=PROMPT_DOSSIERS,
            max_tokens=6000,
            temperature=0.1,
            thinking_budget=0,
        )
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        log.warning("dossiers: IA en échec pour la rencontre %s (%s)", r.id, exc)
        return {"rencontre_id": r.id, "statut": "ia_erreur", "erreur": str(exc)[:200]}
    data = _parse_ai_json(res.text or "")
    if not isinstance(data, dict) or not isinstance(data.get("dossiers"), list):
        log.warning("dossiers: réponse IA illisible pour la rencontre %s", r.id)
        return {"rencontre_id": r.id, "statut": "ia_illisible"}
    stats = await appliquer_analyse(
        db, r, data["dossiers"], entreprises=entreprises
    )
    r.dossiers_empreinte = emp
    await db.flush()
    return {"rencontre_id": r.id, "statut": "analysee", **stats}


async def rencontres_a_analyser(
    db, *, forcer: bool = False
) -> list[tuple[Rencontre, list[RencontreSection]]]:
    """Rencontres dont le contenu a changé depuis leur analyse (ou
    toutes avec ``forcer``), de la plus ANCIENNE à la plus récente :
    l'état d'un dossier se construit dans l'ordre du temps."""
    # ``populate_existing`` : une course de fond garde sa session d'une
    # passe à l'autre ; sans lui, elle ne verrait pas une rencontre
    # modifiée ou remise « à analyser » entre-temps par une autre session.
    frais = {"populate_existing": True}
    rencontres = list(
        (await db.execute(select(Rencontre).execution_options(**frais)))
        .scalars()
        .all()
    )
    if not rencontres:
        return []
    sections = (
        (await db.execute(select(RencontreSection).execution_options(**frais)))
        .scalars()
        .all()
    )
    par_r: dict[int, list[RencontreSection]] = {}
    for s in sections:
        par_r.setdefault(s.rencontre_id, []).append(s)
    out = []
    for r in rencontres:
        secs = par_r.get(r.id, [])
        if forcer or r.dossiers_empreinte != empreinte(r, secs):
            out.append((r, secs))
    out.sort(key=lambda p: (_date_rencontre(p[0]), p[0].id))
    return out


async def marquer_a_reanalyser(db, rencontre_ids: Optional[list[int]] = None) -> int:
    """Remet des rencontres (toutes par défaut) « à analyser » : leur
    empreinte est effacée, la prochaine passe refait leurs dossiers —
    sert après une nouvelle consigne."""
    q = select(Rencontre)
    if rencontre_ids:
        q = q.where(Rencontre.id.in_(rencontre_ids))
    rows = (await db.execute(q)).scalars().all()
    for r in rows:
        r.dossiers_empreinte = None
    await db.flush()
    return len(rows)


async def analyser_en_attente(
    db,
    *,
    limite: int = LOT_ANALYSE,
    ignorer: Optional[set[int]] = None,
) -> dict:
    """Analyse les rencontres en attente (au plus ``limite`` appels à
    l'IA réussis), de la plus ancienne à la plus récente, puis passe les
    doublons quand il n'en reste plus à faire.

    Une rencontre que l'IA n'arrive pas à lire ne bloque pas les
    suivantes : elle reste « à analyser » et, quand ``ignorer`` est
    fourni (course de fond), n'est pas retentée dans la même course.
    ``restantes`` compte tout ce qui reste à lire, ``a_faire`` ce qui
    reste hors des rencontres ignorées."""
    async with _verrou:
        resultats = []
        faites = 0
        ratees = 0
        ia_absente = False
        for r, secs in await rencontres_a_analyser(db):
            if ignorer and r.id in ignorer:
                continue
            if faites >= limite:
                break
            res = await analyser_rencontre(db, r, secs)
            resultats.append(res)
            if res["statut"] == "ia_absente":
                ia_absente = True
                break
            if res["statut"] in ("analysee", "vide"):
                await db.commit()
            if res["statut"] == "analysee":
                faites += 1
            elif res["statut"] in ("ia_erreur", "ia_illisible"):
                ratees += 1
                if ignorer is not None:
                    ignorer.add(r.id)
                if ratees >= MAX_RATEES_PAR_PASSE:
                    break
        en_attente = await rencontres_a_analyser(db)
        restantes = len(en_attente)
        a_faire = len(
            [p for p in en_attente if not (ignorer and p[0].id in ignorer)]
        )
        echecs = [
            x for x in resultats if x["statut"] in ("ia_erreur", "ia_illisible")
        ]
        doublons: dict = {}
        if faites and (a_faire == 0 or echecs):
            doublons = await _verifier_doublons(db, avec_ia=True)
            await db.commit()
        return {
            "analysees": faites,
            "restantes": restantes,
            "a_faire": a_faire,
            "ia_absente": ia_absente,
            "echecs": echecs,
            "doublons": doublons,
        }


# ── Fusions ─────────────────────────────────────────────────────────


async def _nb_mentions(db, dossier_id: int) -> int:
    return (
        await db.execute(
            select(func.count(RencontreDossierMention.id)).where(
                RencontreDossierMention.dossier_id == dossier_id
            )
        )
    ).scalar_one()


async def choisir_gagnant(
    db, dossiers: list[RencontreDossier]
) -> RencontreDossier:
    """Le dossier gardé d'un groupe de doublons : celui retouché à la
    main, puis celui qui a le plus d'historique, puis le plus ancien."""
    notes = []
    for d in dossiers:
        manuel = 1 if (d.source == "manuel" or _manuels(d)) else 0
        notes.append((manuel, await _nb_mentions(db, d.id), -d.id, d))
    notes.sort(key=lambda t: t[:3], reverse=True)
    return notes[0][3]


async def _marquer_paire(
    db, a: int, b: int, statut: str, raison: Optional[str] = None
) -> RencontreDossierDoublon:
    pa, pb = _paire(a, b)
    row = (
        await db.execute(
            select(RencontreDossierDoublon).where(
                RencontreDossierDoublon.dossier_a_id == pa,
                RencontreDossierDoublon.dossier_b_id == pb,
            )
        )
    ).scalars().first()
    if row is None:
        row = RencontreDossierDoublon(dossier_a_id=pa, dossier_b_id=pb)
        db.add(row)
    row.statut = statut
    if raison:
        row.raison = raison[:1000]
    if statut != "propose":
        row.decide_le = _now()
    await db.flush()
    return row


async def fusionner(
    db,
    perdant: RencontreDossier,
    gagnant: RencontreDossier,
    *,
    auto: bool = False,
    raison: Optional[str] = None,
) -> RencontreDossier:
    """Fusion douce de ``perdant`` dans ``gagnant`` : l'historique
    s'additionne, le perdant est gardé (masqué) pour pouvoir défaire."""
    gagnant = await racine(db, gagnant)
    if perdant.id == gagnant.id:
        return gagnant
    mentions = (
        await db.execute(
            select(RencontreDossierMention).where(
                RencontreDossierMention.dossier_id == perdant.id
            )
        )
    ).scalars().all()
    for m in mentions:
        if m.dossier_origine_id is None:
            m.dossier_origine_id = perdant.id
        m.dossier_id = gagnant.id
    _ajoute_alias(gagnant, perdant.titre, *alias_de(perdant))
    if gagnant.entreprise_id is None:
        gagnant.entreprise_id = perdant.entreprise_id
    if not gagnant.contexte:
        gagnant.contexte = perdant.contexte
    if not gagnant.responsable:
        gagnant.responsable = perdant.responsable
    perdant.fusionne_dans_id = gagnant.id
    perdant.fusionne_le = _now()
    perdant.fusion_auto = auto
    perdant.fusion_raison = (raison or "")[:1000] or None
    await db.flush()
    await _marquer_paire(db, perdant.id, gagnant.id, "fusionne", raison)
    await recalculer(db, gagnant)
    await db.flush()
    return gagnant


async def _absorbes(db, d: RencontreDossier) -> list[RencontreDossier]:
    """Dossiers fusionnés dans ``d``, directement ou en chaîne."""
    out: list[RencontreDossier] = []
    file = [d.id]
    vus = {d.id}
    while file:
        courant = file.pop()
        enfants = (
            await db.execute(
                select(RencontreDossier).where(
                    RencontreDossier.fusionne_dans_id == courant
                )
            )
        ).scalars().all()
        for e in enfants:
            if e.id not in vus:
                vus.add(e.id)
                out.append(e)
                file.append(e.id)
    return out


async def defusionner(db, perdant: RencontreDossier) -> RencontreDossier:
    """Défait la fusion de ``perdant`` : il reprend son historique (et
    celui des dossiers fusionnés en lui) et la paire est notée « gardés
    séparés » pour ne plus être refusionnée d'office."""
    if perdant.fusionne_dans_id is None:
        return perdant
    parent = await db.get(RencontreDossier, perdant.fusionne_dans_id)
    vivant = await racine(db, perdant)
    origines = {perdant.id} | {e.id for e in await _absorbes(db, perdant)}
    mentions = (
        await db.execute(
            select(RencontreDossierMention).where(
                RencontreDossierMention.dossier_origine_id.in_(origines)
            )
        )
    ).scalars().all()
    for m in mentions:
        m.dossier_id = perdant.id
        if m.dossier_origine_id == perdant.id:
            m.dossier_origine_id = None
    perdant.fusionne_dans_id = None
    perdant.fusionne_le = None
    perdant.fusion_auto = False
    perdant.fusion_raison = None
    # Le dossier gardé ne répond plus aux noms du dossier rendu.
    noms = {normaliser(perdant.titre or "")} | {
        normaliser(a) for a in alias_de(perdant)
    }
    for cible in {x.id: x for x in (parent, vivant) if x is not None}.values():
        reste = [a for a in alias_de(cible) if normaliser(a) not in noms]
        cible.alias_json = json.dumps(reste, ensure_ascii=False) if reste else None
    await db.flush()
    for cible in {x.id: x for x in (parent, vivant) if x is not None}.values():
        if cible.id != perdant.id:
            await _marquer_paire(
                db, perdant.id, cible.id, "separes", "Fusion défaite à la main"
            )
            await recalculer(db, cible)
    await recalculer(db, perdant)
    await db.flush()
    return perdant


# ── Doublons ────────────────────────────────────────────────────────


PROMPT_DOUBLONS = """Tu vérifies le tableau des dossiers d'un dirigeant : \
certains dossiers sont des DOUBLONS (le même sujet suivi sous deux noms, \
à cause de transcriptions approximatives ou de formulations différentes).

On te donne la liste des dossiers. Rends les groupes de doublons.
- "certain" : c'est manifestement le même dossier (même objet, même \
immeuble ou entreprise, mêmes personnes, états qui se suivent).
- "probable" : ça se ressemble mais un humain doit trancher.
- Deux dossiers sur le même immeuble ou la même personne mais sur des \
objets différents ne sont PAS des doublons (« Électros Adam » et \
« Locataires Adam » sont deux dossiers).
- Dans le doute, mets "probable" ou ne mets rien. Respecte les consignes \
du dirigeant quand il y en a.

Sortie : JSON STRICT, rien d'autre.
{"groupes": [{"ids": [3, 7], "certitude": "certain", "raison": "…"}]}
Aucun doublon : {"groupes": []}."""


def similarite(a: RencontreDossier, b: RencontreDossier) -> float:
    """Meilleure ressemblance (Jaccard) entre les titres / alias."""
    meilleur = 0.0
    for ca in _cles(a):
        for cb in _cles(b):
            union = ca | cb
            if union:
                meilleur = max(meilleur, len(ca & cb) / len(union))
    return meilleur


async def _paires_decidees(db) -> dict[tuple[int, int], RencontreDossierDoublon]:
    rows = (await db.execute(select(RencontreDossierDoublon))).scalars().all()
    return {(x.dossier_a_id, x.dossier_b_id): x for x in rows}


async def _verifier_doublons(db, *, avec_ia: bool = True) -> dict:
    fusions: list[dict] = []
    proposes = 0
    decidees = await _paires_decidees(db)

    def separes(a: int, b: int) -> bool:
        row = decidees.get(_paire(a, b))
        return row is not None and row.statut == "separes"

    async def fusion_auto(groupe: list[RencontreDossier], raison: str) -> None:
        gagnant = await choisir_gagnant(db, groupe)
        for d in groupe:
            if d.id == gagnant.id or separes(d.id, gagnant.id):
                continue
            await fusionner(db, d, gagnant, auto=True, raison=raison)
            fusions.append(
                {
                    "dossier_id": d.id,
                    "titre": d.titre,
                    "dans_id": gagnant.id,
                    "dans_titre": gagnant.titre,
                    "raison": raison,
                }
            )

    # 1. Même titre (mots distinctifs), entreprise compatible → fusion.
    actifs = await dossiers_actifs(db)
    restants = list(actifs)
    while restants:
        d = restants.pop(0)
        cles_d = set(_cles(d))
        groupe = [d] + [
            x
            for x in restants
            if cles_d & set(_cles(x))
            and _entreprises_compatibles(d, x)
            and not separes(d.id, x.id)
        ]
        if len(groupe) > 1:
            ids = {x.id for x in groupe}
            restants = [x for x in restants if x.id not in ids]
            await fusion_auto(groupe, "Même titre")

    actifs = await dossiers_actifs(db)
    par_id = {d.id: d for d in actifs}

    async def proposer(a: RencontreDossier, b: RencontreDossier, raison: str) -> None:
        nonlocal proposes
        cle = _paire(a.id, b.id)
        if cle in decidees:
            return
        decidees[cle] = await _marquer_paire(db, a.id, b.id, "propose", raison)
        proposes += 1

    # 2. L'IA compare tous les dossiers.
    ia_faite = False
    if avec_ia and is_configured() and len(actifs) >= 2:
        noms_ent = {
            e.id: e.name
            for e in (await db.execute(select(Entreprise))).scalars().all()
        }
        liste = sorted(
            actifs,
            key=lambda d: (d.derniere_discussion or date.min, d.id),
            reverse=True,
        )[:MAX_DOSSIERS_IA]
        prompt = (
            await bloc_consignes(db, "dossiers")
            + "## Dossiers\n"
            + "\n".join(_ligne_dossier(d, noms_ent) for d in liste)
            + "\n\nRends le JSON."
        )
        try:
            res = await complete(
                prompt=prompt,
                system=PROMPT_DOUBLONS,
                max_tokens=2500,
                temperature=0.0,
                thinking_budget=0,
            )
            data = _parse_ai_json(res.text or "")
        except Exception as exc:  # noqa: BLE001
            log.warning("dossiers: passe de doublons IA en échec (%s)", exc)
            data = None
        if isinstance(data, dict) and isinstance(data.get("groupes"), list):
            ia_faite = True
            for g in data["groupes"]:
                if not isinstance(g, dict):
                    continue
                ids: list[int] = []
                for x in g.get("ids") or []:
                    try:
                        i = int(x)
                    except Exception:  # noqa: BLE001
                        continue
                    if i in par_id and i not in ids:
                        ids.append(i)
                # Un dossier a pu être fusionné plus haut dans la boucle.
                groupe = [
                    par_id[i] for i in ids if par_id[i].fusionne_dans_id is None
                ]
                if len(groupe) < 2:
                    continue
                raison = _txt(g.get("raison"), 500) or "Même sujet selon l'IA"
                certain = normaliser(_txt(g.get("certitude")) or "") == "certain"
                gagnant = await choisir_gagnant(db, groupe)
                for d in groupe:
                    if d.id == gagnant.id or separes(d.id, gagnant.id):
                        continue
                    # Fusion d'office seulement si les deux dossiers
                    # partagent au moins un mot distinctif ; sinon c'est
                    # un humain qui tranche.
                    if (
                        certain
                        and (_mots(d) & _mots(gagnant))
                        and _entreprises_compatibles(d, gagnant)
                    ):
                        await fusionner(db, d, gagnant, auto=True, raison=raison)
                        fusions.append(
                            {
                                "dossier_id": d.id,
                                "titre": d.titre,
                                "dans_id": gagnant.id,
                                "dans_titre": gagnant.titre,
                                "raison": raison,
                            }
                        )
                    else:
                        await proposer(d, gagnant, raison)

    # 3. Sans IA : les titres qui se ressemblent beaucoup sont proposés.
    if not ia_faite:
        actifs = await dossiers_actifs(db)
        for i, a in enumerate(actifs):
            for b in actifs[i + 1 :]:
                if (
                    _entreprises_compatibles(a, b)
                    and similarite(a, b) >= 0.6
                ):
                    await proposer(a, b, "Titres très proches")

    # Paires proposées devenues sans objet (un des deux n'est plus vivant).
    vivants = {d.id for d in await dossiers_actifs(db)}
    for row in list(decidees.values()):
        if row.statut == "propose" and not (
            row.dossier_a_id in vivants and row.dossier_b_id in vivants
        ):
            await db.delete(row)
    await db.flush()
    return {"fusionnes": fusions, "proposes": proposes, "ia": ia_faite}


async def verifier_doublons(db, *, avec_ia: bool = True) -> dict:
    """Passe de doublons (une à la fois par processus)."""
    async with _verrou:
        return await _verifier_doublons(db, avec_ia=avec_ia)


# ── Vues ────────────────────────────────────────────────────────────


def _oublie(d: RencontreDossier, aujourdhui: date) -> bool:
    if d.statut == DossierStatut.REGLE.value:
        return False
    if d.derniere_discussion is None:
        return False
    return (aujourdhui - d.derniere_discussion) > timedelta(days=JOURS_OUBLI)


def _en_retard(d: RencontreDossier, aujourdhui: date) -> bool:
    return (
        d.statut != DossierStatut.REGLE.value
        and d.echeance_date is not None
        and d.echeance_date < aujourdhui
    )


def public(
    d: RencontreDossier,
    *,
    noms_ent: dict[int, str],
    nb_rencontres: int = 0,
    aujourdhui: Optional[date] = None,
) -> dict:
    jour = aujourdhui or _aujourdhui()
    return {
        "id": d.id,
        "titre": d.titre,
        "statut": d.statut,
        "statut_libelle": LIBELLES_STATUT.get(d.statut, d.statut),
        "entreprise_id": d.entreprise_id,
        "entreprise": noms_ent.get(d.entreprise_id) if d.entreprise_id else None,
        "contexte": d.contexte,
        "responsable": d.responsable,
        "dernier_etat": d.dernier_etat,
        "prochaine_action": d.prochaine_action,
        "echeance": d.echeance,
        "echeance_date": d.echeance_date.isoformat() if d.echeance_date else None,
        "derniere_discussion": (
            d.derniere_discussion.isoformat() if d.derniere_discussion else None
        ),
        "jours_sans_discussion": (
            (jour - d.derniere_discussion).days if d.derniere_discussion else None
        ),
        "nb_rencontres": nb_rencontres,
        "oublie": _oublie(d, jour),
        "en_retard": _en_retard(d, jour),
        "alias": alias_de(d),
        "source": d.source,
        "modifie_a_la_main": bool(_manuels(d) or d.etat_manuel_le),
    }


async def _noms_entreprises(db) -> dict[int, str]:
    return {
        e.id: e.name for e in (await db.execute(select(Entreprise))).scalars().all()
    }


async def _nb_rencontres_par_dossier(db) -> dict[int, int]:
    rows = (
        await db.execute(
            select(
                RencontreDossierMention.dossier_id,
                func.count(func.distinct(RencontreDossierMention.rencontre_id)),
            ).group_by(RencontreDossierMention.dossier_id)
        )
    ).all()
    return {did: nb for did, nb in rows}


_ORDRE_STATUT = {"bloque": 0, "en_attente": 1, "en_cours": 2, "regle": 3}


def _cle_tri(p: dict) -> tuple:
    """À relancer d'abord, puis bloqués, en attente, en cours ; à statut
    égal, le plus anciennement discuté en haut."""
    alerte = 0 if (p["oublie"] or p["en_retard"]) and p["statut"] != "regle" else 1
    return (
        1 if p["statut"] == "regle" else 0,
        alerte,
        _ORDRE_STATUT.get(p["statut"], 9),
        p["derniere_discussion"] or "",
        p["id"],
    )


async def lister(
    db,
    *,
    statut: Optional[str] = None,
    entreprise_id: Optional[int] = None,
    responsable: Optional[str] = None,
    inclure_regles: bool = False,
    a_relancer: bool = False,
) -> dict:
    actifs = await dossiers_actifs(db)
    noms_ent = await _noms_entreprises(db)
    nb = await _nb_rencontres_par_dossier(db)
    jour = _aujourdhui()
    tous = [
        public(d, noms_ent=noms_ent, nb_rencontres=nb.get(d.id, 0), aujourdhui=jour)
        for d in actifs
    ]
    compteurs = {s: 0 for s in STATUTS_DOSSIER}
    for p in tous:
        compteurs[p["statut"]] = compteurs.get(p["statut"], 0) + 1
    ouverts = [p for p in tous if p["statut"] != "regle"]
    vue = tous
    if statut:
        vue = [p for p in vue if p["statut"] == statut]
    elif not inclure_regles:
        vue = [p for p in vue if p["statut"] != "regle"]
    if entreprise_id is not None:
        vue = [p for p in vue if p["entreprise_id"] == entreprise_id]
    if responsable:
        cible = normaliser(responsable).strip()
        vue = [
            p for p in vue if cible in normaliser(p["responsable"] or "")
        ]
    if a_relancer:
        vue = [p for p in vue if p["oublie"] or p["en_retard"]]
    vue.sort(key=_cle_tri)
    doublons = (
        await db.execute(
            select(func.count(RencontreDossierDoublon.id)).where(
                RencontreDossierDoublon.statut == "propose"
            )
        )
    ).scalar_one()
    return {
        "dossiers": vue,
        "compteurs": compteurs,
        "ouverts": len(ouverts),
        "a_relancer": sum(1 for p in ouverts if p["oublie"] or p["en_retard"]),
        "responsables": sorted(
            {p["responsable"] for p in tous if p["responsable"]},
            key=lambda s: normaliser(s),
        ),
        "entreprises": sorted(
            (
                {"id": i, "nom": noms_ent.get(i) or f"#{i}"}
                for i in {p["entreprise_id"] for p in tous if p["entreprise_id"]}
            ),
            key=lambda e: normaliser(e["nom"]),
        ),
        "doublons_proposes": doublons,
        "rencontres_a_analyser": len(await rencontres_a_analyser(db)),
        "ia_disponible": is_configured(),
        "analyse": etat_analyse(),
        "jours_oubli": JOURS_OUBLI,
    }


async def _taches_des_actions(
    db, titres: set[str]
) -> dict[str, dict]:
    """Tâches Kratos créées depuis les actions d'une rencontre (bouton
    « actions vers tâches ») : retrouvées par leur titre et leur
    description « De la rencontre … »."""
    if not titres:
        return {}
    from app.models.entreprise_tache import EntrepriseTache

    rows = (
        await db.execute(
            select(EntrepriseTache).where(
                EntrepriseTache.description.like("De la rencontre «%")
            )
        )
    ).scalars().all()
    voulus = {normaliser(t).strip() for t in titres}
    out: dict[str, dict] = {}
    for t in rows:
        cle = normaliser(t.title or "").strip()
        if cle in voulus:
            out[cle] = {
                "id": t.id,
                "statut": t.status,
                "fait": t.status == "done",
                "entreprise_id": t.entreprise_id,
            }
    return out


async def detail(db, d: RencontreDossier) -> dict:
    noms_ent = await _noms_entreprises(db)
    paires = await _mentions_avec_rencontre(db, d.id)
    base = public(
        d,
        noms_ent=noms_ent,
        nb_rencontres=len({r.id for _m, r in paires}),
    )
    titres_actions: set[str] = set()
    for m, _r in paires:
        for a in _liste_json(m.actions_json):
            if isinstance(a, dict) and a.get("title"):
                titres_actions.add(a["title"])
    taches = await _taches_des_actions(db, titres_actions)
    historique = []
    for m, r in reversed(paires):
        actions = []
        for a in _liste_json(m.actions_json):
            if not isinstance(a, dict) or not a.get("title"):
                continue
            actions.append(
                {
                    "titre": a.get("title"),
                    "responsable": a.get("owner"),
                    "echeance": a.get("due"),
                    "tache": taches.get(normaliser(a["title"]).strip()),
                }
            )
        historique.append(
            {
                "mention_id": m.id,
                "rencontre_id": r.id,
                "rencontre_titre": r.title,
                "rencontre_date": _date_rencontre(r).isoformat(),
                "resume": m.resume,
                "etat": m.etat,
                "statut": m.statut,
                "statut_libelle": LIBELLES_STATUT.get(m.statut or "", m.statut),
                "prochaine_action": m.prochaine_action,
                "echeance": m.echeance,
                "decisions": _liste_json(m.decisions_json),
                "actions": actions,
                "questions": _liste_json(m.questions_json),
                "vient_de_dossier_id": m.dossier_origine_id,
            }
        )
    absorbes = await _absorbes(db, d)
    return {
        **base,
        "historique": historique,
        "fusionnes": [
            {
                "id": e.id,
                "titre": e.titre,
                "fusionne_le": e.fusionne_le.isoformat() if e.fusionne_le else None,
                "auto": bool(e.fusion_auto),
                "raison": e.fusion_raison,
                "direct": e.fusionne_dans_id == d.id,
            }
            for e in absorbes
        ],
    }


async def doublons_proposes(db) -> list[dict]:
    rows = (
        await db.execute(
            select(RencontreDossierDoublon)
            .where(RencontreDossierDoublon.statut == "propose")
            .order_by(RencontreDossierDoublon.id.asc())
        )
    ).scalars().all()
    if not rows:
        return []
    noms_ent = await _noms_entreprises(db)
    nb = await _nb_rencontres_par_dossier(db)
    out = []
    for row in rows:
        a = await db.get(RencontreDossier, row.dossier_a_id)
        b = await db.get(RencontreDossier, row.dossier_b_id)
        if (
            a is None
            or b is None
            or a.fusionne_dans_id is not None
            or b.fusionne_dans_id is not None
        ):
            continue
        out.append(
            {
                "id": row.id,
                "raison": row.raison,
                "a": public(a, noms_ent=noms_ent, nb_rencontres=nb.get(a.id, 0)),
                "b": public(b, noms_ent=noms_ent, nb_rencontres=nb.get(b.id, 0)),
            }
        )
    return out


async def fusions_recentes(db, limite: int = 20) -> list[dict]:
    """Dernières fusions (pour les défaire d'un clic)."""
    rows = (
        await db.execute(
            select(RencontreDossier)
            .where(RencontreDossier.fusionne_dans_id.is_not(None))
            .order_by(RencontreDossier.fusionne_le.desc().nulls_last())
            .limit(limite)
        )
    ).scalars().all()
    out = []
    for e in rows:
        cible = await db.get(RencontreDossier, e.fusionne_dans_id)
        out.append(
            {
                "id": e.id,
                "titre": e.titre,
                "dans_id": e.fusionne_dans_id,
                "dans_titre": cible.titre if cible else None,
                "fusionne_le": e.fusionne_le.isoformat() if e.fusionne_le else None,
                "auto": bool(e.fusion_auto),
                "raison": e.fusion_raison,
            }
        )
    return out


def _ligne_odj(p: dict) -> str:
    bouts = [p["titre"]]
    if p.get("entreprise") or p.get("contexte"):
        bouts[0] += " (" + " · ".join(
            x for x in (p.get("entreprise"), p.get("contexte")) if x
        ) + ")"
    if p.get("responsable"):
        bouts.append(p["responsable"])
    if p.get("dernier_etat"):
        bouts.append("État : " + " ".join(p["dernier_etat"].split()))
    if p.get("prochaine_action"):
        suite = "Suite : " + " ".join(p["prochaine_action"].split())
        if p.get("echeance"):
            suite += f" ({p['echeance']})"
        bouts.append(suite)
    if p.get("derniere_discussion"):
        bouts.append(f"Vu le {p['derniere_discussion']}")
    return "- " + " — ".join(bouts)


async def ordre_du_jour(db, *, entreprise_id: Optional[int] = None) -> dict:
    """Ordre du jour de la prochaine rencontre, à partir des dossiers
    ouverts : à relancer et bloqués d'abord."""
    vue = (await lister(db, entreprise_id=entreprise_id))["dossiers"]
    groupes = [
        ("À relancer (oubliés ou en retard)", [p for p in vue if p["oublie"] or p["en_retard"]]),
        ("Bloqués", [p for p in vue if p["statut"] == "bloque" and not (p["oublie"] or p["en_retard"])]),
        ("En attente", [p for p in vue if p["statut"] == "en_attente" and not (p["oublie"] or p["en_retard"])]),
        ("En cours", [p for p in vue if p["statut"] == "en_cours" and not (p["oublie"] or p["en_retard"])]),
    ]
    lignes = [f"Ordre du jour — dossiers ouverts ({_aujourdhui().isoformat()})"]
    n = 0
    for titre, items in groupes:
        if not items:
            continue
        n += 1
        lignes.append(f"\n{n}. {titre}")
        lignes += [_ligne_odj(p) for p in items]
    if n == 0:
        lignes.append("\nAucun dossier ouvert.")
    return {
        "texte": "\n".join(lignes),
        "groupes": [
            {"titre": t, "dossier_ids": [p["id"] for p in items]}
            for t, items in groupes
            if items
        ],
        "nombre": sum(len(items) for _t, items in groupes),
    }


async def chercher_pour_question(db, mots: list[str], limite: int = 8) -> list[dict]:
    """Dossiers dont le titre, les alias, le contexte ou l'état portent
    les mots-clés d'une question (« Demander à Kratos »)."""
    if not mots:
        return []
    actifs = await dossiers_actifs(db)
    if not actifs:
        return []
    noms_ent = await _noms_entreprises(db)
    notes = []
    for d in actifs:
        titre_mots = _mots(d)
        corps = normaliser(
            " ".join(
                x
                for x in (d.dernier_etat, d.prochaine_action, d.responsable)
                if x
            )
        )
        score = 0.0
        for m in mots:
            if m in titre_mots:
                score += 2.0
            elif m in corps:
                score += 0.5
        if score >= 2.0 or (len(mots) > 1 and score >= 1.0):
            notes.append((score, d))
    notes.sort(key=lambda t: (t[0], t[1].derniere_discussion or date.min), reverse=True)
    return [public(d, noms_ent=noms_ent) for _s, d in notes[:limite]]


# ── Tâches de fond ──────────────────────────────────────────────────


async def _course(db) -> dict:
    """Une course complète : passes successives jusqu'à ce qu'il ne
    reste rien à faire, que l'IA manque ou qu'une passe n'avance plus.
    Une rencontre illisible est sautée, pas retentée dans la course."""
    ratees: set[int] = set()
    bilan = {"analysees": 0, "restantes": 0, "echecs": 0, "ia_absente": False}
    for _ in range(MAX_PASSES_FOND):
        res = await analyser_en_attente(db, ignorer=ratees)
        await db.commit()
        bilan["analysees"] += res["analysees"]
        bilan["restantes"] = res["restantes"]
        bilan["echecs"] = len(ratees)
        bilan["ia_absente"] = res["ia_absente"]
        _etat_fond.update(bilan)
        if not res["a_faire"] or res["ia_absente"] or not res["analysees"]:
            break
    return bilan


async def _fond() -> None:
    from app.db.session import AsyncSessionLocal

    _etat_fond.update(
        analysees=0, restantes=None, echecs=0, ia_absente=False, termine_le=None
    )
    try:
        async with AsyncSessionLocal() as db:
            await _course(db)
    except Exception as exc:  # noqa: BLE001
        log.warning("dossiers: analyse en fond en échec (%s)", exc)
        _etat_fond["echecs"] = (_etat_fond.get("echecs") or 0) + 1
    finally:
        _etat_fond["termine_le"] = datetime.now(timezone.utc).isoformat()


def analyse_en_cours() -> bool:
    """Une course de fond tourne-t-elle dans ce processus ?"""
    return any(not t.done() for t in _taches_fond)


def etat_analyse() -> dict:
    """État de la course de fond pour l'écran (qui se rafraîchit tant
    que ``en_cours`` est vrai)."""
    return {"en_cours": analyse_en_cours(), **_etat_fond}


def planifier_analyse() -> bool:
    """Lance l'analyse des rencontres en attente en arrière-plan (après
    un résumé, ou depuis l'onglet Dossiers). Rien sans IA ; une seule
    course à la fois."""
    if not is_configured():
        return False
    if analyse_en_cours():
        return False
    try:
        tache = asyncio.get_running_loop().create_task(_fond())
    except RuntimeError:
        return False
    _taches_fond.add(tache)
    tache.add_done_callback(_taches_fond.discard)
    return True


async def pour_cron() -> dict:
    """Job quotidien : rencontres en attente, puis passe de doublons."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        bilan: dict = await _course(db)
        d = await verifier_doublons(db, avec_ia=True)
        await db.commit()
        bilan["fusionnes"] = len(d.get("fusionnes") or [])
        bilan["proposes"] = d.get("proposes", 0)
    return bilan
