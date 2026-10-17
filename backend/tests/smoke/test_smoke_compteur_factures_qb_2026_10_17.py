"""Smoke — compteur de factures aligné sur QuickBooks (2026-10-17).

Steven : « quand des factures se créent dans QB, le compteur ne se met pas
à jour dans Kratos, ce qui crée des erreurs dans les numéros de
facturation. Le compteur de facturation doit toujours être 1 plus haut que
QB ou Kratos (le plus élevé des 2 dans les numéros de facture). »

Avant : le compteur ne faisait que SAUTER les numéros déjà pris, un par
un (161 pris dans QB → 162…) ; une facture 170 saisie dans QB laissait le
compteur à 160 et chaque numéro intermédiaire devait être essayé.

Couvre :
1. QB plus haut que Kratos → prochain numéro = max QB + 1 ;
2. Kratos plus haut que QB (facture importée) → max Kratos + 1 ;
3. QB injoignable → Kratos seul, sans bloquer la numérotation ;
4. le compteur n'est jamais ABAISSÉ ;
5. les numéros non numériques (QB ou Kratos) sont ignorés ;
6. les factures du pôle logiciel (INV-AAAA-NNNNN, même compteur) comptent ;
7. l'aperçu du prochain numéro libre suit la même règle ;
8. le recalage dans sa propre session (démarrage, filet horaire) ;
9. le bouton « Aligner sur QuickBooks » (POST …/aligner-factures).

QuickBooks est simulé en mémoire (FauxQB du smoke 2026-10-09).
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import delete, select, update

from app.models.devlog_invoice import DevlogInvoice
from app.models.facture import Facture
from app.models.numbering_counter import NumberingCounter
from app.services import numbering
from tests.smoke.conftest import TestSessionLocal
from tests.smoke.test_smoke_facture_numero_pris_qb_2026_10_09 import (  # noqa: F401
    FauxQB,
    _facture,
    _seed,
    faux_qb,
)


def _base(run) -> int:
    """Plage de numéros AU-DESSUS de tout ce que la base de test
    contient déjà (factures d'autres tests) : le recalage prend le plus
    haut numéro existant, il faut donc partir plus haut."""

    async def _max() -> int:
        async with TestSessionLocal() as s:
            refs = (await s.execute(select(Facture.reference))).scalars().all()
            nums = (await s.execute(select(DevlogInvoice.number))).scalars().all()
        plus_haut = 0
        for r in list(refs) + list(nums):
            n = numbering.numero_compteur_de_reference(r)
            if n is not None and n > plus_haut:
                plus_haut = n
        return plus_haut

    return max(run(_max()), 100_000) + 1000 + (uuid.uuid4().int % 800) * 1000


def _compteur(run) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            return int(
                (
                    await s.execute(
                        select(NumberingCounter.next_facture_number).where(
                            NumberingCounter.id == 1
                        )
                    )
                ).scalar_one()
            )

    return run(_go())


def _attribuer(run, fid: int) -> str:
    """Attribue le numéro définitif à un brouillon (comme à l'envoi)."""

    async def _go() -> str:
        async with TestSessionLocal() as s:
            fa = (await s.execute(select(Facture).where(Facture.id == fid))).scalar_one()
            await numbering.ensure_facture_number(s, fa)
            await s.commit()
            return fa.reference

    return run(_go())


def _aligner(run, **kw) -> dict:
    async def _go() -> dict:
        async with TestSessionLocal() as s:
            res = await numbering.aligner_compteur_factures(s, **kw)
            await s.commit()
            return res

    return run(_go())


def _devlog(run, faux: FauxQB, number: Optional[str]) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            inv = DevlogInvoice(number=number, amount=100.0, status="draft")
            s.add(inv)
            await s.commit()
            return int(inv.id)

    iid = run(_go())
    faux.crees.setdefault("devlog", []).append(iid)  # type: ignore[attr-defined]
    return iid


def _nettoyer_devlog(run, faux: FauxQB) -> None:
    ids = faux.crees.get("devlog") or []  # type: ignore[attr-defined]
    if not ids:
        return

    async def _go() -> None:
        async with TestSessionLocal() as s:
            await s.execute(delete(DevlogInvoice).where(DevlogInvoice.id.in_(ids)))
            await s.commit()

    run(_go())


# ── 1. QB plus haut que Kratos ────────────────────────────────────────


def test_facture_qb_fait_avancer_le_compteur(faux_qb, run):
    """Compteur à 160, dernière facture Kratos 160, factures 161 et 162
    saisies directement dans QB → la prochaine facture Kratos est 163
    (et non 161 → sautée → 162 → sautée)."""
    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 160), compteur=b + 161)
    faux_qb.ajouter(str(b + 161), total=500.0)
    faux_qb.ajouter(str(b + 162), total=600.0)
    brouillon = _seed(
        run, faux_qb, reference=f"BR-{uuid.uuid4().hex[:6]}", compteur=b + 161,
        status="draft",
    )

    assert _attribuer(run, brouillon) == str(b + 163)
    assert _compteur(run) == b + 164


def test_aligner_retourne_le_detail(faux_qb, run):
    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 160), compteur=b + 161)
    faux_qb.ajouter(str(b + 170))

    res = _aligner(run)

    assert res == {
        "avant": b + 161,
        "apres": b + 171,
        "kratos_max": b + 160,
        "qb_max": b + 170,
        "qb_consulte": True,
    }
    assert _compteur(run) == b + 171


# ── 2. Kratos plus haut que QB ────────────────────────────────────────


def test_facture_kratos_importee_compte_aussi(faux_qb, run):
    """Facture 170 dans Kratos (import), QB n'a que 165, compteur à 161 →
    prochaine facture 171."""
    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 170), compteur=b + 161)
    faux_qb.ajouter(str(b + 165))
    brouillon = _seed(
        run, faux_qb, reference=f"BR-{uuid.uuid4().hex[:6]}", compteur=b + 161,
        status="draft",
    )

    assert _attribuer(run, brouillon) == str(b + 171)


# ── 3. QB injoignable ─────────────────────────────────────────────────


def test_qb_injoignable_ne_bloque_pas(faux_qb, run):
    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 160), compteur=b + 150)
    faux_qb.ajouter(str(b + 175))
    faux_qb.ready = False

    res = _aligner(run)

    assert res["qb_consulte"] is False and res["qb_max"] is None
    assert res["kratos_max"] == b + 160
    assert res["apres"] == b + 161
    # QB de retour : le recalage suivant rattrape la facture 175.
    faux_qb.ready = True
    assert _aligner(run)["apres"] == b + 176


def test_erreur_qb_ne_bloque_pas(faux_qb, run):
    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 160), compteur=b + 161)

    async def _boom(q: str):
        raise RuntimeError("QB en panne")

    faux_qb.query = _boom  # type: ignore[method-assign]
    brouillon = _seed(
        run, faux_qb, reference=f"BR-{uuid.uuid4().hex[:6]}", compteur=b + 161,
        status="draft",
    )

    assert _attribuer(run, brouillon) == str(b + 161)


# ── 4. Jamais abaissé ─────────────────────────────────────────────────


def test_compteur_jamais_abaisse(faux_qb, run):
    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 160), compteur=b + 200)
    faux_qb.ajouter(str(b + 162))

    res = _aligner(run)

    assert res["avant"] == res["apres"] == b + 200
    assert _compteur(run) == b + 200


# ── 5. Numéros non numériques ─────────────────────────────────────────


def test_numeros_non_numeriques_ignores(faux_qb, run):
    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 160), compteur=b + 161)
    _seed(run, faux_qb, reference="F-ABC", compteur=b + 161)
    # Libellés à la main ou d'autres flux : pas des numéros du compteur.
    _seed(run, faux_qb, reference=f"ECH-{b + 900}", compteur=b + 161)
    _seed(run, faux_qb, reference=f"FA-{b + 800}", compteur=b + 161)
    faux_qb.ajouter("EST-99999999")
    faux_qb.ajouter(f"{b + 165}-A")
    faux_qb.ajouter("")

    res = _aligner(run)

    assert res["kratos_max"] == b + 160
    assert res["qb_max"] == 0
    assert res["apres"] == b + 161


# ── 6. Factures du pôle logiciel ──────────────────────────────────────


def test_facture_devlog_compte_aussi(faux_qb, run):
    b = _base(run)
    try:
        _seed(run, faux_qb, reference=str(b + 160), compteur=b + 161)
        _devlog(run, faux_qb, f"INV-2026-{b + 180:05d}")
        _devlog(run, faux_qb, None)

        res = _aligner(run)

        assert res["kratos_max"] == b + 180
        assert res["apres"] == b + 181
    finally:
        _nettoyer_devlog(run, faux_qb)


# ── 7. Aperçu du prochain numéro libre ────────────────────────────────


def test_apercu_suit_quickbooks(faux_qb, run):
    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 160), compteur=b + 161)
    faux_qb.ajouter(str(b + 162))

    async def _go() -> str:
        async with TestSessionLocal() as s:
            return await numbering.apercu_prochain_numero_libre(s)

    assert run(_go()) == str(b + 163)
    # L'aperçu ne modifie rien.
    assert _compteur(run) == b + 161


# ── 8. Recalage dans sa propre session (démarrage, filet horaire) ─────


def test_recalage_une_session(faux_qb, run):
    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 160), compteur=b + 161)
    faux_qb.ajouter(str(b + 164))

    res = run(numbering.aligner_compteur_factures_une_session())

    assert res["apres"] == b + 165
    assert _compteur(run) == b + 165


# ── 9. Bouton « Aligner sur QuickBooks » ──────────────────────────────


def test_endpoint_aligner_factures(faux_qb, run, client, auth_headers):
    b = _base(run)
    _seed(run, faux_qb, reference=str(b + 160), compteur=b + 161)
    faux_qb.ajouter(str(b + 166))

    r = client.post("/api/v1/settings/numbering/aligner-factures", headers=auth_headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["avant"] == b + 161
    assert body["apres"] == b + 167
    assert body["kratos_max"] == b + 160
    assert body["qb_max"] == b + 166
    assert body["qb_consulte"] is True
    assert body["compteurs"]["next_facture_number"] == b + 167
    assert _compteur(run) == b + 167
