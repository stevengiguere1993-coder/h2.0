"""Smoke — refonte d'Immobilier, lot 2 : écran des loyers (Steven, 2026-11-13).

Ce que le nouvel écran demande au serveur :

- « Dix secondes pour annuler après Marquer payé » : la saisie renvoie
  TOUS les versements qu'elle a créés, et son auteur peut la défaire d'un
  bloc dans la foulée (jamais après, jamais quelqu'un d'autre) ;
- la même chose pour un logement en gestion externe (chaque mois touché
  retrouve son état d'avant) ;
- « dans l'historique, la pastille décrit le mois » : chaque versement de
  la fiche locataire porte le dû et le reçu de son mois ;
- « Aujourd'hui » compte les loyers comme la page Loyers (interne ET
  gestion externe).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models.immobilier import (
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
    PaiementExterne,
    PaiementLoyer,
)
from app.services import immobilier_presentation as pres

from tests.smoke.conftest import TestSessionLocal


def _mois(d: date, delta: int) -> date:
    m = d.month - 1 + delta
    return date(d.year + m // 12, m % 12 + 1, 1)


def _bail(client, auth_headers, run, nom: str, loyer: float = 800.0) -> dict:
    """Un bail actif commencé il y a 3 mois, jamais payé : quatre mois dus
    (les trois passés et le mois courant)."""

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(name=f"Refonte Loyers {nom}", address="2 rue Refonte", is_active=True)
            s.add(imm)
            await s.flush()
            lg = Logement(immeuble_id=imm.id, numero="3", status="vacant")
            loc = Locataire(full_name=f"Locataire {nom}")
            s.add_all([lg, loc])
            await s.commit()
            return {"immeuble_id": imm.id, "logement_id": lg.id, "locataire_id": loc.id}

    seed = run(_seed())
    debut = _mois(date.today(), -3)
    r = client.post("/api/v1/immobilier/baux", headers=auth_headers, json={
        "logement_id": seed["logement_id"], "locataire_id": seed["locataire_id"],
        "date_debut": debut.isoformat(), "date_fin": _mois(debut, 12).isoformat(),
        "loyer_mensuel": loyer, "status": "actif", "jour_echeance": 1,
    })
    assert r.status_code == 201, r.text
    seed["bail_id"] = r.json()["id"]
    return seed


def _ligne(client, auth_headers, bail_id: int) -> dict:
    lo = client.get("/api/v1/immobilier/loyers/overview", headers=auth_headers).json()
    return next(r for r in lo["rows"] if r["bail_id"] == bail_id)


def _payer(client, auth_headers, bail_id: int, montant: float) -> dict:
    r = client.post("/api/v1/immobilier/paiements", headers=auth_headers, json={
        "bail_id": bail_id,
        "mois_couvert": date.today().replace(day=1).isoformat(),
        "montant": montant,
        "paye_le": date.today().isoformat(),
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_lot_loyers_livre():
    lot = next(x for x in pres.LOTS if x["cle"] == "loyers")
    assert lot["livre"] is True
    assert pres.actifs(pres.normaliser({}))["loyers"] is True
    # L'interrupteur ramène l'écran actuel.
    assert pres.actifs(pres.normaliser({"loyers": False}))["loyers"] is False


def test_saisie_renvoie_ses_versements_et_s_annule_d_un_bloc(client, auth_headers, run):
    seed = _bail(client, auth_headers, run, "Annulation")
    avant = _ligne(client, auth_headers, seed["bail_id"])
    assert avant["solde_total"] == 3200.0
    assert len(avant["mois_impayes"]) == 4

    # 1 700 $ : le mois visé (800), puis les arriérés du plus ancien au
    # plus récent (800 + 100) → trois versements pour UN clic.
    cree = _payer(client, auth_headers, seed["bail_id"], 1700)
    assert cree["id"] == cree["versements_crees"][0]
    assert len(cree["versements_crees"]) == 3
    apres = _ligne(client, auth_headers, seed["bail_id"])
    assert apres["solde_total"] == 1500.0

    r = client.post(
        "/api/v1/immobilier/paiements/annuler-saisie",
        headers=auth_headers,
        json={"ids": cree["versements_crees"]},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"bail_id": seed["bail_id"], "annules": 3, "montant": 1700.0}

    # Tout est revenu : mêmes mois dus, même solde, plus aucun versement.
    retour = _ligne(client, auth_headers, seed["bail_id"])
    assert retour["solde_total"] == 3200.0
    assert retour["mois_impayes"] == avant["mois_impayes"]
    assert retour["etat"] == avant["etat"]
    hist = client.get(
        f"/api/v1/immobilier/baux/{seed['bail_id']}/paiements", headers=auth_headers
    ).json()
    assert hist == []

    # Une deuxième annulation de la même saisie ne retire rien d'autre.
    r = client.post(
        "/api/v1/immobilier/paiements/annuler-saisie",
        headers=auth_headers,
        json={"ids": cree["versements_crees"]},
    )
    assert r.status_code == 409, r.text


def test_annulation_reservee_a_l_auteur_dans_la_foulee(client, auth_headers, run):
    seed = _bail(client, auth_headers, run, "Gardes")
    autre = _bail(client, auth_headers, run, "Gardes B")
    url = "/api/v1/immobilier/paiements/annuler-saisie"

    def _modifier(ids: list[int], **champs) -> None:
        async def _s() -> None:
            async with TestSessionLocal() as s:
                for p in (
                    await s.execute(select(PaiementLoyer).where(PaiementLoyer.id.in_(ids)))
                ).scalars().all():
                    for k, v in champs.items():
                        setattr(p, k, v)
                await s.commit()

        run(_s())

    # Saisi par quelqu'un d'autre : refusé, rien n'est retiré.
    a = _payer(client, auth_headers, seed["bail_id"], 800)
    _modifier(a["versements_crees"], cree_par="quelquun.dautre@example.com")
    r = client.post(url, headers=auth_headers, json={"ids": a["versements_crees"]})
    assert r.status_code == 403, r.text

    # Trop tard : après le délai, c'est « Corriger le mois ».
    b = _payer(client, auth_headers, seed["bail_id"], 800)
    _modifier(
        b["versements_crees"],
        created_at=datetime.now(timezone.utc)
        - timedelta(seconds=immo_delai() + 60),
    )
    r = client.post(url, headers=auth_headers, json={"ids": b["versements_crees"]})
    assert r.status_code == 409, r.text
    assert "Corriger le mois" in r.json()["detail"]

    # Corrigé entre-temps : la saisie n'est plus celle du clic.
    c = _payer(client, auth_headers, seed["bail_id"], 800)
    _modifier(c["versements_crees"], modifie_le=datetime.now(timezone.utc))
    r = client.post(url, headers=auth_headers, json={"ids": c["versements_crees"]})
    assert r.status_code == 409, r.text

    # Deux saisies de deux baux ne s'annulent pas ensemble.
    d = _payer(client, auth_headers, seed["bail_id"], 800)
    e = _payer(client, auth_headers, autre["bail_id"], 800)
    r = client.post(
        url, headers=auth_headers,
        json={"ids": d["versements_crees"] + e["versements_crees"]},
    )
    assert r.status_code == 422, r.text
    # Corps mal formé.
    assert client.post(url, headers=auth_headers, json={"ids": []}).status_code == 422
    assert client.post(
        url, headers=auth_headers, json={"ids": [1], "bail_id": 1}
    ).status_code == 422

    # Aucun refus n'a retiré quoi que ce soit : les quatre saisies du
    # premier bail sont toujours là.
    hist = client.get(
        f"/api/v1/immobilier/baux/{seed['bail_id']}/paiements", headers=auth_headers
    ).json()
    assert round(sum(p["montant"] for p in hist), 2) == 3200.0


def immo_delai() -> int:
    from app.api.v1.endpoints.immobilier import DELAI_ANNULATION_SAISIE_S

    return DELAI_ANNULATION_SAISIE_S


def test_annulation_gestion_externe_remet_chaque_mois(client, auth_headers, run):
    mois = date.today().replace(day=1)
    prec = _mois(mois, -1)

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Refonte Externe", address="4 rue Externe",
                is_active=True, gestion_externe=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="EXT-R1",
                status=LogementStatus.OCCUPE.value, loyer_demande=900.0,
            )
            s.add(lg)
            await s.flush()
            # Le mois précédent a reçu 400 $ sur 900 $ (saisi hier).
            s.add(
                PaiementExterne(
                    logement_id=lg.id, mois_couvert=prec, montant=400.0,
                    loyer_attendu=900.0, paye_le=date.today() - timedelta(days=1),
                    created_at=datetime.now(timezone.utc),
                )
            )
            await s.commit()
            return {"logement_id": lg.id}

    seed = run(_seed())
    m = mois.strftime("%Y-%m")

    def _ligne_ext() -> dict:
        rows = client.get(
            f"/api/v1/immobilier/loyers/externes?mois={m}", headers=auth_headers
        ).json()["rows"]
        return next(r for r in rows if r["logement_id"] == seed["logement_id"])

    avant = _ligne_ext()
    assert avant["solde_total"] == 1400.0  # 500 du mois précédent + 900

    # « Marquer payé » sur le solde cumulatif : le mois précédent est
    # complété (ligne modifiée) et le mois courant est créé.
    r = client.post(
        "/api/v1/immobilier/paiements-externes", headers=auth_headers,
        json={"logement_id": seed["logement_id"], "mois": m, "montant": 1400, "cumul": True},
    )
    assert r.status_code == 201, r.text
    photo = r.json()["avant"]
    par_mois = {a["mois"]: a for a in photo}
    assert par_mois[prec.isoformat()] == {
        "mois": prec.isoformat(), "existait": True, "montant": 400.0,
        "paye_le": (date.today() - timedelta(days=1)).isoformat(),
        "loyer_attendu": 900.0,
    }
    assert par_mois[mois.isoformat()]["existait"] is False
    assert _ligne_ext()["solde_total"] == 0.0

    url = "/api/v1/immobilier/paiements-externes/annuler-saisie"
    r = client.post(
        url, headers=auth_headers,
        json={"logement_id": seed["logement_id"], "avant": photo},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"logement_id": seed["logement_id"], "mois_remis": 2}

    retour = _ligne_ext()
    assert retour["solde_total"] == 1400.0
    assert retour["etat"] == avant["etat"]
    assert retour["montant_paye"] == avant["montant_paye"]

    async def _lignes() -> dict:
        async with TestSessionLocal() as s:
            return {
                p.mois_couvert: (float(p.montant), p.paye_le)
                for p in (
                    await s.execute(
                        select(PaiementExterne).where(
                            PaiementExterne.logement_id == seed["logement_id"]
                        )
                    )
                ).scalars().all()
            }

    assert run(_lignes()) == {prec: (400.0, date.today() - timedelta(days=1))}

    # La saisie n'est plus là : une deuxième annulation est refusée, et
    # un mois qui n'a pas été saisi aujourd'hui ne se « remet » pas.
    r = client.post(
        url, headers=auth_headers,
        json={"logement_id": seed["logement_id"], "avant": photo},
    )
    assert r.status_code == 409, r.text
    assert run(_lignes()) == {prec: (400.0, date.today() - timedelta(days=1))}


def test_historique_la_pastille_decrit_le_mois(client, auth_headers, run):
    seed = _bail(client, auth_headers, run, "Historique", loyer=1000.0)
    # 750 $ sur les 1 000 $ du mois courant, en deux versements.
    _payer(client, auth_headers, seed["bail_id"], 500)
    _payer(client, auth_headers, seed["bail_id"], 250)
    dossier = client.get(
        f"/api/v1/immobilier/locataires/{seed['locataire_id']}/dossier",
        headers=auth_headers,
    )
    assert dossier.status_code == 200, dossier.text
    du_mois = [
        p for p in dossier.json()["paiements"]
        if p["mois_couvert"] == date.today().replace(day=1).isoformat()
    ]
    assert len(du_mois) == 2
    for p in du_mois:
        assert p["du_mois"] == 1000.0
        assert p["recu_mois"] == 750.0

    # Un frais de 20 $ sur le mois : le dû du mois le compte.
    r = client.post(
        f"/api/v1/immobilier/baux/{seed['bail_id']}/frais", headers=auth_headers,
        json={
            "mois_couvert": date.today().replace(day=1).isoformat(),
            "montant": 20, "libelle": "Frais de retard",
        },
    )
    assert r.status_code in (200, 201), r.text
    dossier = client.get(
        f"/api/v1/immobilier/locataires/{seed['locataire_id']}/dossier",
        headers=auth_headers,
    ).json()
    assert {p["du_mois"] for p in dossier["paiements"]} == {1020.0}


def test_aujourdhui_compte_les_loyers_comme_la_page(client, auth_headers):
    """La tuile « Impayés » de la page Loyers réunit l'interne et la
    gestion externe : la ligne d'« Aujourd'hui » qui y mène aussi."""
    lo = client.get("/api/v1/immobilier/loyers/overview", headers=auth_headers).json()
    ext = client.get("/api/v1/immobilier/loyers/externes", headers=auth_headers).json()
    attendu = lo["nb_retards"] + ext["nb_retards"]
    assert attendu >= 1
    auj = client.get("/api/v1/immobilier/aujourdhui", headers=auth_headers).json()
    assert auj["indisponibles"] == []
    ligne = next(x for x in auj["lignes"] if x["cle"] == "loyers")
    assert ligne["nb"] == attendu
