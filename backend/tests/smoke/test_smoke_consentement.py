"""Smoke — consentement aux communications électroniques.

Retour Phil 2026-08-19 : le document était bien PRÉPARÉ à la création du
bail — il dormait en « brouillon » dans la section Documents — mais rien
ne disait qu'il fallait l'envoyer, ni qui avait consenti. « Ça va tomber
entre les craques. »

Et surtout : « ça se peut qu'il refuse ». Or le refus n'existait que
pour l'avis de modification, qui porte un cycle de renouvellement. Un
locataire à qui on demandait son CONSENTEMENT n'avait aucun moyen de
dire non — la page publique ne proposait que « signer ». Un consentement
qu'on ne peut pas refuser n'est pas un consentement.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models.immobilier import (
    Bail,
    BailStatus,
    ImmDocument,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
)

from .conftest import TestSessionLocal


def _seed_bail(nom: str, adresse: str):
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name=nom, address=adresse, city="Montréal", is_active=True
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="1",
                status=LogementStatus.OCCUPE.value,
            )
            loc = Locataire(
                full_name=f"Locataire {nom}", email="consent@test.local"
            )
            s.add_all([lg, loc])
            await s.flush()
            b = Bail(
                logement_id=lg.id, locataire_id=loc.id,
                date_debut=date.today() - timedelta(days=60),
                date_fin=date.today() + timedelta(days=300),
                loyer_mensuel=1000.0, status=BailStatus.ACTIF.value,
            )
            s.add(b)
            await s.flush()
            await s.commit()
            return {
                "bail_id": b.id, "locataire_id": loc.id,
                "immeuble_id": imm.id,
            }

    return _seed


def test_overview_distingue_les_six_etats(client, auth_headers, run):
    """Un consentement jamais préparé, préparé mais jamais envoyé,
    envoyé, ouvert, signé et refusé ne demandent pas le même geste."""
    ids = run(_seed_bail("Consent Etats", "50 rue Consent")())

    async def _doc(**kw) -> None:
        async with TestSessionLocal() as s:
            s.add(
                ImmDocument(
                    bail_id=ids["bail_id"],
                    locataire_id=ids["locataire_id"],
                    immeuble_id=ids["immeuble_id"],
                    type="consentement_communications",
                    titre="Consentement aux communications électroniques",
                    **kw,
                )
            )
            await s.commit()

    def statut() -> str:
        r = client.get(
            "/api/v1/immobilier/consentements/overview", headers=auth_headers
        )
        assert r.status_code == 200, r.text
        ligne = next(
            x for x in r.json()["rows"]
            if x["locataire_id"] == ids["locataire_id"]
        )
        return ligne["statut"]

    # Aucun document du tout.
    assert statut() == "aucun"

    # Préparé au dossier, jamais envoyé — l'état que Phil voyait en
    # « brouillon » sans savoir quoi en faire.
    run(_doc())
    assert statut() == "pret"

    run(_doc(envoye_le=datetime(2026, 8, 1, tzinfo=timezone.utc)))
    assert statut() == "envoye"

    run(_doc(
        envoye_le=datetime(2026, 8, 1, tzinfo=timezone.utc),
        ouvert_le=datetime(2026, 8, 2, tzinfo=timezone.utc),
    ))
    assert statut() == "ouvert"

    run(_doc(
        envoye_le=datetime(2026, 8, 1, tzinfo=timezone.utc),
        refuse_le=datetime(2026, 8, 3, tzinfo=timezone.utc),
    ))
    assert statut() == "refuse", "un refus est un état, pas une absence"

    run(_doc(
        envoye_le=datetime(2026, 8, 1, tzinfo=timezone.utc),
        signed_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        signed_by_name="Locataire Consent Etats",
    ))
    assert statut() == "signe"


def test_le_locataire_peut_refuser_le_consentement(client, run):
    """La page publique doit OFFRIR le refus, et l'enregistrer."""
    ids = run(_seed_bail("Consent Refus", "52 rue Refus")())
    token = "tok-consent-refus"

    async def _doc() -> None:
        async with TestSessionLocal() as s:
            s.add(
                ImmDocument(
                    bail_id=ids["bail_id"],
                    locataire_id=ids["locataire_id"],
                    immeuble_id=ids["immeuble_id"],
                    type="consentement_communications",
                    titre="Consentement aux communications électroniques",
                    signature_token=token,
                    envoye_le=datetime(2026, 8, 1, tzinfo=timezone.utc),
                )
            )
            await s.commit()

    run(_doc())

    vue = client.get(f"/api/v1/public/documents/{token}")
    assert vue.status_code == 200, vue.text
    assert vue.json()["refus_possible"] is True, (
        "un consentement qu'on ne peut pas refuser n'est pas un "
        "consentement"
    )

    r = client.post(
        f"/api/v1/public/documents/{token}/refuser",
        json={"motif": "Je préfère le courrier papier"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["refuse_le"] is not None

    # Un deuxième refus est refusé net (anti-rejeu).
    r2 = client.post(
        f"/api/v1/public/documents/{token}/refuser", json={"motif": "encore"}
    )
    assert r2.status_code == 409, r2.text


def test_un_document_sans_signature_ne_se_refuse_pas(client, run):
    """Un avis d'accès ne demande aucune réponse : proposer un refus n'y
    aurait aucun sens."""
    ids = run(_seed_bail("Consent Info", "54 rue Info")())
    token = "tok-consent-info"

    async def _doc() -> None:
        async with TestSessionLocal() as s:
            s.add(
                ImmDocument(
                    bail_id=ids["bail_id"],
                    locataire_id=ids["locataire_id"],
                    type="avis_acces", titre="Avis d'accès",
                    signature_token=token,
                )
            )
            await s.commit()

    run(_doc())
    assert client.get(
        f"/api/v1/public/documents/{token}"
    ).json()["refus_possible"] is False
    r = client.post(
        f"/api/v1/public/documents/{token}/refuser", json={}
    )
    assert r.status_code == 400, r.text
