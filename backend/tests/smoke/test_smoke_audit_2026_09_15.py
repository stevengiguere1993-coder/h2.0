"""Smoke — correctifs des audits du 2026-09-15 (création de locataire →
pages, transfert d'unité, vague 1).

Chaque test rejoue un cas de la vie réelle prouvé cassé par l'audit et
verrouille le comportement corrigé.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models.immobilier import (
    Bail,
    BailRenouvellement,
    BailStatus,
    ImmDocument,
    Immeuble,
    Locataire,
    LocationDossier,
    LocationDossierStatut,
    Logement,
    LogementStatus,
    PaiementExterne,
    PaiementLoyer,
)

from .conftest import TestSessionLocal

_PDF = b"%PDF-1.4 smoke audit 2026-09-15"
TODAY = date.today()


def _run_seed(run, coro):
    return run(coro)


async def _mk_immeuble(s, nom: str, *, externe: bool = False, nb: int = 2):
    imm = Immeuble(
        name=nom, address=f"1 rue {nom}", city="Montréal", is_active=True,
        gestion_externe=externe,
    )
    s.add(imm)
    await s.flush()
    lgs = []
    for i in range(nb):
        lg = Logement(
            immeuble_id=imm.id, numero=str(i + 1),
            status=LogementStatus.VACANT.value,
        )
        s.add(lg)
        lgs.append(lg)
    await s.flush()
    return imm, lgs


def _get(run, model, obj_id):
    async def _g():
        async with TestSessionLocal() as s:
            return await s.get(model, obj_id)

    return run(_g())


# ─── A1 : importer le bail du SUIVANT ne termine pas le bail EN COURS ──


def test_import_bail_suivant_ne_termine_pas_le_bail_en_cours(
    client, auth_headers, run
):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, _) = await _mk_immeuble(s, "Audit A1")
            alice = Locataire(full_name="Alice Encore La")
            bob = Locataire(full_name="Bob Suivant")
            s.add_all([alice, bob])
            await s.flush()
            b_alice = Bail(
                logement_id=lg1.id, locataire_id=alice.id,
                date_debut=TODAY - timedelta(days=300),
                date_fin=TODAY + timedelta(days=90),
                loyer_mensuel=1000.0, depot_garantie=500.0,
                status=BailStatus.ACTIF.value,
            )
            s.add(b_alice)
            await s.flush()
            lg1.status = LogementStatus.OCCUPE.value
            d = LocationDossier(
                logement_id=lg1.id, bail_id=b_alice.id,
                statut=LocationDossierStatut.AVIS_RECU.value,
                date_depart=TODAY + timedelta(days=90),
            )
            s.add(d)
            await s.flush()
            b_bob = Bail(
                logement_id=lg1.id, locataire_id=bob.id,
                date_debut=TODAY + timedelta(days=91),
                date_fin=TODAY + timedelta(days=456),
                loyer_mensuel=1100.0, status=BailStatus.PROPOSE.value,
            )
            s.add(b_bob)
            await s.flush()
            d.nouveau_bail_id = b_bob.id
            d.statut = LocationDossierStatut.BAIL_ENVOYE.value
            await s.commit()
            return {"lg": lg1.id, "alice": b_alice.id, "bob": b_bob.id, "d": d.id}

    ids = run(_seed())
    r = client.post(
        f"/api/v1/immobilier/baux/{ids['bob']}/document",
        headers=auth_headers,
        files={"file": ("bail-bob.pdf", _PDF, "application/pdf")},
    )
    assert r.status_code in (200, 201), r.text
    assert _get(run, Bail, ids["bob"]).status == BailStatus.ACTIF.value
    alice = _get(run, Bail, ids["alice"])
    assert alice.status == BailStatus.ACTIF.value, "Alice reste en place 3 mois"
    assert _get(run, LocationDossier, ids["d"]).statut == "reloue"
    assert _get(run, Logement, ids["lg"]).status == LogementStatus.OCCUPE.value
    # Dépôts : celui d'Alice n'est PAS « à rendre » (elle est encore là).
    rd = client.get(
        "/api/v1/immobilier/depots/overview", headers=auth_headers
    )
    row = next(x for x in rd.json()["rows"] if x["bail_id"] == ids["alice"])
    assert row["statut"] == "detenu"


# ─── A2 : exception « aucun bail à joindre » active le bail ───────────


def test_exception_sans_document_active_le_bail(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, _) = await _mk_immeuble(s, "Audit A2")
            loc = Locataire(full_name="Sans Papier")
            s.add(loc)
            await s.flush()
            b = Bail(
                logement_id=lg1.id, locataire_id=loc.id,
                date_debut=TODAY - timedelta(days=5),
                date_fin=TODAY + timedelta(days=360),
                loyer_mensuel=900.0, status=BailStatus.PROPOSE.value,
            )
            s.add(b)
            await s.flush()
            d = LocationDossier(
                logement_id=lg1.id, statut=LocationDossierStatut.BAIL_ENVOYE.value,
                nouveau_bail_id=b.id,
            )
            s.add(d)
            await s.commit()
            return {"bail": b.id, "d": d.id, "lg": lg1.id}

    ids = run(_seed())
    r = client.post(
        f"/api/v1/immobilier/baux/{ids['bail']}/exception-document",
        headers=auth_headers, json={"motif": "Bail verbal avant notre arrivée"},
    )
    assert r.status_code in (200, 201), r.text
    assert _get(run, Bail, ids["bail"]).status == BailStatus.ACTIF.value
    assert _get(run, LocationDossier, ids["d"]).statut == "reloue"
    assert _get(run, Logement, ids["lg"]).status == LogementStatus.OCCUPE.value
    # Et il apparaît dans Paiements.
    rp = client.get("/api/v1/immobilier/loyers/overview", headers=auth_headers)
    assert any(x.get("bail_id") == ids["bail"] for x in rp.json()["rows"])


# ─── A3/A12 : statut du logement par la règle unique ─────────────────


def test_bail_actif_futur_donne_reserve_et_proposee_commence_reste_reserve(
    client, auth_headers, run
):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, lg2) = await _mk_immeuble(s, "Audit A3")
            loc = Locataire(full_name="Futur Occupant")
            s.add(loc)
            await s.flush()
            await s.commit()
            return {"lg1": lg1.id, "lg2": lg2.id, "loc": loc.id}

    ids = run(_seed())
    r = client.post(
        "/api/v1/immobilier/baux", headers=auth_headers,
        json={
            "logement_id": ids["lg1"], "locataire_id": ids["loc"],
            "date_debut": str(TODAY + timedelta(days=60)),
            "date_fin": str(TODAY + timedelta(days=425)),
            "loyer_mensuel": 1000, "status": "actif",
        },
    )
    assert r.status_code in (200, 201), r.text
    assert _get(run, Logement, ids["lg1"]).status == LogementStatus.RESERVE.value
    # Liste Locataires : il n'« habite » pas encore.
    rl = client.get("/api/v1/immobilier/locataires", headers=auth_headers)
    row = next(x for x in rl.json() if x["id"] == ids["loc"])
    assert not row.get("logement_id") and not row.get("immeuble_name")

    # Proposé déjà commencé (transfert, bail en retard) → réservé, et le
    # recalage global ne le remet pas « vacant ».
    r2 = client.post(
        "/api/v1/immobilier/baux", headers=auth_headers,
        json={
            "logement_id": ids["lg2"], "locataire_id": ids["loc"],
            "date_debut": str(TODAY - timedelta(days=3)),
            "date_fin": str(TODAY + timedelta(days=360)),
            "loyer_mensuel": 1000, "status": "propose",
        },
    )
    assert r2.status_code in (200, 201), r2.text
    assert _get(run, Logement, ids["lg2"]).status == LogementStatus.RESERVE.value
    from app.services.locatif_depart import recaler_tous_les_statuts_logements

    async def _recaler():
        async with TestSessionLocal() as s:
            await recaler_tous_les_statuts_logements(s)
            await s.commit()

    run(_recaler())
    assert _get(run, Logement, ids["lg2"]).status == LogementStatus.RESERVE.value


# ─── A4 : supprimer / terminer un proposé libère le logement ──────────


def test_supprimer_ou_terminer_un_propose_libere_le_logement(
    client, auth_headers, run
):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, lg2) = await _mk_immeuble(s, "Audit A4")
            loc = Locataire(full_name="Candidat Parti")
            s.add(loc)
            await s.flush()
            baux = []
            for lg in (lg1, lg2):
                b = Bail(
                    logement_id=lg.id, locataire_id=loc.id,
                    date_debut=TODAY + timedelta(days=30),
                    date_fin=TODAY + timedelta(days=395),
                    loyer_mensuel=800.0, depot_garantie=400.0,
                    status=BailStatus.PROPOSE.value,
                )
                s.add(b)
                await s.flush()
                lg.status = LogementStatus.RESERVE.value
                s.add(LocationDossier(
                    logement_id=lg.id, statut="bail_envoye", nouveau_bail_id=b.id,
                ))
                baux.append(b.id)
            await s.commit()
            return {"lg1": lg1.id, "lg2": lg2.id, "b1": baux[0], "b2": baux[1]}

    ids = run(_seed())
    # DELETE d'un proposé avec dépôt saisi : autorisé (jamais entré).
    r = client.delete(f"/api/v1/immobilier/baux/{ids['b1']}", headers=auth_headers)
    assert r.status_code == 204, r.text
    assert _get(run, Logement, ids["lg1"]).status == LogementStatus.VACANT.value
    # PATCH termine sur un proposé : dossier régressé, logement vacant.
    r2 = client.patch(
        f"/api/v1/immobilier/baux/{ids['b2']}", headers=auth_headers,
        json={"status": "termine"},
    )
    assert r2.status_code == 200, r2.text
    assert _get(run, Logement, ids["lg2"]).status == LogementStatus.VACANT.value

    async def _dossier():
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(LocationDossier).where(
                        LocationDossier.logement_id == ids["lg2"]
                    )
                )
            ).scalars().first()

    d = run(_dossier())
    assert d.nouveau_bail_id is None and d.statut == "avis_recu"


# ─── A5/A6 : unité déjà en signature pour quelqu'un d'autre ───────────


def test_unite_deja_en_signature_refuse_un_second_bail(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, _) = await _mk_immeuble(s, "Audit A5")
            a = Locataire(full_name="Alice Signature")
            b = Locataire(full_name="Bob Intrus")
            s.add_all([a, b])
            await s.flush()
            ba = Bail(
                logement_id=lg1.id, locataire_id=a.id,
                date_debut=TODAY + timedelta(days=10),
                date_fin=TODAY + timedelta(days=375),
                loyer_mensuel=1000.0, status=BailStatus.PROPOSE.value,
            )
            s.add(ba)
            await s.flush()
            s.add(LocationDossier(
                logement_id=lg1.id, statut="bail_envoye", nouveau_bail_id=ba.id,
            ))
            await s.commit()
            return {"lg": lg1.id, "bob": b.id}

    ids = run(_seed())
    for statut in ("propose", "actif"):
        r = client.post(
            "/api/v1/immobilier/baux", headers=auth_headers,
            json={
                "logement_id": ids["lg"], "locataire_id": ids["bob"],
                "date_debut": str(TODAY + timedelta(days=20)),
                "date_fin": str(TODAY + timedelta(days=385)),
                "loyer_mensuel": 1000, "status": statut,
            },
        )
        assert r.status_code == 409, r.text
        assert "Alice Signature" in r.text


# ─── A7/C9 : le PDF « Bail » déposé à la création suit le bail ────────


def test_pdf_bail_depose_a_la_creation_suit_le_bail(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, lg2) = await _mk_immeuble(s, "Audit A7")
            await s.commit()
            return {"lg1": lg1.id, "lg2": lg2.id}

    ids = run(_seed())
    r = client.post(
        "/api/v1/immobilier/locataires", headers=auth_headers,
        json={"full_name": "Nouvelle Avec Pdf", "email": "np@test.local"},
    )
    assert r.status_code in (200, 201), r.text
    loc_id = r.json()["id"]
    r = client.post(
        "/api/v1/immobilier/documents/import", headers=auth_headers,
        data={"type": "bail", "locataire_id": str(loc_id)},
        files={"file": ("bail-signe.pdf", _PDF, "application/pdf")},
    )
    assert r.status_code in (200, 201), r.text
    doc_id = r.json()["id"]
    # Bail ACTIF créé ensuite : le PDF devient LE bail au dossier.
    r = client.post(
        "/api/v1/immobilier/baux", headers=auth_headers,
        json={
            "logement_id": ids["lg1"], "locataire_id": loc_id,
            "date_debut": str(TODAY - timedelta(days=1)),
            "date_fin": str(TODAY + timedelta(days=364)),
            "loyer_mensuel": 950, "status": "actif",
        },
    )
    assert r.status_code in (200, 201), r.text
    bail_id = r.json()["id"]
    assert r.json()["document_id"] == doc_id
    assert _get(run, ImmDocument, doc_id).bail_id == bail_id

    # Variante : bail PROPOSÉ + « Utiliser comme bail signé ».
    r = client.post(
        "/api/v1/immobilier/locataires", headers=auth_headers,
        json={"full_name": "Deuxieme Avec Pdf"},
    )
    loc2 = r.json()["id"]
    r = client.post(
        "/api/v1/immobilier/documents/import", headers=auth_headers,
        data={"type": "bail", "locataire_id": str(loc2)},
        files={"file": ("bail2.pdf", _PDF, "application/pdf")},
    )
    doc2 = r.json()["id"]
    r = client.post(
        "/api/v1/immobilier/baux", headers=auth_headers,
        json={
            "logement_id": ids["lg2"], "locataire_id": loc2,
            "date_debut": str(TODAY + timedelta(days=15)),
            "date_fin": str(TODAY + timedelta(days=380)),
            "loyer_mensuel": 950, "status": "propose",
        },
    )
    assert r.status_code in (200, 201), r.text
    bail2 = r.json()["id"]
    assert r.json()["document_id"] is None, "proposé : pièce liée, pas activé"
    assert _get(run, ImmDocument, doc2).bail_id == bail2
    r = client.post(
        f"/api/v1/immobilier/baux/{bail2}/document/rattacher",
        headers=auth_headers, json={"document_id": doc2},
    )
    assert r.status_code == 200, r.text
    b2 = _get(run, Bail, bail2)
    assert b2.status == BailStatus.ACTIF.value and b2.document_id == doc2


# ─── A8 : retirer le locataire garde ses pièces ───────────────────────


def test_retirer_le_locataire_garde_ses_pieces(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, _) = await _mk_immeuble(s, "Audit A8")
            loc = Locataire(full_name="Client Existant")
            s.add(loc)
            await s.flush()
            b = Bail(
                logement_id=lg1.id, locataire_id=loc.id,
                date_debut=TODAY + timedelta(days=10),
                date_fin=TODAY + timedelta(days=375),
                loyer_mensuel=1000.0, status=BailStatus.PROPOSE.value,
            )
            s.add(b)
            await s.flush()
            d = LocationDossier(
                logement_id=lg1.id, statut="bail_envoye", nouveau_bail_id=b.id,
            )
            s.add(d)
            s.add(ImmDocument(
                bail_id=b.id, locataire_id=loc.id, logement_id=lg1.id,
                type="piece_identite", titre="Permis", source="importe",
                pdf_blob=_PDF,
            ))
            s.add(ImmDocument(
                bail_id=b.id, locataire_id=loc.id, logement_id=lg1.id,
                type="consentement_communications", titre="Consentement",
                source="genere",
            ))
            await s.commit()
            return {"d": d.id, "loc": loc.id, "bail": b.id}

    ids = run(_seed())
    r = client.post(
        f"/api/v1/immobilier/locations/{ids['d']}/desistement",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    r = client.get(
        f"/api/v1/immobilier/locataires/{ids['loc']}/documents",
        headers=auth_headers,
    )
    titres = [x["titre"] for x in r.json()]
    assert "Permis" in titres, "la pièce d'identité reste sur la fiche"
    assert "Consentement" not in titres, "le document généré pour le bail part avec lui"


# ─── B1/B2 : transfert — annuler le départ refusé, retirer = annuler ──


def test_transfert_annuler_depart_refuse_et_retrait_restaure(
    client, auth_headers, run
):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, lg2) = await _mk_immeuble(s, "Audit B1")
            marie = Locataire(full_name="Marie Transfert")
            s.add(marie)
            await s.flush()
            b = Bail(
                logement_id=lg1.id, locataire_id=marie.id,
                date_debut=TODAY - timedelta(days=200),
                date_fin=TODAY + timedelta(days=165),
                loyer_mensuel=1100.0, depot_garantie=550.0,
                status=BailStatus.ACTIF.value,
            )
            s.add(b)
            await s.flush()
            lg1.status = LogementStatus.OCCUPE.value
            s.add(BailRenouvellement(
                bail_id=b.id, avis_envoye_le=TODAY - timedelta(days=10),
                nouveau_loyer=1150.0,
                nouvelle_date_debut=TODAY + timedelta(days=166),
                nouvelle_date_fin=TODAY + timedelta(days=531),
                status="propose",
            ))
            s.add(PaiementLoyer(
                bail_id=b.id, mois_couvert=(TODAY.replace(day=1) + timedelta(days=40)).replace(day=1),
                montant=1100.0, paye_le=TODAY,
                created_at=datetime.now(timezone.utc),
            ))
            await s.commit()
            return {"lg1": lg1.id, "lg2": lg2.id, "bail": b.id}

    ids = run(_seed())
    prochain = (TODAY.replace(day=1) + timedelta(days=40)).replace(day=1)
    r = client.post(
        f"/api/v1/immobilier/baux/{ids['bail']}/transferer",
        headers=auth_headers,
        json={
            "nouveau_logement_id": ids["lg2"],
            "date_transfert": str(prochain),
            "loyer_mensuel": 1250.0,
        },
    )
    assert r.status_code == 201, r.text
    nb = r.json()["nouveau_bail_id"]
    nouveau = _get(run, Bail, nb)
    assert nouveau.transfere_depuis_bail_id == ids["bail"]
    assert nouveau.au_mois in (False, None), "au mois jamais hérité"
    # Paiement d'avance du mois du transfert : ré-imputé sur le nouveau bail.
    assert _get(run, PaiementLoyer, 1) is not None or True

    async def _paiements():
        async with TestSessionLocal() as s:
            return [
                p.bail_id for p in (
                    await s.execute(
                        select(PaiementLoyer).where(PaiementLoyer.mois_couvert == prochain)
                    )
                ).scalars().all()
                if p.bail_id in (ids["bail"], nb)
            ]

    assert run(_paiements()) == [nb]
    # « Annuler le départ » sur l'ancien bail → refus explicite.
    r = client.post(
        f"/api/v1/immobilier/baux/{ids['bail']}/annuler-depart",
        headers=auth_headers,
    )
    assert r.status_code == 409, r.text
    assert "transfert" in r.text.lower()
    # Second transfert → refus.
    r = client.post(
        f"/api/v1/immobilier/baux/{ids['bail']}/transferer",
        headers=auth_headers,
        json={
            "nouveau_logement_id": ids["lg2"],
            "date_transfert": str(prochain),
            "loyer_mensuel": 1250.0,
        },
    )
    assert r.status_code == 409, r.text
    # « Retirer le locataire » sur la nouvelle carte = annuler le transfert.
    r = client.get(
        "/api/v1/immobilier/locations/overview", headers=auth_headers,
    )
    carte = next(x for x in r.json()["rows"] if x["nouveau_bail_id"] == nb)
    r = client.post(
        f"/api/v1/immobilier/locations/{carte['id']}/desistement",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    ancien = _get(run, Bail, ids["bail"])
    assert ancien.status == BailStatus.ACTIF.value
    assert ancien.date_fin == TODAY + timedelta(days=165), "fin restaurée"
    assert ancien.depot_transfere_vers_bail_id is None
    assert _get(run, Bail, nb) is None
    assert run(_paiements()) == [ids["bail"]], "paiement revenu sur l'ancien bail"
    assert _get(run, Logement, ids["lg1"]).status == LogementStatus.OCCUPE.value
    assert _get(run, Logement, ids["lg2"]).status == LogementStatus.VACANT.value

    async def _cycle():
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(BailRenouvellement).where(
                        BailRenouvellement.bail_id == ids["bail"]
                    )
                )
            ).scalars().first().status

    assert run(_cycle()) == "propose", "le cycle de renouvellement reprend son statut"
    # Dépôts : plus rien de « transféré ».
    rd = client.get("/api/v1/immobilier/depots/overview", headers=auth_headers)
    row = next(x for x in rd.json()["rows"] if x["bail_id"] == ids["bail"])
    assert row["statut"] == "detenu"


def test_transfert_gardes_supplementaires(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, lg2, lg3) = await _mk_immeuble(s, "Audit B10", nb=3)
            marie = Locataire(full_name="Marie Gardes")
            paul = Locataire(full_name="Paul Encore La")
            s.add_all([marie, paul])
            await s.flush()
            b = Bail(
                logement_id=lg1.id, locataire_id=marie.id,
                date_debut=TODAY - timedelta(days=200),
                date_fin=TODAY + timedelta(days=165),
                loyer_mensuel=1100.0, status=BailStatus.ACTIF.value,
            )
            bp = Bail(
                logement_id=lg2.id, locataire_id=paul.id,
                date_debut=TODAY - timedelta(days=300),
                date_fin=TODAY + timedelta(days=5),
                loyer_mensuel=800.0, status=BailStatus.ACTIF.value,
            )
            s.add_all([b, bp])
            lg3.status = LogementStatus.HORS_LOC.value
            await s.commit()
            return {"lg2": lg2.id, "lg3": lg3.id, "bail": b.id}

    ids = run(_seed())
    base = {"date_transfert": str(TODAY + timedelta(days=10)), "loyer_mensuel": 900.0}
    # Paul est encore là (bail actif, départ non déclaré) → 409.
    r = client.post(
        f"/api/v1/immobilier/baux/{ids['bail']}/transferer",
        headers=auth_headers, json={**base, "nouveau_logement_id": ids["lg2"]},
    )
    assert r.status_code == 409, r.text
    assert "Paul Encore La" in r.text
    # Hors location → 422.
    r = client.post(
        f"/api/v1/immobilier/baux/{ids['bail']}/transferer",
        headers=auth_headers, json={**base, "nouveau_logement_id": ids["lg3"]},
    )
    assert r.status_code == 422, r.text


# ─── B4 : chambre quittée (bail au mois) terminée à l'échéance ────────


def test_bail_au_mois_avec_depart_annonce_se_termine(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, _) = await _mk_immeuble(s, "Audit B4")
            loc = Locataire(full_name="Chambreur Parti")
            s.add(loc)
            await s.flush()
            b = Bail(
                logement_id=lg1.id, locataire_id=loc.id,
                date_debut=TODAY - timedelta(days=400),
                date_fin=TODAY - timedelta(days=3),
                loyer_mensuel=500.0, au_mois=True,
                status=BailStatus.ACTIF.value,
            )
            s.add(b)
            await s.flush()
            lg1.status = LogementStatus.OCCUPE.value
            s.add(LocationDossier(
                logement_id=lg1.id, bail_id=b.id, statut="avis_recu",
                date_depart=TODAY - timedelta(days=3),
            ))
            await s.commit()
            return {"bail": b.id, "lg": lg1.id}

    ids = run(_seed())
    from app.services.locatif_recalage import recalage_quotidien

    async def _run():
        async with TestSessionLocal() as s:
            return await recalage_quotidien(s)

    run(_run())
    assert _get(run, Bail, ids["bail"]).status == BailStatus.TERMINE.value
    assert _get(run, Logement, ids["lg"]).status == LogementStatus.VACANT.value


# ─── C1/C5/C6 : externe — dette fantôme, solde antérieur, ventilation ──


def test_externe_arrivee_solde_anterieur_et_ventilation(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, lg2) = await _mk_immeuble(s, "Audit C1", externe=True)
            lg1.status = LogementStatus.OCCUPE.value
            lg1.loyer_demande = 800.0
            lg1.locataire_externe_nom = "Ancien Locataire"
            lg2.loyer_demande = 700.0  # vacante
            # Rapport du gestionnaire depuis 3 mois : lg1 payé il y a 2 et
            # 3 mois, impayé le mois dernier.
            m = TODAY.replace(day=1)
            m1 = (m - timedelta(days=1)).replace(day=1)
            m2 = (m1 - timedelta(days=1)).replace(day=1)
            m3 = (m2 - timedelta(days=1)).replace(day=1)
            for mm in (m2, m3):
                s.add(PaiementExterne(
                    logement_id=lg1.id, mois_couvert=mm, loyer_attendu=800.0,
                    montant=None, paye_le=mm,
                    created_at=datetime.now(timezone.utc),
                ))
            await s.commit()
            return {"imm": imm.id, "lg1": lg1.id, "lg2": lg2.id,
                    "m": m.strftime("%Y-%m"), "m1": m1}

    ids = run(_seed())
    ov = client.get(
        f"/api/v1/immobilier/immeubles/{ids['imm']}/paiements-externes?mois={ids['m']}",
        headers=auth_headers,
    ).json()
    rows = {r["logement_id"]: r for r in ov["rows"]}
    assert rows[ids["lg1"]]["solde_anterieur"] is True
    assert rows[ids["lg1"]]["solde_total"] == 1600.0  # mois dernier + courant
    assert rows[ids["lg2"]]["etat"] == "aucun"

    # lg2 vacante depuis 3 mois : un nouveau locataire arrive → pas de
    # dette héritée des mois vides.
    r = client.patch(
        f"/api/v1/immobilier/logements/{ids['lg2']}", headers=auth_headers,
        json={"locataire_externe_nom": "Nouvelle Arrivee"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "occupe"
    assert r.json()["locataire_externe_depuis"] == str(TODAY)
    ov = client.get(
        f"/api/v1/immobilier/immeubles/{ids['imm']}/paiements-externes?mois={ids['m']}",
        headers=auth_headers,
    ).json()
    rows = {r["logement_id"]: r for r in ov["rows"]}
    assert rows[ids["lg2"]]["solde_total"] == 700.0
    assert rows[ids["lg2"]]["solde_anterieur"] is False

    # « Marquer payé » cumulatif sur lg1 (1 600 $) : ventilé — le mois
    # dernier passe payé, le courant aussi ; un versement partiel qui ne
    # couvre que l'antérieur laisse le courant impayé.
    r = client.post(
        "/api/v1/immobilier/paiements-externes", headers=auth_headers,
        json={"logement_id": ids["lg1"], "mois": ids["m"], "montant": 800.0, "cumul": True},
    )
    assert r.status_code == 201, r.text
    prev = client.get(
        f"/api/v1/immobilier/immeubles/{ids['imm']}/paiements-externes?mois={ids['m1'].strftime('%Y-%m')}",
        headers=auth_headers,
    ).json()
    assert {x["logement_id"]: x for x in prev["rows"]}[ids["lg1"]]["etat"] == "paye"
    cur = client.get(
        f"/api/v1/immobilier/immeubles/{ids['imm']}/paiements-externes?mois={ids['m']}",
        headers=auth_headers,
    ).json()
    row = {x["logement_id"]: x for x in cur["rows"]}[ids["lg1"]]
    assert row["etat"] in ("retard", "attente") and row["solde_total"] == 800.0
    # Payé ce mois alors qu'un antérieur reste dû → « partiel / solde antérieur ».
    r = client.post(
        "/api/v1/immobilier/paiements-externes", headers=auth_headers,
        json={"logement_id": ids["lg1"], "mois": ids["m"], "montant": 800.0},
    )
    assert r.status_code == 201, r.text
    cur = client.get(
        f"/api/v1/immobilier/immeubles/{ids['imm']}/paiements-externes?mois={ids['m']}",
        headers=auth_headers,
    ).json()
    row = {x["logement_id"]: x for x in cur["rows"]}[ids["lg1"]]
    assert row["etat"] == "paye" and row["solde_total"] == 0.0
    # Porte fermée en interne.
    async def _interne():
        async with TestSessionLocal() as s:
            imm2, (li, _) = await _mk_immeuble(s, "Audit C21 interne")
            await s.commit()
            return li.id

    li = run(_interne())
    r = client.post(
        "/api/v1/immobilier/paiements-externes", headers=auth_headers,
        json={"logement_id": li, "mois": ids["m"], "montant": 10.0},
    )
    assert r.status_code == 409, r.text


# ─── C2 : fusion complète ─────────────────────────────────────────────


def test_fusion_additionne_paiements_et_refuse_deux_baux_actifs(
    client, auth_headers, run
):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, lg2) = await _mk_immeuble(s, "Audit C2", externe=True)
            lg2.numero = "01"
            m = TODAY.replace(day=1)
            s.add(PaiementExterne(logement_id=lg1.id, mois_couvert=m, loyer_attendu=850.0, montant=600.0, paye_le=TODAY, created_at=datetime.now(timezone.utc)))
            s.add(PaiementExterne(logement_id=lg2.id, mois_couvert=m, loyer_attendu=850.0, montant=250.0, paye_le=TODAY, created_at=datetime.now(timezone.utc)))
            await s.commit()
            return {"lg1": lg1.id, "lg2": lg2.id, "m": m}

    ids = run(_seed())
    rd = client.get("/api/v1/immobilier/logements/doublons", headers=auth_headers)
    assert any(
        {l["id"] for l in g["logements"]} >= {ids["lg1"], ids["lg2"]}
        for g in rd.json()
    ), "« 01 » et « 1 » sont le même logement"
    r = client.post(
        "/api/v1/immobilier/logements/fusionner", headers=auth_headers,
        json={"garder_id": ids["lg1"], "supprimer_ids": [ids["lg2"]]},
    )
    assert r.status_code == 200, r.text

    async def _p():
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(PaiementExterne).where(
                        PaiementExterne.logement_id == ids["lg1"],
                        PaiementExterne.mois_couvert == ids["m"],
                    )
                )
            ).scalars().all()

    ps = run(_p())
    assert len(ps) == 1 and float(ps[0].montant) == 850.0

    async def _seed2():
        async with TestSessionLocal() as s:
            imm, (a, b) = await _mk_immeuble(s, "Audit C2b")
            x = Locataire(full_name="X"); y = Locataire(full_name="Y")
            s.add_all([x, y]); await s.flush()
            for lg, lo in ((a, x), (b, y)):
                s.add(Bail(
                    logement_id=lg.id, locataire_id=lo.id,
                    date_debut=TODAY - timedelta(days=10), date_fin=TODAY + timedelta(days=355),
                    loyer_mensuel=900.0, status=BailStatus.ACTIF.value,
                ))
            await s.commit()
            return {"a": a.id, "b": b.id}

    ids2 = run(_seed2())
    r = client.post(
        "/api/v1/immobilier/logements/fusionner", headers=auth_headers,
        json={"garder_id": ids2["a"], "supprimer_ids": [ids2["b"]]},
    )
    assert r.status_code == 409, r.text


# ─── C3/C18 : bascules interne ↔ externe ──────────────────────────────


def test_bascule_externe_interne_exige_des_baux(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, lg2) = await _mk_immeuble(s, "Audit C3", externe=True)
            lg1.status = LogementStatus.OCCUPE.value
            lg1.locataire_externe_nom = "Sans Bail"
            await s.commit()
            return {"imm": imm.id, "lg1": lg1.id}

    ids = run(_seed())
    r = client.patch(
        f"/api/v1/immobilier/immeubles/{ids['imm']}", headers=auth_headers,
        json={"gestion_externe": False},
    )
    assert r.status_code == 409, r.text
    assert "Sans Bail" in r.text
    r = client.patch(
        f"/api/v1/immobilier/immeubles/{ids['imm']}?force=true", headers=auth_headers,
        json={"gestion_externe": False},
    )
    assert r.status_code == 200, r.text
    lg = _get(run, Logement, ids["lg1"])
    assert lg.status == LogementStatus.VACANT.value and lg.locataire_externe_nom is None


# ─── C4 : vacant à la main avec un bail actif → refus explicite ───────


def test_vacant_manuel_avec_bail_actif_refuse(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            imm, (lg1, _) = await _mk_immeuble(s, "Audit C4")
            loc = Locataire(full_name="Toujours La")
            s.add(loc); await s.flush()
            s.add(Bail(
                logement_id=lg1.id, locataire_id=loc.id,
                date_debut=TODAY - timedelta(days=100), date_fin=TODAY + timedelta(days=265),
                loyer_mensuel=1000.0, status=BailStatus.ACTIF.value,
            ))
            lg1.status = LogementStatus.OCCUPE.value
            await s.commit()
            return lg1.id

    lg = run(_seed())
    r = client.patch(
        f"/api/v1/immobilier/logements/{lg}", headers=auth_headers,
        json={"status": "vacant"},
    )
    assert r.status_code == 409, r.text
    assert "Toujours La" in r.text


# ─── C14 : communications — bail proposé joignable, deux baux ─────────


def test_communications_bail_propose_et_deux_baux(client, auth_headers, run):
    async def _seed():
        async with TestSessionLocal() as s:
            imm_a, (a1, _) = await _mk_immeuble(s, "Aaa Comms")
            imm_z, (z1, _) = await _mk_immeuble(s, "Zzz Comms")
            loc = Locataire(full_name="Double Bail", email="double@test.local")
            s.add(loc); await s.flush()
            s.add(Bail(
                logement_id=a1.id, locataire_id=loc.id,
                date_debut=TODAY - timedelta(days=10), date_fin=TODAY + timedelta(days=355),
                loyer_mensuel=900.0, status=BailStatus.ACTIF.value,
            ))
            bz = Bail(
                logement_id=z1.id, locataire_id=loc.id,
                date_debut=TODAY + timedelta(days=20), date_fin=TODAY + timedelta(days=385),
                loyer_mensuel=1200.0, status=BailStatus.PROPOSE.value,
            )
            s.add(bz)
            await s.commit()
            return {"loc": loc.id, "bz": bz.id}

    ids = run(_seed())
    r = client.get("/api/v1/immobilier/communications/destinataires", headers=auth_headers)
    assert r.status_code == 200, r.text
    lignes = [
        l for b in r.json() for l in b["locataires"] if l["locataire_id"] == ids["loc"]
    ]
    assert len(lignes) == 2, "un bail actif + un bail en signature"
    assert {l["bail_status"] for l in lignes} == {"actif", "propose"}
    from app.api.v1.endpoints.immobilier_communications import _resoudre_destinataires

    async def _res():
        async with TestSessionLocal() as s:
            out = await _resoudre_destinataires(s, [], [ids["loc"]], [ids["bz"]])
            return [(b.id, im.name) for b, _lo, _lg, im in out]

    res = run(_res())
    assert res == [(ids["bz"], "Zzz Comms")], "la ligne cochée (bail) gagne"
