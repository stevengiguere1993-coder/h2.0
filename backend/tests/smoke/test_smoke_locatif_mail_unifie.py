"""Smoke — porte UNIQUE des courriels au locataire (audit 2026-08-17).

Verrouille les trois invariants que l'audit a trouvés cassés sur 4 des
6 chemins d'envoi (avis TAL, bail à signer, avis de renouvellement,
document en pièce jointe) :

1. le PROFIL D'EXPÉDITEUR configuré est appliqué — le locataire voit le
   bon nom et sa RÉPONSE part chez le gestionnaire, pas dans la boîte
   système ;
2. le journal d'audit ``imm_communications`` reçoit une ligne ;
3. le fil de la fiche du locataire reçoit une entrée.

+ les deux refus francs : aucun destinataire, mailer non configuré.
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.models.immobilier import (
    ImmCommunication,
    Locataire,
    LocataireCommunication,
)
from app.services.locatif_mail import (
    EnvoiLocataireError,
    envoyer_au_locataire,
)

from .conftest import TestSessionLocal


class FakeMailer:
    ready = True
    sender = "systeme@immohorizon.com"

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, **kw):
        self.sent.append(kw)


@pytest.fixture()
def profil(monkeypatch) -> FakeMailer:
    """Mailer factice + profil d'expéditeur « gestionnaire »."""
    import app.services.locatif_mail as mod

    fake = FakeMailer()
    monkeypatch.setattr(
        "app.integrations.email_graph.get_mailer", lambda: fake
    )

    async def _exp():
        return (
            "gestion@immohorizon.com",
            "Horizon — Gestion locative",
            "kyle.gestion@gmail.com",
        )

    monkeypatch.setattr(
        "app.api.v1.endpoints.immobilier_communications."
        "expediteur_defaut",
        _exp,
    )
    assert mod.envoyer_au_locataire is not None
    return fake


def _seed_locataire(run) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            loc = Locataire(full_name="Test Locataire Mail")
            s.add(loc)
            await s.commit()
            return loc.id

    return run(_go())


def _traces(run, locataire_id: int) -> tuple[list, list]:
    async def _go():
        async with TestSessionLocal() as s:
            audit = (
                await s.execute(
                    select(ImmCommunication).where(
                        ImmCommunication.locataire_id == locataire_id
                    )
                )
            ).scalars().all()
            fiche = (
                await s.execute(
                    select(LocataireCommunication).where(
                        LocataireCommunication.locataire_id
                        == locataire_id
                    )
                )
            ).scalars().all()
            return list(audit), list(fiche)

    return run(_go())


def test_profil_expediteur_et_double_trace(run, db_setup, profil):
    """Un envoi = le bon expéditeur + les DEUX traces."""
    loc_id = _seed_locataire(run)

    async def _envoi():
        async with TestSessionLocal() as s:
            await envoyer_au_locataire(
                s,
                destinataires=["locataire@example.com"],
                sujet="Avis de modification du bail",
                corps_html="<p>Bonjour</p>",
                type_envoi="avis_renouvellement",
                locataire_id=loc_id,
                locataire_nom="Test Locataire Mail",
                auteur_email="employe@immohorizon.com",
                resume_fiche="Avis de renouvellement envoyé",
            )
            await s.commit()

    run(_envoi())

    assert len(profil.sent) == 1
    envoi = profil.sent[0]
    assert envoi["to"] == ["locataire@example.com"]
    assert envoi["from_email"] == "gestion@immohorizon.com"
    assert envoi["from_name"] == "Horizon — Gestion locative"
    # LE point de l'audit : la réponse du locataire va au gestionnaire.
    assert envoi["reply_to"] == "kyle.gestion@gmail.com"

    audit, fiche = _traces(run, loc_id)
    assert len(audit) == 1
    assert audit[0].type == "avis_renouvellement"
    assert audit[0].destinataire_email == "locataire@example.com"
    assert audit[0].from_email == "gestion@immohorizon.com"
    assert len(fiche) == 1
    assert fiche[0].kind == "courriel"
    assert "renouvellement" in (fiche[0].contenu or "").lower()


def test_refus_sans_destinataire(run, db_setup, profil):
    """Locataire sans courriel → refus net, aucun envoi, aucune trace."""
    loc_id = _seed_locataire(run)

    async def _go():
        async with TestSessionLocal() as s:
            with pytest.raises(EnvoiLocataireError):
                await envoyer_au_locataire(
                    s,
                    destinataires=["", "   "],
                    sujet="Test",
                    corps_html="<p>x</p>",
                    type_envoi="libre",
                    locataire_id=loc_id,
                )

    run(_go())
    assert profil.sent == []
    audit, fiche = _traces(run, loc_id)
    assert audit == [] and fiche == []


def test_refus_mailer_non_configure(run, db_setup, monkeypatch):
    """Mailer absent → message explicite, rien de tracé."""
    loc_id = _seed_locataire(run)

    class MailerKO:
        ready = False
        sender = None

        async def send(self, **kw):  # pragma: no cover
            raise AssertionError("ne doit jamais être appelé")

    monkeypatch.setattr(
        "app.integrations.email_graph.get_mailer", lambda: MailerKO()
    )

    async def _go():
        async with TestSessionLocal() as s:
            with pytest.raises(EnvoiLocataireError) as exc:
                await envoyer_au_locataire(
                    s,
                    destinataires=["x@example.com"],
                    sujet="Test",
                    corps_html="<p>x</p>",
                    type_envoi="libre",
                    locataire_id=loc_id,
                )
            assert "Mailer" in str(exc.value)

    run(_go())
    audit, fiche = _traces(run, loc_id)
    assert audit == [] and fiche == []


def test_repli_reply_to_sur_la_boite_systeme(run, db_setup, monkeypatch):
    """Aucun profil configuré → la réponse retombe sur la boîte système
    (jamais dans le vide)."""
    loc_id = _seed_locataire(run)
    fake = FakeMailer()
    monkeypatch.setattr(
        "app.integrations.email_graph.get_mailer", lambda: fake
    )

    async def _exp():
        return (None, None, None)

    monkeypatch.setattr(
        "app.api.v1.endpoints.immobilier_communications."
        "expediteur_defaut",
        _exp,
    )

    async def _go():
        async with TestSessionLocal() as s:
            await envoyer_au_locataire(
                s,
                destinataires=["x@example.com"],
                sujet="Test",
                corps_html="<p>x</p>",
                type_envoi="libre",
                locataire_id=loc_id,
            )
            await s.commit()

    run(_go())
    assert fake.sent[0]["reply_to"] == "systeme@immohorizon.com"
