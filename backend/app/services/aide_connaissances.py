"""Base de connaissances du Centre d'aide (onglet « Question »).

Steven, 2026-11-13 : « beaucoup de bugs qui reviennent et qui sont déjà
réglés […] pouvoir aller poser une question sur un fonctionnement et
avoir la réponse ». L'assistant ne connaissait que quelques lignes sur
le punch et les PO : il répondait à côté et ignorait ce qui avait déjà
été corrigé. On lui donne désormais trois sources, cherchées par mots
clés (sans accents, sans mots vides) :

1. **Les signalements** (table ``help_requests``) : statut, section,
   note de résolution et dates — un problème réglé ou en cours y figure.
2. **Le journal des livraisons** (``app/data/journal_livraisons.tsv``,
   régénéré par ``scripts/journal_livraisons.py``) : chaque correction
   et nouveauté livrée, datée.
3. **Les notes de fonctionnement** du dépôt (sections ``##`` de
   ``CLAUDE.md``, lues si le fichier est présent sur le serveur).

Les correspondances trouvées sont aussi renvoyées telles quelles à
l'écran, sous la réponse : la personne voit le signalement réglé même si
l'IA le résume mal.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.help_request import HelpRequest, HelpRequestKind

_DOSSIER_DATA = Path(__file__).resolve().parents[1] / "data"
JOURNAL = _DOSSIER_DATA / "journal_livraisons.tsv"

# Mots trop courants pour départager quoi que ce soit (sans accents).
_MOTS_VIDES = {
    "avec", "sans", "pour", "dans", "vous", "nous", "leur", "leurs", "elle",
    "elles", "cette", "cela", "celui", "celle", "ceux", "celles", "alors",
    "donc", "mais", "comme", "quand", "quoi", "quel", "quels", "quelle",
    "quelles", "tout", "tous", "toute", "toutes", "plus", "moins", "encore",
    "deja", "tres", "bien", "peut", "peux", "veut", "veux", "faire", "fait",
    "faites", "savoir", "sais", "voir", "voici", "voila", "etre", "etait",
    "sont", "suis", "avoir", "avons", "avez", "ont", "est-ce", "comment",
    "pourquoi", "possible", "pouvoir", "faut", "faudrait", "devrait", "doit",
    "aussi", "apres", "avant", "ici", "lorsque", "lorsqu", "puis", "ensuite",
    "chose", "choses", "quelque", "autre", "autres", "meme", "memes", "fois",
    "juste", "seulement", "pas", "plus", "ceci", "celle-ci", "celui-ci",
    "kratos", "dans", "votre", "notre", "sur", "par", "une", "des", "les",
    "fonctionne", "fonctionnement", "marche", "bug", "bugs", "probleme",
    "problemes", "erreur", "regle", "regler", "corrige", "corriger",
    "with", "from", "that", "this", "when", "page",
}


def _sans_accents(texte: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", texte)
        if not unicodedata.combining(c)
    )


def _racine(mot: str) -> str:
    """Racine grossière : pluriel retiré, coupe à 7 lettres (« locataires »
    et « locataire », « paiements » et « paiement » se rejoignent)."""
    if len(mot) > 4 and mot[-1] in "sx":
        mot = mot[:-1]
    return mot[:7]


def mots_cles(texte: Optional[str]) -> set[str]:
    """Racines des mots significatifs (4 lettres et plus, hors mots vides)."""
    if not texte:
        return set()
    propre = _sans_accents(texte.lower())
    mots = re.findall(r"[a-z0-9]{4,}", propre)
    return {_racine(m) for m in mots if m not in _MOTS_VIDES}


def _score(question: set[str], document: set[str]) -> int:
    return len(question & document)


def _seuil(question: set[str]) -> int:
    """Une seule racine commune suffit pour une question de 1–2 mots ;
    au-delà, il en faut deux pour éviter le bruit."""
    return 1 if len(question) <= 2 else 2


# ------------------------------ Section depuis la page ------------------------------

# Préfixe de chemin (sans la langue) → section lisible. Le plus long gagne.
_SECTIONS: tuple[tuple[str, str], ...] = (
    ("/immobilier/gestion", "Immobilier · Gestion locative"),
    ("/immobilier", "Immobilier"),
    ("/entreprises/comptabilite", "Entreprises · Comptabilité"),
    ("/entreprises/rencontres", "Entreprises · Rencontres"),
    ("/entreprises/employes", "Entreprises · Employés"),
    ("/entreprises", "Entreprises"),
    ("/app/punch", "Construction · Punch"),
    ("/app/paie", "Construction · Paie"),
    ("/app/po", "Construction · Bons de commande"),
    ("/app/achats", "Construction · Achats"),
    ("/app/factures", "Construction · Facturation"),
    ("/app/soumissions", "Construction · Soumissions"),
    ("/app/projets", "Construction · Projets"),
    ("/app/agenda", "Construction · Agenda"),
    ("/app/parametres", "Paramètres"),
    ("/app", "Construction"),
    ("/prospection", "Prospection"),
    ("/telephonie", "Communication"),
    ("/dev-logiciel", "Développement logiciel"),
    ("/investisseur", "Espace investisseur"),
    ("/m", "Zone employés (mobile)"),
    ("/parametres", "Paramètres"),
    ("/dev", "Mode dev"),
)


def chemin_sans_langue(url: Optional[str]) -> str:
    """``/fr/immobilier/x?y`` → ``/immobilier/x``."""
    if not url:
        return ""
    chemin = url.split("?", 1)[0].split("#", 1)[0].strip()
    if not chemin.startswith("/"):
        chemin = "/" + chemin
    m = re.match(r"^/(fr|en)(?=/|$)", chemin)
    if m:
        chemin = chemin[m.end():] or "/"
    return chemin


def section_depuis_url(url: Optional[str]) -> Optional[str]:
    chemin = chemin_sans_langue(url)
    if not chemin or chemin == "/":
        return None
    for prefixe, libelle in _SECTIONS:
        if chemin == prefixe or chemin.startswith(prefixe + "/"):
            return libelle
    return None


# ------------------------------ Signalements ------------------------------

STATUT_LIBELLE = {
    "pending": "en attente de triage",
    "accepted": "accepté, correction prévue",
    "rejected": "refusé",
    "resolved": "réglé",
}


@dataclass
class SignalementLie:
    id: int
    status: str
    statut_libelle: str
    section: Optional[str]
    message: str
    resolution_notes: Optional[str]
    created_at: datetime
    traite_le: Optional[datetime]
    score: int


def date_traitement(rec: HelpRequest) -> Optional[datetime]:
    """Date de la décision affichée : la colonne dédiée, sinon la date
    propre au statut (signalements traités avant l'historique)."""
    if rec.traite_le is not None:
        return rec.traite_le
    if rec.status == "resolved":
        return rec.resolved_at
    if rec.status == "rejected":
        return rec.rejected_at
    if rec.status == "accepted":
        return rec.accepted_at
    return None


def _ordre_statut(status: str) -> int:
    # À pertinence égale, un signalement réglé ou refusé (réponse connue)
    # passe devant un signalement en cours.
    return {"resolved": 0, "rejected": 1, "accepted": 2, "pending": 3}.get(status, 4)


async def chercher_signalements(
    db: AsyncSession,
    texte: str,
    *,
    limite: int = 6,
    exclure_id: Optional[int] = None,
) -> list[SignalementLie]:
    question = mots_cles(texte)
    if not question:
        return []
    rows = (
        await db.execute(
            select(HelpRequest)
            .where(HelpRequest.kind == HelpRequestKind.BUG.value)
            .order_by(HelpRequest.created_at.desc())
            .limit(2000)
        )
    ).scalars().all()
    seuil = _seuil(question)
    trouves: list[SignalementLie] = []
    for r in rows:
        if exclure_id is not None and r.id == exclure_id:
            continue
        doc = mots_cles(
            " ".join(filter(None, [r.message, r.resolution_notes, r.section]))
        )
        s = _score(question, doc)
        if s < seuil:
            continue
        trouves.append(
            SignalementLie(
                id=r.id,
                status=r.status,
                statut_libelle=STATUT_LIBELLE.get(r.status, r.status),
                section=r.section or section_depuis_url(r.context_url),
                message=r.message,
                resolution_notes=r.resolution_notes,
                created_at=r.created_at,
                traite_le=date_traitement(r),
                score=s,
            )
        )
    trouves.sort(
        key=lambda x: (-x.score, _ordre_statut(x.status), -x.created_at.timestamp())
    )
    return trouves[:limite]


# ------------------------------ Journal des livraisons ------------------------------


@dataclass
class Livraison:
    date: str
    sujet: str
    score: int = 0


@lru_cache(maxsize=1)
def _journal() -> tuple[tuple[str, str, frozenset[str]], ...]:
    try:
        lignes = JOURNAL.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    out = []
    for ligne in lignes:
        date, _, sujet = ligne.partition("\t")
        if sujet:
            out.append((date, sujet, frozenset(mots_cles(sujet))))
    return tuple(out)


def chercher_livraisons(texte: str, *, limite: int = 8) -> list[Livraison]:
    question = mots_cles(texte)
    if not question:
        return []
    seuil = _seuil(question)
    trouves = [
        Livraison(date=d, sujet=s, score=_score(question, mots))
        for d, s, mots in _journal()
        if _score(question, mots) >= seuil
    ]
    # Pertinence d'abord, puis le plus récent (le journal est trié du
    # plus récent au plus ancien et le tri Python est stable).
    trouves.sort(key=lambda x: -x.score)
    return trouves[:limite]


# ------------------------------ Notes de fonctionnement (CLAUDE.md) ------------------------------


def _trouver_claude_md() -> Optional[Path]:
    for parent in Path(__file__).resolve().parents:
        candidat = parent / "CLAUDE.md"
        if candidat.is_file():
            return candidat
    return None


@lru_cache(maxsize=1)
def _sections_notes() -> tuple[tuple[str, str, frozenset[str]], ...]:
    chemin = _trouver_claude_md()
    if chemin is None:
        return ()
    try:
        texte = chemin.read_text(encoding="utf-8")
    except OSError:
        return ()
    out = []
    for bloc in re.split(r"(?m)^## ", texte)[1:]:
        titre, _, corps = bloc.partition("\n")
        titre = titre.strip()
        # Les règles de travail du dépôt ne disent rien du fonctionnement.
        if re.search(r"workflow git|structure du repo|règles ui|promotion en prod", titre, re.I):
            continue
        out.append((titre, corps.strip(), frozenset(mots_cles(titre + " " + corps))))
    return tuple(out)


def chercher_notes(texte: str, *, limite: int = 2, max_car: int = 1800) -> list[tuple[str, str]]:
    question = mots_cles(texte)
    if not question:
        return []
    seuil = max(2, _seuil(question))
    notes = sorted(
        (
            (_score(question, mots), titre, corps)
            for titre, corps, mots in _sections_notes()
        ),
        key=lambda x: -x[0],
    )
    return [
        (titre, corps if len(corps) <= max_car else corps[:max_car] + "…")
        for s, titre, corps in notes[:limite]
        if s >= seuil
    ]


# ------------------------------ Contexte pour l'IA ------------------------------


def _date(d: Optional[datetime]) -> str:
    return d.strftime("%Y-%m-%d") if d else "?"


def contexte_ia(
    signalements: Iterable[SignalementLie],
    livraisons: Iterable[Livraison],
    notes: Iterable[tuple[str, str]],
) -> str:
    blocs: list[str] = []
    sig = list(signalements)
    if sig:
        lignes = []
        for s in sig:
            ligne = (
                f"- Signalement #{s.id} ({s.statut_libelle}"
                + (f" le {_date(s.traite_le)}" if s.traite_le else "")
                + f", signalé le {_date(s.created_at)}"
                + (f", section {s.section}" if s.section else "")
                + f") : {s.message.strip()[:400]}"
            )
            if s.resolution_notes:
                ligne += f"\n  Note de traitement : {s.resolution_notes.strip()[:400]}"
            lignes.append(ligne)
        blocs.append("SIGNALEMENTS DÉJÀ FAITS (bugs et demandes) :\n" + "\n".join(lignes))
    liv = list(livraisons)
    if liv:
        blocs.append(
            "LIVRAISONS (corrections et nouveautés mises en ligne, datées) :\n"
            + "\n".join(f"- {l.date} : {l.sujet}" for l in liv)
        )
    nts = list(notes)
    if nts:
        blocs.append(
            "NOTES DE FONCTIONNEMENT :\n"
            + "\n\n".join(f"### {t}\n{c}" for t, c in nts)
        )
    return "\n\n".join(blocs)
