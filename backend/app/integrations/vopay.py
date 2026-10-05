"""Client VoPay : paiement automatique des fournisseurs (Comptabilité →
Paiements).

Steven (2026-10-05) : « l'idée est de reproduire Plooto et ce qu'il fait.
Donc si Plooto paie, arrange pour que Kratos le fasse. » Desjardins n'offre
aucune API pour envoyer des paiements ; VoPay, service de paiement
canadien, le fait pour Kratos à partir du compte Desjardins de
l'entreprise :

- ``prelever`` (eft/fund) : débite le compte de l'entreprise (débit
  préautorisé signé à l'ouverture du compte VoPay) vers son solde VoPay ;
- ``deposer`` (eft/withdraw) : dépôt direct dans un compte bancaire, depuis
  ce solde ;
- ``envoyer_interac`` (interac/bulk-payout) : virement Interac, depuis ce
  solde ;
- ``statut`` : où en est une opération.

Authentification (https://docs.vopay.com) : AccountID, Key et Signature =
sha1(Key + SharedSecret + date AAAA-MM-JJ), dans le formulaire (POST) ou la
requête (GET) ; réponses en JSON (« Success », « ErrorMessage »…).

Chaque création porte une clé d'idempotence (IdempotencyKey) : VoPay
refuse une deuxième demande avec la même clé, ce qui empêche un double
paiement quand une réponse se perd. Ce module n'écrit jamais les clés ni
les numéros de compte dans les journaux.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

URLS = {
    "test": "https://earthnode-dev.vopay.com/api/v2/",
    "production": "https://earthnode.vopay.com/api/v2/",
}
DELAI = httpx.Timeout(30.0, connect=10.0)

#: Statuts VoPay (EFT : pending, in progress, successful, failed,
#: cancelled ; Interac : pending, in progress, sent, successful, failed,
#: declined, cancelled, cancellation requested). Un virement Interac
#: « sent » attend que le fournisseur l'accepte : il est encore en cours.
_REUSSIS = {"successful", "completed", "complete", "deposited"}
_ECHOUES = {"failed", "cancelled", "canceled", "declined", "returned", "rejected", "expired"}
#: Codes d'erreur VoPay : 9997 à 9999 = panne chez VoPay (réessayer) ;
#: 3001 = solde ou limite dépassé.
_CODES_TEMPORAIRES = {"9997", "9998", "9999"}
CODE_SOLDE = "3001"


class VoPayErreur(Exception):
    """VoPay a répondu non, ou n'a pas pu être joint : rien n'a été créé."""

    def __init__(self, message: str, *, code: Optional[str] = None, temporaire: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.temporaire = temporaire

    @property
    def solde(self) -> bool:
        """Solde VoPay insuffisant (ou limite du compte) pour l'instant."""
        return self.code == CODE_SOLDE


class VoPayIncertain(Exception):
    """La demande est peut-être arrivée chez VoPay (réponse perdue). Ne
    jamais la refaire avec une autre clé d'idempotence."""


@dataclass(frozen=True)
class Adresse:
    ligne: str
    ville: str
    province: str
    code_postal: str


@dataclass(frozen=True)
class Statut:
    #: Statut VoPay tel quel (« in progress »…).
    brut: str
    #: « en_cours », « reussi » ou « echoue ».
    etat: str
    raison: Optional[str] = None


def etat(brut: str) -> str:
    s = (brut or "").strip().lower()
    if s in _REUSSIS:
        return "reussi"
    if s in _ECHOUES:
        return "echoue"
    return "en_cours"


def montant(cents: int) -> str:
    entier, reste = divmod(int(cents), 100)
    return f"{entier}.{reste:02d}"


def _cherche(donnees: Any, cles: Iterable[str], profondeur: int = 0) -> Optional[Any]:
    """Première valeur non vide d'une des ``cles`` (sans égard à la casse),
    au premier niveau puis dans les objets imbriqués (la forme exacte des
    réponses de statut n'est pas documentée)."""
    voulues = {c.lower() for c in cles}
    if isinstance(donnees, dict):
        for k, v in donnees.items():
            if str(k).lower() in voulues and v not in (None, "", [], {}):
                return v
        if profondeur < 3:
            for v in donnees.values():
                if isinstance(v, (dict, list)):
                    trouve = _cherche(v, voulues, profondeur + 1)
                    if trouve is not None:
                        return trouve
    elif isinstance(donnees, list) and profondeur < 3:
        for v in donnees[:5]:
            trouve = _cherche(v, voulues, profondeur + 1)
            if trouve is not None:
                return trouve
    return None


def lire_statut(reponse: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    # « TransactionStatus » d'abord : un « Status » de premier niveau peut
    # décrire la réponse plutôt que la transaction.
    brut = _cherche(reponse, ("TransactionStatus",))
    if brut is None:
        brut = _cherche(reponse, ("Status",))
    raison = _cherche(reponse, ("FailureReason", "ReturnReason", "Reason"))
    return (str(brut).strip() if brut is not None else None, str(raison).strip()[:500] if raison else None)


def soldes(reponse: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Solde du compte VoPay et fonds disponibles, en dollars."""

    def lire(*cles: str) -> Optional[float]:
        v = _cherche(reponse, cles)
        try:
            return round(float(str(v).replace(",", "")), 2) if v is not None else None
        except ValueError:
            return None

    return {
        "solde": lire("AccountBalance", "Balance"),
        "disponible": lire("AvailableFunds", "AvailableBalance"),
    }


def _succes(reponse: Dict[str, Any]) -> bool:
    v = reponse.get("Success")
    return v is True or str(v).strip().lower() in ("true", "1")


def _message(reponse: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    texte = reponse.get("ErrorMessage") or reponse.get("Message") or reponse.get("message") or ""
    code = reponse.get("ErrorCode") or reponse.get("Code")
    return (str(texte).strip()[:500] or "Demande refusée par VoPay.", str(code).strip() if code else None)


def _signature_refusee(texte: str, code: Optional[str]) -> bool:
    t = texte.lower()
    return code == "1000" or "signature" in t or "auth" in t or "credential" in t


class VoPay:
    """Un compte VoPay (une entreprise), en test ou en production."""

    def __init__(
        self,
        account_id: str,
        cle: str,
        secret: str,
        environnement: str = "test",
        sous_compte: Optional[str] = None,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        if environnement not in URLS:
            raise ValueError("Environnement VoPay inconnu : « test » ou « production ».")
        self.account_id = account_id
        self._cle = cle
        self._secret = secret
        self.environnement = environnement
        self.sous_compte = sous_compte or None
        self._transport = transport

    def signature(self, jour: str) -> str:
        return hashlib.sha1(f"{self._cle}{self._secret}{jour}".encode("utf-8")).hexdigest()

    @staticmethod
    def jours(maintenant: Optional[datetime] = None) -> List[str]:
        """Date du jour en UTC, puis à Vancouver si elle diffère : la
        documentation ne dit pas dans quel fuseau VoPay vérifie la
        signature (une signature refusée n'a rien créé : on réessaie)."""
        m = maintenant or datetime.now(timezone.utc)
        jours = [m.astimezone(timezone.utc).date().isoformat()]
        pacifique = m.astimezone(ZoneInfo("America/Vancouver")).date().isoformat()
        if pacifique not in jours:
            jours.append(pacifique)
        return jours

    async def _appel(
        self, methode: str, chemin: str, params: Dict[str, Any], *, creation: bool = False
    ) -> Dict[str, Any]:
        url = URLS[self.environnement] + chemin
        valeurs = {k: v for k, v in params.items() if v not in (None, "")}
        if self.sous_compte:
            valeurs.setdefault("ClientAccountID", self.sous_compte)
        jours = self.jours()
        for i, jour in enumerate(jours):
            donnees = {"AccountID": self.account_id, "Key": self._cle, "Signature": self.signature(jour), **valeurs}
            try:
                async with httpx.AsyncClient(timeout=DELAI, transport=self._transport) as client:
                    if methode == "GET":
                        r = await client.get(url, params=donnees)
                    else:
                        r = await client.post(url, data=donnees)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                # La demande n'est jamais partie : rien n'a été créé.
                raise VoPayErreur("VoPay ne répond pas pour l'instant.", temporaire=True) from exc
            except httpx.HTTPError as exc:
                if creation:
                    raise VoPayIncertain("VoPay n'a pas répondu à la demande.") from exc
                raise VoPayErreur("VoPay ne répond pas pour l'instant.", temporaire=True) from exc
            try:
                reponse = r.json()
            except ValueError:
                reponse = None
            if not isinstance(reponse, dict):
                # Un 4xx illisible (proxy, page introuvable) n'a rien créé ;
                # un 2xx ou un 5xx illisible, peut-être que si.
                if creation and not 400 <= r.status_code < 500:
                    raise VoPayIncertain(f"Réponse illisible de VoPay (HTTP {r.status_code}).")
                raise VoPayErreur(
                    f"Réponse illisible de VoPay (HTTP {r.status_code}).",
                    temporaire=r.status_code >= 500 or r.status_code == 429,
                )
            if _succes(reponse):
                return reponse
            texte, code = _message(reponse)
            if _signature_refusee(texte, code) and i + 1 < len(jours):
                continue
            if r.status_code >= 500 and creation:
                raise VoPayIncertain(f"VoPay a répondu par une erreur interne : {texte}")
            log.info("VoPay a refusé %s %s (code %s)", methode, chemin, code or "—")
            raise VoPayErreur(
                texte,
                code=code,
                # 429 : trop de demandes, celle-ci n'a pas été traitée.
                temporaire=r.status_code >= 500 or r.status_code == 429 or (code in _CODES_TEMPORAIRES),
            )
        raise VoPayErreur("Clés VoPay refusées.", code="1000")  # pragma: no cover — boucle épuisée

    @staticmethod
    def _transaction(reponse: Dict[str, Any]) -> str:
        tid = reponse.get("TransactionID") or reponse.get("TransactionId") or _cherche(reponse, ("TransactionID",))
        if tid in (None, ""):
            raise VoPayIncertain("VoPay a accepté la demande sans donner de numéro de transaction.")
        return str(tid).strip()

    async def solde(self) -> Dict[str, Any]:
        """Solde du compte : sert aussi à vérifier les clés."""
        return await self._appel("GET", "account/balance", {})

    async def prelever(
        self,
        *,
        montant_cents: int,
        nom: str,
        adresse: Adresse,
        institution: str,
        transit: str,
        compte: str,
        reference: str,
        note: str,
        cle: str,
    ) -> str:
        """Débite le compte bancaire de l'entreprise vers le solde VoPay."""
        r = await self._appel(
            "POST",
            "eft/fund",
            {
                "Amount": montant(montant_cents),
                "Currency": "CAD",
                "CompanyName": nom[:100],
                "Address1": adresse.ligne[:100],
                "City": adresse.ville[:60],
                "Province": adresse.province,
                "Country": "CA",
                "PostalCode": adresse.code_postal,
                "FinancialInstitutionNumber": institution,
                "BranchTransitNumber": transit,
                "AccountNumber": compte,
                "ClientReferenceNumber": reference[:50],
                "Notes": note[:250],
                "IdempotencyKey": cle,
            },
            creation=True,
        )
        return self._transaction(r)

    async def deposer(
        self,
        *,
        montant_cents: int,
        nom: str,
        adresse: Adresse,
        institution: str,
        transit: str,
        compte: str,
        reference: str,
        note: str,
        cle: str,
    ) -> str:
        """Dépôt direct dans un compte bancaire, depuis le solde VoPay."""
        r = await self._appel(
            "POST",
            "eft/withdraw",
            {
                "Amount": montant(montant_cents),
                "Currency": "CAD",
                "CompanyName": nom[:100],
                "Address1": adresse.ligne[:100],
                "City": adresse.ville[:60],
                "Province": adresse.province,
                "Country": "CA",
                "PostalCode": adresse.code_postal,
                "FinancialInstitutionNumber": institution,
                "BranchTransitNumber": transit,
                "AccountNumber": compte,
                "ClientReferenceNumber": reference[:50],
                "Notes": note[:250],
                "IdempotencyKey": cle,
            },
            creation=True,
        )
        return self._transaction(r)

    async def envoyer_interac(
        self,
        *,
        montant_cents: int,
        nom: str,
        destinataire: str,
        question: str,
        reponse: str,
        message: str,
        expediteur: str,
        reference: str,
        cle: str,
    ) -> str:
        """Virement Interac (courriel ou cellulaire), depuis le solde VoPay.
        La question n'est pas posée à un destinataire inscrit au dépôt
        automatique."""
        params: Dict[str, Any] = {
            "Amount": montant(montant_cents),
            "Currency": "CAD",
            "RecipientName": nom[:80],
            "Question": question[:40],
            "Answer": reponse,
            "SenderName": expediteur[:80],
            "Memo": message[:400],
            "Language": "fr",
            "ClientReferenceNumber": reference[:50],
            "IdempotencyKey": cle,
        }
        if "@" in destinataire:
            params["EmailAddress"] = destinataire
        else:
            params["PhoneNumber"] = destinataire
        r = await self._appel("POST", "interac/bulk-payout", params, creation=True)
        return self._transaction(r)

    async def statut(self, sorte: str, transaction_id: str) -> Statut:
        """``sorte`` : « prelevement » (eft/fund), « depot » (eft/withdraw)
        ou « interac » (interac/bulk-payout)."""
        # Les routes « transaction » rendent TransactionStatus et
        # FailureReason (documentation VoPay).
        chemin = {
            "prelevement": "eft/fund/transaction",
            "depot": "eft/withdraw/transaction",
            "interac": "interac/bulk-payout/transaction",
        }[sorte]
        r = await self._appel("GET", chemin, {"TransactionID": transaction_id})
        brut, raison = lire_statut(r)
        if not brut:
            raise VoPayErreur("VoPay n'a pas donné le statut de la transaction.", temporaire=True)
        return Statut(brut=brut, etat=etat(brut), raison=raison)
