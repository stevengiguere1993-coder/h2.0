"""Service UNIQUE du cycle « départ d'un locataire » (vague 1, 2026-08-13).

Avant : 9 portes déclaraient un départ, chacune à sa façon — « Départ » /
« Non renouvelé » créaient un dossier complet mais ne fermaient jamais le
bail ; « Mettre fin au bail » fermait le bail mais laissait un dossier
vide et ne touchait pas au statut du logement ; la réponse publique
« je quitte » laissait le bail actif. Résultat : baux zombies, logements
« occupés » à vie, faux « réputé accepté » un mois plus tard.

Désormais TOUTES les portes qui connaissent le bail sortant passent par
``declarer_depart`` :
  1. ferme le bail (résilié si la date est passée, sinon la date de fin
     est posée et le recalage lazy le terminera à l'échéance) ;
  2. recale le statut du logement (occupe/reserve/vacant, jamais
     hors_location) ;
  3. crée OU COMPLÈTE le dossier de relocation (fill-only : on ne
     remplit que les champs vides d'un dossier existant, sauf
     ``date_depart`` qui est resynchronisée si la résiliation la
     change) ;
  4. passe le cycle de renouvellement courant à « depart » + reponse_le
     (tue le faux « réputé accepté »).

S'y ajoutent :
  - ``reconduire_tacitement_baux_echus`` : reconduction tacite AUTOMATIQUE
    (décision Phil 2026-08-13, aligne l'art. 1941 C.c.Q.) — lazy, à la
    consultation des vues, jamais de cron ni d'envoi au locataire ;
  - ``terminer_baux_echus_avant`` : garde-fou « deux baux actifs » — un
    bail actif ÉCHU est terminé automatiquement à l'arrivée du bail
    suivant (une seule ligne dans le suivi des loyers).

AUCUN envoi de courriel ici — règle absolue du pôle.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.immobilier import (
    Bail,
    BailRenouvellement,
    BailStatus,
    Immeuble,
    LocationDossier,
    LocationDossierStatut,
    Logement,
    LogementStatus,
)

log = logging.getLogger(__name__)

#: Statuts de dossier de relocation « réglés » — tout le reste est ACTIF
#: (même garde-fou que POST /immobilier/locations).
DOSSIER_STATUTS_REGLES = (
    LocationDossierStatut.ANNULE.value,
    LocationDossierStatut.RELOUE.value,
)

NOTE_RECONDUCTION_AUTO = (
    "Reconduction tacite automatique (aucune réponse à l'échéance)"
)
NOTE_TERMINE_BAIL_SUIVANT = (
    "Terminé automatiquement à l'arrivée du bail suivant"
)
NOTE_TERMINE_DEPART_ANNONCE = (
    "Terminé automatiquement à l'échéance — départ annoncé "
    "(dossier de relocation actif)"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _append_note(existant: Optional[str], ajout: str) -> str:
    """Ajoute une ligne aux notes sans écraser ni dupliquer."""
    if not existant:
        return ajout
    if ajout in existant:
        return existant
    return f"{existant}\n{ajout}"


async def dossier_relocation_actif(
    db: AsyncSession, logement_id: int
) -> Optional[LocationDossier]:
    """Dossier de relocation ACTIF du logement (garde-fou existant)."""
    return (
        await db.execute(
            select(LocationDossier).where(
                LocationDossier.logement_id == logement_id,
                LocationDossier.statut.notin_(list(DOSSIER_STATUTS_REGLES)),
            )
        )
    ).scalars().first()


async def recaler_statut_logement(
    db: AsyncSession, logement_id: int
) -> None:
    """Statut du logement recalculé d'après ses baux :

    - OCCUPE si un bail ACTIF couvre aujourd'hui (un bail AU MOIS court
      sans égard à sa date de fin) ;
    - RESERVE si un bail proposé/actif commence plus tard ;
    - VACANT sinon.

    Ne touche JAMAIS un logement HORS_LOC (rénovation, proprio-occupé…).
    Le filtrage se fait en mémoire pour voir les changements de statut
    non encore flushés (autoflush désactivé sur la session).
    """
    lg = await db.get(Logement, logement_id)
    if lg is None or lg.status == LogementStatus.HORS_LOC.value:
        return
    today = date.today()
    baux = (
        await db.execute(
            select(Bail).where(Bail.logement_id == logement_id)
        )
    ).scalars().all()
    occupe = any(
        b.status == BailStatus.ACTIF.value
        and b.date_debut is not None
        and b.date_debut <= today
        and (b.au_mois or (b.date_fin is not None and b.date_fin >= today))
        for b in baux
    )
    reserve = any(
        b.status in (BailStatus.ACTIF.value, BailStatus.PROPOSE.value)
        and b.date_debut is not None
        and b.date_debut > today
        for b in baux
    )
    if occupe:
        nouveau = LogementStatus.OCCUPE.value
    elif reserve:
        nouveau = LogementStatus.RESERVE.value
    else:
        nouveau = LogementStatus.VACANT.value
    if lg.status != nouveau:
        lg.status = nouveau
        lg.updated_at = _now()


async def _basculer_cycle_en_depart(db: AsyncSession, bail: Bail) -> None:
    """Cycle de renouvellement COURANT du bail → « depart » + reponse_le
    (le locataire a annoncé son départ : plus jamais de « réputé
    accepté » sur ce cycle)."""
    from app.services.bail_renouvellement import est_cycle_courant

    today = date.today()
    rows = (
        await db.execute(
            select(BailRenouvellement)
            .where(BailRenouvellement.bail_id == bail.id)
            .order_by(BailRenouvellement.avis_envoye_le.desc())
        )
    ).scalars().all()
    for r in rows:
        if not est_cycle_courant(r, bail.date_fin, today):
            continue
        if r.status != "depart":
            r.status = "depart"
            if r.reponse_le is None:
                r.reponse_le = today
            r.updated_at = _now()
        return


async def declarer_depart(
    db: AsyncSession,
    bail_id: int,
    *,
    date_depart: Optional[date] = None,
    loyer_demande: Optional[float] = None,
    source: str,
    ouvrir_dossier: bool = True,
) -> Optional[LocationDossier]:
    """Point d'entrée UNIQUE d'un départ de locataire (bail connu).

    ``date_depart`` : défaut = la fin du bail (le locataire part à
    l'échéance). Passée ou aujourd'hui → le bail est résilié tout de
    suite ; future → le bail reste actif jusqu'à cette date (posée en
    ``date_fin``), le recalage lazy le terminera à l'échéance.

    ``source`` : consigné dans les notes du dossier (traçabilité —
    ex. « Résiliation immédiate », « Réponse signée du locataire »).

    Retourne le dossier de relocation (créé ou complété), ou None si le
    bail est introuvable / ``ouvrir_dossier=False``.
    """
    bail = await db.get(Bail, bail_id)
    if bail is None:
        return None
    today = date.today()
    if date_depart is None:
        date_depart = bail.date_fin

    # 1) Fermer le bail (seul un bail ACTIF se ferme — on ne ressuscite
    #    ni ne re-date un bail déjà terminé/résilié).
    if bail.status == BailStatus.ACTIF.value and date_depart is not None:
        if bail.date_fin != date_depart:
            bail.date_fin = date_depart
        if date_depart <= today:
            bail.status = BailStatus.RESILIE.value
        bail.updated_at = _now()

    # 2) Cycle de renouvellement courant → « depart ».
    await _basculer_cycle_en_depart(db, bail)

    # 3) Dossier de relocation : créer OU compléter (fill-only).
    dossier: Optional[LocationDossier] = None
    if ouvrir_dossier and bail.logement_id:
        loyer_ancien = (
            float(bail.loyer_mensuel)
            if bail.loyer_mensuel is not None
            else None
        )
        loyer_dem = (
            float(loyer_demande) if loyer_demande is not None else loyer_ancien
        )
        dossier = await dossier_relocation_actif(db, bail.logement_id)
        if dossier is None:
            dossier = LocationDossier(
                logement_id=bail.logement_id,
                bail_id=bail.id,
                statut=LocationDossierStatut.AVIS_RECU.value,
                date_depart=date_depart,
                loyer_ancien=loyer_ancien,
                loyer_demande=loyer_dem,
                notes=source or None,
            )
            dossier.created_at = _now()
            dossier.updated_at = _now()
            db.add(dossier)
        else:
            # Fill-only : ne remplir QUE les champs vides — sauf
            # date_depart, resynchronisée si la résiliation la change
            # (trou M5 : dossier ouvert « à l'échéance », puis entente
            # de départ anticipé → la date du dossier doit suivre).
            if dossier.bail_id is None:
                dossier.bail_id = bail.id
            if dossier.loyer_ancien is None:
                dossier.loyer_ancien = loyer_ancien
            if dossier.loyer_demande is None:
                dossier.loyer_demande = loyer_dem
            if date_depart is not None and dossier.date_depart != date_depart:
                dossier.date_depart = date_depart
            if source:
                dossier.notes = _append_note(dossier.notes, source)
            dossier.updated_at = _now()

    # 4) Recaler le logement + miroir « loyer demandé » (2026-08-13) :
    #    logement VACANT → le prix affiché pour la relocation (porté par
    #    le dossier) fait foi sur la fiche.
    if bail.logement_id:
        await recaler_statut_logement(db, bail.logement_id)
        if dossier is not None and dossier.loyer_demande is not None:
            lg = await db.get(Logement, bail.logement_id)
            if (
                lg is not None
                and lg.status == LogementStatus.VACANT.value
            ):
                lg.loyer_demande = dossier.loyer_demande

    log.info(
        "Départ déclaré (bail %s, date %s, source « %s ») — bail %s",
        bail_id, date_depart, source, bail.status,
    )
    return dossier


def _fin_reconduite_apres(
    date_debut: Optional[date], date_fin: date, today: date
) -> date:
    """Fin de la période reconduite, répétée jusqu'à couvrir aujourd'hui
    (bail échu depuis plusieurs cycles → UNE ligne de rattrapage).
    Art. 1941 C.c.Q. : 12 mois et plus → reconduit 12 mois ; plus court
    → même durée."""
    duree = (date_fin - date_debut).days if date_debut else 365

    def _suivante(fin: date) -> date:
        if duree >= 360:
            try:
                return fin.replace(year=fin.year + 1)
            except ValueError:  # 29 février
                return fin.replace(year=fin.year + 1, day=28)
        return fin + timedelta(days=max(duree, 27) + 1)

    nouvelle = _suivante(date_fin)
    for _ in range(200):  # garde anti-boucle (données dégénérées)
        if nouvelle >= today:
            break
        nouvelle = _suivante(nouvelle)
    return nouvelle


async def reconduire_tacitement_baux_echus(
    db: AsyncSession, baux: Iterable[Bail]
) -> bool:
    """Reconduction tacite AUTOMATIQUE des baux échus — LAZY, déclenchée
    à la consultation (loyers, page Baux, renouvellements). Aucun cron,
    aucun envoi.

    Un bail ACTIF dont la fin est passée :
    - avec un dossier de relocation ACTIF sur son logement → le départ
      était annoncé : le bail se TERMINE à sa date de fin, logement
      recalé ;
    - sans réponse « depart »/« refuse » et sans cycle de renouvellement
      en cours → reconduit tel quel (cycle « reconduit », date de fin
      étirée — même logique que le bouton « Reconduire tel quel ») ;
    - avec un cycle en cours (avis envoyé, négociation, refus…) → on ne
      touche à rien, la machine à états des renouvellements décide.

    Exclusions : baux AU MOIS (reconduits par nature), logements « louer
    indéfiniment (chambres) », immeubles en gestion externe.

    Retourne True (et commit) si quelque chose a changé.
    """
    from app.services.bail_renouvellement import est_cycle_courant

    today = date.today()
    candidats = [
        b
        for b in baux
        if b.status == BailStatus.ACTIF.value
        and b.date_fin is not None
        and b.date_fin < today
        and not b.au_mois
    ]
    if not candidats:
        return False

    log_ids = {b.logement_id for b in candidats if b.logement_id}
    log_by_id = {
        lg.id: lg
        for lg in (
            await db.execute(
                select(Logement).where(Logement.id.in_(list(log_ids)))
            )
        ).scalars().all()
    } if log_ids else {}
    imm_ids = {lg.immeuble_id for lg in log_by_id.values() if lg.immeuble_id}
    imm_by_id = {
        im.id: im
        for im in (
            await db.execute(
                select(Immeuble).where(Immeuble.id.in_(list(imm_ids)))
            )
        ).scalars().all()
    } if imm_ids else {}

    # Dossier de relocation ACTIF par logement.
    dossier_by_log: dict[int, LocationDossier] = {}
    if log_ids:
        for d in (
            await db.execute(
                select(LocationDossier).where(
                    LocationDossier.logement_id.in_(list(log_ids)),
                    LocationDossier.statut.notin_(
                        list(DOSSIER_STATUTS_REGLES)
                    ),
                )
            )
        ).scalars().all():
            dossier_by_log[d.logement_id] = d

    # Dernier renouvellement par bail (même sémantique que les vues).
    last_ren_by_bail: dict[int, BailRenouvellement] = {}
    bail_ids = [b.id for b in candidats]
    for r in (
        await db.execute(
            select(BailRenouvellement).where(
                BailRenouvellement.bail_id.in_(bail_ids)
            )
        )
    ).scalars().all():
        cur = last_ren_by_bail.get(r.bail_id)
        if cur is None or (r.avis_envoye_le, r.id) > (
            cur.avis_envoye_le,
            cur.id,
        ):
            last_ren_by_bail[r.bail_id] = r

    dirty = False
    for b in candidats:
        lg = log_by_id.get(b.logement_id)
        if lg is None or getattr(lg, "location_en_chambres", False):
            continue  # « louer indéfiniment » — jamais de cycle
        im = imm_by_id.get(lg.immeuble_id)
        if im is not None and getattr(im, "gestion_externe", None):
            continue  # gestion externe — le tiers décide

        dossier = dossier_by_log.get(b.logement_id)
        if dossier is not None:
            # Le départ était annoncé : le bail se termine à sa fin.
            b.status = BailStatus.TERMINE.value
            b.notes = _append_note(b.notes, NOTE_TERMINE_DEPART_ANNONCE)
            b.updated_at = _now()
            await recaler_statut_logement(db, b.logement_id)
            if (
                dossier.loyer_demande is not None
                and lg.status == LogementStatus.VACANT.value
            ):
                lg.loyer_demande = dossier.loyer_demande
            dirty = True
            log.info(
                "Bail %s terminé à l'échéance (départ annoncé, "
                "dossier %s)", b.id, dossier.id,
            )
            continue

        last_ren = last_ren_by_bail.get(b.id)
        if last_ren is not None and est_cycle_courant(
            last_ren, b.date_fin, today
        ):
            # Avis en cours, refus, négociation… : la machine à états
            # des renouvellements garde la main — pas de reconduction.
            continue

        ancienne = b.date_fin
        nouvelle = _fin_reconduite_apres(b.date_debut, ancienne, today)
        b.date_fin = nouvelle
        b.updated_at = _now()
        ren = BailRenouvellement(
            bail_id=b.id,
            avis_envoye_le=today,
            nouveau_loyer=b.loyer_mensuel,
            nouvelle_date_debut=ancienne + timedelta(days=1),
            nouvelle_date_fin=nouvelle,
            status="reconduit",
            notes=NOTE_RECONDUCTION_AUTO,
        )
        ren.created_at = _now()
        ren.updated_at = _now()
        db.add(ren)
        dirty = True
        log.info(
            "Bail %s reconduit tacitement (auto) : %s → %s",
            b.id, ancienne, nouvelle,
        )

    if dirty:
        await db.commit()
    return dirty


async def terminer_baux_echus_avant(
    db: AsyncSession,
    logement_id: int,
    date_debut: Optional[date],
    exclure_bail_id: Optional[int] = None,
) -> int:
    """Garde-fou « deux baux actifs » (C4) : à l'arrivée d'un bail actif
    sur un logement, tout bail ACTIF déjà ÉCHU (sa fin précède le début
    du nouveau) passe « termine » automatiquement — sinon les deux
    coexistent et le suivi des loyers double la ligne.

    Un bail actif NON échu qui chevauche reste bloqué par le 409
    existant (ce n'est pas le rôle de ce helper). Baux AU MOIS et
    logements « louer indéfiniment » exclus (ils courent sans égard à
    leur date de fin).
    """
    if date_debut is None:
        return 0
    lg = await db.get(Logement, logement_id)
    if lg is not None and getattr(lg, "location_en_chambres", False):
        return 0
    q = select(Bail).where(
        Bail.logement_id == logement_id,
        Bail.status == BailStatus.ACTIF.value,
        Bail.date_fin < date_debut,
    )
    if exclure_bail_id is not None:
        q = q.where(Bail.id != exclure_bail_id)
    n = 0
    for b in (await db.execute(q)).scalars().all():
        if b.au_mois:
            continue
        b.status = BailStatus.TERMINE.value
        b.notes = _append_note(b.notes, NOTE_TERMINE_BAIL_SUIVANT)
        b.updated_at = _now()
        n += 1
        log.info(
            "Bail %s (échu le %s) terminé automatiquement — bail "
            "suivant au %s", b.id, b.date_fin, date_debut,
        )
    return n
