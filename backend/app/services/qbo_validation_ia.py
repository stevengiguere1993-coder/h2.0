"""Suggestions IA pour la validation bancaire des loyers (v7).

L'IA ne VALIDE JAMAIS : elle PRÉ-SÉLECTIONNE le bail le plus probable
pour les transactions que le rapprochement déterministe laisse
ambiguës ou non rapprochées — l'humain confirme d'un clic, et la
confirmation apprend l'alias payeur : l'IA sert donc de moins en moins
avec le temps. Décision Phil 2026-08-17 (« il va falloir changer
quelque chose ») après la v6 déterministe.

Cascade GRATUITE ``app.integrations.ai`` (Gemini → Anthropic → Groq),
UN SEUL appel batché par synchro, fail-quiet : sans clé configurée ou
en cas d'erreur, aucune suggestion — rien ne casse, le flux
déterministe reste intact.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.integrations.ai import AIProviderError, complete, is_configured
from app.models.immobilier import Locataire
from app.models.qbo_loyers import QboAliasPayeur, QboCompteLoyer, QboTransactionLoyer
from app.services.qbo_validation_loyers import (
    FENETRE_SYNC_JOURS,
    _baux_des_immeubles,
    immeubles_du_compte,
    liens_par_compte,
)

log = logging.getLogger(__name__)

#: Borne d'un lot (le prompt reste court, l'appel reste rapide).
_MAX_TXNS_PAR_LOT = 40

_SYSTEM = (
    "Tu rapproches des virements de loyers (souvent Interac) à des baux "
    "d'immeubles locatifs au Québec. Pour chaque transaction, choisis le "
    "bail candidat le plus probable, ou null si vraiment incertain.\n"
    "Indices à utiliser :\n"
    "- le nom du payeur Interac est souvent TRONQUÉ (~14 caractères) ;\n"
    "- un conjoint, un colocataire ou un parent peut payer (nom de "
    "famille différent) ;\n"
    "- le montant colle souvent au loyer mensuel (ou à un multiple, ou "
    "à un montant partiel) ;\n"
    "- les alias appris (provenances déjà confirmées par un humain) "
    "sont fiables.\n"
    "Réponds UNIQUEMENT avec un tableau JSON strict :\n"
    '[{"txn_id": <int>, "bail_id": <int|null>, "confiance": <0..1>}]'
)


def _parse_json_tableau(raw: str) -> Optional[List[Dict[str, Any]]]:
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        data = json.loads(s)
    except ValueError:
        start, end = s.find("["), s.rfind("]")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(s[start : end + 1])
        except ValueError:
            return None
    return data if isinstance(data, list) else None


async def suggerer_ia(db) -> int:
    """Pose ``suggestion_bail_id``/``suggestion_confiance`` sur les
    transactions ambiguës/non rapprochées qui n'en ont pas encore.
    Retourne le nombre de suggestions posées. Ne commit pas."""
    if not is_configured():
        return 0

    plancher = (
        datetime.now(timezone.utc).date()
        - timedelta(days=FENETRE_SYNC_JOURS)
    )
    txns = list(
        (
            await db.execute(
                select(QboTransactionLoyer)
                .where(
                    QboTransactionLoyer.sens == "entree",
                    QboTransactionLoyer.statut.in_(
                        ["ambigu", "non_rapproche"]
                    ),
                    QboTransactionLoyer.suggestion_bail_id.is_(None),
                    QboTransactionLoyer.date_txn >= plancher,
                )
                .order_by(QboTransactionLoyer.date_txn.desc())
                .limit(_MAX_TXNS_PAR_LOT)
            )
        ).scalars().all()
    )
    if not txns:
        return 0

    # Candidats par transaction = baux des immeubles couverts par SON
    # compte (même périmètre que le rapprochement déterministe).
    liens = await liens_par_compte(db)
    comptes = {
        c.id: c
        for c in (
            await db.execute(select(QboCompteLoyer))
        ).scalars().all()
    }
    candidats_par_compte: Dict[int, List[Dict[str, Any]]] = {}
    baux_valides_par_compte: Dict[int, set] = {}
    locataires: Dict[int, str] = {}
    for compte_id in {t.compte_id for t in txns}:
        compte = comptes.get(compte_id)
        if compte is None:
            continue
        imm_ids = await immeubles_du_compte(db, compte, liens)
        baux, _lg = await _baux_des_immeubles(db, imm_ids)
        ids_loc = [b.locataire_id for b in baux if b.locataire_id]
        if ids_loc:
            for lid, nom in (
                await db.execute(
                    select(Locataire.id, Locataire.full_name).where(
                        Locataire.id.in_(ids_loc)
                    )
                )
            ).all():
                locataires[int(lid)] = nom or ""
        candidats_par_compte[compte_id] = [
            {
                "bail_id": b.id,
                "locataire": locataires.get(b.locataire_id or 0, ""),
                "loyer": float(b.loyer_mensuel or 0),
            }
            for b in baux
        ]
        baux_valides_par_compte[compte_id] = {b.id for b in baux}

    aliases = [
        {"texte": a.texte_normalise, "bail_id": a.bail_id}
        for a in (
            await db.execute(select(QboAliasPayeur))
        ).scalars().all()
    ]

    lot = [
        {
            "txn_id": t.id,
            "date": t.date_txn.isoformat(),
            "montant": float(t.montant or 0),
            "payeur": t.payeur or "",
            "memo": (t.description or "")[:120],
            "candidats": candidats_par_compte.get(t.compte_id, []),
        }
        for t in txns
        if candidats_par_compte.get(t.compte_id)
    ]
    if not lot:
        return 0

    prompt = (
        "## Alias appris (provenance confirmée par un humain)\n"
        + json.dumps(aliases, ensure_ascii=False)
        + "\n\n## Transactions à rapprocher (avec leurs candidats)\n"
        + json.dumps(lot, ensure_ascii=False)
        + "\n\nRetourne le tableau JSON."
    )
    try:
        res = await complete(
            prompt=prompt,
            system=_SYSTEM,
            max_tokens=2000,
            temperature=0.0,
        )
    except AIProviderError as exc:
        log.warning("Suggestions IA loyers indisponibles : %s", exc)
        return 0
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        log.warning("Suggestions IA loyers, erreur inattendue : %s", exc)
        return 0

    parsed = _parse_json_tableau(res.text)
    if not parsed:
        log.warning("Suggestions IA loyers : réponse illisible")
        return 0

    par_id = {t.id: t for t in txns}
    posees = 0
    for item in parsed:
        if not isinstance(item, dict):
            continue
        txn = par_id.get(item.get("txn_id"))
        bail_id = item.get("bail_id")
        if txn is None or not isinstance(bail_id, int):
            continue
        # GARDE-FOU : la suggestion doit viser un bail RÉELLEMENT
        # candidat de cette transaction — jamais de pronostic hors champ.
        if bail_id not in baux_valides_par_compte.get(txn.compte_id, set()):
            continue
        try:
            confiance = float(item.get("confiance") or 0)
        except (TypeError, ValueError):
            confiance = 0.0
        txn.suggestion_bail_id = bail_id
        txn.suggestion_confiance = max(0.0, min(1.0, round(confiance, 2)))
        posees += 1
    if posees:
        await db.flush()
    return posees
