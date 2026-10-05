"""Paiement automatique des lots par VoPay (Comptabilité → Paiements).

Steven (2026-10-05) : « l'idée est de ne pas faire les virements nous-mêmes.
Juste approuver et que tout se fasse par la suite ! », puis « l'idée est
de reproduire Plooto et ce qu'il fait ». Desjardins n'a pas d'API : une
entreprise qui active le paiement automatique dans ses réglages confie à
VoPay (``app.integrations.vopay``) le prélèvement de son compte Desjardins
et le paiement de ses fournisseurs. Personne n'envoie plus rien dans
AccèsD ; l'approbation (autre personne, double authentification) reste le
seul geste humain avant l'argent.

Un lot payé automatiquement (``LotPaiement.envoi_auto``, décidé à la
dernière approbation) suit ces étapes :

1. ``approuve`` : le jour du lot venu, Kratos relit les soldes dans
   QuickBooks, vérifie les coordonnées approuvées et l'adresse des
   fournisseurs, puis demande à VoPay de prélever le total du lot dans le
   compte de l'entreprise. Ce qui bloque (réglages, QuickBooks…) est
   affiché sur le lot et réessayé.
2. ``prelevement`` : Kratos suit le prélèvement. Refusé, le lot passe à
   ``echec`` : aucun argent n'a bougé, un approbateur réessaie, remet le
   lot en brouillon ou l'annule.
3. ``envoi`` : l'argent est chez VoPay ; un paiement par fournisseur (dépôt
   direct ou virement Interac, selon le lot), suivi jusqu'au bout. Un
   paiement refusé attend un approbateur : réessayer (coordonnées
   approuvées du moment) ou retirer le fournisseur du lot, et l'argent
   revient au compte de l'entreprise (opération « retour »).
4. ``transmis`` puis ``paye`` : tous les fournisseurs sont payés ; les
   paiements sont inscrits dans QuickBooks (``VOP-<lot>-<fournisseur>``).
   En environnement de test VoPay, rien n'est inscrit dans QuickBooks.

Jamais deux paiements pour une même opération : chaque opération a sa clé
d'idempotence, gardée en base avant l'envoi. Une demande est « réclamée »
(statut ``envoi``, validé en base) avant de partir, ce qui empêche deux
serveurs de l'envoyer en même temps. Une réponse perdue est reprise une
fois avec la même clé (VoPay refuse le doublon) ; une deuxième incertitude
attend qu'un approbateur dise, portail VoPay à l'appui, si la demande est
partie. Une nouvelle clé n'est créée que par un approbateur (réessayer).

``boucle()`` (démarrée avec l'application) fait avancer les lots et suit
les opérations toutes les 5 minutes ; aucun webhook n'est exposé.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import vopay
from app.integrations.vopay import Adresse, VoPay, VoPayErreur, VoPayIncertain
from app.models.entreprise import Entreprise
from app.models.paiement_fournisseur import (
    FournisseurCompteBancaire,
    LotPaiement,
    LotPaiementLigne,
    PaiementOperation,
    PaiementReglage,
)
from app.models.user import User
from app.services import paiements_fournisseurs as pf
from app.services.secret_vault import VaultNotConfigured, decrypt_secret

log = logging.getLogger(__name__)

#: Premier passage de la boucle après le démarrage, puis intervalle.
PREMIER_PASSAGE_S = 120
INTERVALLE_S = 300
#: Demande restée « envoi » plus longtemps (serveur arrêté pendant
#: l'envoi) : traitée comme une réponse perdue.
ENVOI_SANS_REPONSE = timedelta(minutes=15)
#: Réponse perdue : Kratos reprend la demande, avec la même clé, après ce délai.
REPRISE_INCERTAINE = timedelta(minutes=10)
#: VoPay injoignable ou solde VoPay insuffisant : nouvel essai après ces
#: délais (minutes), puis l'opération est refusée.
ATTENTES = (5, 15, 30, 60, 120, 240, 480, 720)
#: Ce qui bloque avant l'envoi (QuickBooks injoignable…) : nouvel essai.
REPRISE_BLOCAGE = timedelta(minutes=30)
#: Lot bloqué avant le prélèvement, ou inscription QuickBooks à reprendre.
REPRISE_LOT = timedelta(minutes=30)

#: Opérations qui ne sont pas terminées.
OPS_OUVERTES = ("a_envoyer", "envoi", "incertain", "a_verifier", "en_cours")
LIBELLES_OPERATION = {
    "a_envoyer": "À envoyer",
    "envoi": "Envoi à VoPay",
    "incertain": "Réponse perdue, Kratos réessaie",
    "a_verifier": "À vérifier dans VoPay",
    "en_cours": "En cours",
    "reussi": "Réussi",
    "echoue": "Refusé",
    "annule": "Annulé",
}
SORTES = {
    "prelevement": "Prélèvement",
    "paiement": "Paiement",
    "retour": "Retour à l'entreprise",
}
#: Statuts d'un lot payé automatiquement que la boucle fait avancer.
LOTS_EN_COURS = ("approuve", "prelevement", "envoi", "transmis")


class Bloque(Exception):
    """Ce qui empêche une étape d'avancer maintenant ; rien n'a été envoyé
    à VoPay."""

    def __init__(self, message: str, *, temporaire: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.temporaire = temporaire


# ──────────────────────────────────────────────────────────────────────
# Client VoPay et adresses
# ──────────────────────────────────────────────────────────────────────


def connexion(
    account_id: str, cle: str, secret: str, environnement: str, sous_compte: Optional[str] = None
) -> VoPay:
    """Un client VoPay ; les tests le remplacent par un faux."""
    return VoPay(account_id, cle, secret, environnement, sous_compte)


def _dechiffrer(valeur: Optional[str], quoi: str) -> str:
    if not valeur:
        raise Bloque(f"« {quoi} » manque dans les réglages des paiements.")
    try:
        return decrypt_secret(valeur)
    except (VaultNotConfigured, ValueError) as exc:
        raise Bloque(
            "La clé de chiffrement de Kratos est absente ou a changé : saisis de nouveau "
            f"« {quoi} » dans les réglages des paiements."
        ) from exc


def client(r: Optional[PaiementReglage], environnement: Optional[str] = None) -> VoPay:
    """Client VoPay d'une entreprise, avec ses clés déchiffrées."""
    if r is None or not r.vopay_account_id:
        raise Bloque("Le compte VoPay de l'entreprise n'est pas saisi dans les réglages des paiements.")
    cle = _dechiffrer(r.vopay_cle_chiffree, "Clé API VoPay")
    secret = _dechiffrer(r.vopay_secret_chiffre, "Secret partagé VoPay")
    return connexion(r.vopay_account_id, cle, secret, environnement or r.auto_environnement or "test", r.vopay_sous_compte)


def _client_op(r: Optional[PaiementReglage], op: PaiementOperation) -> VoPay:
    if r is not None and (r.auto_environnement or "test") != op.environnement:
        raise Bloque(
            "L'environnement VoPay de l'entreprise a changé depuis cette opération : "
            "vérifie-la dans le portail VoPay."
        )
    return client(r, op.environnement)


def adresse_entreprise(r: PaiementReglage) -> Adresse:
    province = pf.province_canadienne(r.province)
    code_postal = pf.code_postal_canadien(r.code_postal)
    if not (r.adresse and r.ville and province and code_postal):
        raise Bloque("L'adresse de l'entreprise est incomplète dans les réglages des paiements (VoPay l'exige).")
    return Adresse(r.adresse.strip(), r.ville.strip(), province, code_postal)


def _compte_entreprise(r: PaiementReglage) -> None:
    if not (r.retour_institution and r.retour_transit and r.retour_compte):
        raise Bloque("Le compte bancaire de l'entreprise manque dans les réglages des paiements.")


def adresse_qbo(fournisseur: Dict[str, Any]) -> Optional[Adresse]:
    """Adresse de facturation d'un fournisseur QuickBooks, si elle est
    complète et canadienne (VoPay l'exige pour un dépôt direct)."""
    a = fournisseur.get("BillAddr") or {}
    pays = str(a.get("Country") or "").strip().lower()
    if pays and pays not in ("ca", "can", "canada"):
        return None
    ligne = ", ".join(str(a.get(k)).strip() for k in ("Line1", "Line2") if str(a.get(k) or "").strip())
    ville = str(a.get("City") or "").strip()
    province = pf.province_canadienne(a.get("CountrySubDivisionCode"))
    code_postal = pf.code_postal_canadien(a.get("PostalCode"))
    if not (ligne and ville and province and code_postal):
        return None
    return Adresse(ligne[:100], ville[:60], province, code_postal)


async def _adresses_fournisseurs(scope: str, vids: Iterable[str]) -> Dict[str, Optional[Adresse]]:
    qbo = pf._qbo(scope)
    out: Dict[str, Optional[Adresse]] = {}
    for vid in vids:
        if not str(vid).isdigit():
            out[vid] = None
            continue
        try:
            rows = await qbo.query(f"SELECT * FROM Vendor WHERE Id = '{vid}'")
        except Exception as exc:  # noqa: BLE001
            raise Bloque(pf._erreur_qbo(exc).message, temporaire=True) from exc
        out[vid] = adresse_qbo(rows[0]) if rows else None
    return out


async def _scope(db: AsyncSession, entreprise_id: int) -> str:
    try:
        _, scope, _ = await pf._entreprise_qbo(db, entreprise_id)
    except pf.PaiementErreur as exc:
        raise Bloque(exc.message, temporaire=True) from exc
    return scope


async def _factures(scope: str) -> Dict[str, Dict[str, Any]]:
    try:
        return await pf._factures_ouvertes(scope)
    except pf.PaiementErreur as exc:
        raise Bloque(exc.message, temporaire=True) from exc


async def tester(db: AsyncSession, entreprise_id: int, user: User) -> Dict[str, Any]:
    """Vérifie les clés VoPay enregistrées (lecture du solde du compte)."""
    e = await pf._entreprise(db, entreprise_id)
    r = await pf._reglage(db, e.id)
    try:
        vp = client(r)
        reponse = await vp.solde()
    except Bloque as exc:
        raise pf.PaiementErreur(exc.message, 409) from exc
    except VoPayErreur as exc:
        if exc.temporaire:
            raise pf.PaiementErreur("VoPay ne répond pas pour l'instant : réessaie dans quelques minutes.", 502) from exc
        raise pf.PaiementErreur(f"VoPay refuse ces clés : {exc.message}", 422) from exc
    assert r is not None
    environnement = r.auto_environnement or "test"
    await pf._evenement(
        db, "vopay_teste", user=user, entreprise_id=e.id,
        detail="environnement de test" if environnement == "test" else "production",
    )
    await db.commit()
    return {"ok": True, "environnement": environnement, **vopay.soldes(reponse)}


async def verifier_connexion(
    account_id: str, cle: str, secret: str, environnement: str, sous_compte: Optional[str]
) -> None:
    """Clés saisies dans les réglages : VoPay doit les accepter avant que
    le paiement automatique ne s'en serve."""
    try:
        await connexion(account_id, cle, secret, environnement, sous_compte).solde()
    except VoPayErreur as exc:
        if exc.temporaire:
            raise pf.PaiementErreur(
                "VoPay ne répond pas pour l'instant : les clés n'ont pas pu être vérifiées. Réessaie dans quelques minutes.",
                502,
            ) from exc
        raise pf.PaiementErreur(f"VoPay refuse ces clés : {exc.message}", 422) from exc


# ──────────────────────────────────────────────────────────────────────
# Opérations
# ──────────────────────────────────────────────────────────────────────


def _du(moment: Optional[datetime], maintenant: datetime) -> bool:
    m = pf._utc(moment)
    return m is None or m <= maintenant


def _quoi(op: PaiementOperation) -> str:
    argent = pf._argent(op.montant_cents)
    if op.sorte == "prelevement":
        return f"Prélèvement de {argent} dans le compte de l'entreprise"
    if op.sorte == "retour":
        return f"Retour de {argent} au compte de l'entreprise ({op.fournisseur_nom or 'paiement retiré'})"
    rail = "virement Interac" if op.rail == "interac" else "dépôt direct"
    return f"Paiement de {argent} à {op.fournisseur_nom or 'un fournisseur'} ({rail})"


def _sorte_vopay(op: PaiementOperation) -> str:
    if op.sorte == "prelevement":
        return "prelevement"
    return "interac" if op.rail == "interac" else "depot"


def _attente_suivi(op: PaiementOperation, maintenant: datetime) -> timedelta:
    """Interac se règle en minutes (ou attend que le fournisseur accepte) ;
    un transfert électronique, en jours ouvrables."""
    age = maintenant - (pf._utc(op.envoye_le) or maintenant)
    if op.rail == "interac" and age < timedelta(hours=1):
        return timedelta(minutes=5)
    if age < timedelta(days=1):
        return timedelta(minutes=30)
    return timedelta(hours=2)


async def _operations(db: AsyncSession, lot_id: int) -> List[PaiementOperation]:
    return list(
        (
            await db.execute(
                select(PaiementOperation)
                .where(PaiementOperation.lot_id == lot_id)
                .order_by(PaiementOperation.id)
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
    )


def courantes(ops: Sequence[PaiementOperation], sorte: str) -> Dict[Optional[str], PaiementOperation]:
    """Dernière opération de chaque fournisseur (ou du lot, pour le
    prélèvement) : une reprise remplace la précédente."""
    out: Dict[Optional[str], PaiementOperation] = {}
    for op in sorted(ops, key=lambda o: o.id):
        if op.sorte == sorte:
            out[op.qbo_vendor_id] = op
    return out


async def _nouvelle_operation(
    db: AsyncSession,
    lot: LotPaiement,
    *,
    sorte: str,
    rail: str,
    montant_cents: int,
    vid: Optional[str] = None,
    nom: Optional[str] = None,
    compte_id: Optional[int] = None,
    user: Optional[User] = None,
) -> PaiementOperation:
    filtre = PaiementOperation.qbo_vendor_id == vid if vid else PaiementOperation.qbo_vendor_id.is_(None)
    n = (
        await db.execute(
            select(func.count(PaiementOperation.id)).where(
                PaiementOperation.lot_id == lot.id, PaiementOperation.sorte == sorte, filtre
            )
        )
    ).scalar_one() + 1
    if sorte == "prelevement":
        reference = f"KRATOS-L{lot.id}-P{n}"
    else:
        reference = f"KRATOS-L{lot.id}-{'F' if sorte == 'paiement' else 'R'}{vid}-{n}"
    op = PaiementOperation(
        lot_id=lot.id,
        entreprise_id=lot.entreprise_id,
        sorte=sorte,
        rail=rail,
        qbo_vendor_id=vid,
        fournisseur_nom=nom[:255] if nom else None,
        compte_bancaire_id=compte_id,
        montant_cents=int(montant_cents),
        environnement=lot.auto_environnement or "test",
        cle_idempotence=uuid.uuid4().hex,
        reference=reference[:64],
        statut="a_envoyer",
        tentatives=0,
        cree_par_user_id=user.id if user else None,
    )
    db.add(op)
    await db.flush()
    return op


async def _preparer_appel(db: AsyncSession, op: PaiementOperation) -> Callable[[], Awaitable[str]]:
    """Tout ce qu'il faut pour envoyer l'opération, vérifié AVANT l'envoi :
    une erreur ici n'a rien envoyé à VoPay."""
    lot = await db.get(LotPaiement, op.lot_id)
    e = await db.get(Entreprise, op.entreprise_id)
    r = await pf._reglage(db, op.entreprise_id)
    if lot is None or e is None or r is None:
        raise Bloque("Lot, entreprise ou réglages introuvables.")
    vp = _client_op(r, op)

    if op.sorte in ("prelevement", "retour"):
        adresse = adresse_entreprise(r)
        _compte_entreprise(r)
        assert r.retour_institution and r.retour_transit and r.retour_compte
        institution, transit, compte = r.retour_institution, r.retour_transit, r.retour_compte
        if op.sorte == "prelevement":
            note = f"Lot de paiements Kratos n° {lot.id} ({lot.nb_lignes} facture(s))"
            return lambda: vp.prelever(
                montant_cents=op.montant_cents, nom=e.name, adresse=adresse, institution=institution,
                transit=transit, compte=compte, reference=op.reference, note=note, cle=op.cle_idempotence,
            )
        note = f"Retour du paiement à {op.fournisseur_nom or 'un fournisseur'}, retiré du lot Kratos n° {lot.id}"
        return lambda: vp.deposer(
            montant_cents=op.montant_cents, nom=e.name, adresse=adresse, institution=institution,
            transit=transit, compte=compte, reference=op.reference, note=note, cle=op.cle_idempotence,
        )

    # Paiement d'un fournisseur : ses factures sont relues dans QuickBooks
    # à chaque envoi (pas de double paiement si quelqu'un l'a payé ailleurs).
    nom = op.fournisseur_nom or "ce fournisseur"
    lignes = [l for l in await pf._lignes(db, lot.id) if l.qbo_vendor_id == op.qbo_vendor_id]
    if not lignes:
        raise Bloque(f"{nom} n'est plus dans le lot.")
    if sum(int(l.montant_cents) for l in lignes) != int(op.montant_cents):
        raise Bloque(f"Le montant à payer à {nom} a changé depuis la création du paiement.")
    mode = "interac" if op.rail == "interac" else "depot_direct"
    c = await db.get(FournisseurCompteBancaire, op.compte_bancaire_id) if op.compte_bancaire_id else None
    if c is None or c.statut != "approuve" or c.mode != mode:
        raise Bloque(
            f"Les coordonnées de {nom} ont changé depuis l'approbation du lot : réessaie pour payer "
            "avec les coordonnées approuvées maintenant, ou retire ce paiement du lot."
        )
    scope = await _scope(db, op.entreprise_id)
    bills = await _factures(scope)
    for l in lignes:
        b = bills.get(l.qbo_bill_id)
        if b is None or pf.cents(b.get("Balance")) < int(l.montant_cents):
            raise Bloque(
                f"La facture {l.numero_facture or l.qbo_bill_id} de {nom} a déjà été payée en tout ou "
                "en partie dans QuickBooks : vérifie, puis retire ce paiement du lot (l'argent revient "
                "au compte de l'entreprise)."
            )
    numeros = [l.numero_facture for l in lignes]
    if op.rail == "interac":
        if op.montant_cents > pf.LIMITE_INTERAC_CENTS:
            raise Bloque(
                f"Un virement Interac est limité à {pf._argent(pf.LIMITE_INTERAC_CENTS)} : retire ce paiement du lot "
                "et paie ce fournisseur par dépôt direct."
            )
        if not r.interac_question:
            raise Bloque("La question Interac manque dans les réglages des paiements.")
        question = r.interac_question
        reponse = _dechiffrer(r.interac_reponse_chiffree, "Réponse Interac")
        destinataire = c.interac_destinataire or ""
        message = pf._message_interac(numeros)
        return lambda: vp.envoyer_interac(
            montant_cents=op.montant_cents, nom=c.fournisseur_nom, destinataire=destinataire,
            question=question, reponse=reponse, message=message, expediteur=e.name,
            reference=op.reference, cle=op.cle_idempotence,
        )
    adresse = (await _adresses_fournisseurs(scope, [op.qbo_vendor_id or ""])).get(op.qbo_vendor_id or "")
    if adresse is None:
        raise Bloque(
            f"L'adresse de {nom} est incomplète dans QuickBooks (rue, ville, province, code postal) : "
            "VoPay l'exige pour un dépôt direct. Complète la fiche du fournisseur, puis réessaie."
        )
    try:
        numero = decrypt_secret(c.compte_chiffre or "")
    except (VaultNotConfigured, ValueError) as exc:
        raise Bloque(
            "La clé de chiffrement de Kratos est absente ou a changé : les coordonnées bancaires sont illisibles."
        ) from exc
    institution, transit = c.institution or "", c.transit or ""
    note = f"Lot Kratos n° {lot.id} : " + (pf._information(numeros) or "paiement de factures")
    return lambda: vp.deposer(
        montant_cents=op.montant_cents, nom=c.fournisseur_nom, adresse=adresse, institution=institution,
        transit=transit, compte=numero, reference=op.reference, note=note, cle=op.cle_idempotence,
    )


async def _notifier_approbateurs(db: AsyncSession, titre: str, corps: str) -> None:
    await pf._notifier(db, await pf._approbateurs(db, []), titre, corps)


async def _echec(db: AsyncSession, op: PaiementOperation, message: str) -> None:
    maintenant = pf._maintenant()
    op.statut = "echoue"
    op.erreur = message[:2000]
    op.termine_le = maintenant
    op.prochain_essai = None
    await pf._evenement(
        db, "vopay_refuse", entreprise_id=op.entreprise_id, lot_id=op.lot_id, detail=f"{_quoi(op)} : {message}"[:2000]
    )
    if op.sorte != "prelevement":
        # Le refus d'un prélèvement est annoncé avec le lot (« echec »).
        quoi = "Paiement refusé" if op.sorte == "paiement" else "Retour à l'entreprise refusé"
        await _notifier_approbateurs(
            db, quoi, f"Lot n° {op.lot_id} : {_quoi(op)}. {message[:300]}"
        )


async def _a_verifier(db: AsyncSession, op: PaiementOperation, message: str) -> None:
    op.statut = "a_verifier"
    op.erreur = message[:2000]
    op.prochain_essai = None
    await pf._evenement(
        db, "vopay_a_verifier", entreprise_id=op.entreprise_id, lot_id=op.lot_id,
        detail=f"{_quoi(op)} : {message}"[:2000],
    )
    await _notifier_approbateurs(
        db,
        "Paiement à vérifier dans VoPay",
        f"Lot n° {op.lot_id} : {_quoi(op)}. Kratos ne sait pas si la demande est partie : cherche la "
        f"référence {op.reference} dans le portail VoPay, puis indique-le dans Kratos.",
    )


async def _incertain(db: AsyncSession, op: PaiementOperation, message: str) -> None:
    """Réponse perdue : une reprise avec la même clé (VoPay refuse un
    doublon), puis un approbateur."""
    maintenant = pf._maintenant()
    if op.incertain_le is not None:
        await _a_verifier(db, op, message)
        return
    op.incertain_le = maintenant
    op.statut = "incertain"
    op.erreur = message[:2000]
    op.prochain_essai = maintenant + REPRISE_INCERTAINE
    await pf._evenement(
        db, "vopay_incertain", entreprise_id=op.entreprise_id, lot_id=op.lot_id,
        detail=f"{_quoi(op)} : {message} Kratos reprend la demande avec la même clé."[:2000],
    )


async def _envoyer(db: AsyncSession, op_id: int, *, forcer: bool = False) -> None:
    """Envoie une opération à VoPay (ou la reprend avec la même clé)."""
    op = await db.get(PaiementOperation, op_id, populate_existing=True)
    if op is None or op.statut not in ("a_envoyer", "incertain"):
        return
    maintenant = pf._maintenant()
    if not forcer and not _du(op.prochain_essai, maintenant):
        return
    avant = op.statut
    try:
        appel = await _preparer_appel(db, op)
    except Bloque as exc:
        if avant == "incertain":
            # Peut-être partie la première fois : jamais classée refusée.
            await _a_verifier(db, op, f"{exc.message} La première demande est peut-être partie.")
        elif exc.temporaire:
            op.erreur = exc.message[:2000]
            op.prochain_essai = maintenant + REPRISE_BLOCAGE
        else:
            await _echec(db, op, exc.message)
        await db.commit()
        return

    # Réclamer l'opération : statut « envoi » validé en base AVANT l'appel.
    # Deux serveurs ne l'envoient pas deux fois ; un arrêt pendant l'envoi
    # la laisse en « envoi », reprise plus tard avec la même clé.
    res = await db.execute(
        update(PaiementOperation)
        .where(PaiementOperation.id == op.id, PaiementOperation.statut == avant)
        .values(
            statut="envoi",
            tentatives=PaiementOperation.tentatives + 1,
            prochain_essai=maintenant + ENVOI_SANS_REPONSE,
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    if res.rowcount != 1:
        return
    await db.refresh(op)

    try:
        transaction = await appel()
    except VoPayIncertain as exc:
        await _incertain(db, op, str(exc))
    except VoPayErreur as exc:
        if op.incertain_le is not None:
            # La première demande est peut-être partie (VoPay refuse alors
            # le doublon) : un approbateur vérifie.
            await _a_verifier(db, op, f"Reprise refusée par VoPay : {exc.message}")
        elif exc.temporaire or exc.solde:
            n = int(op.tentatives or 1)
            if n > len(ATTENTES):
                await _echec(db, op, f"Toujours refusé après {n} essais : {exc.message}")
            else:
                op.statut = "a_envoyer"
                op.erreur = (
                    f"Solde ou limite VoPay insuffisant pour l'instant : {exc.message}"
                    if exc.solde
                    else exc.message
                )[:2000]
                op.prochain_essai = pf._maintenant() + timedelta(minutes=ATTENTES[n - 1])
        else:
            await _echec(db, op, f"Refusé par VoPay : {exc.message}")
    else:
        fin = pf._maintenant()
        op.transaction_id = str(transaction)[:64]
        op.statut = "en_cours"
        op.envoye_le = fin
        op.erreur = None
        op.prochain_essai = fin + _attente_suivi(op, fin)
        await pf._evenement(
            db, "vopay_envoye", entreprise_id=op.entreprise_id, lot_id=op.lot_id,
            detail=f"{_quoi(op)} : transaction VoPay {op.transaction_id}"
            + (" (environnement de test)" if op.environnement == "test" else ""),
        )
    await db.commit()


async def _envoi_sans_reponse(db: AsyncSession, op_id: int) -> None:
    """Opération restée « envoi » (serveur arrêté pendant l'envoi)."""
    op = await db.get(PaiementOperation, op_id, populate_existing=True)
    if op is None or op.statut != "envoi" or not _du(op.prochain_essai, pf._maintenant()):
        return
    res = await db.execute(
        update(PaiementOperation)
        .where(PaiementOperation.id == op.id, PaiementOperation.statut == "envoi")
        .values(statut="incertain")
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        await db.rollback()
        return
    await db.refresh(op)
    await _incertain(db, op, "La demande est partie vers VoPay sans réponse (serveur redémarré).")
    await db.commit()


async def _suivre(db: AsyncSession, op_id: int, *, forcer: bool = False) -> None:
    """Demande à VoPay où en est une opération acceptée."""
    op = await db.get(PaiementOperation, op_id, populate_existing=True)
    if op is None or op.statut != "en_cours" or not op.transaction_id:
        return
    maintenant = pf._maintenant()
    if not forcer and not _du(op.prochain_essai, maintenant):
        return
    r = await pf._reglage(db, op.entreprise_id)
    try:
        st = await _client_op(r, op).statut(_sorte_vopay(op), op.transaction_id)
    except Bloque as exc:
        op.erreur = exc.message[:2000]
        op.prochain_essai = maintenant + timedelta(hours=1)
        await db.commit()
        return
    except VoPayErreur as exc:
        op.erreur = f"Suivi impossible pour l'instant : {exc.message}"[:2000]
        op.prochain_essai = maintenant + (timedelta(minutes=15) if exc.temporaire else timedelta(hours=1))
        await db.commit()
        return
    op.statut_vopay = st.brut[:40]
    op.verifie_le = maintenant
    if st.etat == "reussi":
        op.statut = "reussi"
        op.termine_le = maintenant
        op.erreur = None
        op.prochain_essai = None
        await pf._evenement(
            db, "vopay_reussi", entreprise_id=op.entreprise_id, lot_id=op.lot_id,
            detail=f"{_quoi(op)} : transaction VoPay {op.transaction_id}",
        )
    elif st.etat == "echoue":
        await _echec(db, op, f"{st.raison or 'Refusé'} (statut VoPay : {st.brut})")
    else:
        op.erreur = None
        op.prochain_essai = maintenant + _attente_suivi(op, maintenant)
    await db.commit()


# ──────────────────────────────────────────────────────────────────────
# Lots
# ──────────────────────────────────────────────────────────────────────


async def _lot_verrouille(db: AsyncSession, lot_id: int) -> Optional[LotPaiement]:
    return (
        await db.execute(
            select(LotPaiement)
            .where(LotPaiement.id == lot_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _lot_bloque(db: AsyncSession, lot: LotPaiement, message: str) -> None:
    nouveau = message != lot.auto_erreur
    lot.auto_erreur = message[:2000]
    lot.auto_tentatives = int(lot.auto_tentatives or 0) + 1
    lot.auto_prochain_essai = pf._maintenant() + REPRISE_LOT
    if nouveau:
        await pf._evenement(db, "auto_bloque", entreprise_id=lot.entreprise_id, lot_id=lot.id, detail=message[:2000])
        await _notifier_approbateurs(db, "Paiement automatique en attente", f"Lot n° {lot.id} : {message[:400]}")


async def _verifier_avant_prelevement(db: AsyncSession, lot: LotPaiement, r: Optional[PaiementReglage]) -> None:
    """Avant de prélever l'entreprise : chaque fournisseur du lot pourra
    être payé (rien n'est prélevé pour rester bloqué chez VoPay)."""
    if not pf.auto_actif(r):
        raise Bloque(
            "Le paiement automatique est désactivé dans les réglages de l'entreprise : réactive-le, "
            "ou remets le lot en brouillon pour le payer autrement."
        )
    assert r is not None
    manque = pf.manque_auto(r, interac=lot.mode == "interac")
    if manque:
        raise Bloque("Réglages du paiement automatique incomplets : " + ", ".join(manque) + ".")
    lignes = await pf._lignes(db, lot.id)
    if not lignes:
        raise Bloque("Le lot est vide.")
    scope = await _scope(db, lot.entreprise_id)
    bills = await _factures(scope)
    try:
        pf._verifier_lignes_contre_qbo(
            [(l.qbo_bill_id, int(l.montant_cents)) for l in lignes],
            bills,
            await pf._factures_dans_lots(db, lot.entreprise_id, lot.id),
        )
    except pf.PaiementErreur as exc:
        raise Bloque(f"{exc.message} Remets le lot en brouillon pour le corriger.") from exc
    groupes = pf._par_fournisseur(lignes)
    for groupe in groupes.values():
        compte_id = groupe[0].compte_bancaire_id
        c = await db.get(FournisseurCompteBancaire, compte_id) if compte_id else None
        if c is None or c.statut != "approuve" or c.mode != lot.mode:
            raise Bloque(
                f"Les coordonnées de {groupe[0].fournisseur_nom} ont changé depuis la soumission : "
                "remets le lot en brouillon et soumets-le de nouveau."
            )
    if lot.mode == "interac":
        try:
            pf._verifier_limite_interac(lignes)
        except pf.PaiementErreur as exc:
            raise Bloque(f"{exc.message} Remets le lot en brouillon pour le corriger.") from exc
        return
    adresses = await _adresses_fournisseurs(scope, list(groupes))
    sans = sorted(groupes[vid][0].fournisseur_nom for vid, a in adresses.items() if a is None)
    if sans:
        raise Bloque(
            "Adresse incomplète dans QuickBooks (rue, ville, province, code postal) pour : "
            + ", ".join(sans)
            + ". VoPay l'exige pour un dépôt direct : complète la fiche du fournisseur dans QuickBooks ; "
            "Kratos réessaiera."
        )


async def _demarrer(db: AsyncSession, lot: LotPaiement, *, forcer: bool) -> List[int]:
    """Le jour du lot venu : prélèvement du total dans le compte de
    l'entreprise."""
    if lot.date_paiement > pf._aujourdhui():
        return []
    if not forcer and not _du(lot.auto_prochain_essai, pf._maintenant()):
        return []
    r = await pf._reglage(db, lot.entreprise_id)
    try:
        await _verifier_avant_prelevement(db, lot, r)
    except Bloque as exc:
        await _lot_bloque(db, lot, exc.message)
        return []
    assert r is not None
    lot.auto_environnement = r.auto_environnement or "test"
    op = await _nouvelle_operation(db, lot, sorte="prelevement", rail="eft", montant_cents=lot.total_cents)
    lot.statut = "prelevement"
    lot.auto_erreur = None
    lot.auto_prochain_essai = None
    lot.auto_tentatives = None
    return [op.id]


async def _inscrire(db: AsyncSession, lot: LotPaiement) -> None:
    """Paiements inscrits dans QuickBooks ; repris plus tard au besoin."""
    try:
        restantes = await pf.inscrire_qbo(db, lot, None)
    except pf.PaiementErreur as exc:
        lot.auto_erreur = f"Inscription dans QuickBooks : {exc.message}"[:2000]
        lot.auto_prochain_essai = pf._maintenant() + REPRISE_LOT
        return
    if restantes:
        lot.auto_erreur = (
            f"Inscription dans QuickBooks incomplète ({len(restantes)} facture(s)) : Kratos réessaie."
        )
        lot.auto_prochain_essai = pf._maintenant() + REPRISE_LOT
    else:
        lot.auto_erreur = None
        lot.auto_prochain_essai = None


async def _paiements_termines(db: AsyncSession, lot: LotPaiement, user: Optional[User] = None) -> None:
    maintenant = pf._maintenant()
    lot.statut = "transmis"
    lot.transmis_le = maintenant
    lot.transmis_par_user_id = user.id if user else None
    await pf._evenement(
        db, "paiements_termines", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
        detail=f"{pf._argent(lot.total_cents)} versés aux fournisseurs",
    )
    test = lot.auto_environnement == "test"
    await pf._notifier(
        db,
        [lot.cree_par_user_id, lot.soumis_par_user_id],
        "Fournisseurs payés" + (" (test)" if test else ""),
        f"Lot n° {lot.id} : {pf._argent(lot.total_cents)}."
        + (" Environnement de test VoPay : aucun argent réel." if test else ""),
    )
    if test:
        # Aucun argent réel n'a bougé : rien dans QuickBooks, les factures
        # restent à payer.
        lot.statut = "paye"
        lot.paye_le = maintenant
        await pf._evenement(
            db, "test_termine", entreprise_id=lot.entreprise_id, lot_id=lot.id,
            detail="Environnement de test VoPay : rien n'est inscrit dans QuickBooks.",
        )
        return
    await _inscrire(db, lot)


async def _avancer(db: AsyncSession, lot_id: int, *, forcer: bool) -> List[int]:
    """Une étape du lot ; rend les opérations à envoyer maintenant."""
    lot = await _lot_verrouille(db, lot_id)
    if lot is None or not lot.envoi_auto or lot.statut not in LOTS_EN_COURS:
        await db.rollback()
        return []
    maintenant = pf._maintenant()
    if lot.statut == "approuve":
        ids = await _demarrer(db, lot, forcer=forcer)
        await db.commit()
        return ids

    ops = await _operations(db, lot.id)
    a_envoyer: List[int] = []
    if lot.statut == "prelevement":
        p = courantes(ops, "prelevement").get(None)
        if p is None or p.statut in ("echoue", "annule"):
            lot.statut = "echec"
            lot.auto_erreur = (p.erreur if p else None) or "Prélèvement refusé."
            e = await db.get(Entreprise, lot.entreprise_id)
            await pf._notifier(
                db,
                [*await pf._approbateurs(db, []), lot.cree_par_user_id, lot.soumis_par_user_id],
                "Prélèvement refusé",
                f"{e.name if e else 'Lot'} : lot n° {lot.id}, {pf._argent(lot.total_cents)}. "
                f"{lot.auto_erreur[:300]} Aucun fournisseur n'a été payé.",
            )
            await db.commit()
            return []
        if p.statut != "reussi":
            if p.statut in ("a_envoyer", "incertain") and (forcer or _du(p.prochain_essai, maintenant)):
                a_envoyer.append(p.id)
            await db.commit()
            return a_envoyer
        lot.statut = "envoi"
        lot.preleve_le = p.termine_le or maintenant
        lot.auto_erreur = None

    if lot.statut == "envoi":
        groupes = pf._par_fournisseur(await pf._lignes(db, lot.id))
        paiements = courantes(ops, "paiement")
        for vid, groupe in groupes.items():
            if vid in paiements:
                continue
            paiements[vid] = await _nouvelle_operation(
                db, lot, sorte="paiement", rail="interac" if lot.mode == "interac" else "eft",
                montant_cents=sum(int(l.montant_cents) for l in groupe), vid=vid,
                nom=groupe[0].fournisseur_nom, compte_id=groupe[0].compte_bancaire_id,
            )
        if groupes and all(paiements[vid].statut == "reussi" for vid in groupes):
            await _paiements_termines(db, lot)
        else:
            a_envoyer = [
                paiements[vid].id
                for vid in groupes
                if paiements[vid].statut in ("a_envoyer", "incertain")
                and (forcer or _du(paiements[vid].prochain_essai, maintenant))
            ]
        await db.commit()
        return a_envoyer

    if lot.statut == "transmis" and lot.auto_environnement != "test":
        if forcer or _du(lot.auto_prochain_essai, maintenant):
            await _inscrire(db, lot)
    await db.commit()
    return []


async def traiter_lot(
    db: AsyncSession, lot_id: int, *, forcer: bool = False, deja: Iterable[int] = ()
) -> None:
    """Fait avancer un lot payé automatiquement aussi loin que possible
    maintenant. Ne lève jamais d'erreur : ce qui bloque est inscrit sur le
    lot ou sur l'opération.

    « forcer » (approbation, geste d'un approbateur) passe outre les délais
    d'attente au premier tour seulement. Une opération n'est jamais envoyée
    deux fois dans le même appel (ni celles de « deja », déjà essayées par
    l'appelant) : après un refus temporaire ou une réponse perdue, la
    reprise attend son délai."""
    essayees = set(deja)
    for tour in range(4):
        force = forcer and tour == 0
        try:
            a_envoyer = [i for i in await _avancer(db, lot_id, forcer=force) if i not in essayees]
        except Exception:  # noqa: BLE001
            await db.rollback()
            log.exception("Paiement automatique : le lot %s n'a pas pu avancer", lot_id)
            return
        if not a_envoyer:
            return
        for op_id in a_envoyer:
            essayees.add(op_id)
            try:
                await _envoyer(db, op_id, forcer=force)
            except Exception:  # noqa: BLE001
                await db.rollback()
                log.exception("Paiement automatique : envoi de l'opération %s impossible", op_id)


async def demarrer(db: AsyncSession, lot_id: int) -> None:
    """Après la dernière approbation : le prélèvement part tout de suite si
    la date du lot est arrivée."""
    await traiter_lot(db, lot_id, forcer=True)


# ──────────────────────────────────────────────────────────────────────
# Gestes des approbateurs
# ──────────────────────────────────────────────────────────────────────


async def _lot_auto(db: AsyncSession, lot_id: int) -> LotPaiement:
    lot = await pf._lot(db, lot_id, verrou=True)
    if not lot.envoi_auto:
        raise pf.PaiementErreur("Ce lot n'est pas payé automatiquement.", 409)
    return lot


async def _operation_du_lot(db: AsyncSession, lot: LotPaiement, operation_id: int) -> PaiementOperation:
    op = await db.get(PaiementOperation, operation_id, populate_existing=True)
    if op is None or op.lot_id != lot.id:
        raise pf.PaiementErreur("Opération introuvable.", 404)
    return op


async def reessayer(
    db: AsyncSession, lot_id: int, user: User, code_2fa: Optional[str], operation_id: Optional[int] = None
) -> Dict[str, Any]:
    """Approbateur + double authentification. Sans opération : relance un
    lot dont le prélèvement a été refusé, ou qui attend (réglages,
    QuickBooks). Avec une opération refusée : nouveau paiement du
    fournisseur (coordonnées approuvées du moment, soldes relus dans
    QuickBooks) ou nouveau retour à l'entreprise."""
    lot = await _lot_auto(db, lot_id)
    if operation_id is None:
        if lot.statut not in ("echec", "approuve"):
            raise pf.PaiementErreur("Rien à réessayer pour ce lot.", 409)
        await pf.exiger_2fa(db, user, code_2fa)
        lot.statut = "approuve"
        lot.auto_erreur = None
        lot.auto_prochain_essai = None
        await pf._evenement(db, "auto_reessaye", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id)
        await db.commit()
        await traiter_lot(db, lot.id, forcer=True)
        return await pf.detail_lot(db, lot.id, user)

    op = await _operation_du_lot(db, lot, operation_id)
    if op.statut != "echoue":
        raise pf.PaiementErreur("Seule une opération refusée se réessaie.", 409)
    if op.sorte == "prelevement":
        raise pf.PaiementErreur("Pour un prélèvement refusé, réessaie le lot.", 409)
    derniere = courantes(await _operations(db, lot.id), op.sorte).get(op.qbo_vendor_id)
    if derniere is None or derniere.id != op.id:
        raise pf.PaiementErreur("Cette opération a déjà été reprise.", 409)
    if op.sorte == "paiement":
        if lot.statut != "envoi":
            raise pf.PaiementErreur("Les paiements de ce lot ne sont plus en cours.", 409)
        groupe = pf._par_fournisseur(await pf._lignes(db, lot.id)).get(op.qbo_vendor_id or "")
        if not groupe:
            raise pf.PaiementErreur("Ce fournisseur n'est plus dans le lot.", 409)
        c = (await pf._comptes_par_fournisseur(db, lot.entreprise_id, ("approuve",), lot.mode)).get(
            op.qbo_vendor_id or ""
        )
        if c is None:
            raise pf.PaiementErreur(
                f"{op.fournisseur_nom} n'a plus de coordonnées approuvées : saisis-les et fais-les "
                "approuver, puis réessaie.",
                409,
            )
        await pf.exiger_2fa(db, user, code_2fa)
        detail = _quoi(op)
        if c.id != op.compte_bancaire_id:
            for l in groupe:
                l.compte_bancaire_id = c.id
            detail += f", vers les coordonnées approuvées maintenant ({pf._libelle_compte(c)})"
        nouvelle = await _nouvelle_operation(
            db, lot, sorte="paiement", rail=op.rail, montant_cents=sum(int(l.montant_cents) for l in groupe),
            vid=op.qbo_vendor_id, nom=op.fournisseur_nom, compte_id=c.id, user=user,
        )
    else:
        await pf.exiger_2fa(db, user, code_2fa)
        detail = _quoi(op)
        nouvelle = await _nouvelle_operation(
            db, lot, sorte="retour", rail="eft", montant_cents=op.montant_cents,
            vid=op.qbo_vendor_id, nom=op.fournisseur_nom, user=user,
        )
    await pf._evenement(
        db, "vopay_reessaye", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id, detail=detail[:2000]
    )
    await db.commit()
    await _envoyer(db, nouvelle.id, forcer=True)
    await traiter_lot(db, lot.id, deja=[nouvelle.id])
    return await pf.detail_lot(db, lot.id, user)


_TRANSACTION = re.compile(r"[A-Za-z0-9-]{1,64}")


async def resoudre(
    db: AsyncSession,
    lot_id: int,
    operation_id: int,
    user: User,
    code_2fa: Optional[str],
    parti: bool,
    transaction_id: Optional[str],
) -> Dict[str, Any]:
    """Opération « à vérifier » : l'approbateur a cherché sa référence dans
    le portail VoPay. Partie : Kratos la suit avec le numéro de
    transaction. Pas partie : elle est classée refusée (réessayer en crée
    une nouvelle)."""
    lot = await _lot_auto(db, lot_id)
    op = await _operation_du_lot(db, lot, operation_id)
    if op.statut != "a_verifier":
        raise pf.PaiementErreur("Cette opération n'attend pas de vérification.", 409)
    tid = re.sub(r"\s", "", transaction_id or "")
    if parti and not _TRANSACTION.fullmatch(tid):
        raise pf.PaiementErreur("Indique le numéro de transaction affiché dans le portail VoPay.")
    await pf.exiger_2fa(db, user, code_2fa)
    maintenant = pf._maintenant()
    if parti:
        op.transaction_id = tid
        op.statut = "en_cours"
        op.envoye_le = op.envoye_le or maintenant
        op.erreur = None
        op.prochain_essai = None
        detail = f"{_quoi(op)} : partie, transaction VoPay {tid}"
    else:
        op.statut = "echoue"
        op.termine_le = maintenant
        op.prochain_essai = None
        op.erreur = f"Pas partie, selon {user.display_name} (portail VoPay vérifié)."
        detail = f"{_quoi(op)} : pas partie"
    await pf._evenement(db, "vopay_verifie", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id, detail=detail)
    await db.commit()
    if parti:
        await _suivre(db, op.id, forcer=True)
    await traiter_lot(db, lot.id)
    return await pf.detail_lot(db, lot.id, user)


async def retirer_paiement(
    db: AsyncSession, lot_id: int, user: User, fournisseur_id: str, motif: str, code_2fa: Optional[str]
) -> Dict[str, Any]:
    """Retire du lot un fournisseur dont le paiement est refusé (ou pas
    encore parti) : ses factures redeviennent à payer et son montant revient
    au compte de l'entreprise (opération « retour »)."""
    lot = await _lot_auto(db, lot_id)
    if lot.statut != "envoi":
        raise pf.PaiementErreur("Seul un paiement d'un lot en cours de paiement peut être retiré.", 409)
    motif = (motif or "").strip()
    if not motif:
        raise pf.PaiementErreur("Indique pourquoi tu retires ce paiement.")
    lignes = await pf._lignes(db, lot.id)
    groupe = pf._par_fournisseur(lignes).get(fournisseur_id)
    if not groupe:
        raise pf.PaiementErreur("Ce fournisseur n'est pas dans le lot.", 404)
    courante = courantes(await _operations(db, lot.id), "paiement").get(fournisseur_id)
    if courante is not None and courante.statut == "reussi":
        raise pf.PaiementErreur(f"{groupe[0].fournisseur_nom} est déjà payé.", 409)
    if courante is not None and courante.statut not in ("echoue", "a_envoyer"):
        raise pf.PaiementErreur(
            "Ce paiement est parti ou en route chez VoPay : il ne peut plus être retiré.", 409
        )
    await pf.exiger_2fa(db, user, code_2fa)
    if courante is not None and courante.statut == "a_envoyer":
        res = await db.execute(
            update(PaiementOperation)
            .where(PaiementOperation.id == courante.id, PaiementOperation.statut == "a_envoyer")
            .values(statut="annule", erreur=f"Retiré du lot : {motif[:500]}", prochain_essai=None, termine_le=pf._maintenant())
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            raise pf.PaiementErreur("Ce paiement vient de partir chez VoPay : il ne peut plus être retiré.", 409)
    nom = groupe[0].fournisseur_nom
    total = sum(int(l.montant_cents) for l in groupe)
    ids = {l.id for l in groupe}
    restantes = [l for l in lignes if l.id not in ids]
    for l in groupe:
        await db.delete(l)
    pf._totaux(lot, restantes)
    retour = await _nouvelle_operation(
        db, lot, sorte="retour", rail="eft", montant_cents=total, vid=fournisseur_id, nom=nom, user=user
    )
    await pf._evenement(
        db, "paiement_retire", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
        detail=f"{nom} : {pf._argent(total)} retirés du lot et retournés au compte de l'entreprise, "
        f"motif : {motif[:500]}",
    )
    await pf._notifier(
        db,
        [*await pf._approbateurs(db, [user.id]), lot.cree_par_user_id, lot.soumis_par_user_id],
        "Paiement retiré d'un lot",
        f"Lot n° {lot.id} : {nom}, {pf._argent(total)}, retiré par {user.display_name}. "
        "Ses factures redeviennent à payer ; le montant revient au compte de l'entreprise.",
    )
    if not restantes:
        lot.statut = "annule"
        lot.annule_par_user_id = user.id
        lot.annule_le = pf._maintenant()
        lot.motif_annulation = motif[:2000]
        await pf._evenement(
            db, "lot_annule", user=user, entreprise_id=lot.entreprise_id, lot_id=lot.id,
            detail="dernier paiement retiré",
        )
    else:
        paiements = courantes(await _operations(db, lot.id), "paiement")
        if all(
            (paiements.get(vid) is not None and paiements[vid].statut == "reussi")
            for vid in pf._par_fournisseur(restantes)
        ):
            await _paiements_termines(db, lot, user)
    await db.commit()
    await _envoyer(db, retour.id, forcer=True)
    return await pf.detail_lot(db, lot.id, user)


async def verifier(db: AsyncSession, lot_id: int, user: User) -> Dict[str, Any]:
    """Suivi immédiat d'un lot (sans attendre le prochain passage)."""
    lot = await pf._lot(db, lot_id)
    if not lot.envoi_auto:
        raise pf.PaiementErreur("Ce lot n'est pas payé automatiquement.", 409)
    essayees: List[int] = []
    for op in await _operations(db, lot.id):
        try:
            if op.statut == "en_cours":
                await _suivre(db, op.id, forcer=True)
            elif op.statut in ("a_envoyer", "incertain"):
                essayees.append(op.id)
                await _envoyer(db, op.id, forcer=True)
            elif op.statut == "envoi":
                await _envoi_sans_reponse(db, op.id)
        except Exception:  # noqa: BLE001
            await db.rollback()
            log.exception("Paiement automatique : suivi de l'opération %s impossible", op.id)
    await traiter_lot(db, lot.id, forcer=True, deja=essayees)
    return await pf.detail_lot(db, lot.id, user)


async def annuler_operations_test(db: AsyncSession, lot: LotPaiement) -> None:
    """Lot de test abandonné : ses opérations ouvertes sont annulées (aucun
    argent réel)."""
    for op in await _operations(db, lot.id):
        if op.statut in OPS_OUVERTES:
            op.statut = "annule"
            op.prochain_essai = None
            op.termine_le = pf._maintenant()


# ──────────────────────────────────────────────────────────────────────
# Lecture (détail d'un lot)
# ──────────────────────────────────────────────────────────────────────


def operation_dict(op: PaiementOperation, *, courante: bool, peut: Dict[str, bool]) -> Dict[str, Any]:
    return {
        "id": op.id,
        "sorte": op.sorte,
        "sorte_libelle": SORTES.get(op.sorte, op.sorte),
        "rail": op.rail,
        "fournisseur_id": op.qbo_vendor_id,
        "fournisseur": op.fournisseur_nom,
        "montant": pf.dollars(op.montant_cents),
        "statut": op.statut,
        "statut_libelle": LIBELLES_OPERATION.get(op.statut, op.statut),
        "statut_vopay": op.statut_vopay,
        "transaction_id": op.transaction_id,
        "reference": op.reference,
        "environnement": op.environnement,
        "erreur": op.erreur,
        "tentatives": op.tentatives,
        "cree_le": pf._iso(op.created_at),
        "envoye_le": pf._iso(op.envoye_le),
        "termine_le": pf._iso(op.termine_le),
        "prochain_essai": pf._iso(op.prochain_essai) if op.statut in ("a_envoyer", "incertain", "en_cours") else None,
        "courante": courante,
        "peut_reessayer": bool(peut.get("reessayer")),
        "peut_resoudre": bool(peut.get("resoudre")),
    }


async def detail(
    db: AsyncSession, lot: LotPaiement, lignes: Sequence[LotPaiementLigne], approbateur: bool
) -> Dict[str, Any]:
    """Prélèvement, paiement de chaque fournisseur et historique des
    opérations VoPay d'un lot."""
    ops = await _operations(db, lot.id)
    prelevements = courantes(ops, "prelevement")
    paiements = courantes(ops, "paiement")
    retours = courantes(ops, "retour")
    courants = {o.id for o in (*prelevements.values(), *paiements.values(), *retours.values())}

    def peut(op: PaiementOperation) -> Dict[str, bool]:
        courant = op.id in courants
        reessayer_op = (
            approbateur
            and courant
            and op.statut == "echoue"
            and (op.sorte == "retour" or (op.sorte == "paiement" and lot.statut == "envoi"))
        )
        return {"reessayer": reessayer_op, "resoudre": approbateur and op.statut == "a_verifier"}

    sorties = [operation_dict(o, courante=o.id in courants, peut=peut(o)) for o in reversed(ops)]
    par_id = {o["id"]: o for o in sorties}
    p = prelevements.get(None)
    fournisseurs: List[Dict[str, Any]] = []
    for vid, groupe in pf._par_fournisseur(lignes).items():
        op = paiements.get(vid)
        retirable = (
            approbateur
            and lot.statut == "envoi"
            and (op is None or op.statut in ("echoue", "a_envoyer"))
        )
        fournisseurs.append(
            {
                "fournisseur_id": vid,
                "fournisseur": groupe[0].fournisseur_nom,
                "montant": pf.dollars(sum(int(l.montant_cents) for l in groupe)),
                "nb_factures": len(groupe),
                "operation": par_id.get(op.id) if op else None,
                "peut_retirer": retirable,
            }
        )
    return {
        "prelevement": par_id.get(p.id) if p else None,
        "paiements_auto": fournisseurs,
        "retours": [par_id[o.id] for o in retours.values()],
        "operations": sorties,
        "a_verifier": sum(1 for o in ops if o.statut == "a_verifier"),
    }


# ──────────────────────────────────────────────────────────────────────
# Boucle de fond
# ──────────────────────────────────────────────────────────────────────


async def passer() -> Dict[str, int]:
    """Un passage : envois et reprises dus, suivi des opérations, puis
    avancement des lots (prélèvement le jour venu, paiements, QuickBooks)."""
    from app.db.session import AsyncSessionLocal

    maintenant = pf._maintenant()
    async with AsyncSessionLocal() as db:
        ops = (
            await db.execute(
                select(PaiementOperation.id, PaiementOperation.lot_id, PaiementOperation.statut, PaiementOperation.prochain_essai)
                .where(PaiementOperation.statut.in_(("a_envoyer", "envoi", "incertain", "en_cours")))
                .order_by(PaiementOperation.id)
            )
        ).all()
        lots = set(
            (
                await db.execute(
                    select(LotPaiement.id).where(
                        LotPaiement.envoi_auto.is_(True), LotPaiement.statut.in_(LOTS_EN_COURS)
                    )
                )
            ).scalars().all()
        )
    stats = {"operations": 0, "lots": 0, "erreurs": 0}
    essayees: Dict[int, List[int]] = {}
    for op_id, lot_id, statut, prochain in ops:
        if statut != "envoi" and not _du(prochain, maintenant):
            continue
        async with AsyncSessionLocal() as db:
            try:
                if statut == "en_cours":
                    await _suivre(db, op_id)
                elif statut == "envoi":
                    await _envoi_sans_reponse(db, op_id)
                else:
                    essayees.setdefault(lot_id, []).append(op_id)
                    await _envoyer(db, op_id)
                stats["operations"] += 1
                lots.add(lot_id)
            except Exception:  # noqa: BLE001
                stats["erreurs"] += 1
                await db.rollback()
                log.exception("Paiement automatique : opération %s", op_id)
    for lot_id in sorted(lots):
        async with AsyncSessionLocal() as db:
            await traiter_lot(db, lot_id, deja=essayees.get(lot_id, ()))
            stats["lots"] += 1
    if stats["operations"] or stats["erreurs"]:
        log.info("Paiements automatiques : %s", stats)
    return stats


async def boucle() -> None:
    """Démarrée avec l'application : premier passage 2 minutes après le
    démarrage, puis toutes les 5 minutes."""
    attente = PREMIER_PASSAGE_S
    while True:
        try:
            await asyncio.sleep(attente)
            attente = INTERVALLE_S
            await passer()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.warning("Paiements automatiques : passage échoué", exc_info=True)
