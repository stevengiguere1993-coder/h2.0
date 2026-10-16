"""Mode ESSAI de l'aperçu « voir comme » — tester sans rien enregistrer.

Demande de Steven (2026-10-16) : dans l'aperçu « voir comme » (jeton émis
par ``POST /users/{id}/apercu``), pouvoir réellement ESSAYER les actions de
l'utilisateur regardé pour voir ce qu'il peut faire ou non, sans qu'aucun
changement ne reste une fois l'aperçu quitté.

Contrat :

- Activation : requête d'ÉCRITURE (POST/PUT/PATCH/DELETE) portant un jeton
  d'aperçu (revendication ``apercu_par``) ET l'en-tête ``X-Kratos-Essai: 1``
  (interrupteur « Mode essai » du bandeau d'aperçu). Sans l'en-tête, un
  jeton d'aperçu reste en lecture seule stricte (403 sur toute écriture,
  comportement d'origine). Les lectures (GET…) ne changent pas.
- Base de données : ``EssaiMiddleware`` ouvre UNE connexion dédiée et une
  transaction englobante pour toute la requête. Chaque session ORM créée
  pendant la requête (``get_db``, ``AsyncSessionLocal()`` dans un
  endpoint, une BackgroundTask ou le journal d'audit) s'y greffe en
  SAVEPOINT via ``SessionKratos.get_bind`` : les ``commit()`` de
  l'endpoint réussissent (la suite de la requête voit ses propres
  écritures), puis TOUT est annulé (ROLLBACK) à la fin de la requête.
  Une tâche lancée pendant l'essai qui tenterait d'écrire APRÈS la fin
  de la requête est refusée (connexion close) : jamais d'écriture réelle.
- Permissions : la requête s'exécute avec l'utilisateur REGARDÉ, par les
  mêmes dépendances et gardes que pour lui — un refus (403…) est donc
  exactement celui qu'il verrait.
- Effets externes : pendant un essai, tout appel sortant (httpx — dont
  les SDK Anthropic/Groq —, requests — Google auth, Stripe, web push —,
  httplib2 — Google Drive —, urllib, SMTP ; Gemini/gRPC par appel explicite
  à ``bloquer_si_essai`` dans ``lead_analyses``) lève
  ``EffetExterneBloque`` AVANT de partir : QuickBooks, Drive, courriel,
  VoPay, SMS, notifications, paiements, IA… rien ne sort. Non rattrapée
  par l'endpoint, l'exception devient une réponse 409 explicite (handler
  posé dans ``app.main``). Les appels internes in-process
  (``httpx.ASGITransport``…) ne sont pas concernés.
- Réponse : en-tête ``X-Kratos-Essai: annule`` (le frontend affiche
  « permis, rien n'a été enregistré » ou le refus), plus
  ``X-Kratos-Essai-Externe: hote1,hote2`` si des appels ont été bloqués.
- Journal d'audit : RIEN n'est enregistré pour un essai (le middleware
  d'audit l'ignore, et toute entrée ``log_action`` est annulée avec le
  reste) — aucune action n'est jamais imputée à l'utilisateur regardé.
"""

from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit

from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger(__name__)

#: En-tête envoyé par le frontend quand l'interrupteur « Mode essai » du
#: bandeau d'aperçu est activé.
ENTETE_DEMANDE = "x-kratos-essai"
#: En-têtes posés sur chaque réponse d'essai.
ENTETE_REPONSE = "x-kratos-essai"
ENTETE_EXTERNE = "x-kratos-essai-externe"
VALEUR_ANNULE = "annule"

_METHODES_LECTURE = frozenset({"GET", "HEAD", "OPTIONS"})
_VALEURS_VRAIES = frozenset({"1", "true", "oui", "on"})


@dataclass
class EtatEssai:
    """État d'un essai pour la requête courante (porté par un ContextVar,
    donc hérité par les BackgroundTasks, ``asyncio.create_task`` et les
    appels synchrones passés au threadpool)."""

    connexion: Any  # AsyncConnection dédiée, transaction englobante ouverte
    ouvert: bool = True
    bloques: list[str] = field(default_factory=list)


_essai: contextvars.ContextVar[Optional[EtatEssai]] = contextvars.ContextVar(
    "kratos_essai", default=None
)


def essai_courant() -> Optional[EtatEssai]:
    """État de l'essai en cours, ou None hors essai."""
    return _essai.get()


def essai_actif() -> bool:
    """True quand la requête courante est un essai (rien ne sera gardé)."""
    return _essai.get() is not None


class EffetExterneBloque(RuntimeError):
    """Appel vers un service externe refusé pendant un essai."""

    def __init__(self, cible: str) -> None:
        self.cible = cible
        super().__init__(
            "Mode essai : cette action aurait contacté un service externe "
            f"({cible}). L'appel a été bloqué : rien n'a été envoyé ni "
            "enregistré."
        )


def bloquer_si_essai(cible: Any) -> None:
    """Lève ``EffetExterneBloque`` si un essai est en cours (no-op sinon).
    ``cible`` = URL ou hôte, noté dans l'état pour l'en-tête de réponse."""
    etat = _essai.get()
    if etat is None:
        return
    brut = str(cible or "")
    hote = urlsplit(brut).hostname if "://" in brut else None
    hote = hote or brut or "service externe"
    if hote not in etat.bloques:
        etat.bloques.append(hote)
    raise EffetExterneBloque(hote)


class SessionKratos(Session):
    """Session ORM de Kratos : identique à ``Session`` hors essai.

    Pendant un essai, toute session se greffe sur la connexion dédiée de
    l'essai en mode SAVEPOINT (``join_transaction_mode``) : ``commit()``
    ne fait que libérer un savepoint, la transaction englobante est
    annulée par ``EssaiMiddleware`` à la fin de la requête."""

    def get_bind(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        etat = _essai.get()
        if etat is not None:
            if not etat.ouvert:
                raise RuntimeError(
                    "Mode essai terminé : écriture refusée (rien n'est "
                    "enregistré en mode essai)."
                )
            self.join_transaction_mode = "create_savepoint"
            return etat.connexion.sync_connection
        return super().get_bind(*args, **kwargs)


def _entete(scope: Scope, nom: bytes) -> str:
    for cle, valeur in scope.get("headers") or []:
        if cle.lower() == nom:
            return valeur.decode("latin-1")
    return ""


def demande_essai(scope: Scope) -> bool:
    """La requête demande-t-elle un essai valide ? Écriture + en-tête
    ``X-Kratos-Essai`` + jeton d'APERÇU valide (``apercu_par``)."""
    if scope.get("type") != "http":
        return False
    if str(scope.get("method", "")).upper() in _METHODES_LECTURE:
        return False
    if _entete(scope, ENTETE_DEMANDE.encode()).strip().lower() not in _VALEURS_VRAIES:
        return False
    auth = _entete(scope, b"authorization")
    if not auth.lower().startswith("bearer "):
        return False
    from app.core.security import verify_token

    payload = verify_token(auth[7:].strip())
    return bool(payload) and payload.get("apercu_par") is not None


class EssaiMiddleware:
    """Middleware ASGI « pur », monté le plus à l'extérieur : il englobe
    l'app, le middleware d'audit et les BackgroundTasks de l'endpoint,
    pour que l'annulation finale couvre absolument tout."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not demande_essai(scope):
            await self.app(scope, receive, send)
            return

        from app.db.session import engine

        async with engine.connect() as connexion:
            etat = EtatEssai(connexion=connexion)
            jeton = _essai.set(etat)
            # ``begin`` APRÈS avoir posé l'état : les écouteurs d'événement
            # « begin » voient déjà l'essai (cf. tests/smoke/conftest.py).
            try:
                transaction = await connexion.begin()
            except BaseException:
                etat.ouvert = False
                _essai.reset(jeton)
                raise

            async def _send(message: Message) -> None:
                if message["type"] == "http.response.start":
                    entetes = [
                        (k, v)
                        for k, v in (message.get("headers") or [])
                        if k.lower()
                        not in (ENTETE_REPONSE.encode(), ENTETE_EXTERNE.encode())
                    ]
                    entetes.append(
                        (ENTETE_REPONSE.encode(), VALEUR_ANNULE.encode())
                    )
                    if etat.bloques:
                        entetes.append(
                            (
                                ENTETE_EXTERNE.encode(),
                                ",".join(etat.bloques).encode("latin-1", "replace"),
                            )
                        )
                    message = {**message, "headers": entetes}
                await send(message)

            try:
                await self.app(scope, receive, _send)
            finally:
                etat.ouvert = False
                _essai.reset(jeton)
                try:
                    await transaction.rollback()
                except Exception as exc:  # noqa: BLE001
                    # La connexion est de toute façon fermée/invalidée à
                    # la sortie du ``async with`` : une transaction non
                    # validée n'est jamais conservée par la base.
                    log.warning("essai : rollback final en erreur : %s", exc)


# ── Garde des appels sortants ─────────────────────────────────────────

_garde_installee = False


def installer_garde_sorties() -> None:
    """Enveloppe les points de sortie réseau connus pour qu'ils refusent
    de partir pendant un essai. Idempotent ; hors essai, aucun effet."""
    global _garde_installee
    if _garde_installee:
        return
    _garde_installee = True

    # httpx (appels directs + SDK Anthropic / Groq).
    try:
        import httpx

        internes = tuple(
            t
            for t in (
                getattr(httpx, "ASGITransport", None),
                getattr(httpx, "WSGITransport", None),
                getattr(httpx, "MockTransport", None),
            )
            if t is not None
        )

        def _interne(client: Any) -> bool:
            return isinstance(getattr(client, "_transport", None), internes)

        envoi_async = httpx.AsyncClient.send
        envoi_sync = httpx.Client.send

        async def _send_async(self, request, *args, **kwargs):  # noqa: ANN001
            if _essai.get() is not None and not _interne(self):
                bloquer_si_essai(request.url)
            return await envoi_async(self, request, *args, **kwargs)

        def _send_sync(self, request, *args, **kwargs):  # noqa: ANN001
            if _essai.get() is not None and not _interne(self):
                bloquer_si_essai(request.url)
            return envoi_sync(self, request, *args, **kwargs)

        httpx.AsyncClient.send = _send_async  # type: ignore[method-assign]
        httpx.Client.send = _send_sync  # type: ignore[method-assign]
    except Exception as exc:  # noqa: BLE001
        log.warning("essai : garde httpx non installée : %s", exc)

    # requests (google-auth, Stripe, pywebpush).
    try:
        import requests.adapters

        envoi_requests = requests.adapters.HTTPAdapter.send

        def _send_requests(self, request, *args, **kwargs):  # noqa: ANN001
            bloquer_si_essai(getattr(request, "url", ""))
            return envoi_requests(self, request, *args, **kwargs)

        requests.adapters.HTTPAdapter.send = _send_requests  # type: ignore[method-assign]
    except Exception as exc:  # noqa: BLE001
        log.debug("essai : garde requests non installée : %s", exc)

    # httplib2 (googleapiclient → Google Drive).
    try:
        import httplib2

        requete_httplib2 = httplib2.Http.request

        def _request_httplib2(self, uri, *args, **kwargs):  # noqa: ANN001
            bloquer_si_essai(uri)
            return requete_httplib2(self, uri, *args, **kwargs)

        httplib2.Http.request = _request_httplib2  # type: ignore[method-assign]
    except Exception as exc:  # noqa: BLE001
        log.debug("essai : garde httplib2 non installée : %s", exc)

    # urllib.request.
    try:
        import urllib.request

        ouvrir = urllib.request.OpenerDirector.open

        def _open(self, fullurl, *args, **kwargs):  # noqa: ANN001
            cible = fullurl.get_full_url() if hasattr(fullurl, "get_full_url") else fullurl
            bloquer_si_essai(cible)
            return ouvrir(self, fullurl, *args, **kwargs)

        urllib.request.OpenerDirector.open = _open  # type: ignore[method-assign]
    except Exception as exc:  # noqa: BLE001
        log.debug("essai : garde urllib non installée : %s", exc)

    # SMTP (courriels).
    try:
        import smtplib

        connecter = smtplib.SMTP.connect

        def _connect(self, host="localhost", *args, **kwargs):  # noqa: ANN001
            bloquer_si_essai(f"smtp://{host}")
            return connecter(self, host, *args, **kwargs)

        smtplib.SMTP.connect = _connect  # type: ignore[method-assign]
    except Exception as exc:  # noqa: BLE001
        log.debug("essai : garde SMTP non installée : %s", exc)

