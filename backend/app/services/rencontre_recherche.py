"""Recherche dans TOUTES les rencontres + réponse IA sourcée (2026-11-13).

Steven : « dans la section rencontre, beaucoup de choses peuvent être
discutées ; si je pose une question à Kratos sur un élément, il doit être
capable de regarder dans chacune des rencontres et me dire si nous avons
discuté de quelque chose ou l'avancement d'un dossier ».

Deux étages :

1. ``rechercher`` — recherche plein texte locale, sans IA : la question
   est réduite à ses mots-clés (accents, majuscules et pluriels près,
   mots vides et mots « méta » comme rencontre / discuté / dossier
   retirés), puis chaque rencontre est découpée en PASSAGES (résumé
   global, notes, résumé IA de chaque section — décisions, actions,
   questions en suspens, risques — et transcript brut par tranches).
   Un passage est noté par les mots-clés qu'il contient, pondérés par
   leur rareté (un mot présent partout pèse peu) ; le titre de la
   rencontre donne un bonus. Résultat : les meilleurs passages, en
   ordre CHRONOLOGIQUE, avec la rencontre et la section d'origine.

2. ``repondre`` — l'IA (cascade habituelle) reçoit ces passages et
   l'index de toutes les rencontres, et répond : discuté ou non, dans
   quelles rencontres, et l'évolution du dossier d'une rencontre à
   l'autre jusqu'au dernier état connu. Sans IA (ou en panne), la
   réponse est la liste des passages trouvés : jamais de blocage.

Le service ne lit QUE les rencontres ; les gardes d'accès (page
« entreprises.rencontres ») sont faites par les appelants.
"""

from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from sqlalchemy import select

from app.integrations.ai import AIProviderError, complete, is_configured
from app.models.rencontre import Rencontre, RencontreSection

log = logging.getLogger(__name__)

#: Taille visée d'un passage de transcript (caractères).
TAILLE_PASSAGE = 700
#: Passages envoyés à l'IA au maximum.
MAX_PASSAGES_IA = 16
#: Passages retenus au maximum pour une même rencontre (pour laisser la
#: place aux autres rencontres : c'est l'évolution qui intéresse).
MAX_PAR_RENCONTRE = 5
#: Rencontres listées dans l'index envoyé à l'IA.
MAX_INDEX = 60
#: Rencontres lues au maximum (les plus récentes).
MAX_RENCONTRES = 500


# ── Normalisation et mots-clés ──────────────────────────────────────


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, apostrophes et tirets → espaces."""
    t = unicodedata.normalize("NFKD", texte or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().replace("’", " ").replace("'", " ")
    return re.sub(r"[-_/]", " ", t)


# Mots vides (déjà sans accents) + mots « méta » de la question : ils
# sont dans toutes les questions sur les rencontres et ne disent rien du
# sujet cherché.
_MOTS_VIDES = set(
    """
    les des une un le la de du et ou au aux en dans sur sous par pour
    avec sans que qui quoi quel quels quelle quelles dont est sont ete
    etait etaient avoir avons avez ont eu fait faire fais faites ce ces
    cet cette ca cela celui celle ceux celles il elle ils elles on nous
    vous je tu me te se mon ma mes ton ta tes son sa ses notre nos votre
    vos leur leurs lui y ne pas plus moins tres bien deja encore aussi
    alors donc mais comme quand tout tous toute toutes peut peux veut
    veux dois doit savoir sais voir dire dis dit depuis entre chez vers
    est-ce estce oui non si qu quoi combien comment pourquoi ou etc
    rencontre rencontres reunion reunions meeting meetings discute
    discutes discutee discutees discuter discussion discussions parle
    parles parlee parler parle dossier dossiers sujet sujets avancement
    avance avancee ou-en point points etat suivi suivis question
    questions mentionne mentionnes mentionner kratos dernier derniere
    derniers dernieres nouvelle nouvelles jour mois semaine annee
    there the and what about
    """.split()
)


def _racine(mot: str) -> str:
    """Pluriel français simple retiré (« locataires » → « locataire »)."""
    if len(mot) > 4 and (mot.endswith("s") or mot.endswith(("aux", "eux"))):
        return mot[:-1]
    return mot


def mots_cles(question: str, maximum: int = 10) -> list[str]:
    """Mots-clés normalisés de la question, dans leur ordre, sans
    doublon. Un mot garde 3 lettres ou plus ; un code avec chiffre
    (« P9 », « 1660 ») est gardé dès 2 caractères."""
    vus: list[str] = []
    for brut in re.findall(r"[a-z0-9]+", normaliser(question)):
        a_chiffre = any(c.isdigit() for c in brut)
        if len(brut) < (2 if a_chiffre else 3):
            continue
        if brut in _MOTS_VIDES:
            continue
        r = _racine(brut)
        if r not in vus:
            vus.append(r)
        if len(vus) >= maximum:
            break
    return vus


def _contient(texte_norm: str, mot: str) -> bool:
    """Le mot (racine) apparaît au début d'un mot du texte normalisé.
    Les codes courts avec chiffre (« p9 ») doivent être un mot entier."""
    if any(c.isdigit() for c in mot) and len(mot) <= 3:
        return re.search(rf"\b{re.escape(mot)}\b", texte_norm) is not None
    return re.search(rf"\b{re.escape(mot)}", texte_norm) is not None


# ── Passages ────────────────────────────────────────────────────────


@dataclass
class Passage:
    rencontre_id: int
    rencontre_titre: str
    rencontre_date: Optional[date]
    section: Optional[str]
    #: global | notes | resume | decision | action | question | risque | transcript
    type: str
    texte: str
    score: float = 0.0
    mots: list[str] = field(default_factory=list)
    _norm: str = ""

    def public(self) -> dict:
        return {
            "rencontre_id": self.rencontre_id,
            "rencontre_titre": self.rencontre_titre,
            "rencontre_date": (
                self.rencontre_date.isoformat() if self.rencontre_date else None
            ),
            "section": self.section,
            "type": self.type,
            "extrait": self.texte,
            "score": round(self.score, 3),
            "mots_trouves": self.mots,
        }


def _tranches(texte: str, taille: int = TAILLE_PASSAGE) -> list[str]:
    """Découpe un long texte en tranches d'environ ``taille`` caractères,
    en respectant les paragraphes puis les phrases."""
    texte = (texte or "").strip()
    if not texte:
        return []
    morceaux: list[str] = []
    for para in re.split(r"\n\s*\n|\n", texte):
        para = para.strip()
        if not para:
            continue
        if len(para) <= taille:
            morceaux.append(para)
            continue
        phrase_courante = ""
        for ph in re.split(r"(?<=[.!?])\s+", para):
            if len(ph) > taille:
                # Phrase géante (transcript sans ponctuation) : coupe dure.
                if phrase_courante:
                    morceaux.append(phrase_courante)
                    phrase_courante = ""
                for i in range(0, len(ph), taille):
                    morceaux.append(ph[i : i + taille])
                continue
            if len(phrase_courante) + len(ph) + 1 > taille and phrase_courante:
                morceaux.append(phrase_courante)
                phrase_courante = ph
            else:
                phrase_courante = f"{phrase_courante} {ph}".strip()
        if phrase_courante:
            morceaux.append(phrase_courante)
    # Regroupe les petits morceaux consécutifs.
    out: list[str] = []
    for m in morceaux:
        if out and len(out[-1]) + len(m) + 1 <= taille:
            out[-1] = f"{out[-1]}\n{m}"
        else:
            out.append(m)
    return out


def _resume_section(s: RencontreSection) -> dict:
    if not s.ai_summary_json:
        return {}
    try:
        v = json.loads(s.ai_summary_json)
    except Exception:  # noqa: BLE001
        return {}
    return v if isinstance(v, dict) else {}


def _txt(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def passages_de_rencontre(
    r: Rencontre, sections: list[RencontreSection]
) -> list[Passage]:
    """Tous les passages cherchables d'une rencontre."""
    out: list[Passage] = []

    def ajoute(section: Optional[str], typ: str, texte: str) -> None:
        texte = (texte or "").strip()
        if not texte:
            return
        out.append(
            Passage(
                rencontre_id=r.id,
                rencontre_titre=r.title,
                rencontre_date=r.meeting_date,
                section=section,
                type=typ,
                texte=texte,
            )
        )

    for t in _tranches(r.global_summary or ""):
        ajoute(None, "global", t)
    for t in _tranches(r.notes or ""):
        ajoute(None, "notes", t)
    for s in sorted(sections, key=lambda x: (x.position, x.id)):
        res = _resume_section(s)
        for t in _tranches(_txt(res.get("summary"))):
            ajoute(s.title, "resume", t)
        for d in res.get("decisions") or []:
            ajoute(s.title, "decision", _txt(d))
        for a in res.get("action_items") or []:
            if isinstance(a, dict):
                bouts = [_txt(a.get("title"))]
                if a.get("owner"):
                    bouts.append(f"responsable : {_txt(a.get('owner'))}")
                if a.get("entreprise_hint"):
                    bouts.append(f"entreprise : {_txt(a.get('entreprise_hint'))}")
                if a.get("due"):
                    bouts.append(f"échéance : {_txt(a.get('due'))}")
                ajoute(s.title, "action", " — ".join(b for b in bouts if b))
            else:
                ajoute(s.title, "action", _txt(a))
        for q in res.get("open_questions") or []:
            ajoute(s.title, "question", _txt(q))
        for rk in res.get("risks") or []:
            ajoute(s.title, "risque", _txt(rk))
        for t in _tranches(s.transcript or ""):
            ajoute(s.title, "transcript", t)
    return out


def _entreprise_ids(r: Rencontre) -> list[int]:
    if not r.entreprise_ids_json:
        return []
    try:
        v = json.loads(r.entreprise_ids_json)
        return [int(x) for x in v] if isinstance(v, list) else []
    except Exception:  # noqa: BLE001
        return []


async def charger_rencontres(
    db, entreprise_id: Optional[int] = None
) -> list[tuple[Rencontre, list[RencontreSection]]]:
    """Les rencontres (plus récentes d'abord) avec leurs sections."""
    rencontres = (
        await db.execute(
            select(Rencontre)
            .order_by(
                Rencontre.meeting_date.desc().nulls_last(), Rencontre.id.desc()
            )
            .limit(MAX_RENCONTRES)
        )
    ).scalars().all()
    if entreprise_id is not None:
        rencontres = [r for r in rencontres if entreprise_id in _entreprise_ids(r)]
    if not rencontres:
        return []
    ids = [r.id for r in rencontres]
    sections = (
        await db.execute(
            select(RencontreSection).where(RencontreSection.rencontre_id.in_(ids))
        )
    ).scalars().all()
    par_r: dict[int, list[RencontreSection]] = {}
    for s in sections:
        par_r.setdefault(s.rencontre_id, []).append(s)
    return [(r, par_r.get(r.id, [])) for r in rencontres]


# Poids par type : une décision ou une action pèse un peu plus qu'une
# tranche de transcript brut (déjà synthétisée, plus fiable).
_POIDS_TYPE = {
    "decision": 1.25,
    "action": 1.2,
    "question": 1.1,
    "risque": 1.1,
    "resume": 1.1,
    "global": 1.0,
    "notes": 1.0,
    "transcript": 0.9,
}


def noter_passages(passages: list[Passage], mots: list[str]) -> list[Passage]:
    """Note chaque passage ; retourne ceux qui contiennent au moins un
    mot-clé, du meilleur au moins bon."""
    if not mots or not passages:
        return []
    for p in passages:
        p._norm = normaliser(p.texte)
    n = len(passages)
    # Rareté (idf) : présent dans tous les passages → poids faible.
    idf: dict[str, float] = {}
    for m in mots:
        df = sum(1 for p in passages if _contient(p._norm, m))
        idf[m] = math.log(1 + n / (1 + df)) if df else 0.0
    titres_norm: dict[int, str] = {}
    trouves: list[Passage] = []
    for p in passages:
        presents = [m for m in mots if idf[m] and _contient(p._norm, m)]
        if not presents:
            continue
        t_norm = titres_norm.setdefault(
            p.rencontre_id, normaliser(p.rencontre_titre or "")
        )
        bonus_titre = sum(0.3 * idf[m] for m in mots if _contient(t_norm, m))
        # Couverture : avoir TOUS les mots vaut plus que d'en répéter un.
        couverture = len(presents) / len(mots)
        p.score = (
            sum(idf[m] for m in presents) * (0.5 + couverture)
            + bonus_titre
        ) * _POIDS_TYPE.get(p.type, 1.0)
        p.mots = presents
        trouves.append(p)
    trouves.sort(key=lambda p: p.score, reverse=True)
    return trouves


def _selection(trouves: list[Passage], limite: int) -> list[Passage]:
    """Meilleurs passages, au plus ``MAX_PAR_RENCONTRE`` par rencontre,
    remis en ordre chronologique (rencontre puis ordre d'origine)."""
    par_r: dict[int, int] = {}
    choisis: list[Passage] = []
    for p in trouves:
        if len(choisis) >= limite:
            break
        if par_r.get(p.rencontre_id, 0) >= MAX_PAR_RENCONTRE:
            continue
        par_r[p.rencontre_id] = par_r.get(p.rencontre_id, 0) + 1
        choisis.append(p)
    return sorted(
        choisis,
        key=lambda p: (p.rencontre_date or date.min, p.rencontre_id),
    )


async def rechercher(
    db,
    question: str,
    *,
    entreprise_id: Optional[int] = None,
    limite: int = 20,
) -> dict:
    """Recherche locale (sans IA) dans toutes les rencontres."""
    mots = mots_cles(question)
    donnees = await charger_rencontres(db, entreprise_id)
    passages: list[Passage] = []
    for r, sections in donnees:
        passages.extend(passages_de_rencontre(r, sections))
    trouves = noter_passages(passages, mots)
    choisis = _selection(trouves, limite)
    # Synthèse par rencontre (toutes les correspondances, pas seulement
    # les passages retenus) : pour « dans quelles rencontres ».
    par_r: dict[int, dict] = {}
    for p in trouves:
        e = par_r.setdefault(
            p.rencontre_id,
            {
                "rencontre_id": p.rencontre_id,
                "titre": p.rencontre_titre,
                "date": (
                    p.rencontre_date.isoformat() if p.rencontre_date else None
                ),
                "passages": 0,
                "score": 0.0,
            },
        )
        e["passages"] += 1
        e["score"] = round(e["score"] + p.score, 3)
    rencontres = sorted(
        par_r.values(), key=lambda e: (e["date"] or "", e["rencontre_id"])
    )
    return {
        "question": question,
        "mots_cles": mots,
        "rencontres_lues": len(donnees),
        "rencontres_trouvees": rencontres,
        "passages": [p.public() for p in choisis],
        "_choisis": choisis,
        "_donnees": donnees,
    }


# ── Réponse IA ──────────────────────────────────────────────────────


PROMPT_SYSTEME = """Tu es Kratos, l'assistant interne d'un dirigeant qui \
gère plusieurs entreprises (construction, immobilier locatif, \
développement). On te pose une question sur ce qui a été dit dans ses \
RENCONTRES (réunions d'équipe, conseils d'actionnaires, suivis). Tu \
reçois l'index des rencontres et les passages pertinents trouvés dans \
leurs résumés, décisions, actions et transcripts, en ordre chronologique.

Réponds en français québécois, clair et concret :
1. Dis d'abord si le sujet a été discuté (oui / non / seulement en \
passant), et dans quelles rencontres : « Rencontre #ID — titre (date) ».
2. S'il s'agit d'un dossier, retrace son AVANCEMENT d'une rencontre à \
l'autre : ce qui a été décidé, qui devait faire quoi et pour quand, et \
le DERNIER ÉTAT CONNU (la rencontre la plus récente fait foi). Signale \
les actions qui n'ont pas de suivi dans une rencontre plus récente.
3. Termine par les points en suspens s'il y en a.

Règles :
- Appuie-toi UNIQUEMENT sur les passages fournis ; n'invente rien. Si \
les passages ne parlent pas vraiment du sujet, dis-le franchement \
(« Je ne trouve pas ce sujet dans les rencontres ») et suggère d'autres \
mots à chercher.
- Les transcripts sont souvent bruités (dictée, mots mal transcrits) : \
reconstitue le sens sans le signaler, mais garde les mentions \
« [à vérifier] » quand le passage les porte.
- Cite toujours la rencontre (#ID et date) pour chaque fait.
- Sois concis : quelques paragraphes ou une courte liste, pas de \
préambule."""

_LIBELLES_TYPE = {
    "global": "Résumé global",
    "notes": "Notes",
    "resume": "Résumé",
    "decision": "Décision",
    "action": "Action",
    "question": "Question en suspens",
    "risque": "Risque",
    "transcript": "Transcript",
}


def _date_txt(d: Optional[date]) -> str:
    return d.isoformat() if d else "sans date"


def _bloc_index(donnees: list[tuple[Rencontre, list[RencontreSection]]]) -> str:
    lignes = []
    for r, _s in donnees[:MAX_INDEX]:
        apercu = re.sub(r"\s+", " ", (r.global_summary or "").strip())[:220]
        ligne = f"- Rencontre #{r.id} — {r.title} ({_date_txt(r.meeting_date)})"
        if apercu:
            ligne += f" : {apercu}"
        lignes.append(ligne)
    return "\n".join(lignes)


def _bloc_passages(choisis: list[Passage]) -> str:
    blocs = []
    for p in choisis:
        entete = (
            f"[Rencontre #{p.rencontre_id} — {p.rencontre_titre} "
            f"({_date_txt(p.rencontre_date)})"
        )
        if p.section and p.section != p.rencontre_titre:
            entete += f" · section « {p.section} »"
        entete += f" · {_LIBELLES_TYPE.get(p.type, p.type)}]"
        blocs.append(f"{entete}\n{p.texte}")
    return "\n\n".join(blocs)


def _sources(choisis: list[Passage]) -> list[dict]:
    """Passages regroupés par rencontre (ordre chronologique)."""
    par_r: dict[int, dict] = {}
    for p in choisis:
        e = par_r.setdefault(
            p.rencontre_id,
            {
                "rencontre_id": p.rencontre_id,
                "titre": p.rencontre_titre,
                "date": (
                    p.rencontre_date.isoformat() if p.rencontre_date else None
                ),
                "extraits": [],
            },
        )
        e["extraits"].append(
            {
                "section": p.section,
                "type": p.type,
                "libelle": _LIBELLES_TYPE.get(p.type, p.type),
                "texte": p.texte,
            }
        )
    return list(par_r.values())


def reponse_sans_ia(question: str, choisis: list[Passage], motif: str = "") -> str:
    """Réponse de repli : les passages trouvés, rencontre par rencontre."""
    if not choisis:
        return "Je ne trouve pas ce sujet dans les rencontres enregistrées."
    lignes = []
    if motif:
        lignes.append(motif)
    lignes.append(
        "Voici les passages des rencontres qui en parlent (du plus ancien "
        "au plus récent) :"
    )
    for src in _sources(choisis):
        lignes.append(
            f"\n**Rencontre #{src['rencontre_id']} — {src['titre']} "
            f"({src['date'] or 'sans date'})**"
        )
        for ex in src["extraits"]:
            t = ex["texte"]
            if len(t) > 300:
                t = t[:300].rstrip() + "…"
            lignes.append(f"- {ex['libelle']} : {t}")
    return "\n".join(lignes)


async def repondre(
    db,
    question: str,
    *,
    entreprise_id: Optional[int] = None,
) -> dict:
    """Réponse à une question sur les rencontres, avec ses sources."""
    res = await rechercher(
        db, question, entreprise_id=entreprise_id, limite=MAX_PASSAGES_IA
    )
    choisis: list[Passage] = res.pop("_choisis")
    donnees = res.pop("_donnees")
    base = {
        "question": question,
        "mots_cles": res["mots_cles"],
        "rencontres_lues": res["rencontres_lues"],
        "rencontres_trouvees": res["rencontres_trouvees"],
        "sources": _sources(choisis),
    }
    if not donnees:
        return {
            **base,
            "reponse": "Aucune rencontre n'est encore enregistrée dans Kratos.",
            "ia": False,
            "fournisseur": None,
        }
    if not res["mots_cles"]:
        return {
            **base,
            "reponse": (
                "Précise le sujet cherché (un nom de projet, d'immeuble, "
                "de personne ou un mot-clé) : la question ne contient que "
                "des mots trop généraux."
            ),
            "ia": False,
            "fournisseur": None,
        }
    if not choisis:
        return {
            **base,
            "reponse": (
                "Je ne trouve aucune mention de « "
                + ", ".join(res["mots_cles"])
                + f" » dans les {len(donnees)} rencontre(s) enregistrée(s). "
                "Essaie un autre mot (nom du projet, de l'immeuble, de la "
                "personne)."
            ),
            "ia": False,
            "fournisseur": None,
        }
    if not is_configured():
        return {
            **base,
            "reponse": reponse_sans_ia(question, choisis),
            "ia": False,
            "fournisseur": None,
        }
    prompt = (
        "## Index des rencontres (plus récentes d'abord)\n"
        f"{_bloc_index(donnees)}\n\n"
        "## Passages trouvés (ordre chronologique)\n"
        f"{_bloc_passages(choisis)}\n\n"
        f"## Question\n{question}"
    )
    try:
        out = await complete(
            prompt=prompt,
            system=PROMPT_SYSTEME,
            max_tokens=1500,
            temperature=0.2,
            thinking_budget=0,
        )
        texte = (out.text or "").strip()
        if not texte:
            raise AIProviderError("réponse vide")
        return {**base, "reponse": texte, "ia": True, "fournisseur": out.provider}
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        log.warning("rencontre_recherche: IA indisponible (%s)", exc)
        return {
            **base,
            "reponse": reponse_sans_ia(
                question,
                choisis,
                "(L'IA ne répond pas pour le moment ; voici la recherche brute.)",
            ),
            "ia": False,
            "fournisseur": None,
        }


async def contexte_pour_assistant(db, question: str, limite: int = 8) -> str:
    """Passages des rencontres liés à une question posée ailleurs (Centre
    d'aide). Chaîne vide quand rien ne correspond vraiment."""
    res = await rechercher(db, question, limite=limite)
    nb_mots = len(res["mots_cles"]) or 1
    # Seuil de pertinence : au moins la moitié des mots-clés dans le
    # passage, pour ne pas polluer une question d'aide sur le portail.
    choisis: list[Passage] = [
        p for p in res["_choisis"] if len(p.mots) / nb_mots >= 0.5
    ]
    if not choisis:
        return ""
    return _bloc_passages(choisis)
