"""Client de l'API FRW du TAL — deux appels, selon la documentation officielle
« APIdocPartenaires » (TAL, 3 nov. 2026) :

1. FRW111 — ``POST {base}/api/v1/SIS/CreerFormulaireIndividu/{typeFormulaire}``
   (typeFormulaire = ``53000BAIL``). Corps : ``{"form": {...}}``, l'objet de
   pré-remplissage, rien d'autre. Réponse : ``{"noPublicSession": "…",
   "noPublicForm": "…", "noTransactionChiffre": null}`` — le numéro public du
   formulaire (le « ShortGuid ») est ``noPublicForm``. Non facturable.
2. FRW122 — ``POST {base}/api/v1/SIS/DeclencherTransmissionPersonnalisee/
   {noPublicFormulaire}/{idTransmissionPerso}`` (idTransmissionPerso =
   « transmission-personnalisee »), SANS corps. Le formulaire devient FACTURABLE
   (2,99 $). Réponse : ``{"documents": [{"nom": "Bail de logement.pdf",
   "fichier": "<base64>", "_type": "genererPDF"}], "messages":
   [{"mnemonique": "TypeFormulaire", "message": "53000BAIL"}]}`` — aucun
   numéro de confirmation.

En-têtes des deux appels : ``X-ClePartenaire`` (la clé de partenaire externe),
``Accept-Language`` (``fr-CA`` ou ``en-CA`` ; au FRW122 c'est la LANGUE DU BAIL
produit) et ``accept: application/json``. Base : ``https://formulaires.mtess.
gouv.qc.ca``. Erreurs 400 / 401 / 403 : ``{type, title, status, detail, instance}``.

Ces valeurs sont les DÉFAUTS de Kratos : il n'y a rien à saisir, sauf la clé.
Elles restent modifiables (Admin locative → Connexion au TAL, ou variables
``TAL_*``) si le TAL les change un jour. Les valeurs d'avant la documentation —
des hypothèses de Kratos (``X-Api-Key``, ``/FRW111/…``, ``/FRW122/…``, corps JSON
au FRW122, « envoi-partenaire ») — sont remplacées d'office, même enregistrées.

Mode ``simulation`` (défaut) : aucun appel réseau ; ShortGuid « SIM-… », PDF local
clairement marqué « SIMULATION — CE N'EST PAS UN BAIL OFFICIEL », message
mnémonique SIMULATION. Le mode réel refuse de partir sans clé, et vers une
adresse qui n'est pas en https. La clé n'apparaît jamais dans les journaux ni
dans les erreurs.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

#: Adresse de base de l'API (documentation du TAL) — la plateforme de formulaires du gouvernement.
URL_DEFAUT = "https://formulaires.mtess.gouv.qc.ca"
#: Valeur imposée du paramètre idTransmissionPerso (documentation du TAL).
ID_TRANSMISSION_PERSO = "transmission-personnalisee"
MODE_SIMULATION = "simulation"
MODE_REEL = "reel"
MODES = (MODE_SIMULATION, MODE_REEL)
TYPE_FORMULAIRE = "53000BAIL"
ENTETE_CLE_DEFAUT = "X-ClePartenaire"
CHEMIN_FRW111_DEFAUT = "/api/v1/SIS/CreerFormulaireIndividu/{typeFormulaire}"
CHEMIN_FRW122_DEFAUT = "/api/v1/SIS/DeclencherTransmissionPersonnalisee/{noPublicFormulaire}/{idTransmissionPerso}"
#: Langue du bail produit : en-tête Accept-Language (fr-CA par défaut).
LANGUES: dict[str, str] = {"fr": "fr-CA", "en": "en-CA"}
LANGUE_DEFAUT = "fr"
VALEURS_OFFICIELLES: dict[str, str] = {
    "api_url": URL_DEFAUT,
    "entete_cle": ENTETE_CLE_DEFAUT,
    "chemin_frw111": CHEMIN_FRW111_DEFAUT,
    "chemin_frw122": CHEMIN_FRW122_DEFAUT,
}
#: Hypothèses de Kratos d'avant la documentation : jamais valides pour cette API.
ANCIENNES_VALEURS: dict[str, tuple[str, ...]] = {
    "entete_cle": ("x-api-key",),
    "chemin_frw111": ("/frw111/creerformulaireindividu",),
    "chemin_frw122": ("/frw122/declenchertransmissionpersonnalisee",),
}
_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


def valeur_officielle(champ: str, valeur: Optional[str]) -> str:
    """La valeur à utiliser pour un réglage de connexion : celle fournie, sauf si elle
    est vide ou si c'est une ancienne hypothèse de Kratos — alors la valeur de la
    documentation du TAL."""
    v = (valeur or "").strip()
    if champ == "api_url":
        v = v.rstrip("/")
    if not v or v.lower() in ANCIENNES_VALEURS.get(champ, ()):
        return VALEURS_OFFICIELLES[champ]
    return v


def code_langue(langue: Optional[str]) -> str:
    """« fr » ou « en » (défaut : fr)."""
    l = (langue or LANGUE_DEFAUT).strip().lower()[:2]
    return l if l in LANGUES else LANGUE_DEFAUT


def _chemin(gabarit: str, **params: str) -> str:
    """Chemin d'un service : remplit ``{typeFormulaire}``, ``{noPublicFormulaire}`` et
    ``{idTransmissionPerso}`` (encodés). Un chemin saisi sans ces repères reçoit les
    valeurs à la suite, dans l'ordre de la documentation."""
    chemin = gabarit.strip()
    if not chemin.startswith("/"):
        chemin = "/" + chemin
    reste: list[str] = []
    for nom, valeur in params.items():
        repere = "{" + nom + "}"
        v = quote(str(valeur), safe="")
        if repere in chemin:
            chemin = chemin.replace(repere, v)
        else:
            reste.append(v)
    if reste:
        chemin = chemin.rstrip("/") + "/" + "/".join(reste)
    return chemin


def _message_erreur(statut: int, texte: str) -> str:
    """Message lisible d'une erreur du TAL : le titre et le détail du format
    ``{type, title, status, detail, instance}`` quand c'est lui, sinon le texte reçu."""
    detail = ""
    try:
        d = json.loads(texte) if texte else None
    except ValueError:
        d = None
    if isinstance(d, dict):
        morceaux = [str(d[k]) for k in ("title", "detail") if d.get(k)]
        erreurs = d.get("errors")
        if isinstance(erreurs, dict):
            for k, v in list(erreurs.items())[:8]:
                morceaux.append(f"{k} : {', '.join(map(str, v)) if isinstance(v, list) else v}")
        detail = " · ".join(morceaux)
    aide = {
        401: "clé refusée par le TAL (vérifie la clé dans Admin locative → Connexion au TAL)",
        403: "accès refusé par le TAL pour cette clé",
        404: "adresse introuvable (vérifie l'adresse de l'API et les chemins)",
    }.get(statut)
    base = f"HTTP {statut}" + (f" — {aide}" if aide else "")
    suite = (detail or texte or "").strip()[:400]
    return f"{base} : {suite}" if suite else base


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
    url: str = URL_DEFAUT
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

    @property
    def adresse_sure(self) -> bool:
        """L'adresse est chiffrée (https) : condition pour y envoyer la clé."""
        return str(self.url or "").strip().lower().startswith("https://")

    @property
    def officielle(self) -> bool:
        """Adresse, en-tête et chemins sont ceux de la documentation du TAL."""
        return (
            (self.url or "").rstrip("/") == URL_DEFAUT and self.entete_cle == ENTETE_CLE_DEFAUT
            and self.chemin_frw111 == CHEMIN_FRW111_DEFAUT and self.chemin_frw122 == CHEMIN_FRW122_DEFAUT
        )

    def etat(self) -> dict[str, Any]:
        """Pour Paramètres : jamais la clé."""
        mode = (self.mode or MODE_SIMULATION).lower()
        return {
            "valeurs_officielles": self.officielle,
            "officiel": dict(VALEURS_OFFICIELLES),
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
        url=valeur_officielle("api_url", getattr(settings, "tal_api_url", None)),
        cle=(getattr(settings, "tal_api_key", None) or "").strip(),
        entete_cle=valeur_officielle("entete_cle", getattr(settings, "tal_api_entete_cle", None)),
        chemin_frw111=valeur_officielle("chemin_frw111", getattr(settings, "tal_api_chemin_frw111", None)),
        chemin_frw122=valeur_officielle("chemin_frw122", getattr(settings, "tal_api_chemin_frw122", None)),
    )


def etat_configuration(connexion: Optional[ConnexionTal] = None) -> dict[str, Any]:
    return (connexion or connexion_depuis_env()).etat()


@dataclass
class ReponseCreation:
    short_guid: str
    brut: Any = None
    duree_ms: int = 0
    #: ``noPublicSession`` du FRW111 (gardé au journal ; pas utilisé par le FRW122 documenté).
    no_public_session: Optional[str] = None


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
    async def creer_formulaire(
        self, form: dict[str, Any], *, langue: Optional[str] = None, identifiant_utilisateur: Optional[str] = None
    ) -> ReponseCreation:
        t0 = time.monotonic()
        if self.simulation:
            return ReponseCreation(short_guid="SIM-" + secrets.token_urlsafe(8), brut={"simulation": True}, duree_ms=1)
        self._exiger_config("FRW111")
        # Corps = l'objet de pré-remplissage, tel quel : {"form": {...}}. Le type de
        # formulaire est dans l'adresse ; aucun identifiant de suivi n'est documenté
        # (``identifiant_utilisateur`` reste dans Kratos, il n'est pas envoyé).
        payload: dict[str, Any] = {"form": form}
        chemin = _chemin(self.cx.chemin_frw111, typeFormulaire=TYPE_FORMULAIRE)
        corps = await self._post("FRW111", chemin, payload, langue=langue)
        short_guid = _extraire(corps, "noPublicForm", "noPublicFormulaire", "shortGuid", "numeroPublic", "id")
        if not short_guid:
            raise TalApiError("FRW111", "réponse sans numéro public de formulaire (noPublicForm)", corps=corps)
        session = _extraire(corps, "noPublicSession")
        return ReponseCreation(
            short_guid=str(short_guid), brut=corps, duree_ms=int((time.monotonic() - t0) * 1000),
            no_public_session=(str(session) if session else None),
        )

    # ── FRW122 ──────────────────────────────────────────────────────
    async def declencher_transmission(
        self, short_guid: str, *, langue: Optional[str] = None, identifiant_utilisateur: Optional[str] = None,
        form_pour_simulation: Optional[dict[str, Any]] = None,
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
        # Tout est dans l'adresse ; l'appel n'a pas de corps. La langue demandée ici est
        # celle du bail produit.
        chemin = _chemin(self.cx.chemin_frw122, noPublicFormulaire=short_guid, idTransmissionPerso=ID_TRANSMISSION_PERSO)
        corps = await self._post("FRW122", chemin, None, langue=langue)
        docs_brut = _extraire(corps, "documents") or []
        documents: list[DocumentTal] = []
        for d in docs_brut if isinstance(docs_brut, list) else []:
            if not isinstance(d, dict):
                continue
            b64 = _extraire(d, "fluxFichier", "flux", "contenu", "fichier", "base64", "contenuBase64", "data")
            if not b64:
                continue
            type_source = _extraire(d, "_type", "typeSource", "type", "source")
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
            raise TalApiError(etape, "Clé de l'API du TAL non enregistrée (Admin locative → Connexion au TAL) : mode réel impossible.")
        if not self.cx.adresse_sure:
            # Aussi pour une adresse posée hors de l'écran (variable d'environnement, ancienne valeur).
            raise TalApiError(etape, "L'adresse de l'API du TAL doit commencer par https:// : aucun appel n'est fait, la clé ne voyage jamais en clair.")

    async def _post(self, etape: str, chemin: str, payload: Optional[dict[str, Any]], *, langue: Optional[str] = None) -> Any:
        url = self.cx.url.rstrip("/") + (chemin if chemin.startswith("/") else "/" + chemin)
        headers = {self.cx.entete_cle: self.cx.cle, "Accept": "application/json", "Accept-Language": LANGUES[code_langue(langue)]}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                if payload is None:
                    r = await client.post(url, headers=headers, content=b"")
                else:
                    r = await client.post(url, json=payload, headers={**headers, "Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            raise TalApiError(etape, f"TAL injoignable ({type(exc).__name__})") from exc
        # Jamais la clé : si le TAL la renvoyait dans son message, elle est masquée
        # avant que le texte ne parte vers l'écran, le journal ou l'audit.
        texte = r.text or ""
        if self.cx.cle and len(self.cx.cle) >= 6:
            texte = texte.replace(self.cx.cle, "***")
        if r.status_code >= 400:
            raise TalApiError(etape, _message_erreur(r.status_code, texte), http_status=r.status_code, corps=texte[:2000])
        try:
            return r.json()
        except ValueError as exc:
            raise TalApiError(etape, "réponse non JSON", http_status=r.status_code, corps=texte[:2000]) from exc


def pdf_simulation(form: dict[str, Any], short_guid: str) -> bytes:
    """PDF local marqué partout « SIMULATION », au gabarit du bail officiel : quatre pages
    612 × 1008, lignes de signature et cases d'initiales aux mêmes endroits que sur le
    formulaire du TAL. Le parcours complet se teste sans appel ni frais, signature en
    ligne comprise (les zones se posent comme sur un vrai bail)."""
    from reportlab.pdfgen import canvas

    from app.integrations.tal.gabarit_signature import GABARIT, HAUTEUR, LARGEUR, PAGES_FORMULAIRE

    titres = {
        "fumee": "Avertisseurs de fumée", "cheques": "Chèques postdatés", "reglement": "Règlement de l'immeuble",
        "copropriete": "Copropriété divise", "avis": "G · Avis au nouveau locataire", "signatures": "H · Signatures des parties",
        "solidaire": "Engagement solidaire", "autre": "Autres signataires", "famille": "I · Avis de résidence familiale",
    }
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(LARGEUR, HAUTEUR))
    w, h = LARGEUR, HAUTEUR
    for page in range(1, PAGES_FORMULAIRE + 1):
        for yy in range(140, int(h) - 150, 150):
            c.saveState()
            c.setFont("Helvetica-Bold", 40)
            c.setFillGray(0.88)
            c.drawCentredString(w / 2, yy, "SIMULATION")
            c.restoreState()
        c.setFont("Helvetica-Bold", 15 if page == 1 else 10)
        c.drawCentredString(w / 2, h - 60, "SIMULATION — CE N'EST PAS UN BAIL OFFICIEL")
        c.setFont("Helvetica", 9)
        c.drawCentredString(w / 2, h - 76, "Aucun appel au Tribunal administratif du logement n'a été fait. Document non valide, non facturé.")
        if page == 1:
            y = h - 112
            c.setFont("Helvetica", 10)
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
            c.drawString(72, y - 6, "Ce PDF est produit par Kratos en mode simulation. Le vrai bail viendra du TAL, verrouillé et numéroté.")
        # Lignes et libellés du gabarit officiel : mêmes positions que sur le formulaire du TAL.
        vus: set[str] = set()
        for zone in GABARIT:
            if zone.page != page:
                continue
            ligne = h - zone.ligne_y
            c.setStrokeGray(0.25)
            c.setLineWidth(0.5)
            c.line(zone.x - 2, ligne, zone.x + zone.w + 2, ligne)
            c.setFillGray(0.15)
            c.setFont("Helvetica", 6)
            c.drawString(zone.x - 2, ligne - 8, zone.libelle)
            if zone.cle in titres and zone.cle not in vus:
                vus.add(zone.cle)
                c.setFont("Helvetica-Bold", 7)
                if zone.x >= 150:
                    c.drawString(36, ligne + 2, titres[zone.cle])
                else:
                    c.drawString(36, h - zone.y + 4, titres[zone.cle])
        c.setFillGray(0)
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
