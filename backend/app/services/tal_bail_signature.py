"""Signature du bail officiel du TAL, pilotée de bout en bout depuis Gestion immobilière.

Phil 2026-11-11 : « J'aimerais que tout se contrôle uniquement à partir de gestion
immobilière, donc on ne va pas du tout dans gestion d'entreprise… que ça l'envoie
automatiquement aussitôt que je clique sur envoyer, donc ça vient mettre au bon endroit
toutes les initiales, toutes les signatures demandées… Puis de là je peux faire le
suivi : ceux qui ont été envoyés, je peux les renvoyer, changer le courriel, les
annuler… comme indépendant de la section signature déjà créée. »

Ce module ne réécrit pas l'outil de signature : il s'en sert. Il décide QUI signe
(``tal_bail.personnes_a_signer``), OÙ (``integrations.tal.gabarit_signature``), crée le
document avec ses zones et le fait partir en un geste ; le suivi, le renvoi, la
correction d'un courriel et l'annulation passent par les mêmes fonctions que la section
Signature, mais derrière les routes de Gestion immobilière.

Garde-fous :
- jamais de zone posée à l'aveugle : le PDF est comparé à l'empreinte du formulaire
  officiel, sinon l'envoi automatique se refuse ;
- personne n'est invité sans courriel explicite : une personne sans courriel ne reçoit
  rien et garde ses cases libres ;
- les liens de signature sont enregistrés AVANT le départ des courriels : un lien parti
  n'est jamais un lien mort ;
- le formulaire transmis au TAL n'est jamais modifié : un courriel corrigé à l'envoi ne
  vit que sur le document de signature.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.tal import gabarit_signature as gab
from app.services import tal_bail_annexes as annexes_bail
from app.models.immobilier import ImmDocument
from app.models.tal_bail import TalTransmission
from app.services import tal_bail as svc
from app.services.audit import log_action

log = logging.getLogger(__name__)

MESSAGE_DEFAUT = (
    "Voici votre bail de logement (formulaire officiel du Tribunal administratif du logement) "
    "à signer électroniquement."
)
#: Verdict du gabarit par empreinte SHA-256 du PDF (un PDF archivé ne change jamais).
_VERDICTS: dict[str, gab.Verdict] = {}

_NOMS_PARTIES = {"locateur": "locateurs", "locataire": "locataires", "autre": "autres signataires"}


def _phrase_documents_joints(description: list[dict[str, Any]]) -> str:
    """Suite du message d'invitation quand des documents partent avec le bail."""
    titres = [str(a.get("titre") or "").strip() for a in description or [] if str(a.get("titre") or "").strip()]
    if not titres:
        return ""
    return " À la suite du bail, dans le même document : " + " ; ".join(titres) + "."


def _iso(v: Any) -> Optional[str]:
    return v.isoformat() if isinstance(v, datetime) else None


def _detail(exc: HTTPException) -> str:
    d = exc.detail
    return d if isinstance(d, str) else str(d)


# ─── Qui signe, et le PDF est-il au gabarit ? ─────────────────────────


async def _pdf_officiel(db: AsyncSession, t: TalTransmission) -> Optional[bytes]:
    if not t.document_id:
        return None
    blob = (await db.execute(select(ImmDocument.pdf_blob).where(ImmDocument.id == t.document_id))).scalar_one_or_none()
    return bytes(blob) if blob else None


async def _verdict(pdf: Optional[bytes]) -> gab.Verdict:
    if not pdf:
        return gab.Verdict(False, "le PDF du bail officiel est introuvable au dossier")
    cle = hashlib.sha256(pdf).hexdigest()
    verdict = _VERDICTS.get(cle)
    if verdict is None:
        verdict = await asyncio.to_thread(gab.verifier_gabarit, pdf)
        if len(_VERDICTS) > 200:
            _VERDICTS.clear()
        _VERDICTS[cle] = verdict
    return verdict


def personnes(t: TalTransmission, *, user) -> list[dict[str, Any]]:
    """Les personnes qui doivent signer CE bail (avec ou sans courriel)."""
    form = svc._charger_json(t.payload_json, {}) or {}
    if getattr(t, "independant", False):
        return svc.personnes_a_signer(form, independant=True)
    return svc.personnes_a_signer(
        form, independant=False,
        representant_nom=(getattr(user, "display_name", None) or "").strip(),
        representant_courriel=(getattr(user, "email", None) or "").strip(),
    )


def _motif_limites(liste: list[dict[str, Any]]) -> Optional[str]:
    if not liste:
        return "aucune personne n'est nommée au bail"
    for partie, nom in _NOMS_PARTIES.items():
        n = sum(1 for pers in liste if pers["partie"] == partie)
        if n > gab.MAX_PAR_PARTIE:
            return f"le bail officiel n'a que {gab.MAX_PAR_PARTIE} lignes de signature par partie, et ce bail compte {n} {nom}"
    return None


async def _motif_refus(db: AsyncSession, t: TalTransmission, liste: list[dict[str, Any]], pdf: Optional[bytes]) -> Optional[str]:
    """Pourquoi la signature en ligne automatique n'est pas offerte pour ce bail (None = offerte)."""
    if t.statut != "transmise" or not t.document_id:
        return "le bail officiel n'a pas encore été généré"
    if getattr(t, "remplacee_par_id", None):
        return "ce bail a été remplacé par une version corrigée"
    if (t.langue or "fr") != "fr":
        return "le placement automatique des signatures est validé pour le bail en français seulement"
    motif = _motif_limites(liste)
    if motif:
        return motif
    verdict = await _verdict(pdf)
    return None if verdict.ok else verdict.motif


async def etat_envoi(db: AsyncSession, t: TalTransmission, *, user) -> dict[str, Any]:
    """Tout ce que l'écran doit savoir : qui signe, l'envoi est-il possible, où en est la signature."""
    liste = personnes(t, user=user)
    motif = await _motif_refus(db, t, liste, await _pdf_officiel(db, t))
    return {
        "transmission_id": t.id,
        "personnes": liste,
        "envoi_possible": motif is None,
        "motif": motif,
        "max_par_partie": gab.MAX_PAR_PARTIE,
        # Documents qui peuvent partir avec le bail, et ceux du dernier envoi.
        "annexes": await annexes_bail.disponibles(db),
        "annexes_envoyees": svc._charger_json(getattr(t, "annexes_json", None), []),
        "signature": await svc.etat_signature(db, t.esign_document_id),
        "signe_le": _iso(t.signe_le),
        "document_signe_id": t.document_signe_id,
    }


# ─── Envoi en un geste ────────────────────────────────────────────────


def _courriel_valide(valeur: str, nom: str) -> str:
    from pydantic import EmailStr, TypeAdapter, ValidationError

    try:
        return str(TypeAdapter(EmailStr).validate_python((valeur or "").strip())).lower()
    except ValidationError as exc:
        raise svc.TalBailError(f"Courriel invalide pour {nom} : « {valeur} ».", http_status=422) from exc


async def _verrouiller(db: AsyncSession, transmission_id: int) -> TalTransmission:
    """Verrou de ligne : deux clics simultanés deviennent séquentiels (état relu, jamais celui en mémoire)."""
    t = (
        await db.execute(
            select(TalTransmission).where(TalTransmission.id == transmission_id)
            .with_for_update().execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if t is None:
        raise svc.TalBailError("Transmission introuvable.", http_status=404)
    return t


async def envoyer(
    db: AsyncSession, transmission_id: int, *, user,
    courriels: Optional[dict[str, Optional[str]]] = None, message: Optional[str] = None,
    annexes: Optional[list[str]] = None,
) -> dict[str, Any]:
    """« Envoyer pour signature » : crée le document sur le PDF officiel, pose les zones
    du gabarit pour chaque personne invitée et fait partir les invitations.

    ``courriels`` : courriel par personne (clé « partie:rang »), tel que vu à l'écran —
    une clé présente remplace celui du formulaire, une valeur vide retire la personne de
    l'envoi. ``annexes`` : documents joints au bail dans le même envoi (clé « consentement »
    ou « modele:<id> ») ; chaque locataire invité les signe à la suite du bail. Valide ses
    transactions lui-même (brouillon complet, puis envoi).
    """
    from app.api.v1.endpoints import esign as moteur
    from app.models.esign import EsignDocument, EsignDocumentStatus, EsignEvent, EsignField, EsignSigner
    from app.services.esign_send import ensure_token

    t = await _verrouiller(db, transmission_id)
    if t.statut != "transmise" or not t.document_id:
        raise svc.TransmissionFermee("Génère d'abord le bail officiel (PDF du TAL) avant de l'envoyer pour signature.")
    if t.document_signe_id or t.signe_le:
        raise svc.TalBailError("Ce bail est déjà signé.", http_status=409)
    ancien = await db.get(EsignDocument, t.esign_document_id) if t.esign_document_id else None
    if ancien is not None and ancien.status == EsignDocumentStatus.ENVOYE.value:
        raise svc.TalBailError(
            "Ce bail est déjà en signature : renvoie une invitation, corrige un courriel ou annule l'envoi depuis le suivi.",
            http_status=409,
        )
    if ancien is not None and ancien.status == EsignDocumentStatus.COMPLETE.value:
        raise svc.TalBailError("Ce bail est déjà signé par tous.", http_status=409)

    pdf = await _pdf_officiel(db, t)
    liste = personnes(t, user=user)
    motif = await _motif_refus(db, t, liste, pdf)
    if motif:
        raise svc.TalBailError(
            f"Signature en ligne impossible pour ce bail : {motif}. Imprime le bail pour le faire signer à la main.",
            http_status=422,
        )
    assert pdf is not None

    retenus: list[dict[str, Any]] = []
    sans_courriel: list[str] = []
    for pers in liste:
        courriel = pers["courriel"]
        if courriels is not None and pers["cle"] in courriels:
            courriel = (courriels[pers["cle"]] or "").strip()
        if not courriel:
            sans_courriel.append(f"{pers['nom']} ({pers['role']})")
            continue
        retenus.append({**pers, "courriel": _courriel_valide(courriel, pers["nom"])})
    if not retenus:
        raise svc.TalBailError(
            "Personne à inviter : inscris au moins un courriel pour envoyer le bail en signature.",
            http_status=422, details={"sans_courriel": sans_courriel},
        )
    form = svc._charger_json(t.payload_json, {}) or {}
    zones = gab.zones_a_poser(form, {(pers["partie"], pers["rang"]) for pers in retenus})
    # Documents joints (consentement aux communications, règlement d'immeuble…) : à la suite du
    # bail dans la même enveloppe, signés par chaque locataire invité.
    locataires_invites = [(pers["rang"], pers["nom"]) for pers in retenus if pers["partie"] == "locataire"]
    demandees = [c for c in (annexes or []) if str(c or "").strip()]
    if demandees and not locataires_invites:
        raise svc.TalBailError(
            "Aucun locataire n'est invité à signer : les documents joints au bail ne pourraient pas être signés. "
            "Inscris le courriel d'un locataire, ou retire les documents joints.",
            http_status=422,
        )
    construites = await annexes_bail.construire(db, demandees, form, locataires_invites)
    enveloppe, zones_annexes, description = await asyncio.to_thread(annexes_bail.assembler, pdf, construites)

    # ── 1. Le document, ses signataires, leurs zones et leurs liens : enregistrés avant tout courriel.
    if ancien is not None and ancien.status == EsignDocumentStatus.BROUILLON.value:
        await moteur.delete_document(ancien.id, db, user)      # brouillon jamais parti : remplacé
    maintenant = datetime.now(timezone.utc)
    doc = EsignDocument(
        entreprise_id=await svc.entreprise_proprietaire(db, t), created_by_user_id=getattr(user, "id", None),
        title=(f"Bail de logement — {t.adresse}" if t.adresse else "Bail de logement (TAL)")[:255],
        message=((message or "").strip() or (MESSAGE_DEFAUT + _phrase_documents_joints(description)))[:2000],
        status=EsignDocumentStatus.BROUILLON.value, use_signing_order=False,
        filename=svc.nom_fichier_bail(form), content_type="application/pdf", pdf_blob=enveloppe,
        page_count=max(1, description[-1]["pages"][1] if description else (await _verdict(pdf)).pages),
        sha256=hashlib.sha256(enveloppe).hexdigest(),
        origine=svc.ORIGINE_ESIGN,
    )
    db.add(doc)
    await db.flush()
    signataires: dict[tuple[str, int], Any] = {}
    for i, pers in enumerate(retenus):
        prenom, famille = svc._prenom_nom(pers["nom"])
        signataire = EsignSigner(
            document_id=doc.id, order_index=i, first_name=prenom or pers["nom"][:100], last_name=famille,
            email=pers["courriel"][:320], phone=pers["telephone"], require_sms_auth=False,
            contact_ref=svc.reference_signataire(pers["role"], pers["rang"]),
        )
        ensure_token(signataire)
        db.add(signataire)
        signataires[(pers["partie"], pers["rang"])] = signataire
    await db.flush()
    for zone in zones:
        db.add(EsignField(
            document_id=doc.id, signer_id=signataires[(zone.partie, zone.rang)].id, kind=zone.kind, page=zone.page,
            required=True, label=zone.libelle[:120], **gab.fractions(zone),
        ))
    for za in zones_annexes:
        db.add(EsignField(
            document_id=doc.id, signer_id=signataires[("locataire", za["rang"])].id, kind=za["kind"], page=za["page"],
            required=True, label=("Signature du locataire" if za["kind"] == "signature" else "Date"),
            x=za["x"], y=za["y"], w=za["w"], h=za["h"],
        ))
    joints = (" — documents joints : " + ", ".join(a["titre"] for a in description)) if description else ""
    db.add(EsignEvent(
        document_id=doc.id, type="cree",
        detail=(f"Bail officiel TAL (transmission #{t.id}) — {len(zones)} zones posées selon le gabarit officiel{joints} — par {getattr(user, 'email', '')}")[:500],
    ))
    t.annexes_json = svc._json(description) if description else None
    t.esign_document_id = doc.id
    t.updated_at = maintenant
    doc_id = doc.id
    await db.commit()

    # ── 2. Les invitations partent, sous verrou : un second clic attend, puis voit « déjà envoyé ».
    t = await _verrouiller(db, transmission_id)
    if t.esign_document_id != doc_id:
        raise svc.TalBailError("Un autre envoi vient d'être lancé pour ce bail : recharge le suivi.", http_status=409)
    try:
        resultat = await moteur.send_document(doc_id, db, user)
    except HTTPException as exc:
        await db.rollback()
        raise svc.TalBailError(
            f"Les invitations ne sont pas parties : {_detail(exc)} Rien n'a été envoyé — corrige puis renvoie.",
            http_status=exc.status_code if exc.status_code >= 400 else 502,
        ) from exc
    await log_action(
        db, user=user, action="tal_bail.signature_envoyee", entity_type="tal_transmission", entity_id=t.id,
        details={
            "esign_document_id": doc_id, "bail_id": t.bail_id, "zones": len(zones) + len(zones_annexes),
            "documents_joints": [a["titre"] for a in description],
            "signataires": [{"role": pers["role"], "rang": pers["rang"], "courriel": pers["courriel"]} for pers in retenus],
            "sans_courriel": sans_courriel, "envoyes": resultat.sent, "erreurs": resultat.errors,
        },
    )
    await db.commit()
    return {
        "esign_document_id": doc_id, "envoyes": resultat.sent, "erreurs": list(resultat.errors),
        "sans_courriel": sans_courriel, "zones": len(zones) + len(zones_annexes), "annexes": description,
        "signature": await svc.etat_signature(db, doc_id),
    }


# ─── Suivi : renvoyer, corriger un courriel, annuler ──────────────────


async def _signataire_du_bail(db: AsyncSession, t: TalTransmission, signataire_id: int):
    from app.models.esign import EsignSigner

    signataire = await db.get(EsignSigner, signataire_id)
    if signataire is None or not t.esign_document_id or signataire.document_id != t.esign_document_id:
        raise svc.TalBailError("Ce signataire n'appartient pas à la signature de ce bail.", http_status=404)
    return signataire


async def renvoyer(db: AsyncSession, t: TalTransmission, signataire_id: int, *, user) -> dict[str, Any]:
    """Renvoie son invitation à UNE personne qui n'a pas encore signé."""
    from app.api.v1.endpoints import esign as moteur

    signataire = await _signataire_du_bail(db, t, signataire_id)
    await moteur.resend_signer(signataire.id, db, user)
    await log_action(db, user=user, action="tal_bail.signature_renvoyee", entity_type="tal_transmission", entity_id=t.id,
                     details={"esign_document_id": t.esign_document_id, "courriel": signataire.email})
    await db.flush()
    return {"signature": await svc.etat_signature(db, t.esign_document_id)}


async def changer_courriel(db: AsyncSession, t: TalTransmission, signataire_id: int, courriel: str, *, user) -> dict[str, Any]:
    """Corrige le courriel d'une personne qui n'a pas encore signé : l'ancien lien cesse de
    fonctionner, une invitation part à la nouvelle adresse. Le formulaire transmis au TAL
    n'est pas touché."""
    from pydantic import ValidationError

    from app.api.v1.endpoints import esign as moteur

    signataire = await _signataire_du_bail(db, t, signataire_id)
    ancien = signataire.email
    try:
        patch = moteur.SignerPatch(email=(courriel or "").strip())
    except ValidationError as exc:
        raise svc.TalBailError(f"Courriel invalide : « {courriel} ».", http_status=422) from exc
    if patch.email is None:
        raise svc.TalBailError("Inscris le nouveau courriel.", http_status=422)
    await moteur.patch_signer(signataire.id, patch, db, user)
    await db.refresh(signataire)
    # L'outil ne renvoie de lui-même que si une invitation était déjà partie : une première
    # invitation restée en panne part maintenant, à la bonne adresse.
    if signataire.sent_at is None and signataire.signed_at is None and signataire.declined_at is None:
        await moteur.resend_signer(signataire.id, db, user)
    await log_action(db, user=user, action="tal_bail.signature_courriel_corrige", entity_type="tal_transmission", entity_id=t.id,
                     details={"esign_document_id": t.esign_document_id, "avant": ancien, "apres": signataire.email})
    await db.flush()
    return {"signature": await svc.etat_signature(db, t.esign_document_id)}


async def annuler(db: AsyncSession, t: TalTransmission, *, user) -> dict[str, Any]:
    """Annule l'envoi en cours : les liens cessent de fonctionner ; le bail peut repartir en
    signature (nouveau document, nouvelles invitations)."""
    from app.api.v1.endpoints import esign as moteur

    if not t.esign_document_id:
        raise svc.TalBailError("Aucune signature lancée pour ce bail.", http_status=404)
    await moteur.cancel_document(t.esign_document_id, db, user)
    t.updated_at = datetime.now(timezone.utc)
    await log_action(db, user=user, action="tal_bail.signature_annulee", entity_type="tal_transmission", entity_id=t.id,
                     details={"esign_document_id": t.esign_document_id})
    await db.flush()
    return {"signature": await svc.etat_signature(db, t.esign_document_id)}


# ─── Où suivre un document de signature de bail ───────────────────────


async def lien_de_suivi(db: AsyncSession, esign_document_id: int) -> Optional[str]:
    """Page de Gestion immobilière où se suit ce document, None si ce n'est pas un bail."""
    t = (
        await db.execute(
            select(TalTransmission).where(TalTransmission.esign_document_id == esign_document_id)
            .order_by(TalTransmission.id.desc()).limit(1)
        )
    ).scalars().first()
    if t is None:
        return None
    return "/immobilier/admin-locative?onglet=baux" if getattr(t, "independant", False) else "/immobilier/locations"


__all__ = [
    "MESSAGE_DEFAUT", "personnes", "etat_envoi", "envoyer", "renvoyer", "changer_courriel", "annuler", "lien_de_suivi",
]
