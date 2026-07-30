"""Smoke — Renouvellement v3 (2026-07-30) : cycle de réponse du
locataire. Délais légaux : réponse dans le MOIS de la réception
(art. 1945 C.c.Q., silence = réputé accepté) ; après un refus, le
locateur a un MOIS pour demander la fixation au TAL (art. 1947).
"""
from __future__ import annotations

from datetime import date, timedelta


def test_plus_un_mois():
    """« Un mois » légal = même jour le mois suivant ; un 31 tombe sur
    le dernier jour d'un mois plus court."""
    from app.api.v1.endpoints.immobilier_extras import _plus_un_mois

    assert _plus_un_mois(date(2026, 7, 15)) == date(2026, 8, 15)
    assert _plus_un_mois(date(2026, 1, 31)) == date(2026, 2, 28)
    assert _plus_un_mois(date(2024, 1, 31)) == date(2024, 2, 29)
    assert _plus_un_mois(date(2026, 12, 15)) == date(2027, 1, 15)
    assert _plus_un_mois(date(2026, 3, 31)) == date(2026, 4, 30)


def _seed(run, avis_envoye_le: date, avec_doc: bool = True):
    """Immeuble → logement → locataire → bail actif + cycle « propose »
    (et son document d'avis tokenisé si demandé)."""
    from app.models.immobilier import (
        Bail,
        BailRenouvellement,
        BailStatus,
        ImmDocument,
        Immeuble,
        Locataire,
        Logement,
        LogementStatus,
    )

    from .conftest import TestSessionLocal

    async def _s():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Renouv V3", address="9085 Avenue Millen",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="1",
                status=LogementStatus.OCCUPE.value,
            )
            lo = Locataire(full_name="Philippe Test V3")
            s.add_all([lg, lo])
            await s.flush()
            bail = Bail(
                logement_id=lg.id, locataire_id=lo.id,
                date_debut=date.today() - timedelta(days=250),
                date_fin=date.today() + timedelta(days=115),
                loyer_mensuel=1400.0,
                status=BailStatus.ACTIF.value,
            )
            s.add(bail)
            await s.flush()
            doc_id = None
            token = None
            if avec_doc:
                doc = ImmDocument(
                    bail_id=bail.id,
                    locataire_id=lo.id,
                    immeuble_id=imm.id,
                    type="avis_modification",
                    titre="Avis d'augmentation (test v3)",
                    signature_token="tok-v3-" + str(bail.id),
                )
                s.add(doc)
                await s.flush()
                doc_id = doc.id
                token = doc.signature_token
            ren = BailRenouvellement(
                bail_id=bail.id,
                avis_envoye_le=avis_envoye_le,
                nouveau_loyer=1450.0,
                nouvelle_date_debut=bail.date_fin + timedelta(days=1),
                status="propose",
                document_id=doc_id,
            )
            s.add(ren)
            await s.commit()
            return bail.id, ren.id, token

    return run(_s())


def _row_for(client, auth_headers, bail_id):
    rows = client.get(
        "/api/v1/immobilier/renouvellements/overview",
        headers=auth_headers,
    ).json()
    return next((r for r in rows if r["bail_id"] == bail_id), None)


def test_refus_en_ligne_et_deadlines(client, auth_headers, run):
    """Avis envoyé → jaune « attente » avec deadline ; refus PUBLIC (le
    lien du courriel) → rouge avec deadline de fixation TAL."""
    bail_id, ren_id, token = _seed(
        run, avis_envoye_le=date.today() - timedelta(days=3)
    )

    row = _row_for(client, auth_headers, bail_id)
    assert row is not None, "ligne absente de l'overview"
    assert row["reponse"] == "attente"
    assert row["deadline_reponse"] is not None
    assert row["fenetre"] == "envoye"

    # Refus depuis la page publique (le courriel du locataire).
    r = client.post(
        f"/api/v1/public/documents/{token}/refuser",
        json={"motif": "Hausse trop élevée."},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["refuse_le"] is not None
    assert d["refus_possible"] is False

    row = _row_for(client, auth_headers, bail_id)
    assert row["reponse"] == "refuse"
    assert row["deadline_fixation"] is not None  # art. 1947 : 1 mois
    assert "élevée" in (row["refus_motif"] or "")

    # Refuser deux fois → 409 propre.
    assert (
        client.post(
            f"/api/v1/public/documents/{token}/refuser", json={}
        ).status_code
        == 409
    )

    # ENTENTE négociée (hausse réduite) : PATCH manuel → accepté.
    p = client.patch(
        f"/api/v1/immobilier/renouvellements/{ren_id}",
        headers=auth_headers,
        json={"status": "accepte", "nouveau_loyer": 1425},
    )
    assert p.status_code == 200, p.text
    assert p.json()["status"] == "accepte"
    row = _row_for(client, auth_headers, bail_id)
    assert row["reponse"] == "accepte"


def test_repute_accepte_et_application(client, auth_headers, run):
    """Aucune réponse un mois après l'avis → RÉPUTÉ ACCEPTÉ
    (art. 1945) ; et à la date effective, le nouveau loyer est reporté
    sur le bail (lazy, à la consultation)."""
    from app.models.immobilier import Bail, BailRenouvellement

    from .conftest import TestSessionLocal

    # Avis envoyé il y a 40 jours → deadline (1 mois) dépassée.
    bail_id, ren_id, _tok = _seed(
        run, avis_envoye_le=date.today() - timedelta(days=40)
    )
    row = _row_for(client, auth_headers, bail_id)
    assert row["reponse"] == "repute_accepte"

    # Application : on force la date effective dans le PASSÉ puis on
    # re-consulte — le bail doit prendre 1450 $ et la nouvelle période.
    async def _forcer_date():
        async with TestSessionLocal() as s:
            ren = await s.get(BailRenouvellement, ren_id)
            ren.nouvelle_date_debut = date.today() - timedelta(days=1)
            ren.nouvelle_date_fin = date.today() + timedelta(days=364)
            await s.commit()

    run(_forcer_date())
    row = _row_for(client, auth_headers, bail_id)
    assert row["applique_le"] is not None
    assert row["bail_loyer_mensuel"] == 1450.0

    async def _verif_bail():
        async with TestSessionLocal() as s:
            b = await s.get(Bail, bail_id)
            return float(b.loyer_mensuel), b.date_fin

    loyer, fin = run(_verif_bail())
    assert loyer == 1450.0
    assert fin == date.today() + timedelta(days=364)


def test_refus_impossible_sur_document_sans_cycle(client, auth_headers, run):
    """Un document qui n'est pas un avis de modification ne peut pas
    être refusé en ligne (400 propre)."""
    from app.models.immobilier import ImmDocument

    from .conftest import TestSessionLocal

    async def _s():
        async with TestSessionLocal() as s:
            doc = ImmDocument(
                type="avis_acces",
                titre="Avis d'accès (test v3)",
                signature_token="tok-v3-acces",
            )
            s.add(doc)
            await s.commit()

    run(_s())
    r = client.post(
        "/api/v1/public/documents/tok-v3-acces/refuser", json={}
    )
    assert r.status_code == 400, r.text
