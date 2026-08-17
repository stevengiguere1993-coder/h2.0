"""Portail Investisseur — synchronisation des avances d'actionnaires
QuickBooks (via le projet d'optimisation de chaque compagnie).

Deux effets, AUCUNE double saisie :

1. le TOTAL des avances remplace ``profil.avances_actionnaires``
   (équité = valeur − hypothèques − avances) ;
2. chaque compte d'avances est apparié à un investisseur par NOM
   (fiche entreprise / compte utilisateur) et ses variations mensuelles
   deviennent des flux ``source=qbo`` : hausse du solde = apport,
   baisse = remboursement. Les flux qbo précédents sont remplacés
   (idempotent), les flux manuels ne sont jamais touchés.

Consommé par l'endpoint admin (bouton « Synchroniser QuickBooks ») et
par le méga-cron quotidien (`sync_all`) — les chiffres des
investisseurs restent à jour sans action manuelle.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invest_portal import (
    InvestFlux,
    InvestFluxType,
    InvestParticipation,
    InvestProjetProfil,
)
from app.models.user import User
from app.services.invest_portfolio import (
    get_or_default_profil,
    optimisation_projet_qbo,
    partner_directory,
)

log = logging.getLogger(__name__)

_MOIS_TOKENS = {
    # anglais (libellés de colonnes QBO par défaut)
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    # français
    "janv": 1, "fevr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
    "juil": 7, "aout": 8, "sept": 9, "octo": 10, "nove": 11, "dece": 12,
}


def parse_mois_qbo(label: str) -> Optional[date]:
    """« Jul 2025 » / « juil. 2025 » → date(2025, 7, 1). None si le
    libellé ne ressemble pas à un mois."""
    m = re.search(r"([A-Za-zÀ-ÿ]+)\.?\s+(\d{4})", label or "")
    if not m:
        return None
    tok = "".join(
        c
        for c in unicodedata.normalize("NFD", m.group(1).lower())
        if unicodedata.category(c) != "Mn"
    )
    for prefix, num in _MOIS_TOKENS.items():
        if tok.startswith(prefix) or (
            len(tok) >= 3 and prefix.startswith(tok)
        ):
            return date(int(m.group(2)), num, 1)
    return None


def _norm_nom(s: str) -> str:
    s = "".join(
        c
        for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


#: Mots génériques ignorés dans l'appariement par nom — ce qui reste
#: doit identifier l'actionnaire (« Forget-Léon immobilier inc. » →
#: {forget, leon}).
_STOPWORDS = {
    "inc", "ltee", "llc", "cie", "co", "les", "des", "de", "du", "la",
    "le", "et", "au", "aux", "avance", "avances", "actionnaire",
    "actionnaires", "effets", "payer", "immobilier", "immobiliers",
    "immobiliere", "investissement", "investissements", "gestion",
    "groupe", "services", "service", "compagnie", "entreprise",
    "entreprises", "holding", "holdings", "capital",
}


def _tokens(s: str) -> set[str]:
    """Jetons identifiants d'un nom (sans mots génériques). Ordre des
    mots indifférent : « Léon-Forget » ≈ « Forget-Léon immobilier »."""
    toks = {t for t in _norm_nom(s).split() if len(t) >= 3}
    identifiants = toks - _STOPWORDS
    return identifiants or toks


def _match(candidat_noms: set[frozenset], compte_tokens: set[str]) -> bool:
    """Vrai si UN des jeux de jetons du candidat est inclus dans les
    jetons du compte QBO."""
    return any(
        noms and noms <= compte_tokens for noms in candidat_noms
    )


async def sync_entreprise(db: AsyncSession, entreprise_id: int) -> dict:
    """Synchronise UNE compagnie. Retourne un dict avec ``statut`` :
    aucun_projet | sans_qbo | erreur | ok (+ apparies / non_apparies).
    Ne commit PAS — l'appelant décide."""
    p, premier = await optimisation_projet_qbo(db, entreprise_id)
    if premier is None:
        return {"statut": "aucun_projet"}
    if p is None:
        return {"statut": "sans_qbo", "projet_nom": premier.name}

    from app.services.qbo_optimisation import avances_actionnaires

    try:
        av = await avances_actionnaires(
            p.qbo_scope,
            (p.date_debut or date(2000, 1, 1)).isoformat(),
            date.today().isoformat(),
            p.avances_accounts_json,
        )
    except Exception as exc:  # noqa: BLE001 — message propre à l'UI
        log.info("invest sync-qbo entreprise #%s: %s", entreprise_id, exc)
        return {
            "statut": "erreur",
            "projet_nom": p.name,
            "erreur": str(exc)[:300],
        }

    comptes = av.get("comptes") or []
    total = float(av.get("total") or 0.0)

    # 1. Avances totales → profil (équité).
    profil = await get_or_default_profil(db, entreprise_id)
    if profil is None:
        profil = InvestProjetProfil(entreprise_id=entreprise_id)
        db.add(profil)
        await db.flush()
    profil.avances_actionnaires = round(total, 2)

    # 2. Appariement compte ↔ investisseur par JETONS de nom (ordre des
    # mots indifférent, mots génériques ignorés).
    directory = await partner_directory(db, entreprise_id)
    parts = (
        await db.execute(
            select(InvestParticipation)
            .where(InvestParticipation.entreprise_id == entreprise_id)
            .order_by(InvestParticipation.id)
        )
    ).scalars().all()
    candidats: list[tuple[InvestParticipation, set[frozenset]]] = []
    for part in parts:
        noms: set[frozenset] = set()
        dirrow = directory["by_user"].get(part.user_id)
        if dirrow:
            noms.add(frozenset(_tokens(dirrow["name"])))
        u = await db.get(User, part.user_id)
        if u:
            noms.add(
                frozenset(
                    _tokens(f"{u.first_name or ''} {u.last_name or ''}")
                )
            )
            if u.last_name and len(u.last_name) > 3:
                noms.add(frozenset(_tokens(u.last_name)))
        candidats.append((part, {n for n in noms if n}))

    # Actionnaires de la fiche SANS participation (pas de compte
    # activé) — pour expliquer où dort l'argent non synchronisé.
    part_user_ids = {p.user_id for p in parts}
    sans_participation: list[tuple[str, set[frozenset]]] = []
    for row in directory["rows"]:
        if row["user_id"] in part_user_ids and row["user_id"] is not None:
            continue
        toks = frozenset(_tokens(row["name"]))
        if toks:
            sans_participation.append((row["name"], {toks}))

    apparies: list[dict] = []
    non_apparies: list[str] = []
    sans_compte: list[dict] = []
    for compte in comptes:
        compte_tokens = _tokens(str(compte.get("nom") or ""))
        mois_rows_c = compte.get("mois") or []
        inactif = abs(float(compte.get("solde") or 0)) < 0.005 and all(
            abs(float(r.get("variation") or 0)) < 0.005
            for r in mois_rows_c
        )
        matches = [
            part
            for part, noms in candidats
            if _match(noms, compte_tokens)
        ]
        if len(matches) != 1:
            if inactif:
                continue  # compte à zéro sans mouvement — pas de bruit
            proprietaires = [
                nom
                for nom, noms in sans_participation
                if _match(noms, compte_tokens)
            ]
            if len(proprietaires) == 1:
                sans_compte.append(
                    {
                        "compte": compte.get("nom"),
                        "solde": compte.get("solde"),
                        "partenaire": proprietaires[0],
                    }
                )
            else:
                non_apparies.append(str(compte.get("nom") or "?"))
            continue
        part = matches[0]

        # Remplace les flux qbo de cette participation (idempotent).
        anciens = (
            await db.execute(
                select(InvestFlux).where(
                    InvestFlux.participation_id == part.id,
                    InvestFlux.source == "qbo",
                )
            )
        ).scalars().all()
        for f in anciens:
            await db.delete(f)

        nb = 0
        mois_rows = compte.get("mois") or []
        # Solde AVANT le premier mois affiché = apport initial (compte
        # ouvert avant la période demandée).
        if mois_rows:
            r0 = mois_rows[0]
            initial = float(r0.get("solde") or 0) - float(
                r0.get("variation") or 0
            )
            d0 = parse_mois_qbo(str(r0.get("mois") or ""))
            if abs(initial) > 0.005 and d0 is not None:
                db.add(
                    InvestFlux(
                        participation_id=part.id,
                        type=(
                            InvestFluxType.APPORT.value
                            if initial > 0
                            else InvestFluxType.REMBOURSEMENT.value
                        ),
                        montant=round(abs(initial), 2),
                        date_flux=d0,
                        note=f"QBO · {compte.get('nom')} (solde initial)",
                        source="qbo",
                    )
                )
                nb += 1
        for r in mois_rows:
            variation = float(r.get("variation") or 0)
            if abs(variation) < 0.005:
                continue
            d = parse_mois_qbo(str(r.get("mois") or ""))
            if d is None:
                continue
            db.add(
                InvestFlux(
                    participation_id=part.id,
                    type=(
                        InvestFluxType.APPORT.value
                        if variation > 0
                        else InvestFluxType.REMBOURSEMENT.value
                    ),
                    montant=round(abs(variation), 2),
                    date_flux=d,
                    note=f"QBO · {compte.get('nom')}",
                    source="qbo",
                )
            )
            nb += 1
        dirrow = directory["by_user"].get(part.user_id)
        apparies.append(
            {
                "compte": compte.get("nom"),
                "solde": compte.get("solde"),
                "participation_id": part.id,
                "investisseur": (
                    dirrow["name"] if dirrow else str(part.user_id)
                ),
                "nb_flux": nb,
            }
        )

    resultat = {
        "statut": "ok",
        "projet_nom": p.name,
        "avances_total": round(total, 2),
        "apparies": apparies,
        # Compte QBO reconnu comme appartenant à un actionnaire de la
        # fiche qui n'a PAS encore de compte investisseur activé.
        "sans_compte": sans_compte,
        "non_apparies": non_apparies,
    }
    # Résumé persistant — la console affiche l'état de la dernière
    # sync en tout temps (pas seulement dans la bannière du clic).
    import json as _json
    from datetime import datetime, timezone

    profil.qbo_sync_at = datetime.now(timezone.utc)
    profil.qbo_sync_json = _json.dumps(resultat, ensure_ascii=False)

    await db.flush()
    return resultat


async def sync_all(db: AsyncSession) -> dict:
    """Cron quotidien : synchronise toutes les compagnies qui ont un
    projet d'optimisation avec connexion QuickBooks. Best-effort — une
    compagnie en erreur ne bloque pas les autres."""
    from app.models.optimisation import OptimisationProjet

    eids = [
        row[0]
        for row in (
            await db.execute(
                select(OptimisationProjet.entreprise_id)
                .where(
                    OptimisationProjet.entreprise_id.isnot(None),
                    OptimisationProjet.qbo_scope.isnot(None),
                )
                .distinct()
            )
        ).all()
    ]
    ok = 0
    erreurs: dict[int, str] = {}
    for eid in eids:
        try:
            r = await sync_entreprise(db, eid)
            if r.get("statut") == "ok":
                ok += 1
            elif r.get("statut") == "erreur":
                erreurs[eid] = str(r.get("erreur") or "?")
        except Exception as exc:  # noqa: BLE001 — best-effort par compagnie
            erreurs[eid] = str(exc)[:200]
    return {"compagnies": len(eids), "ok": ok, "erreurs": erreurs}
