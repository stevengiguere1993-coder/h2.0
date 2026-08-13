"""Smoke — Relevés 31 : sélection par CHEVAUCHEMENT + fenêtre de
production (retour Phil 2026-08-13).

Deux régressions couvertes :

1. « Pour 2026, Drissa n'apparaît même pas comme locataire. » — la liste
   se construisait à partir des baux couvrant le 31 décembre. Un bail
   qui commence en octobre N-1 et se termine en juin N faisait
   disparaître son locataire de l'année N. Elle se construit désormais
   par chevauchement de l'année d'imposition.
2. « Il devrait avoir un mécanisme m'empêchant de les créer avant. » —
   les relevés de l'année N ne se produisent qu'à partir du 1er décembre
   N (même bascule que ``releve31_bascule_mois``, défaut novembre).
"""
from __future__ import annotations

from datetime import date

from app.services.locatif_suivis import SuivisConfig


def _annee_fermee(today: date) -> int:
    """Une année dont la fenêtre de production n'est PAS encore ouverte."""
    return today.year if today < date(today.year, 12, 1) else today.year + 1


def _annee_ouverte(today: date) -> int:
    """Une année dont la fenêtre est ouverte depuis longtemps."""
    return today.year - 1


def _set_bascule(client, auth_headers, mois: int) -> None:
    """Fixe ``releve31_bascule_mois`` — d'autres smoke tests la bougent,
    on ne peut pas se fier au défaut."""
    r = client.put(
        "/api/v1/immobilier/suivis-config",
        headers=auth_headers,
        json={
            "renouvellement_mois_avant": 6,
            "assurance_bascule_mois": 1,
            "releve31_bascule_mois": mois,
        },
    )
    assert r.status_code == 200, r.text


# ── 1) Logique pure de la fenêtre (déterministe) ────────────────────


def test_ouverture_releve31_1er_decembre():
    """Bascule par défaut (novembre) → ouverture le 1er décembre de N."""
    c = SuivisConfig()  # releve31_bascule_mois = 11
    assert c.ouverture_releve31(2026) == date(2026, 12, 1)
    assert c.releve31_creation_ouverte(2026, date(2026, 11, 30)) is False
    assert c.releve31_creation_ouverte(2026, date(2026, 12, 1)) is True
    # Décembre + janvier + février pour produire ET remettre.
    assert c.releve31_creation_ouverte(2026, date(2027, 2, 28)) is True
    # L'ouverture suit la MÊME bascule que l'année par défaut de l'onglet.
    assert c.annee_releve31_defaut(date(2026, 11, 30)) == 2025
    assert c.annee_releve31_defaut(date(2026, 12, 1)) == 2026


def test_ouverture_suit_le_reglage():
    """Bascule réglée en septembre → ouverture le 1er octobre ; réglée en
    décembre → le 1er janvier N+1 (pas de mois 13)."""
    sept = SuivisConfig(releve31_bascule_mois=9)
    assert sept.ouverture_releve31(2026) == date(2026, 10, 1)
    dec = SuivisConfig(releve31_bascule_mois=12)
    assert dec.ouverture_releve31(2026) == date(2027, 1, 1)
    assert dec.releve31_creation_ouverte(2026, date(2026, 12, 31)) is False


# ── 2) Bout en bout : liste + garde-fou ─────────────────────────────


def test_releve31_chevauchement_et_fenetre(client, auth_headers, run):
    """Un bail qui ne couvre QU'UNE PARTIE de l'année N met quand même
    son locataire dans la liste de N ; la production est refusée avant le
    1er décembre N et acceptée après."""
    from app.models.immobilier import (
        Bail,
        BailStatus,
        Immeuble,
        Locataire,
        Logement,
        LogementStatus,
    )

    from .conftest import TestSessionLocal

    today = date.today()
    an_ouvert = _annee_ouverte(today)
    an_ferme = _annee_fermee(today)
    # Bascule = novembre (défaut produit) → ouverture le 1er décembre.
    _set_bascule(client, auth_headers, 11)

    async def _seed():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="8900 St-Hubert (smoke R31)",
                address="8900 rue Saint-Hubert",
                city="Montréal",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id,
                numero="8906-B",
                status=LogementStatus.OCCUPE.value,
            )
            loc = Locataire(full_name="Drissa Smoke R31")
            s.add_all([lg, loc])
            await s.flush()
            # Bail du 1er oct. (N-1) au 30 juin (N) : il NE couvre PAS le
            # 31 décembre de N — c'est exactement le cas rapporté.
            b = Bail(
                logement_id=lg.id,
                locataire_id=loc.id,
                date_debut=date(an_ouvert - 1, 10, 1),
                date_fin=date(an_ouvert, 6, 30),
                loyer_mensuel=1150.0,
                status=BailStatus.ACTIF.value,
            )
            s.add(b)
            await s.commit()
            return {"logement": lg.id, "immeuble": imm.id, "bail": b.id}

    ids = run(_seed())

    # (a) Le locataire apparaît pour l'année où il n'a occupé QUE le
    #     premier semestre — avant le correctif, la ligne était absente.
    d = client.get(
        f"/api/v1/immobilier/releves31?annee={an_ouvert}",
        headers=auth_headers,
    ).json()
    ligne = next(
        (r for r in d["rows"] if r["logement_id"] == ids["logement"]), None
    )
    assert ligne is not None, (
        f"Le logement 8906-B doit apparaître en {an_ouvert} même si son "
        f"bail se termine le 30 juin."
    )
    assert ligne["locataire_nom"] == "Drissa Smoke R31"
    assert ligne["bail_id"] == ids["bail"]
    # Période d'occupation bornée à l'année.
    assert ligne["occupation_debut"] == f"{an_ouvert}-01-01"
    assert ligne["occupation_fin"] == f"{an_ouvert}-06-30"
    assert [o["locataire_nom"] for o in ligne["occupants"]] == [
        "Drissa Smoke R31"
    ]

    # (b) … et aussi pour l'année précédente (occupée d'octobre à déc.).
    d0 = client.get(
        f"/api/v1/immobilier/releves31?annee={an_ouvert - 1}",
        headers=auth_headers,
    ).json()
    l0 = next(
        (r for r in d0["rows"] if r["logement_id"] == ids["logement"]), None
    )
    assert l0 is not None
    assert l0["occupation_debut"] == f"{an_ouvert - 1}-10-01"
    assert l0["occupation_fin"] == f"{an_ouvert - 1}-12-31"

    # (c) Fenêtre FERMÉE : création refusée en 422, message explicite.
    ferme = client.get(
        f"/api/v1/immobilier/releves31?annee={an_ferme}", headers=auth_headers
    ).json()
    assert ferme["creation_ouverte"] is False
    assert ferme["ouverture_le"] == f"{an_ferme}-12-01"
    r = client.patch(
        f"/api/v1/immobilier/releves31/{an_ferme}/{ids['logement']}",
        headers=auth_headers,
        json={"numero_releve": "R310000001"},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert str(an_ferme) in detail and "1er décembre" in detail
    assert str(an_ferme + 1) in detail  # remise avant fin février N+1

    # (d) Fenêtre OUVERTE : la même création passe.
    ouvert = client.get(
        f"/api/v1/immobilier/releves31?annee={an_ouvert}", headers=auth_headers
    ).json()
    assert ouvert["creation_ouverte"] is True
    assert ouvert["ouverture_le"] == f"{an_ouvert}-12-01"
    r = client.patch(
        f"/api/v1/immobilier/releves31/{an_ouvert}/{ids['logement']}",
        headers=auth_headers,
        json={"numero_releve": "R310000002"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["numero_releve"] == "R310000002"
    assert r.json()["statut"] == "produit"

    # Nettoyage : la ligne repart « à produire » et la config revient à
    # la valeur que laissent les autres smoke tests.
    client.delete(
        f"/api/v1/immobilier/releves31/{an_ouvert}/{ids['logement']}",
        headers=auth_headers,
    )
    _set_bascule(client, auth_headers, 2)


def test_releve31_deux_locataires_dans_lannee(client, auth_headers, run):
    """Changement de locataire en cours d'année : les DEUX apparaissent
    (aucun ne disparaît) et le relevé est porté par celui présent au
    31 décembre — la règle de Revenu Québec."""
    from app.models.immobilier import (
        Bail,
        BailStatus,
        Immeuble,
        Locataire,
        Logement,
        LogementStatus,
    )

    from .conftest import TestSessionLocal

    an = _annee_ouverte(date.today())

    async def _seed():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Duplex smoke R31 turnover",
                address="12 rue Turnover",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id,
                numero="T-1",
                status=LogementStatus.OCCUPE.value,
            )
            sortant = Locataire(full_name="Sortant Smoke R31")
            entrant = Locataire(full_name="Entrant Smoke R31")
            s.add_all([lg, sortant, entrant])
            await s.flush()
            s.add_all(
                [
                    Bail(
                        logement_id=lg.id, locataire_id=sortant.id,
                        date_debut=date(an - 1, 7, 1),
                        date_fin=date(an, 6, 30),
                        loyer_mensuel=900.0,
                        status=BailStatus.TERMINE.value,
                    ),
                    Bail(
                        logement_id=lg.id, locataire_id=entrant.id,
                        date_debut=date(an, 7, 1),
                        date_fin=date(an + 1, 6, 30),
                        loyer_mensuel=1000.0,
                        status=BailStatus.ACTIF.value,
                    ),
                ]
            )
            await s.commit()
            return lg.id

    lg_id = run(_seed())

    d = client.get(
        f"/api/v1/immobilier/releves31?annee={an}", headers=auth_headers
    ).json()
    ligne = next((r for r in d["rows"] if r["logement_id"] == lg_id), None)
    assert ligne is not None
    noms = {o["locataire_nom"] for o in ligne["occupants"]}
    assert noms == {"Sortant Smoke R31", "Entrant Smoke R31"}
    # Le relevé revient à l'occupant du 31 décembre.
    assert ligne["locataire_nom"] == "Entrant Smoke R31"
    principal = [o for o in ligne["occupants"] if o["principal"]]
    assert len(principal) == 1
    assert principal[0]["locataire_nom"] == "Entrant Smoke R31"
    # Un seul logement = une seule ligne (la clé du suivi reste
    # (année, logement) — pas de doublon dans le tableau).
    assert sum(1 for r in d["rows"] if r["logement_id"] == lg_id) == 1
