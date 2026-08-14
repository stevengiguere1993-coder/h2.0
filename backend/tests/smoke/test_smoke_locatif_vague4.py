"""Smoke — retours client du 2026-08-14 (vague 4).

Trois chantiers :
(1) LOYER, une seule source de vérité — en gestion EXTERNE le loyer
    SAISI sur le logement prime partout (un bail résiduel invisible ne
    le masque plus), et les mois déjà marqués payés gardent leur
    montant historique (attendu figé à la saisie) ;
(2) PAIEMENTS — un bail terminé reste visible dans les mois APRÈS sa
    fin tant que son solde est > 0 (dette à percevoir), puis disparaît
    de ces mois-là une fois soldé — il reste toujours visible dans les
    mois qu'il COUVRAIT ;
(3) le helper partagé ``loyer_effectif`` (hiérarchie pure).
"""
from __future__ import annotations

from datetime import date, timedelta

from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
)

from .conftest import TestSessionLocal


def _mois_precedent(d: date) -> date:
    """1er du mois précédant celui de ``d``."""
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def _seed_immeuble_logement(
    run,
    *,
    numero: str,
    gestion_externe: bool = False,
    logement_status: str = LogementStatus.OCCUPE.value,
    loyer_demande: float | None = None,
    bail: dict | None = None,
) -> dict:
    """Immeuble + logement (+ locataire/bail optionnels). Retourne les ids."""

    async def _go() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name=f"Immeuble V4 {numero}",
                address=f"{numero} rue Vague4",
                is_active=True,
                gestion_externe=gestion_externe,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id,
                numero=numero,
                status=logement_status,
                loyer_demande=loyer_demande,
            )
            s.add(lg)
            await s.flush()
            out = {"immeuble_id": imm.id, "logement_id": lg.id}
            if bail is not None:
                loc = Locataire(full_name=f"Locataire V4 {numero}")
                s.add(loc)
                await s.flush()
                b = Bail(
                    logement_id=lg.id,
                    locataire_id=loc.id,
                    **bail,
                )
                s.add(b)
                await s.flush()
                out["locataire_id"] = loc.id
                out["bail_id"] = b.id
            await s.commit()
            return out

    return run(_go())


# ─── (3) Helper « loyer effectif » — hiérarchie pure ───────────────────


def test_helper_loyer_effectif_hierarchie():
    from app.services.loyer_effectif import loyer_effectif, loyer_effectif_loue

    class _Lg:
        def __init__(self, demande, status="occupe"):
            self.loyer_demande = demande
            self.status = status

    # EXTERNE : le loyer saisi prime ; bail résiduel en filet.
    assert loyer_effectif(_Lg(1000.0), 850.0, True) == 1000.0
    assert loyer_effectif(_Lg(None), 850.0, True) == 850.0
    # INTERNE : bail d'abord ; demandé pour un vacant.
    assert loyer_effectif(_Lg(999.0), 1400.0, False) == 1400.0
    assert loyer_effectif(_Lg(875.0, status="vacant"), None, False) == 875.0
    # « Loué » : rien d'attendu d'une unité ni louée ni occupée.
    assert loyer_effectif_loue(_Lg(875.0, status="vacant"), None, False) is None
    assert loyer_effectif_loue(_Lg(875.0, status="occupe"), None, False) == 875.0


# ─── (1) Gestion externe : le loyer saisi se transpose PARTOUT ─────────


def test_externe_loyer_saisi_prime_et_se_transpose(client, auth_headers, run):
    """Scénario exact du client : immeuble en gestion externe, le prix
    changé sur le logement doit se refléter immédiatement dans la liste
    des logements et le suivi des paiements — même avec un bail actif
    RÉSIDUEL dans Kratos (invisible, l'onglet Baux est caché)."""
    today = date.today()
    ids = _seed_immeuble_logement(
        run,
        numero="V4-EXT1",
        gestion_externe=True,
        loyer_demande=1000.0,
        bail={
            "date_debut": today - timedelta(days=200),
            "date_fin": today + timedelta(days=165),
            "loyer_mensuel": 850.0,
            "status": BailStatus.ACTIF.value,
        },
    )
    mois = today.strftime("%Y-%m")

    # Le loyer SAISI (1000 $) prime sur le bail résiduel (850 $).
    ov = client.get(
        f"/api/v1/immobilier/immeubles/{ids['immeuble_id']}"
        f"/paiements-externes?mois={mois}",
        headers=auth_headers,
    )
    assert ov.status_code == 200, ov.text
    row = next(
        x for x in ov.json()["rows"]
        if x["logement_id"] == ids["logement_id"]
    )
    assert row["loyer_attendu"] == 1000.0

    # Changer le prix sur le logement → répercuté PARTOUT, tout de suite.
    p = client.patch(
        f"/api/v1/immobilier/logements/{ids['logement_id']}",
        headers=auth_headers,
        json={"loyer_demande": 1100.0},
    )
    assert p.status_code == 200, p.text

    ov2 = client.get(
        f"/api/v1/immobilier/immeubles/{ids['immeuble_id']}"
        f"/paiements-externes?mois={mois}",
        headers=auth_headers,
    )
    row2 = next(
        x for x in ov2.json()["rows"]
        if x["logement_id"] == ids["logement_id"]
    )
    assert row2["loyer_attendu"] == 1100.0

    # Page Paiements générale (vue portefeuille des externes).
    ge = client.get(
        f"/api/v1/immobilier/loyers/externes?mois={mois}",
        headers=auth_headers,
    )
    assert ge.status_code == 200, ge.text
    ligne = next(
        (
            x for x in ge.json()["rows"]
            if x["logement_id"] == ids["logement_id"]
        ),
        None,
    )
    assert ligne is not None
    assert ligne["loyer_mensuel"] == 1100.0

    # Liste des logements : pas de miroir bail en externe — le loyer
    # saisi fait foi (loyer_actuel vide → l'UI affiche loyer_demande).
    lst = client.get(
        f"/api/v1/immobilier/immeubles/{ids['immeuble_id']}/logements",
        headers=auth_headers,
    )
    assert lst.status_code == 200, lst.text
    lg_row = next(x for x in lst.json() if x["id"] == ids["logement_id"])
    assert lg_row["loyer_demande"] == 1100.0
    assert lg_row["loyer_actuel"] is None


def test_externe_mois_paye_garde_son_montant_historique(
    client, auth_headers, run
):
    """Marquer un mois payé fige le loyer attendu : changer le loyer du
    logement ensuite ne réécrit pas l'historique — seuls le mois courant
    impayé et les mois à venir suivent le nouveau montant."""
    today = date.today()
    ids = _seed_immeuble_logement(
        run,
        numero="V4-EXT2",
        gestion_externe=True,
        loyer_demande=1100.0,
    )
    mois = today.strftime("%Y-%m")
    prochain = (today.replace(day=1) + timedelta(days=32)).strftime("%Y-%m")

    # Payé au complet (sans montant = loyer attendu du moment, figé).
    r = client.post(
        "/api/v1/immobilier/paiements-externes",
        headers=auth_headers,
        json={"logement_id": ids["logement_id"], "mois": mois},
    )
    assert r.status_code == 201, r.text

    # Le loyer monte à 1200 $ APRÈS coup.
    p = client.patch(
        f"/api/v1/immobilier/logements/{ids['logement_id']}",
        headers=auth_headers,
        json={"loyer_demande": 1200.0},
    )
    assert p.status_code == 200, p.text

    # Mois payé : attendu FIGÉ à 1100 $, toujours réglé au complet.
    ov = client.get(
        f"/api/v1/immobilier/immeubles/{ids['immeuble_id']}"
        f"/paiements-externes?mois={mois}",
        headers=auth_headers,
    )
    row = next(
        x for x in ov.json()["rows"]
        if x["logement_id"] == ids["logement_id"]
    )
    assert row["loyer_attendu"] == 1100.0
    assert row["etat"] == "paye"
    assert row["solde_total"] == 0.0

    # Mois À VENIR : le nouveau montant s'applique.
    ov2 = client.get(
        f"/api/v1/immobilier/immeubles/{ids['immeuble_id']}"
        f"/paiements-externes?mois={prochain}",
        headers=auth_headers,
    )
    row2 = next(
        x for x in ov2.json()["rows"]
        if x["logement_id"] == ids["logement_id"]
    )
    assert row2["loyer_attendu"] == 1200.0


# ─── (2) Bail terminé : dette visible après la fin, jusqu'au solde 0 ───


def test_bail_termine_reste_visible_tant_que_dette_puis_disparait(
    client, auth_headers, run
):
    """Scénario exact du client (4005 St-Laurent) : un locataire parti
    à la fin du mois dernier en devant son loyer. Le mois d'APRÈS le
    montre encore (dette à percevoir) ; le paiement soldant la dette le
    fait disparaître de ces mois-là — mais il reste visible dans le
    mois que son bail couvrait."""
    today = date.today()
    fin = today.replace(day=1) - timedelta(days=1)  # dernier jour du mois passé
    debut = fin.replace(day=1)  # bail d'un mois — dette déterministe
    ids = _seed_immeuble_logement(
        run,
        numero="V4-DETTE",
        logement_status=LogementStatus.VACANT.value,
        bail={
            "date_debut": debut,
            "date_fin": fin,
            "loyer_mensuel": 875.0,
            "status": BailStatus.TERMINE.value,
        },
    )
    mois_courant = today.strftime("%Y-%m")
    mois_couvert = debut.strftime("%Y-%m")

    # Mois APRÈS la fin : la ligne est là, pour la dette seulement
    # (0 $ de loyer du mois, solde = le loyer impayé).
    ov = client.get(
        f"/api/v1/immobilier/loyers/overview?mois={mois_courant}",
        headers=auth_headers,
    )
    assert ov.status_code == 200, ov.text
    dettes = [
        x for x in ov.json()["rows"] if x["bail_id"] == ids["bail_id"]
    ]
    assert len(dettes) == 1
    assert dettes[0]["loyer_mensuel"] == 0.0
    assert dettes[0]["solde_total"] == 875.0
    assert dettes[0]["etat"] == "retard"
    assert dettes[0]["bail_termine_le"] == str(fin)

    # Mois COUVERT : visible, toujours (loyer du mois entamé).
    ovc = client.get(
        f"/api/v1/immobilier/loyers/overview?mois={mois_couvert}",
        headers=auth_headers,
    )
    couverts = [
        x for x in ovc.json()["rows"] if x["bail_id"] == ids["bail_id"]
    ]
    assert len(couverts) == 1
    assert couverts[0]["loyer_mensuel"] == 875.0

    # Paiement soldant la dette (imputé au mois couvert par le bail).
    p = client.post(
        "/api/v1/immobilier/paiements",
        headers=auth_headers,
        json={
            "bail_id": ids["bail_id"],
            "mois_couvert": str(debut),
            "montant": 875.0,
            "paye_le": str(today),
        },
    )
    assert p.status_code == 201, p.text

    # Solde à 0 → il DISPARAÎT du mois qu'il ne couvrait pas…
    ov2 = client.get(
        f"/api/v1/immobilier/loyers/overview?mois={mois_courant}",
        headers=auth_headers,
    )
    assert not [
        x for x in ov2.json()["rows"] if x["bail_id"] == ids["bail_id"]
    ]

    # …mais reste dans le mois COUVERT, réglé.
    ov3 = client.get(
        f"/api/v1/immobilier/loyers/overview?mois={mois_couvert}",
        headers=auth_headers,
    )
    regle = [
        x for x in ov3.json()["rows"] if x["bail_id"] == ids["bail_id"]
    ]
    assert len(regle) == 1
    assert regle[0]["etat"] == "paye"
    assert regle[0]["solde_total"] == 0.0
