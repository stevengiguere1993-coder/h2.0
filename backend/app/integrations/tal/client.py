"""Client de l'API FRW du TAL — deux appels (fiche « Déclencher une
transmission personnalisée ») :

1. FRW111 CreerFormulaireIndividu : clé partenaire + ``{"form": {...}}``
   → numéro public de formulaire (ShortGuid). Gratuit tant que la
   transmission n'est pas déclenchée (à confirmer avec le TAL).
2. FRW122 DeclencherTransmissionPersonnalisee : NoPublicFormulaire =
   ShortGuid, IdTransmissionPerso = « envoi-partenaire », Identifiant
   Utilisateur (optionnel, notre suivi) → le formulaire devient
   FACTURABLE (2,99 $) ; réponse : ``documents[]`` (nom, flux base64,
   type source ex. genererPdf) + ``messages[]`` (mnémonique, texte).

URL de base, chemins, nom de l'en-tête de la clé et format exact ne sont
PAS encore connus (ils arrivent avec la clé) : tout vient d'une
``ConnexionTal`` résolue par le service (table ``tal_connexion`` →
variables d'environnement ``TAL_*`` en repli) et s'ajuste sans toucher
au reste.

Mode ``simulation`` (défaut tant qu'il n'y a pas de clé) : aucun appel
réseau ; ShortGuid « SIM-… », PDF local clairement marqué « SIMULATION —
CE N'EST PAS UN BAIL OFFICIEL », message mnémonique SIMULATION. Le mode
réel refuse de partir sans URL ni clé. La clé n'apparaît jamais dans les
journaux ni dans les erreurs.
"""

from __future__ import annotations

import base64
import io
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

ID_TRANSMISSION_PERSO = "envoi-partenaire"
MODE_SIMULATION = "simulation"
MODE_REEL = "reel"
MODES = (MODE_SIMULATION, MODE_REEL)
TYPE_FORMULAIRE = "53000BAIL"
ENTETE_CLE_DEFAUT = "X-Api-Key"
CHEMIN_FRW111_DEFAUT = "/FRW111/CreerFormulaireIndividu"
CHEMIN_FRW122_DEFAUT = "/FRW122/DeclencherTransmissionPersonnalisee"
_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


class TalApiError(Exception):
    """Erreur d'appel (HTTP ≥ 400, réponse illisible, réseau). ``etape``
    ∈ {FRW111, FRW122}. Jamais la clé dans le message."""

    def __init__(self, etape: str, message: str, *, http_status: Optional[int] = None, corps: Any = None):
        super().__init__(f"{etape} : {message}")
        self.etape = etape
        self.message = message
        self.http_status = http_status
        self.corps = corps


@dataclass
class ConnexionTal:
    """Paramètres de connexion résolus (clé en clair SEULEMENT en mémoire,
    le temps de l'appel)."""

    mode: str = MODE_SIMULATION
    url: str = ""
    cle: str = ""
    entete_cle: str = ENTETE_CLE_DEFAUT
    chemin_frw111: str = CHEMIN_FRW111_DEFAUT
    chemin_frw122: str = CHEMIN_FRW122_DEFAUT

    @property
    def simulation(self) -> bool:
        return (self.mode or MODE_SIMULATION).lower() != MODE_REEL

    @property
    def prete_pour_reel(self) -> bool:
        return bool(self.url) and bool(self.cle)

    def etat(self) -> dict[str, Any]:
        """Pour Paramètres : jamais la clé."""
        mode = (self.mode or MODE_SIMULATION).lower()
        return {
            "mode": mode,
            "url_configuree": bool(self.url),
            "api_url": self.url or None,
            "cle_configuree": bool(self.cle),
            "pret_pour_reel": mode == MODE_REEL and self.prete_pour_reel,
            "entete_cle": self.entete_cle,
            "chemin_frw111": self.chemin_frw111,
            "chemin_frw122": self.chemin_frw122,
        }


def connexion_depuis_env() -> ConnexionTal:
    """Repli : variables d'environnement ``TAL_MODE``, ``TAL_API_URL``,
    ``TAL_API_KEY``, ``TAL_API_ENTETE_CLE``, ``TAL_API_CHEMIN_FRW111/122``."""
    return ConnexionTal(
        mode=((getattr(settings, "tal_mode", None) or MODE_SIMULATION).strip().lower()),
        url=(getattr(settings, "tal_api_url", None) or "").strip().rstrip("/"),
        cle=(getattr(settings, "tal_api_key", None) or "").strip(),
        entete_cle=(getattr(settings, "tal_api_entete_cle", None) or ENTETE_CLE_DEFAUT).strip(),
        chemin_frw111=(getattr(settings, "tal_api_chemin_frw111", None) or CHEMIN_FRW111_DEFAUT).strip(),
        chemin_frw122=(getattr(settings, "tal_api_chemin_frw122", None) or CHEMIN_FRW122_DEFAUT).strip(),
    )


def etat_configuration(connexion: Optional[ConnexionTal] = None) -> dict[str, Any]:
    return (connexion or connexion_depuis_env()).etat()


@dataclass
class ReponseCreation:
    short_guid: str
    brut: Any = None
    duree_ms: int = 0


@dataclass
class DocumentTal:
    nom: str
    contenu_base64: str
    type_source: Optional[str] = None

    def octets(self) -> bytes:
        return base64.b64decode(self.contenu_base64, validate=False)


@dataclass
class ReponseTransmission:
    no_confirmation: Optional[str]
    documents: list[DocumentTal] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    brut: Any = None
    duree_ms: int = 0


def _extraire(d: Any, *cles: str) -> Any:
    """Première clé présente (insensible à la casse) dans un dict."""
    if not isinstance(d, dict):
        return None
    bas = {str(k).lower(): v for k, v in d.items()}
    for k in cles:
        if k.lower() in bas and bas[k.lower()] not in (None, ""):
            return bas[k.lower()]
    return None


class ClientTal:
    def __init__(self, connexion: Optional[ConnexionTal] = None):
        self.cx = connexion or connexion_depuis_env()

    @property
    def simulation(self) -> bool:
        return self.cx.simulation

    @property
    def mode(self) -> str:
        return MODE_SIMULATION if self.simulation else MODE_REEL

    # ── FRW111 ──────────────────────────────────────────────────────
    async def creer_formulaire(self, form: dict[str, Any], *, identifiant_utilisateur: Optional[str] = None) -> ReponseCreation:
        t0 = time.monotonic()
        if self.simulation:
            return ReponseCreation(short_guid="SIM-" + secrets.token_urlsafe(8), brut={"simulation": True}, duree_ms=1)
        self._exiger_config("FRW111")
        payload: dict[str, Any] = {"typeFormulaire": TYPE_FORMULAIRE, "form": form}
        if identifiant_utilisateur:
            payload["identifiantUtilisateur"] = identifiant_utilisateur
        corps = await self._post("FRW111", self.cx.chemin_frw111, payload)
        short_guid = _extraire(corps, "shortGuid", "noPublicFormulaire", "NoPublicFormulaire", "numeroPublic", "id")
        if not short_guid:
            raise TalApiError("FRW111", "réponse sans ShortGuid", corps=corps)
        return ReponseCreation(short_guid=str(short_guid), brut=corps, duree_ms=int((time.monotonic() - t0) * 1000))

    # ── FRW122 ──────────────────────────────────────────────────────
    async def declencher_transmission(
        self, short_guid: str, *, identifiant_utilisateur: Optional[str] = None, form_pour_simulation: Optional[dict[str, Any]] = None
    ) -> ReponseTransmission:
        t0 = time.monotonic()
        if self.simulation:
            pdf = pdf_simulation(form_pour_simulation or {}, short_guid)
            return ReponseTransmission(
                no_confirmation="SIM-CONF-" + secrets.token_hex(4).upper(),
                documents=[DocumentTal(nom=f"bail_simulation_{short_guid}.pdf", contenu_base64=base64.b64encode(pdf).decode("ascii"), type_source="simulation")],
                messages=[{"mnemonique": "SIMULATION", "texte": "Aucun appel au TAL : PDF de simulation, non officiel, non facturé."}],
                brut={"simulation": True},
                duree_ms=int((time.monotonic() - t0) * 1000),
            )
        self._exiger_config("FRW122")
        payload: dict[str, Any] = {"NoPublicFormulaire": short_guid, "IdTransmissionPerso": ID_TRANSMISSION_PERSO}
        if identifiant_utilisateur:
            payload["IdentifiantUtilisateur"] = identifiant_utilisateur
        corps = await self._post("FRW122", self.cx.chemin_frw122, payload)
        docs_brut = _extraire(corps, "documents") or []
        documents: list[DocumentTal] = []
        for d in docs_brut if isinstance(docs_brut, list) else []:
            if not isinstance(d, dict):
                continue
            b64 = _extraire(d, "fluxFichier", "flux", "contenu", "fichier", "base64", "contenuBase64", "data")
            if not b64:
                continue
            type_source = _extraire(d, "typeSource", "type", "source")
            documents.append(DocumentTal(
                nom=str(_extraire(d, "nom", "nomFichier", "name") or "document.pdf"),
                contenu_base64=str(b64),
                type_source=(str(type_source) if type_source else None),
            ))
        messages_brut = _extraire(corps, "messages") or []
        messages = [
            {"mnemonique": _extraire(m, "mnemonique", "mnemonic", "code"), "texte": _extraire(m, "texte", "message", "text")}
            for m in (messages_brut if isinstance(messages_brut, list) else []) if isinstance(m, dict)
        ]
        conf = _extraire(corps, "noConfirmation", "numeroConfirmation", "confirmation", "NoConfirmation")
        return ReponseTransmission(
            no_confirmation=(str(conf) if conf else None),
            documents=documents, messages=messages, brut=corps,
            duree_ms=int((time.monotonic() - t0) * 1000),
        )

    # ── HTTP ─────────────────────────────────────────────────────────
    def _exiger_config(self, etape: str) -> None:
        if not self.cx.prete_pour_reel:
            raise TalApiError(etape, "URL ou clé API du TAL non configurée (Paramètres → Gestion locative → Bail TAL) : mode réel impossible.")

    async def _post(self, etape: str, chemin: str, payload: dict[str, Any]) -> Any:
        url = self.cx.url.rstrip("/") + (chemin if chemin.startswith("/") else "/" + chemin)
        headers = {self.cx.entete_cle: self.cx.cle, "Accept": "application/json", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise TalApiError(etape, f"TAL injoignable ({type(exc).__name__})") from exc
        if r.status_code >= 400:
            # Jamais la clé ; le corps tronqué sert au diagnostic.
            raise TalApiError(etape, f"HTTP {r.status_code} : {(r.text or '')[:400]}", http_status=r.status_code, corps=(r.text or "")[:2000])
        try:
            return r.json()
        except ValueError as exc:
            raise TalApiError(etape, "réponse non JSON", http_status=r.status_code, corps=(r.text or "")[:2000]) from exc


def pdf_simulation(form: dict[str, Any], short_guid: str) -> bytes:
    """PDF local, une page, marqué partout « SIMULATION » : pour tester le
    parcours complet (archivage, signature, frais) sans appel ni frais."""
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    w, h = LETTER
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(w / 2, h - 72, "SIMULATION — CE N'EST PAS UN BAIL OFFICIEL")
    c.setFont("Helvetica", 10)
    c.drawCentredString(w / 2, h - 92, "Aucun appel au Tribunal administratif du logement n'a été fait. Document non valide, non facturé.")
    y = h - 130
    c.drawString(72, y, f"Référence de simulation : {short_guid}")
    y -= 18
    adresse = ""
    try:
        a = (form.get("adresseLogement") or [{}])[0]
        adresse = a.get("AdresseComplete") or f"{a.get('NoCivique', '')} {a.get('Rue', '')} app. {a.get('Appartement', '')}, {a.get('Municipalite', '')}"
    except Exception:  # noqa: BLE001
        pass
    lignes = [
        f"Logement : {adresse}",
        f"Locateur : {((form.get('locateurs') or [{}])[0] or {}).get('nom', '')}",
        f"Locataire(s) : {', '.join(str((l or {}).get('nom', '')) for l in (form.get('locataires') or []))}",
        f"Type de bail : {form.get('typeBail', '')}  du {form.get('dateDebutBail', '')} au {form.get('dateFinBail', '')}",
        f"Loyer : {form.get('coutLoyer', '')} $ / {form.get('frequenceCoutLoyer', '')}",
        f"Nombre de pièces : {form.get('nbPieces', '')}",
    ]
    for l in lignes:
        c.drawString(72, y, l[:110])
        y -= 16
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(72, 60, "Ce PDF est produit par Kratos en mode simulation. Le vrai bail viendra du TAL, verrouillé et numéroté.")
    for yy in range(80, int(h) - 150, 120):
        c.saveState()
        c.setFont("Helvetica-Bold", 40)
        c.setFillGray(0.85)
        c.drawCentredString(w / 2, yy, "SIMULATION")
        c.restoreState()
    c.showPage()
    c.save()
    return buf.getvalue()


__all__ = [
    "ClientTal",
    "ConnexionTal",
    "TalApiError",
    "ReponseCreation",
    "ReponseTransmission",
    "DocumentTal",
    "ID_TRANSMISSION_PERSO",
    "MODE_SIMULATION",
    "MODE_REEL",
    "MODES",
    "ENTETE_CLE_DEFAUT",
    "CHEMIN_FRW111_DEFAUT",
    "CHEMIN_FRW122_DEFAUT",
    "connexion_depuis_env",
    "etat_configuration",
    "pdf_simulation",
]
