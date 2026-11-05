"""Smoke — numéros de facture sortis de la suite (2026-11-05).

Steven : « Pourquoi mes numéros de factures ont fait un bond, ramener ça à
la suite d'où j'étais après 171. Je ne devrais pas être dans les 10..
Mettre à jour les factures envoyées dans les 10.. en ordre d'envoi. »

Couvre :
1. un numéro QuickBooks hors série (1042) ne fait plus sauter le compteur ;
2. la renumérotation : simulation sans écriture, puis remise dans la suite
   en ordre d'ENVOI, numéros pris dans QB sautés, DocNumber mis à jour
   dans QuickBooks, compteur ramené juste après ;
3. une facture mensuelle QB (« Créé par Kratos — facture mensuelle »)
   n'est pas prise pour une facture Kratos dont le lien est perdu ;
4. l'adresse de l'entreprise figure sur le PDF de facture.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.models.facture import Facture
from app.services import facture_qbo as fq
from app.services import numbering
from app.services.facture_renumerotation import renumeroter_factures_hors_serie
from tests.smoke.conftest import TestSessionLocal
from tests.smoke.test_smoke_compteur_factures_qb_2026_10_17 import (  # noqa: F401
    _aligner,
    _base,
    _compteur,
)
from tests.smoke.test_smoke_facture_numero_pris_qb_2026_10_09 import (  # noqa: F401
    FauxQB,
    _facture,
    _seed,
    faux_qb,
)


def _lier(run, faux: FauxQB, fid: int, *, envoyee: datetime) -> str:
    """Facture déjà envoyée et synchronisée : Invoice QB signée Kratos."""
    fa = _facture(run, fid)
    iid = faux.ajouter(
        fa.reference, client="Connor", customer_id="C-CONNOR",
        total=float(fa.total), memo=fq.MEMO_KRATOS.format(id=fid),
    )

    async def _go() -> None:
        async with TestSessionLocal() as s:
            await s.execute(
                update(Facture)
                .where(Facture.id == fid)
                .values(
                    qbo_invoice_id=iid, qbo_doc_number=fa.reference,
                    qbo_sync_token="0", issued_at=envoyee,
                )
            )
            await s.commit()

    run(_go())
    return iid


# ── 1. Numéro QB hors série ignoré ────────────────────────────────────


def test_numero_qb_hors_serie_ne_fait_pas_sauter(faux_qb, run):
    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 171), compteur=b + 172)
    faux_qb.ajouter(str(b + 1042))  # autre série, saisie hors Kratos
    faux_qb.ajouter(str(b + 175))   # dans la série : compte

    res = _aligner(run)

    assert res["qb_max"] == b + 175
    assert res["qb_hors_serie"] == [b + 1042]
    assert res["apres"] == b + 176


def test_plus_haut_dans_la_serie():
    assert numbering.plus_haut_dans_la_serie([150, 171, 1042], 171) == (171, [1042])
    assert numbering.plus_haut_dans_la_serie([180, 1042], 171) == (180, [1042])
    # Base neuve : QuickBooks donne la série.
    assert numbering.plus_haut_dans_la_serie([96, 1042], 0) == (1042, [])
    assert numbering.plus_haut_dans_la_serie([], 171) == (0, [])


# ── 2. Renumérotation ────────────────────────────────────────────────


def test_renumerotation_en_ordre_d_envoi(faux_qb, run):
    b = _base(run)
    t0 = datetime(2026, 10, 26, 19, 0, tzinfo=timezone.utc)
    _seed(run, faux_qb, reference=str(b + 171), compteur=b + 1052)
    # Créées dans le désordre ; l'ordre d'envoi est 1043, 1045, 1046.
    f46 = _seed(run, faux_qb, reference=str(b + 1046), compteur=b + 1052, total=300.0)
    f43 = _seed(run, faux_qb, reference=str(b + 1043), compteur=b + 1052, total=100.0)
    f45 = _seed(run, faux_qb, reference=str(b + 1045), compteur=b + 1052, total=200.0)
    brouillon = _seed(
        run, faux_qb, reference=str(b + 1050), compteur=b + 1052, status="draft"
    )
    i46 = _lier(run, faux_qb, f46, envoyee=t0 + timedelta(days=3, minutes=50))
    i43 = _lier(run, faux_qb, f43, envoyee=t0)
    i45 = _lier(run, faux_qb, f45, envoyee=t0 + timedelta(days=3))
    faux_qb.ajouter(str(b + 1042))  # la cause : hors Kratos
    faux_qb.ajouter(str(b + 173))   # déjà pris dans QB par une autre facture

    async def _go(simuler: bool) -> dict:
        async with TestSessionLocal() as s:
            return await renumeroter_factures_hors_serie(
                s, seuil=b + 1000, simuler=simuler
            )

    # Simulation : le plan, rien d'écrit.
    sim = run(_go(True))
    assert [(p["ancien"], p["nouveau"]) for p in sim["plan"]] == [
        (str(b + 1043), str(b + 172)),
        (str(b + 1045), str(b + 174)),
        (str(b + 1046), str(b + 175)),
    ]
    assert [x["numero"] for x in sim["numeros_sautes_pris_dans_qb"]] == [str(b + 173)]
    assert [x["numero"] for x in sim["factures_qb_hors_serie"]] == [str(b + 1042)]
    assert sim["compteur_vise"] == b + 176
    assert _facture(run, f43).reference == str(b + 1043)
    assert faux_qb.invoices[i43]["DocNumber"] == str(b + 1043)

    # Pour de vrai.
    res = run(_go(False))
    assert res["erreur"] is None
    assert len(res["faites"]) == 3
    for fid, iid, num in ((f43, i43, 172), (f45, i45, 174), (f46, i46, 175)):
        fa = _facture(run, fid)
        assert fa.reference == str(b + num)
        assert fa.qbo_doc_number == str(b + num)
        assert faux_qb.invoices[iid]["DocNumber"] == str(b + num)
        assert "remise dans la suite" in (fa.internal_notes or "")
    # Le brouillon n'est pas touché ; le compteur repart juste après.
    assert _facture(run, brouillon).reference == str(b + 1050)
    assert _compteur(run) == b + 176


# ── 3. Facture mensuelle QB ≠ facture Kratos ─────────────────────────


def test_facture_mensuelle_pas_prise_pour_kratos():
    mensuelle = {"PrivateNote": "Créé par Kratos — facture mensuelle (frais de gestion locative)"}
    assert fq._est_de_kratos(mensuelle) is False
    assert fq._est_de_kratos({"PrivateNote": fq.MEMO_KRATOS.format(id=12)}) is True


def test_numero_mensuelle_suit_le_compteur(faux_qb, run):
    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 171), compteur=b + 172)
    faux_qb.ajouter(str(b + 1042))
    faux_qb.ajouter(str(b + 172))  # pris dans QB

    async def _go() -> str:
        async with TestSessionLocal() as s:
            n = await numbering.numero_pour_facture_qb_hors_kratos(s, faux_qb)
            await s.commit()
            return n

    assert run(_go()) == str(b + 173)
    assert _compteur(run) == b + 174


# ── 4. Adresse sur le PDF ────────────────────────────────────────────


def test_adresse_entreprise_sur_la_facture():
    import inspect

    from app.services import facture_pdf
    from app.services.soumission_pdf import COMPANY_ADDRESS

    assert "158 rue Maurice" in COMPANY_ADDRESS
    assert "COMPANY_ADDRESS" in inspect.getsource(facture_pdf)


# ── 5. Facture faite à la main dans QuickBooks (absente de Kratos) ───


def test_renumerotation_facture_qb_seule(faux_qb, run):
    from app.services.facture_renumerotation import renumeroter_facture_qb_seule

    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 179), compteur=b + 180)
    iid = faux_qb.ajouter(str(b + 1044), client="Millen & Legendre", total=1909.11)
    faux_qb.invoices[iid]["Line"] = [
        {
            "DetailType": "SalesItemLineDetail",
            "Amount": 1660.0,
            "Description": "Main-d'œuvre",
            "SalesItemLineDetail": {"ItemRef": {"name": "Services"}, "Qty": 20, "UnitPrice": 83.0},
        },
        {"DetailType": "SubTotalLineDetail", "Amount": 1660.0},
    ]

    async def _apercu() -> dict:
        async with TestSessionLocal() as s:
            return await renumeroter_factures_hors_serie(s, seuil=b + 1000, simuler=True)

    hors = run(_apercu())["factures_qb_hors_serie"]
    assert [x["numero"] for x in hors] == [str(b + 1044)]
    assert hors[0]["lignes"] == [
        {
            "produit": "Services", "description": "Main-d'œuvre",
            "quantite": 20, "prix_unitaire": 83.0, "montant": 1660.0,
        }
    ]

    async def _go(numero=None) -> dict:
        async with TestSessionLocal() as s:
            return await renumeroter_facture_qb_seule(
                s, qbo_invoice_id=iid, numero=numero
            )

    res = run(_go())
    assert res["ancien"] == str(b + 1044) and res["nouveau"] == str(b + 180)
    assert faux_qb.invoices[iid]["DocNumber"] == str(b + 180)
    assert _compteur(run) == b + 181
    # Plus rien hors série.
    assert run(_apercu())["factures_qb_hors_serie"] == []


def test_renumerotation_facture_qb_refus(faux_qb, run):
    import pytest

    from app.services.facture_renumerotation import renumeroter_facture_qb_seule

    b = _base(run)
    fid = _seed(run, faux_qb, reference=str(b + 179), compteur=b + 180)
    iid = _lier(run, faux_qb, fid, envoyee=datetime(2026, 11, 5, tzinfo=timezone.utc))
    autre = faux_qb.ajouter(str(b + 1044))

    async def _go(i, numero=None):
        async with TestSessionLocal() as s:
            return await renumeroter_facture_qb_seule(s, qbo_invoice_id=i, numero=numero)

    # Invoice d'une facture Kratos : refusée.
    with pytest.raises(ValueError):
        run(_go(iid))
    # Numéro déjà porté dans Kratos : refusé.
    with pytest.raises(ValueError):
        run(_go(autre, numero=str(b + 179)))
    assert faux_qb.invoices[autre]["DocNumber"] == str(b + 1044)
