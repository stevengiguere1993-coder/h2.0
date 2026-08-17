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

from sqlalchemy import select

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
    NOTE_FIN_RECALEE,
    NOTE_PAIEMENT_REDATE,
    NOTE_REACTIVE_IMPORT,
    reactiver_baux_termines_a_tort,
    recaler_fins_baux_placeholder,
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


# ── v13 : dates de fin placeholder recalées sur le successeur ──────────


def _seed_avec_successeur(
    run,
    *,
    numero: str,
    debut_successeur: date,
    mois_paiement: date | None,
    paiement_dernier_mois: bool = False,
    note: str = NOTE_IMPORT,
) -> dict:
    """Bail placeholder TERMINÉ à fin future + bail successeur ACTIF
    déjà commencé. ``mois_paiement`` : mois du paiement resté sur
    l'ancien bail ; ``paiement_dernier_mois`` ajoute en plus un
    paiement sur le dernier mois réel (cas « déjà payé »)."""

    today = date.today()

    async def _go() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name=f"Immeuble Fin {numero}",
                address=f"{numero} rue Placeholder",
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
            loc = Locataire(full_name=f"Ancien {numero}")
            s.add(loc)
            await s.flush()
            ancien = Bail(
                logement_id=lg.id,
                locataire_id=loc.id,
                date_debut=debut_successeur - timedelta(days=60),
                date_fin=today + timedelta(days=300),
                loyer_mensuel=400.0,
                status=BailStatus.TERMINE.value,
                notes=note,
            )
            s.add(ancien)
            await s.flush()
            if mois_paiement is not None:
                s.add(
                    PaiementLoyer(
                        bail_id=ancien.id,
                        mois_couvert=mois_paiement,
                        montant=400.0,
                        paye_le=today,
                        created_at=datetime.now(timezone.utc),
                    )
                )
            if paiement_dernier_mois:
                s.add(
                    PaiementLoyer(
                        bail_id=ancien.id,
                        mois_couvert=(
                            debut_successeur - timedelta(days=1)
                        ).replace(day=1),
                        montant=400.0,
                        paye_le=today - timedelta(days=30),
                        created_at=datetime.now(timezone.utc),
                    )
                )
            loc2 = Locataire(full_name=f"Successeur {numero}")
            s.add(loc2)
            await s.flush()
            s.add(
                Bail(
                    logement_id=lg.id,
                    locataire_id=loc2.id,
                    date_debut=debut_successeur,
                    date_fin=debut_successeur + timedelta(days=364),
                    loyer_mensuel=450.0,
                    status=BailStatus.ACTIF.value,
                )
            )
            await s.commit()
            return {"bail_id": ancien.id, "logement_id": lg.id}

    return run(_go())


def _recaler(run) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            n = await recaler_fins_baux_placeholder(s)
            await s.commit()
            return n

    return run(_go())


def _paiements(run, bail_id: int):
    async def _go():
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(PaiementLoyer).where(
                        PaiementLoyer.bail_id == bail_id
                    )
                )
            ).scalars().all()

    return run(_go())


def test_fin_recalee_et_paiement_redate_au_dernier_mois(run, db_setup):
    """Le bail se termine la veille de l'arrivée du successeur, et le
    paiement resté sur un mois non couvert glisse au dernier mois réel
    (qui était libre)."""
    today = date.today()
    debut_succ = today.replace(day=1)
    mois_hors = debut_succ  # mois du successeur, plus couvert
    ids = _seed_avec_successeur(
        run,
        numero="F-1",
        debut_successeur=debut_succ,
        mois_paiement=mois_hors,
    )
    assert _recaler(run) >= 1
    bail = _bail(run, ids["bail_id"])
    assert bail.date_fin == debut_succ - timedelta(days=1)
    assert NOTE_FIN_RECALEE in (bail.notes or "")
    ps = _paiements(run, ids["bail_id"])
    assert len(ps) == 1
    assert ps[0].mois_couvert == (debut_succ - timedelta(days=1)).replace(
        day=1
    )
    assert NOTE_PAIEMENT_REDATE in (ps[0].notes or "")

    # Idempotent : la fin est passée, plus rien à recaler.
    _recaler(run)
    assert _bail(run, ids["bail_id"]).date_fin == (
        debut_succ - timedelta(days=1)
    )


def test_paiement_laisse_quand_le_dernier_mois_est_deja_paye(
    run, db_setup
):
    """Zéro invention : si le dernier mois réel a déjà son paiement, le
    paiement orphelin reste où il est (trop-payé à arbitrer)."""
    today = date.today()
    debut_succ = today.replace(day=1)
    ids = _seed_avec_successeur(
        run,
        numero="F-2",
        debut_successeur=debut_succ,
        mois_paiement=debut_succ,
        paiement_dernier_mois=True,
    )
    _recaler(run)
    bail = _bail(run, ids["bail_id"])
    assert bail.date_fin == debut_succ - timedelta(days=1)
    mois = {p.mois_couvert for p in _paiements(run, ids["bail_id"])}
    # Le paiement orphelin n'a PAS bougé (les deux mois coexistent).
    assert debut_succ in mois


def test_resiliation_legitime_a_date_future_non_touchee(run, db_setup):
    """Garde-fou : un bail résilié pour une date future SANS note
    d'import (départ annoncé pour plus tard) n'est jamais recalé."""
    today = date.today()
    debut_succ = today.replace(day=1)
    ids = _seed_avec_successeur(
        run,
        numero="F-3",
        debut_successeur=debut_succ,
        mois_paiement=None,
        note="Résiliation signée — départ annoncé pour plus tard.",
    )
    _recaler(run)
    bail = _bail(run, ids["bail_id"])
    assert bail.date_fin > today
    assert NOTE_FIN_RECALEE not in (bail.notes or "")
