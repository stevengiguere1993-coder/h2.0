"""Consignes à Kratos pour les rencontres (2026-11-13).

Steven : « j'aimerais que les tableaux, les résumés et les bilans
s'ajustent à travers le temps selon mes différentes demandes de
modifications pour amener le tout comme je veux ».

Chaque demande de modification est RETENUE (table
``rencontre_consignes``) et redonnée à l'IA à chaque passage suivant :
résumé d'une section, résumé global (dont le rapport envoyé découle),
détection des dossiers, passe de doublons, réponses de « Demander à
Kratos ». Une consigne a une portée : ``resumes`` (résumés et rapports),
``dossiers`` (tableau des dossiers) ou ``tout``. Elle se désactive ou se
supprime ; rien n'est appris en cachette.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from app.models.rencontre_dossier import PORTEES_CONSIGNE, RencontreConsigne

#: Garde-fous de taille : le bloc part dans chaque prompt.
MAX_CONSIGNES = 40
MAX_CARACTERES = 4000


async def consignes_actives(db, portee: str) -> list[RencontreConsigne]:
    """Consignes actives qui s'appliquent à ``portee`` (celles de la
    portée + celles « tout »), de la plus ancienne à la plus récente :
    la plus récente a le dernier mot en cas de contradiction."""
    portees = {"tout", portee} if portee in PORTEES_CONSIGNE else {"tout"}
    rows = (
        await db.execute(
            select(RencontreConsigne)
            .where(
                RencontreConsigne.actif.is_(True),
                RencontreConsigne.portee.in_(portees),
            )
            .order_by(RencontreConsigne.id.desc())
            .limit(MAX_CONSIGNES)
        )
    ).scalars().all()
    return list(reversed(rows))


def bloc_depuis(consignes: list[RencontreConsigne]) -> str:
    """Bloc de prompt. Chaîne vide s'il n'y a aucune consigne."""
    lignes: list[str] = []
    total = 0
    # Les plus récentes d'abord pour la coupe, puis remises en ordre.
    for c in reversed(consignes):
        t = " ".join((c.texte or "").split())
        if not t:
            continue
        if total + len(t) > MAX_CARACTERES:
            break
        total += len(t)
        lignes.append(f"- {t}")
    if not lignes:
        return ""
    lignes.reverse()
    return (
        "## Consignes permanentes du dirigeant\n"
        "Ce sont ses demandes de modification, de la plus ancienne à la "
        "plus récente. Respecte-les EN PRIORITÉ sur tes règles de forme "
        "habituelles ; si deux se contredisent, la plus récente gagne. "
        "Elles ne t'autorisent jamais à inventer un fait.\n"
        + "\n".join(lignes)
        + "\n\n"
    )


async def bloc_consignes(db, portee: str) -> str:
    """Bloc de prompt des consignes actives pour ``portee`` ; jamais
    bloquant (table absente, erreur de lecture → chaîne vide)."""
    try:
        return bloc_depuis(await consignes_actives(db, portee))
    except Exception:  # noqa: BLE001
        return ""


def public(c: RencontreConsigne) -> dict:
    return {
        "id": c.id,
        "portee": c.portee,
        "texte": c.texte,
        "actif": bool(c.actif),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


async def ajouter(
    db, *, texte: str, portee: str = "tout", user_id: Optional[int] = None
) -> RencontreConsigne:
    c = RencontreConsigne(
        texte=texte.strip(),
        portee=portee if portee in PORTEES_CONSIGNE else "tout",
        actif=True,
        created_by_user_id=user_id,
    )
    db.add(c)
    await db.flush()
    return c
