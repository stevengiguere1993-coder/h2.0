"""Smoke — backfill 2026-08-17 : baux placeholder PlexFlow « terminés »
par erreur à l'import du 12 août alors que le locataire est en place.

Un bail « termine » à date de fin FUTURE, portant la note d'import
PlexFlow, SANS bail successeur actif et qui encaisse encore (loyer
marqué payé ce mois-ci ou le mois dernier) est réactivé au boot ; un
bail remplacé par un successeur (locataire vraiment parti) ou qui
n'encaisse plus reste terminé. Le badge frontend, lui, n'affiche plus
la date contractuelle trompeuse quand elle est future.

S'y ajoute ``_candidat_selecteur`` (validation bancaire v11) : les menus
de rapprochement manuel proposent aussi les baux terminés/résiliés à fin
récente ou future — le locataire parti qui paie sa dette par Interac
doit pouvoir être confirmé sur SON bail.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
    PaiementLoyer,
)
from app.services.locatif_depart import (
    NOTE_REACTIVE_IMPORT,
    reactiver_baux_termines_a_tort,
)
from app.services.qbo_validation_loyers import _candidat_selecteur

from .conftest import TestSessionLocal

NOTE_IMPORT = "Importé de PlexFlow le 2026-06-03 — dates à confirmer."


def _seed(
    run,
    *,
    numero: str,
    paiement_recent: bool = True,
    avec_successeur: bool = False,
) -> dict:
    """Immeuble + logement + bail placeholder TERMINE (note PlexFlow,
    fin future) ; option paiement du mois courant et bail successeur."""

    today = date.today()

    async def _go() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name=f"Immeuble React {numero}",
                address=f"{numero} rue Reactivation",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id,
                numero=numero,
                status=LogementStatus.OCCUPE.value,
            )
            s.add(lg)
            await s.flush()
            loc = Locataire(full_name=f"Locataire React {numero}")
            s.add(loc)
            await s.flush()
            bail = Bail(
                logement_id=lg.id,
                locataire_id=loc.id,
                date_debut=today.replace(day=1) - timedelta(days=90),
                date_fin=today + timedelta(days=200),
                loyer_mensuel=800.0,
                status=BailStatus.TERMINE.value,
                notes=NOTE_IMPORT,
            )
            s.add(bail)
            await s.flush()
            if paiement_recent:
                s.add(
                    PaiementLoyer(
                        bail_id=bail.id,
                        mois_couvert=today.replace(day=1),
                        montant=800.0,
                        paye_le=today,
                        created_at=datetime.now(timezone.utc),
                    )
                )
            if avec_successeur:
                loc2 = Locataire(full_name=f"Successeur {numero}")
                s.add(loc2)
                await s.flush()
                s.add(
                    Bail(
                        logement_id=lg.id,
                        locataire_id=loc2.id,
                        date_debut=today.replace(day=1),
                        date_fin=today + timedelta(days=365),
                        loyer_mensuel=850.0,
                        status=BailStatus.ACTIF.value,
                    )
                )
            await s.commit()
            return {"bail_id": bail.id, "logement_id": lg.id}

    return run(_go())


def _reactiver(run) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            n = await reactiver_baux_termines_a_tort(s)
            await s.commit()
            return n

    return run(_go())


def _bail(run, bail_id: int) -> Bail:
    async def _go():
        async with TestSessionLocal() as s:
            return await s.get(Bail, bail_id)

    return run(_go())


def test_bail_vivant_termine_a_tort_est_reactive(run, db_setup):
    ids = _seed(run, numero="R-1", paiement_recent=True)
    n = _reactiver(run)
    assert n >= 1
    bail = _bail(run, ids["bail_id"])
    assert bail.status == BailStatus.ACTIF.value
    assert NOTE_REACTIVE_IMPORT in (bail.notes or "")

    # Idempotent : un second passage ne retouche pas ce bail.
    _reactiver(run)
    bail2 = _bail(run, ids["bail_id"])
    assert bail2.status == BailStatus.ACTIF.value
    assert (bail2.notes or "").count(NOTE_REACTIVE_IMPORT) == 1


def test_bail_remplace_par_un_successeur_reste_termine(run, db_setup):
    ids = _seed(
        run, numero="R-2", paiement_recent=True, avec_successeur=True
    )
    _reactiver(run)
    bail = _bail(run, ids["bail_id"])
    assert bail.status == BailStatus.TERMINE.value


def test_bail_sans_encaissement_recent_reste_termine(run, db_setup):
    ids = _seed(run, numero="R-3", paiement_recent=False)
    _reactiver(run)
    bail = _bail(run, ids["bail_id"])
    assert bail.status == BailStatus.TERMINE.value


def test_candidat_selecteur_inclut_les_termines_recents(run, db_setup):
    today = date.today()

    def bail(status: str, fin: date | None) -> Bail:
        return Bail(
            logement_id=1,
            locataire_id=1,
            date_debut=today - timedelta(days=400),
            date_fin=fin,
            loyer_mensuel=700.0,
            status=status,
        )

    assert _candidat_selecteur(bail(BailStatus.ACTIF.value, None))
    # Terminé à fin récente ou future : proposé (dette payée après coup).
    assert _candidat_selecteur(
        bail(BailStatus.TERMINE.value, today - timedelta(days=10))
    )
    assert _candidat_selecteur(
        bail(BailStatus.RESILIE.value, today + timedelta(days=200))
    )
    # Vieux bail terminé : hors menu.
    assert not _candidat_selecteur(
        bail(BailStatus.TERMINE.value, today - timedelta(days=180))
    )
    assert not _candidat_selecteur(
        bail(BailStatus.PROPOSE.value, today + timedelta(days=100))
    )
