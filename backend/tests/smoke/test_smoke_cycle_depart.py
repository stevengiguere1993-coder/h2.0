"""Smoke — cycle unifié « départ d'un locataire » (vague 1, 2026-08-13).

Couvre le service ``locatif_depart`` branché sur toutes les portes :
(a) résiliation immédiate → bail résilié + logement vacant + dossier
    COMPLET (avant : dossier vide, logement jamais recalé) ;
(b) « Départ » / « Non renouvelé » (POST /locations avec bail_id) →
    dossier complet + cycle de renouvellement à « depart » + PAS de
    « réputé accepté » un mois plus tard ;
(c) bail échu sans réponse → reconduit tacitement (lazy) au chargement
    de loyers/overview ;
(d) bail échu AVEC dossier de relocation actif → terminé à sa fin,
    logement vacant ;
(e) import d'un bail signé sur un logement au bail actif ÉCHU →
    l'ancien passe « termine », une seule ligne dans loyers/overview ;
(f) PATCH /renouvellements/{id} status=depart (bouton « Quitte ») →
    reponse_le posé + dossier ouvert + bail fermé à sa fin ;
(g) résiliation à date FUTURE → le bail reste actif jusqu'à la date
    convenue et la date de départ du dossier est resynchronisée (M5) ;
(h) avis « propose » au délai écoulé MAIS dossier de relocation actif
    sur le logement → PAS de bascule « réputé accepté ».
"""
from __future__ import annotations

from datetime import date, timedelta

from app.models.immobilier import (
    Bail,
    BailRenouvellement,
    BailStatus,
    Immeuble,
    Locataire,
    LocationDossier,
    Logement,
    LogementStatus,
)

from .conftest import TestSessionLocal

_PDF = b"%PDF-1.4 smoke bail signe"


def _seed(
    run,
    *,
    numero: str,
    date_debut: date,
    date_fin: date,
    loyer: float = 900.0,
    bail_status: str = BailStatus.ACTIF.value,
    logement_status: str = LogementStatus.OCCUPE.value,
) -> dict:
    """Immeuble + logement + locataire + bail. Retourne les ids."""

    async def _go() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name=f"Immeuble Depart {numero}",
                address=f"{numero} rue du Depart",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero=numero, status=logement_status
            )
            loc = Locataire(full_name=f"Locataire {numero}")
            s.add_all([lg, loc])
            await s.flush()
            bail = Bail(
                logement_id=lg.id,
                locataire_id=loc.id,
                date_debut=date_debut,
                date_fin=date_fin,
                loyer_mensuel=loyer,
                status=bail_status,
            )
            s.add(bail)
            await s.commit()
            return {
                "immeuble_id": imm.id,
                "logement_id": lg.id,
                "locataire_id": loc.id,
                "bail_id": bail.id,
            }

    return run(_go())


def _db_get(run, model, obj_id: int):
    async def _go():
        async with TestSessionLocal() as s:
            return await s.get(model, obj_id)

    return run(_go())


def _dossier_actif(run, logement_id: int):
    from sqlalchemy import select

    async def _go():
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(LocationDossier).where(
                        LocationDossier.logement_id == logement_id,
                        LocationDossier.statut.notin_(
                            ["annule", "reloue"]
                        ),
                    )
                )
            ).scalars().all()

    return run(_go())


# ─── (a) Résiliation immédiate ─────────────────────────────────────────


def test_resilier_immediat_dossier_complet(client, auth_headers, run):
    today = date.today()
    ids = _seed(
        run,
        numero="RES-1",
        date_debut=today - timedelta(days=300),
        date_fin=today + timedelta(days=65),
        loyer=940.0,
    )
    r = client.post(
        f"/api/v1/immobilier/baux/{ids['bail_id']}/resilier",
        headers=auth_headers,
        json={
            "date_fin": str(today),
            "ouvrir_relocation": True,
            "envoyer_avis": False,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["relocation_ouverte"] is True

    bail = _db_get(run, Bail, ids["bail_id"])
    assert bail.status == BailStatus.RESILIE.value
    assert bail.date_fin == today

    lg = _db_get(run, Logement, ids["logement_id"])
    assert lg.status == LogementStatus.VACANT.value

    dossiers = _dossier_actif(run, ids["logement_id"])
    assert len(dossiers) == 1
    d = dossiers[0]
    # AVANT : dossier vide (ni date ni loyers). Maintenant : complet.
    assert d.bail_id == ids["bail_id"]
    assert d.date_depart == today
    assert float(d.loyer_ancien) == 940.0
    assert float(d.loyer_demande) == 940.0
    assert "Résiliation immédiate" in (d.notes or "")


# ─── (b) « Départ » / « Non renouvelé » ────────────────────────────────


def test_depart_via_locations_tue_le_repute_accepte(
    client, auth_headers, run
):
    today = date.today()
    ids = _seed(
        run,
        numero="DEP-1",
        date_debut=today - timedelta(days=275),
        date_fin=today + timedelta(days=90),
        loyer=1000.0,
    )

    # Avis envoyé il y a 45 jours, sans réponse : le délai d'un mois est
    # écoulé — sans départ déclaré, la vue le passerait « réputé
    # accepté » et appliquerait la hausse à un locataire qui s'en va.
    async def _seed_cycle():
        async with TestSessionLocal() as s:
            ren = BailRenouvellement(
                bail_id=ids["bail_id"],
                avis_envoye_le=today - timedelta(days=45),
                nouveau_loyer=1080.0,
                status="propose",
            )
            s.add(ren)
            await s.commit()
            return ren.id

    ren_id = run(_seed_cycle())

    r = client.post(
        "/api/v1/immobilier/locations",
        headers=auth_headers,
        json={"bail_id": ids["bail_id"]},
    )
    assert r.status_code == 201, r.text
    row = r.json()
    # Dossier complet, comme avant — MAIS le bail se fermera à sa fin.
    assert row["bail_id"] == ids["bail_id"]
    assert row["date_depart"] == str(today + timedelta(days=90))
    assert row["loyer_ancien"] == 1000.0

    # Cycle de renouvellement basculé « depart » + reponse_le posé.
    ren = _db_get(run, BailRenouvellement, ren_id)
    assert ren.status == "depart"
    assert ren.reponse_le is not None

    # Le bail reste actif jusqu'à l'échéance (fin inchangée, future).
    bail = _db_get(run, Bail, ids["bail_id"])
    assert bail.status == BailStatus.ACTIF.value
    assert bail.date_fin == today + timedelta(days=90)

    # La consultation de la vue ne fabrique PAS de « réputé accepté ».
    ov = client.get(
        "/api/v1/immobilier/renouvellements/overview", headers=auth_headers
    )
    assert ov.status_code == 200, ov.text
    ren_apres = _db_get(run, BailRenouvellement, ren_id)
    assert ren_apres.status == "depart"
    ligne = next(
        (x for x in ov.json() if x["bail_id"] == ids["bail_id"]), None
    )
    assert ligne is not None
    assert ligne["renouvellement_status"] == "depart"
    assert ligne["relocation_dossier_id"] is not None


# ─── (c) Reconduction tacite automatique (lazy) ────────────────────────


def test_bail_echu_sans_reponse_reconduit_tacitement(
    client, auth_headers, run
):
    today = date.today()
    ancienne_fin = today - timedelta(days=10)
    ids = _seed(
        run,
        numero="TAC-1",
        date_debut=ancienne_fin - timedelta(days=365),
        date_fin=ancienne_fin,
        loyer=850.0,
    )

    r = client.get("/api/v1/immobilier/loyers/overview", headers=auth_headers)
    assert r.status_code == 200, r.text

    bail = _db_get(run, Bail, ids["bail_id"])
    assert bail.status == BailStatus.ACTIF.value
    assert bail.date_fin >= today  # étiré d'un cycle

    from sqlalchemy import select

    async def _cycles():
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(BailRenouvellement).where(
                        BailRenouvellement.bail_id == ids["bail_id"]
                    )
                )
            ).scalars().all()

    cycles = run(_cycles())
    assert len(cycles) == 1
    assert cycles[0].status == "reconduit"
    assert "Reconduction tacite automatique" in (cycles[0].notes or "")
    assert cycles[0].nouvelle_date_debut == ancienne_fin + timedelta(days=1)
    assert cycles[0].nouvelle_date_fin == bail.date_fin

    # La ligne reste dans le suivi des loyers (bail toujours actif).
    lignes = [
        x for x in r.json()["rows"] if x["bail_id"] == ids["bail_id"]
    ]
    assert len(lignes) == 1


# ─── (d) Bail échu avec départ annoncé → terminé ───────────────────────


def test_bail_echu_avec_dossier_actif_est_termine(
    client, auth_headers, run
):
    today = date.today()
    ids = _seed(
        run,
        numero="FIN-1",
        date_debut=today - timedelta(days=375),
        date_fin=today - timedelta(days=10),
        loyer=780.0,
    )

    async def _seed_dossier():
        async with TestSessionLocal() as s:
            d = LocationDossier(
                logement_id=ids["logement_id"],
                bail_id=ids["bail_id"],
                statut="avis_recu",
                date_depart=today - timedelta(days=10),
            )
            s.add(d)
            await s.commit()

    run(_seed_dossier())

    r = client.get("/api/v1/immobilier/suivi-baux", headers=auth_headers)
    assert r.status_code == 200, r.text

    bail = _db_get(run, Bail, ids["bail_id"])
    assert bail.status == BailStatus.TERMINE.value
    assert bail.date_fin == today - timedelta(days=10)  # PAS étiré

    lg = _db_get(run, Logement, ids["logement_id"])
    assert lg.status == LogementStatus.VACANT.value

    # Et la page Baux montre la ligne SANS bail courant (à relouer).
    ligne = next(
        (
            x
            for x in r.json()
            if x["logement_id"] == ids["logement_id"]
        ),
        None,
    )
    assert ligne is not None
    assert ligne["bail_id"] is None


# ─── (e) Import du bail suivant → l'ancien (échu) se termine ───────────


def test_import_bail_signe_termine_l_ancien_echu(
    client, auth_headers, run
):
    today = date.today()
    ids = _seed(
        run,
        numero="IMP-1",
        date_debut=today - timedelta(days=800),
        date_fin=today - timedelta(days=100),
        loyer=700.0,
    )
    ancien_bail_id = ids["bail_id"]

    # Nouveau locataire + bail « proposé » (relocation CORPIQ).
    async def _nouveau_locataire():
        async with TestSessionLocal() as s:
            loc = Locataire(full_name="Nouveau IMP-1")
            s.add(loc)
            await s.commit()
            return loc.id

    nouveau_loc_id = run(_nouveau_locataire())
    r = client.post(
        "/api/v1/immobilier/baux",
        headers=auth_headers,
        json={
            "logement_id": ids["logement_id"],
            "locataire_id": nouveau_loc_id,
            "date_debut": str(today - timedelta(days=30)),
            "date_fin": str(today + timedelta(days=335)),
            "loyer_mensuel": 825.0,
            "status": "propose",
        },
    )
    assert r.status_code in (200, 201), r.text
    nouveau_bail_id = r.json()["id"]

    # Import du bail signé → le proposé devient ACTIF et l'ancien bail
    # actif ÉCHU passe « termine » (fini la double ligne).
    up = client.post(
        f"/api/v1/immobilier/baux/{nouveau_bail_id}/document",
        headers=auth_headers,
        files={"file": ("bail-signe.pdf", _PDF, "application/pdf")},
    )
    assert up.status_code == 200, up.text

    ancien = _db_get(run, Bail, ancien_bail_id)
    assert ancien.status == BailStatus.TERMINE.value
    assert "Terminé automatiquement à l'arrivée du bail suivant" in (
        ancien.notes or ""
    )
    nouveau = _db_get(run, Bail, nouveau_bail_id)
    assert nouveau.status == BailStatus.ACTIF.value

    # UNE seule ligne de bail COURANT dans le suivi des loyers pour ce
    # logement. (Une ligne « dette » du locataire sortant peut coexister
    # tant que son solde n'est pas réglé — c'est voulu, 2026-08-14.)
    lo = client.get(
        "/api/v1/immobilier/loyers/overview", headers=auth_headers
    )
    assert lo.status_code == 200, lo.text
    lignes = [
        x
        for x in lo.json()["rows"]
        if x["logement_id"] == ids["logement_id"]
        and x["bail_statut"] == "actif"
    ]
    assert len(lignes) == 1
    assert lignes[0]["bail_id"] == nouveau_bail_id


# ─── (f) Bouton « Quitte » (PATCH renouvellement → depart) ─────────────


def test_patch_renouvellement_depart_ouvre_le_cycle(
    client, auth_headers, run
):
    today = date.today()
    ids = _seed(
        run,
        numero="QUI-1",
        date_debut=today - timedelta(days=245),
        date_fin=today + timedelta(days=120),
        loyer=1150.0,
    )

    async def _seed_cycle():
        async with TestSessionLocal() as s:
            ren = BailRenouvellement(
                bail_id=ids["bail_id"],
                avis_envoye_le=today - timedelta(days=5),
                nouveau_loyer=1200.0,
                status="propose",
            )
            s.add(ren)
            await s.commit()
            return ren.id

    ren_id = run(_seed_cycle())

    r = client.patch(
        f"/api/v1/immobilier/renouvellements/{ren_id}",
        headers=auth_headers,
        json={"status": "depart"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "depart"
    assert r.json()["reponse_le"] == str(today)

    # Dossier ouvert, complet, départ à la fin du bail.
    dossiers = _dossier_actif(run, ids["logement_id"])
    assert len(dossiers) == 1
    assert dossiers[0].bail_id == ids["bail_id"]
    assert dossiers[0].date_depart == today + timedelta(days=120)
    assert float(dossiers[0].loyer_ancien) == 1150.0

    # Bail actif jusqu'à l'échéance, logement toujours occupé.
    bail = _db_get(run, Bail, ids["bail_id"])
    assert bail.status == BailStatus.ACTIF.value
    lg = _db_get(run, Logement, ids["logement_id"])
    assert lg.status == LogementStatus.OCCUPE.value


# ─── (g) Résiliation à date future + resync date_depart (M5) ───────────


def test_resilier_date_future_resynchronise_le_dossier(
    client, auth_headers, run
):
    today = date.today()
    fin_bail = today + timedelta(days=150)
    ids = _seed(
        run,
        numero="FUT-1",
        date_debut=today - timedelta(days=215),
        date_fin=fin_bail,
        loyer=990.0,
    )

    # 1) Départ annoncé à l'échéance (dossier ouvert, date = fin).
    r1 = client.post(
        "/api/v1/immobilier/locations",
        headers=auth_headers,
        json={"bail_id": ids["bail_id"]},
    )
    assert r1.status_code == 201, r1.text
    assert r1.json()["date_depart"] == str(fin_bail)

    # 2) Entente trouvée : il part finalement dans 30 jours — le MÊME
    #    dossier suit (pas de doublon) et sa date est resynchronisée.
    nouvelle_fin = today + timedelta(days=30)
    r2 = client.post(
        f"/api/v1/immobilier/baux/{ids['bail_id']}/resilier",
        headers=auth_headers,
        json={
            "date_fin": str(nouvelle_fin),
            "ouvrir_relocation": True,
            "envoyer_avis": False,
        },
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["relocation_ouverte"] is False  # dossier déjà là

    dossiers = _dossier_actif(run, ids["logement_id"])
    assert len(dossiers) == 1
    assert dossiers[0].date_depart == nouvelle_fin  # M5 : resynchronisée

    # Date future → le bail RESTE actif jusqu'à la date convenue (le
    # locataire paie jusque-là) ; le recalage lazy le terminera après.
    bail = _db_get(run, Bail, ids["bail_id"])
    assert bail.status == BailStatus.ACTIF.value
    assert bail.date_fin == nouvelle_fin
    lg = _db_get(run, Logement, ids["logement_id"])
    assert lg.status == LogementStatus.OCCUPE.value


# ─── (h) Dossier actif → pas de « réputé accepté » ─────────────────────


def test_repute_accepte_saute_les_baux_en_relocation(
    client, auth_headers, run
):
    """Avis « propose » au délai écoulé + dossier de relocation ACTIF
    ouvert À CÔTÉ du cycle (sans passer par une porte de départ) : la
    consultation ne fabrique PAS de « réputé accepté » — le départ est
    annoncé, on n'applique pas une hausse à un locataire qui s'en va."""
    today = date.today()
    ids = _seed(
        run,
        numero="REP-1",
        date_debut=today - timedelta(days=305),
        date_fin=today + timedelta(days=60),
        loyer=910.0,
    )

    async def _seed_cycle_et_dossier():
        async with TestSessionLocal() as s:
            ren = BailRenouvellement(
                bail_id=ids["bail_id"],
                avis_envoye_le=today - timedelta(days=45),
                nouveau_loyer=960.0,
                status="propose",
            )
            # Dossier ouvert à la main (kanban) — sans bail_id.
            d = LocationDossier(
                logement_id=ids["logement_id"],
                statut="avis_recu",
            )
            s.add_all([ren, d])
            await s.commit()
            return ren.id

    ren_id = run(_seed_cycle_et_dossier())

    ov = client.get(
        "/api/v1/immobilier/renouvellements/overview", headers=auth_headers
    )
    assert ov.status_code == 200, ov.text

    ren = _db_get(run, BailRenouvellement, ren_id)
    assert ren.status == "propose"  # PAS « repute_accepte »
    ligne = next(
        (x for x in ov.json() if x["bail_id"] == ids["bail_id"]), None
    )
    assert ligne is not None
    assert ligne["renouvellement_status"] == "propose"
    assert ligne["relocation_dossier_id"] is not None


def test_dette_bail_termine_pas_dans_les_mois_futurs(
    client, auth_headers, run
):
    """Retour Phil 2026-08-26 : deux baux « terminés (avant terme) »
    apparaissaient en rouge dans SEPTEMBRE (mois futur). La dette d'un
    locataire parti se réclame au présent — visible dans le mois
    courant, jamais projetée dans les mois à venir."""
    today = date.today()
    debut = (today.replace(day=1) - timedelta(days=40)).replace(day=1)
    fin_bail = today.replace(day=1) - timedelta(days=1)
    ids = _seed(
        run,
        numero="FUTUR-1",
        date_debut=debut,
        date_fin=fin_bail,
        loyer=400.0,
        bail_status=BailStatus.RESILIE.value,
        logement_status=LogementStatus.VACANT.value,
    )

    mois_courant = today.strftime("%Y-%m")
    ov = client.get(
        f"/api/v1/immobilier/loyers/overview?mois={mois_courant}",
        headers=auth_headers,
    ).json()
    lignes = [r for r in ov["rows"] if r["bail_id"] == ids["bail_id"]]
    # Mois courant : la dette est là, en retard.
    assert len(lignes) == 1
    assert lignes[0]["etat"] == "retard"
    assert lignes[0]["solde_total"] > 0

    futur = (
        f"{today.year + 1}-01"
        if today.month == 12
        else f"{today.year}-{today.month + 1:02d}"
    )
    ov2 = client.get(
        f"/api/v1/immobilier/loyers/overview?mois={futur}",
        headers=auth_headers,
    ).json()
    assert all(r["bail_id"] != ids["bail_id"] for r in ov2["rows"])


def test_mois_paye_avec_solde_anterieur_remonte(
    client, auth_headers, run
):
    """Cas Mouad (retour Phil 2026-08-26) : juillet impayé, août payé —
    la ligne d'août était « payée » en vert au bas de la liste et la
    dette de juillet invisible. Un mois payé avec un solde antérieur
    devient « partiel » (badge Solde antérieur) et remonte."""
    today = date.today()
    mois_courant = today.replace(day=1)
    mois_prec = (mois_courant - timedelta(days=1)).replace(day=1)
    ids = _seed(
        run,
        numero="SOLDE-1",
        date_debut=mois_prec,
        date_fin=(
            mois_courant.replace(day=28) + timedelta(days=4)
        ).replace(day=1) - timedelta(days=1),
        loyer=500.0,
        bail_status=BailStatus.TERMINE.value,
        logement_status=LogementStatus.VACANT.value,
    )
    # Le mois COURANT est payé ; le mois précédent, non.
    p = client.post(
        "/api/v1/immobilier/paiements",
        headers=auth_headers,
        json={
            "bail_id": ids["bail_id"],
            "mois_couvert": str(mois_courant),
            "montant": 500.0,
            "paye_le": str(today),
        },
    )
    assert p.status_code == 201, p.text

    ov = client.get(
        f"/api/v1/immobilier/loyers/overview"
        f"?mois={mois_courant.strftime('%Y-%m')}",
        headers=auth_headers,
    ).json()
    lignes = [r for r in ov["rows"] if r["bail_id"] == ids["bail_id"]]
    assert len(lignes) == 1
    # Le mois est réglé mais le compte du bail non → « partiel » avec
    # le drapeau, jamais « paye » planqué en vert.
    assert lignes[0]["etat"] == "partiel"
    assert lignes[0]["solde_anterieur"] is True
    assert lignes[0]["solde_total"] == 500.0

    # Une fois le mois précédent réglé, la ligne redevient « payé ».
    p2 = client.post(
        "/api/v1/immobilier/paiements",
        headers=auth_headers,
        json={
            "bail_id": ids["bail_id"],
            "mois_couvert": str(mois_prec),
            "montant": 500.0,
            "paye_le": str(today),
        },
    )
    assert p2.status_code == 201, p2.text
    ov2 = client.get(
        f"/api/v1/immobilier/loyers/overview"
        f"?mois={mois_courant.strftime('%Y-%m')}",
        headers=auth_headers,
    ).json()
    ligne = [
        r for r in ov2["rows"] if r["bail_id"] == ids["bail_id"]
    ][0]
    assert ligne["etat"] == "paye"
    assert ligne["solde_anterieur"] is False
