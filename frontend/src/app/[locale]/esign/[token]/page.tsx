"use client";

/* eSign — page PUBLIQUE de signature (lien envoyé par courriel).

   Étapes :
   1. (si exigé) vérification d'identité par code SMS ;
   2. lecture du document (pages rendues en PNG, zones surlignées) ;
   3. signature GUIDÉE (Phil 2026-11-13, « comme Authentisign ») : chaque
      endroit à signer se clique ; le premier ouvre le tracé (dessiné ou
      tapé, encre foncée), les suivants s'apposent d'un clic, et la page
      amène au prochain endroit. Texte et cases se remplissent sur place ;
   4. consentement + signature, ou refus motivé.

   Page volontairement claire (document blanc, encre foncée) et
   autonome — aucun thème du portail interne ici. */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { useParams } from "next/navigation";
import {
  CheckCircle2,
  Download,
  Loader2,
  Paperclip,
  PenLine,
  RotateCcw,
  ShieldCheck,
  XCircle
} from "lucide-react";

type FieldT = {
  id: number;
  signer_id: number;
  mine: boolean;
  signer_name: string;
  signer_signed: boolean;
  kind: string;
  page: number;
  x: number;
  y: number;
  w: number;
  h: number;
  required: boolean;
  label: string | null;
  value_text: string | null;
};

type SignerSummary = {
  name: string;
  is_me: boolean;
  signed_at: string | null;
  declined: boolean;
};

type AttachmentT = {
  id: number;
  filename: string;
  size_bytes: number;
};

type Info = {
  title: string;
  status: string;
  page_count: number;
  entreprise_name: string | null;
  message: string | null;
  expires_at: string | null;
  attachments: AttachmentT[];
  signer_first_name: string;
  signer_last_name: string;
  signer_email: string;
  already_signed: boolean;
  already_declined: boolean;
  is_my_turn: boolean;
  sms_required: boolean;
  sms_verified: boolean;
  phone_masked: string | null;
  fields: FieldT[];
  signers: SignerSummary[];
  completed: boolean;
};

const KIND_LABEL: Record<string, string> = {
  signature: "Signature",
  initiales: "Initiales",
  date: "Date (automatique)",
  texte: "Texte",
  case: "Case à cocher"
};

/* ------------------- Pad de signature (encre foncée) ------------------- */

function InkPad({
  label,
  onChange,
  lecteur
}: {
  label: string;
  onChange: (dataUrl: string | null) => void;
  /** Reçoit une fonction qui relit le tracé À L'INSTANT (au clic sur
   *  « Signer ») : la signature ne dépend plus d'un événement de fin de
   *  trait, qui se perdait sur iPhone (retour Phil 2026-11-13 : « quand
   *  il pèse, ça fait rien »). */
  lecteur?: React.MutableRefObject<(() => string | null) | null>;
}) {
  const [mode, setMode] = useState<"draw" | "type">("draw");
  const [typed, setTyped] = useState("");
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const drawing = useRef(false);
  const last = useRef<{ x: number; y: number } | null>(null);
  const [empty, setEmpty] = useState(true);
  // Vérité synchrone sur « le pad contient un tracé » — l'état React
  // peut être en retard d'un rendu quand un trait rapide se termine
  // (mobile), ce qui faisait rater l'enregistrement dans up().
  const emptyRef = useRef(true);
  // Largeur au dernier setup : sur mobile, scroller (barre d'adresse)
  // ou ouvrir le clavier déclenche un resize de HAUTEUR seulement —
  // il ne doit JAMAIS effacer la signature en cours.
  const lastWidthRef = useRef(0);
  // Dernier tracé enregistré (dessiné ou tapé), pour le relire à la demande.
  const dernierRef = useRef<string | null>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;

  function publier(url: string | null) {
    dernierRef.current = url;
    onChange(url);
  }

  useEffect(() => {
    if (!lecteur) return;
    lecteur.current = () => {
      if (modeRef.current === "draw") {
        const c = canvasRef.current;
        if (c && !emptyRef.current && c.width > 0) {
          try {
            return c.toDataURL("image/png");
          } catch {
            return dernierRef.current;
          }
        }
        return null;
      }
      return dernierRef.current;
    };
    return () => {
      lecteur.current = null;
    };
  }, [lecteur]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;

    function setup(preserveDataUrl: string | null) {
      if (!canvas || !parent) return;
      const dpr = window.devicePixelRatio || 1;
      const w = parent.clientWidth;
      const h = 160;
      lastWidthRef.current = w;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      const ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.scale(dpr, dpr);
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.lineWidth = 2.2;
        ctx.strokeStyle = "#1e3a8a"; // encre bleu foncé, lisible sur blanc
      }
      if (preserveDataUrl && ctx) {
        // Rotation / vraie variation de largeur : on redessine le
        // tracé existant au lieu de le perdre.
        const img = new Image();
        img.onload = () => {
          ctx.drawImage(img, 0, 0, w, h);
        };
        img.src = preserveDataUrl;
      } else {
        emptyRef.current = true;
        setEmpty(true);
        publier(null);
      }
    }

    setup(null);

    function onResize() {
      if (!canvas || !parent) return;
      const w = parent.clientWidth;
      // Resize de hauteur seule (barre d'adresse mobile, clavier
      // virtuel) → on ne touche à rien.
      if (Math.abs(w - lastWidthRef.current) < 2) return;
      const preserve =
        !emptyRef.current && canvas.width > 0
          ? canvas.toDataURL("image/png")
          : null;
      setup(preserve);
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  function pt(e: React.PointerEvent<HTMLCanvasElement>) {
    const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function down(e: React.PointerEvent<HTMLCanvasElement>) {
    e.preventDefault();
    try {
      canvasRef.current?.setPointerCapture(e.pointerId);
    } catch {
      /* capture refusée par le navigateur : le tracé continue sans elle */
    }
    drawing.current = true;
    last.current = pt(e);
  }
  function move(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return;
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx || !last.current) return;
    const p = pt(e);
    ctx.beginPath();
    ctx.moveTo(last.current.x, last.current.y);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    last.current = p;
    if (emptyRef.current) {
      emptyRef.current = false;
      setEmpty(false);
    }
  }
  function up(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return;
    drawing.current = false;
    last.current = null;
    // Le tracé s'enregistre D'ABORD : sur iPhone, relâcher la capture du
    // pointeur peut lever une erreur, et tout ce qui suivait était perdu
    // (le dessin restait à l'écran, mais « signature requise »).
    const canvas = canvasRef.current;
    if (canvas && !emptyRef.current) {
      try {
        publier(canvas.toDataURL("image/png"));
      } catch {
        /* relu au moment de signer (lecteur) */
      }
    }
    try {
      canvasRef.current?.releasePointerCapture(e.pointerId);
    } catch {
      /* capture déjà relâchée par le navigateur */
    }
  }

  function clear() {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    emptyRef.current = true;
    setEmpty(true);
    publier(null);
  }

  function applyTyped(value: string) {
    setTyped(value);
    const text = value.trim();
    if (!text) {
      publier(null);
      return;
    }
    const c = document.createElement("canvas");
    const scale = 2;
    c.width = 560 * scale;
    c.height = 140 * scale;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.scale(scale, scale);
    ctx.fillStyle = "#1e3a8a";
    ctx.font = "italic 44px 'Brush Script MT', 'Segoe Script', cursive";
    ctx.textBaseline = "middle";
    let size = 44;
    while (size > 16 && ctx.measureText(text).width > 540) {
      size -= 2;
      ctx.font = `italic ${size}px 'Brush Script MT', 'Segoe Script', cursive`;
    }
    ctx.fillText(text, 10, 70);
    publier(c.toDataURL("image/png"));
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-800">{label}</p>
        <div className="flex gap-1">
          {(
            [
              ["draw", "Dessiner"],
              ["type", "Taper"]
            ] as const
          ).map(([key, lbl]) => (
            <button
              key={key}
              type="button"
              onClick={() => {
                setMode(key);
                setTyped("");
                publier(null);
              }}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                mode === key
                  ? "bg-blue-700 text-white"
                  : "bg-slate-200 text-slate-700 hover:bg-slate-300"
              }`}
            >
              {lbl}
            </button>
          ))}
        </div>
      </div>

      {mode === "draw" ? (
        <>
          <div className="relative overflow-hidden rounded-lg border-2 border-dashed border-slate-300 bg-white">
            <canvas
              ref={canvasRef}
              onPointerDown={down}
              onPointerMove={move}
              onPointerUp={up}
              onPointerCancel={up}
              className="block w-full touch-none"
              aria-label={label}
            />
            {empty ? (
              <p className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-slate-400">
                Signez avec le doigt ou la souris
              </p>
            ) : null}
          </div>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={clear}
              className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1 text-[11px] text-slate-700 hover:bg-slate-100"
            >
              <RotateCcw className="h-3 w-3" /> Effacer
            </button>
          </div>
        </>
      ) : (
        <div className="rounded-lg border-2 border-dashed border-slate-300 bg-white p-3">
          <input
            value={typed}
            onChange={(e) => applyTyped(e.target.value)}
            placeholder="Tapez votre nom…"
            className="w-full border-0 bg-transparent text-center text-2xl italic text-blue-900 outline-none"
            style={{
              fontFamily: "'Brush Script MT', 'Segoe Script', cursive"
            }}
          />
        </div>
      )}
    </div>
  );
}

/* Aperçu du tracé adopté, avec la possibilité de le refaire. */
function ApercuTrace({
  titre,
  url,
  onModifier
}: {
  titre: string;
  url: string;
  onModifier: () => void;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div>
        <p className="text-[11px] font-medium text-slate-500">{titre}</p>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url} alt={titre} className="mt-0.5 h-10 w-36 object-contain object-left" />
      </div>
      <button
        type="button"
        onClick={onModifier}
        className="rounded-md border border-slate-300 px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100"
      >
        Modifier
      </button>
    </div>
  );
}

/* ============================== Page ============================== */

export default function PublicEsignPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const base = `/api/v1/public/esign/${token}`;

  const [info, setInfo] = useState<Info | null>(null);
  const [loading, setLoading] = useState(true);
  const [fatal, setFatal] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // SMS
  const [smsSent, setSmsSent] = useState(false);
  const [smsCode, setSmsCode] = useState("");
  const [smsBusy, setSmsBusy] = useState(false);

  // Remplissage
  const [textValues, setTextValues] = useState<Record<number, string>>({});
  const [signatureUrl, setSignatureUrl] = useState<string | null>(null);
  const [initialsUrl, setInitialsUrl] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [signBusy, setSignBusy] = useState(false);
  const [declineOpen, setDeclineOpen] = useState(false);
  const [declineReason, setDeclineReason] = useState("");

  const finRef = useRef<HTMLDivElement | null>(null);
  // Signature guidée : endroits déjà apposés, endroit en cours, fenêtre du tracé.
  const [faits, setFaits] = useState<Set<number>>(new Set());
  const [courant, setCourant] = useState<number | null>(null);
  const [pad, setPad] = useState<{
    kind: "signature" | "initiales";
    /** Endroit à apposer une fois le tracé adopté ; null = simple changement de tracé. */
    fieldId: number | null;
  } | null>(null);
  const [padErr, setPadErr] = useState<string | null>(null);
  // Relecture directe du tracé au moment de l'adopter (ne dépend d'aucun événement de fin de trait).
  const lirePad = useRef<(() => string | null) | null>(null);
  const zones = useRef<Map<number, HTMLElement>>(new Map());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(base, { cache: "no-store" });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setFatal(
          typeof body?.detail === "string"
            ? body.detail
            : "Lien invalide ou expiré."
        );
        return;
      }
      const data = (await res.json()) as Info;
      setInfo(data);
      const tv: Record<number, string> = {};
      data.fields
        .filter((f) => f.mine && (f.kind === "texte" || f.kind === "case"))
        .forEach((f) => {
          tv[f.id] = f.value_text || "";
        });
      setTextValues(tv);
    } catch {
      setFatal("Chargement impossible — vérifiez votre connexion.");
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    void load();
  }, [load]);

  const myFields = useMemo(
    () => (info ? info.fields.filter((f) => f.mine) : []),
    [info]
  );
  // Mes endroits à remplir, dans l'ordre de lecture du document. Les dates se posent seules.
  const etapes = useMemo(
    () =>
      myFields
        .filter((f) => f.kind !== "date")
        .sort((a, b) => a.page - b.page || a.y - b.y || a.x - b.x),
    [myFields]
  );
  const estFait = (f: FieldT): boolean => {
    if (f.kind === "signature" || f.kind === "initiales") return faits.has(f.id);
    if (f.kind === "texte") return !!textValues[f.id]?.trim();
    if (f.kind === "case") return textValues[f.id] === "oui";
    return true;
  };
  const obligatoires = etapes.filter((f) => f.required);
  const restants = obligatoires.filter((f) => !estFait(f));
  const prochain = restants[0] ?? null;
  const nbFaits = obligatoires.length - restants.length;

  function retenirZone(id: number, el: HTMLElement | null) {
    if (el) zones.current.set(id, el);
    else zones.current.delete(id);
  }

  /** Amène à un endroit du document ; null = la dernière étape (consentement). */
  function allerA(f: FieldT | null) {
    if (!f) {
      setCourant(null);
      finRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    setCourant(f.id);
    zones.current.get(f.id)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  /** L'endroit ``id`` vient d'être rempli : au prochain endroit obligatoire encore vide. */
  function auSuivant(id: number) {
    allerA(obligatoires.find((f) => f.id !== id && !estFait(f)) ?? null);
  }

  /** Clic sur un endroit (ou sur le bouton du bas) : on le remplit. */
  function apposer(f: FieldT) {
    setError(null);
    if (f.kind === "signature" || f.kind === "initiales") {
      const url = f.kind === "signature" ? signatureUrl : initialsUrl;
      if (!url) {
        // Première fois : on trace (ou on tape), puis ça s'appose ici.
        setCourant(f.id);
        setPadErr(null);
        setPad({ kind: f.kind, fieldId: f.id });
        return;
      }
      setFaits((prev) => new Set(prev).add(f.id));
      auSuivant(f.id);
      return;
    }
    if (f.kind === "case") {
      const coche = textValues[f.id] === "oui";
      setTextValues((prev) => ({ ...prev, [f.id]: coche ? "" : "oui" }));
      if (!coche) auSuivant(f.id);
      else setCourant(f.id);
      return;
    }
    // Texte : le curseur va dans le champ.
    setCourant(f.id);
    const el = zones.current.get(f.id);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    (el as HTMLInputElement | undefined)?.focus?.({ preventScroll: true });
  }

  /** « Adopter » dans la fenêtre du tracé. */
  function adopter() {
    if (!pad) return;
    const url = lirePad.current?.() ?? null;
    if (!url) {
      setPadErr(
        pad.kind === "signature"
          ? "Tracez votre signature avec le doigt ou la souris, ou tapez votre nom."
          : "Tracez vos initiales avec le doigt ou la souris, ou tapez-les."
      );
      return;
    }
    if (pad.kind === "signature") setSignatureUrl(url);
    else setInitialsUrl(url);
    const id = pad.fieldId;
    setPad(null);
    if (id != null) {
      setFaits((prev) => new Set(prev).add(id));
      auSuivant(id);
    }
  }

  async function sendSms() {
    setSmsBusy(true);
    setError(null);
    try {
      const res = await fetch(`${base}/sms/send`, { method: "POST" });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setError(
          typeof body?.detail === "string"
            ? body.detail
            : "Envoi du code échoué."
        );
        return;
      }
      setSmsSent(true);
    } finally {
      setSmsBusy(false);
    }
  }

  async function verifySms(e: React.FormEvent) {
    e.preventDefault();
    setSmsBusy(true);
    setError(null);
    try {
      const res = await fetch(`${base}/sms/verify`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code: smsCode })
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setError(
          typeof body?.detail === "string" ? body.detail : "Code incorrect."
        );
        return;
      }
      setInfo(body as Info);
    } finally {
      setSmsBusy(false);
    }
  }

  async function submitSign() {
    if (!info) return;
    setError(null);
    if (restants.length > 0) {
      setError(
        `Il reste ${restants.length} endroit${restants.length > 1 ? "s" : ""} à remplir dans le document. Le bouton du bas de l'écran vous y amène.`
      );
      allerA(restants[0]);
      return;
    }
    if (!consent) {
      setError("Cochez la case de consentement pour signer.");
      finRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    const signature = signatureUrl;
    const initiales = initialsUrl;
    // Endroits FACULTATIFS laissés vides : ils ne reçoivent ni signature ni initiales.
    const sautes = etapes
      .filter(
        (f) =>
          !f.required &&
          (f.kind === "signature" || f.kind === "initiales") &&
          !faits.has(f.id)
      )
      .map((f) => f.id);
    setSignBusy(true);
    try {
      const res = await fetch(`${base}/sign`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          signature_data_url: signature,
          initials_data_url: initiales,
          text_values: Object.entries(textValues).map(([id, value]) => ({
            field_id: Number(id),
            value
          })),
          skipped_field_ids: sautes,
          consent: true
        })
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setError(
          typeof body?.detail === "string"
            ? body.detail
            : "Signature échouée — réessayez."
        );
        return;
      }
      setInfo(body as Info);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setSignBusy(false);
    }
  }

  async function submitDecline() {
    setSignBusy(true);
    setError(null);
    try {
      const res = await fetch(`${base}/decline`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ reason: declineReason })
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setError(
          typeof body?.detail === "string" ? body.detail : "Refus échoué."
        );
        return;
      }
      setInfo(body as Info);
      setDeclineOpen(false);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setSignBusy(false);
    }
  }

  /* --------------------------- Rendus --------------------------- */

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-100">
        <Loader2 className="h-6 w-6 animate-spin text-blue-700" />
      </main>
    );
  }

  if (fatal || !info) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-100 p-4">
        <div className="w-full max-w-md rounded-2xl bg-white p-8 text-center shadow">
          <XCircle className="mx-auto h-10 w-10 text-rose-500" />
          <h1 className="mt-4 text-lg font-semibold text-slate-900">
            Lien non disponible
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            {fatal || "Lien invalide ou expiré."}
          </p>
        </div>
      </main>
    );
  }

  const smsGate = info.sms_required && !info.sms_verified;
  const canSign =
    !info.already_signed &&
    !info.already_declined &&
    info.status === "envoye" &&
    info.is_my_turn &&
    !smsGate;
  const aujourdHui = new Date().toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });
  const libelleEtape = (f: FieldT): string =>
    `${KIND_LABEL[f.kind] || f.kind} · page ${f.page}`;
  const actionEtape = (f: FieldT): string =>
    f.kind === "signature"
      ? "Signer ici"
      : f.kind === "initiales"
        ? "Apposer mes initiales"
        : f.kind === "case"
          ? "Cocher la case"
          : "Remplir le champ";

  return (
    <main className="min-h-screen bg-slate-100 pb-40">
      {/* Bandeau */}
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-2 px-4 py-4">
          <div className="min-w-0">
            <h1 className="truncate text-base font-semibold text-slate-900">
              {info.title}
            </h1>
            <p className="text-xs text-slate-500">
              {info.entreprise_name
                ? `${info.entreprise_name} · `
                : ""}
              Pour : {info.signer_first_name} {info.signer_last_name} (
              {info.signer_email})
            </p>
          </div>
          {info.completed ? (
            <a
              href={`${base}/signed-pdf`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700"
            >
              <Download className="h-3.5 w-3.5" />
              Télécharger le document signé
            </a>
          ) : (
            <a
              href={`${base}/pdf`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs font-medium text-blue-700 hover:underline"
            >
              Ouvrir le PDF dans un onglet →
            </a>
          )}
        </div>
      </header>

      <div className="mx-auto max-w-4xl space-y-4 px-4 py-6">
        {/* Statuts */}
        {info.already_signed ? (
          <div className="flex items-start gap-3 rounded-xl border border-emerald-300 bg-emerald-50 p-4">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
            <div>
              <p className="text-sm font-semibold text-emerald-800">
                Merci, votre signature a bien été enregistrée.
              </p>
              <p className="mt-1 text-xs text-emerald-700">
                {info.completed
                  ? "Toutes les parties ont signé — la version finale vous a été envoyée par courriel."
                  : "Les autres parties doivent encore signer. Vous recevrez la version finale par courriel une fois le document complété."}
              </p>
            </div>
          </div>
        ) : null}
        {info.already_declined ? (
          <div className="flex items-start gap-3 rounded-xl border border-rose-300 bg-rose-50 p-4">
            <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
            <p className="text-sm font-semibold text-rose-800">
              Vous avez refusé de signer ce document. L&apos;émetteur en a
              été informé.
            </p>
          </div>
        ) : null}
        {!info.is_my_turn &&
        !info.already_signed &&
        !info.already_declined &&
        info.status === "envoye" ? (
          <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-800">
            Ce document se signe dans un ordre précis — ce n&apos;est pas
            encore votre tour. Vous recevrez un courriel quand ce sera à
            vous.
          </div>
        ) : null}

        {info.message && !info.already_signed && !info.already_declined ? (
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="whitespace-pre-line text-sm text-slate-700">
              {info.message}
            </p>
          </div>
        ) : null}

        {info.expires_at && canSign ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-800">
            ⏳ Ce lien de signature expire le{" "}
            {new Date(info.expires_at).toLocaleDateString("fr-CA", {
              day: "numeric",
              month: "long",
              year: "numeric"
            })}
            .
          </div>
        ) : null}

        {info.attachments.length > 0 ? (
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Annexes consultables
            </p>
            <ul className="space-y-1.5">
              {info.attachments.map((a) => (
                <li key={a.id}>
                  <a
                    href={`${base}/attachments/${a.id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-700 hover:underline"
                  >
                    <Paperclip className="h-3.5 w-3.5" />
                    {a.filename}
                    <span className="text-xs font-normal text-slate-400">
                      ({(a.size_bytes / 1024 / 1024).toFixed(1)} Mo)
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {/* Progression des signataires */}
        {info.signers.length > 1 ? (
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Signataires
            </p>
            <div className="flex flex-wrap gap-2">
              {info.signers.map((s, i) => (
                <span
                  key={i}
                  className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
                    s.declined
                      ? "bg-rose-100 text-rose-800"
                      : s.signed_at
                      ? "bg-emerald-100 text-emerald-800"
                      : "bg-slate-200 text-slate-700"
                  }`}
                >
                  {s.declined ? (
                    <XCircle className="h-3 w-3" />
                  ) : s.signed_at ? (
                    <CheckCircle2 className="h-3 w-3" />
                  ) : (
                    <PenLine className="h-3 w-3" />
                  )}
                  {s.name}
                  {s.is_me ? " (vous)" : ""}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {/* Vérification SMS */}
        {smsGate && !info.already_signed && !info.already_declined ? (
          <div className="rounded-xl border border-blue-200 bg-white p-5">
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-6 w-6 shrink-0 text-blue-700" />
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-semibold text-slate-900">
                  Vérification d&apos;identité requise
                </h2>
                <p className="mt-1 text-xs text-slate-600">
                  Pour signer ce document, saisissez le code de validation
                  envoyé par SMS au {info.phone_masked || "numéro au dossier"}.
                </p>
                {!smsSent ? (
                  <button
                    type="button"
                    onClick={() => void sendSms()}
                    disabled={smsBusy}
                    className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-blue-700 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-800 disabled:opacity-50"
                  >
                    {smsBusy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : null}
                    Recevoir mon code par SMS
                  </button>
                ) : (
                  <form
                    onSubmit={verifySms}
                    className="mt-3 flex flex-wrap items-center gap-2"
                  >
                    <input
                      value={smsCode}
                      onChange={(e) =>
                        setSmsCode(e.target.value.replace(/\D/g, ""))
                      }
                      inputMode="numeric"
                      maxLength={6}
                      placeholder="123456"
                      className="w-32 rounded-lg border border-slate-300 px-3 py-2 text-center text-lg tracking-[0.3em] text-slate-900 outline-none focus:border-blue-600"
                      autoFocus
                    />
                    <button
                      type="submit"
                      disabled={smsBusy || smsCode.length < 4}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-blue-700 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-800 disabled:opacity-50"
                    >
                      {smsBusy ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : null}
                      Vérifier
                    </button>
                    <button
                      type="button"
                      onClick={() => void sendSms()}
                      disabled={smsBusy}
                      className="text-xs text-blue-700 hover:underline"
                    >
                      Renvoyer le code
                    </button>
                  </form>
                )}
              </div>
            </div>
          </div>
        ) : null}

        {error ? (
          <div className="rounded-xl border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        ) : null}

        {canSign && obligatoires.length > 0 ? (
          <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm">
            <p className="font-semibold text-slate-900">
              {obligatoires.length} endroit{obligatoires.length > 1 ? "s" : ""} à remplir dans ce document.
            </p>
            <p className="mt-0.5 text-xs text-blue-800">
              Appuyez sur le bouton bleu, en bas de l&apos;écran : la page vous amène à chaque endroit, l&apos;un après
              l&apos;autre. Vous tracez votre signature et vos initiales une seule fois ; ensuite un clic suffit.
            </p>
          </div>
        ) : null}

        {/* Pages du document */}
        {Array.from({ length: info.page_count }, (_, i) => i + 1).map(
          (p) => (
            <div
              key={p}
              className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
            >
              <div className="border-b border-slate-100 px-3 py-1.5 text-[10px] uppercase tracking-wider text-slate-400">
                Page {p} / {info.page_count}
              </div>
              <div className="relative w-full bg-white">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`${base}/pages/${p}`}
                  alt={`Page ${p}`}
                  className="block w-full"
                  draggable={false}
                />
                {info.fields
                  .filter((f) => f.page === p)
                  .map((f) => {
                    const mine = f.mine;
                    const color = mine ? "#1d4ed8" : "#94a3b8";
                    const style: React.CSSProperties = {
                      left: `${f.x * 100}%`,
                      top: `${f.y * 100}%`,
                      width: `${f.w * 100}%`,
                      height: `${f.h * 100}%`,
                      borderColor: color
                    };
                    // Zone texte remplissable inline
                    if (mine && canSign && f.kind === "texte") {
                      return (
                        <input
                          key={f.id}
                          ref={(el) => retenirZone(f.id, el)}
                          onFocus={() => setCourant(f.id)}
                          value={textValues[f.id] || ""}
                          onChange={(e) =>
                            setTextValues((prev) => ({
                              ...prev,
                              [f.id]: e.target.value
                            }))
                          }
                          placeholder={f.label || "Texte…"}
                          className={`absolute rounded border-2 bg-blue-50/80 px-1 text-[11px] text-slate-900 outline-none placeholder:text-slate-400 focus:bg-white ${
                            courant === f.id ? "z-10 ring-4 ring-blue-500/60" : ""
                          }`}
                          style={style}
                        />
                      );
                    }
                    if (mine && canSign && f.kind === "case") {
                      const checked = textValues[f.id] === "oui";
                      return (
                        <button
                          key={f.id}
                          type="button"
                          ref={(el) => retenirZone(f.id, el)}
                          onClick={() => apposer(f)}
                          title={f.label || "Case à cocher"}
                          className={`absolute flex items-center justify-center rounded border-2 bg-blue-50/80 text-blue-800 ${
                            courant === f.id && !checked ? "z-10 ring-4 ring-blue-500/60" : ""
                          }`}
                          style={style}
                        >
                          {checked ? "✕" : ""}
                        </button>
                      );
                    }
                    if (
                      mine &&
                      canSign &&
                      (f.kind === "signature" || f.kind === "initiales")
                    ) {
                      const url =
                        f.kind === "signature" ? signatureUrl : initialsUrl;
                      const fait = faits.has(f.id) && !!url;
                      const actif = courant === f.id && !fait;
                      return (
                        <button
                          key={f.id}
                          type="button"
                          ref={(el) => retenirZone(f.id, el)}
                          onClick={() => apposer(f)}
                          className={`absolute rounded border-2 ${
                            fait
                              ? "border-solid bg-white/50"
                              : "border-dashed bg-amber-100/90"
                          } ${actif ? "z-10 ring-4 ring-blue-500/70" : ""}`}
                          style={{
                            ...style,
                            borderColor: fait
                              ? "#059669"
                              : actif
                                ? "#1d4ed8"
                                : "#d97706"
                          }}
                          title={
                            fait
                              ? `${KIND_LABEL[f.kind]} apposée`
                              : f.kind === "signature"
                                ? "Cliquez pour signer ici"
                                : "Cliquez pour apposer vos initiales"
                          }
                        >
                          {fait && url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={url}
                              alt={KIND_LABEL[f.kind]}
                              className="h-full w-full object-contain object-left-bottom"
                            />
                          ) : (
                            <span className="flex h-full items-center justify-center whitespace-nowrap px-0.5 text-[8px] font-bold leading-none text-amber-800 sm:text-[10px]">
                              {f.kind === "signature"
                                ? "✍ Signer ici"
                                : "Initiales"}
                            </span>
                          )}
                        </button>
                      );
                    }
                    // Zones en lecture seule (les miennes déjà signées,
                    // celles des autres, dates automatiques…)
                    return (
                      <div
                        key={f.id}
                        className="absolute flex items-center overflow-hidden rounded border px-1"
                        style={{
                          ...style,
                          backgroundColor: mine
                            ? "rgba(29,78,216,0.08)"
                            : "rgba(148,163,184,0.12)"
                        }}
                        title={`${KIND_LABEL[f.kind] || f.kind} — ${f.signer_name}`}
                      >
                        <span
                          className="truncate text-[10px] font-medium"
                          style={{ color: mine ? "#1e3a8a" : "#475569" }}
                        >
                          {f.value_text ||
                            (f.signer_signed &&
                            (f.kind === "signature" ||
                              f.kind === "initiales")
                              ? "✓ Signé"
                              : f.kind === "date"
                              ? mine && canSign
                                ? aujourdHui
                                : "Date automatique"
                              : `${KIND_LABEL[f.kind] || f.kind} · ${
                                  f.signer_name
                                }`)}
                        </span>
                      </div>
                    );
                  })}
              </div>
            </div>
          )
        )}

        {/* Dernière étape : consentement et signature */}
        {canSign ? (
          <div
            ref={finRef}
            className="space-y-4 rounded-xl border border-slate-200 bg-white p-5"
          >
            <div>
              <h2 className="text-sm font-semibold text-slate-900">
                Dernière étape
              </h2>
              <p className="mt-1 text-xs text-slate-600">
                {restants.length > 0
                  ? `Il reste ${restants.length} endroit${
                      restants.length > 1 ? "s" : ""
                    } à remplir dans le document. Le bouton bleu, en bas de l'écran, vous y amène.`
                  : "Tout est rempli. Confirmez pour signer le document."}
              </p>
            </div>
            {signatureUrl || initialsUrl ? (
              <div className="flex flex-wrap gap-3">
                {signatureUrl ? (
                  <ApercuTrace
                    titre="Votre signature"
                    url={signatureUrl}
                    onModifier={() => {
                      setPadErr(null);
                      setPad({ kind: "signature", fieldId: null });
                    }}
                  />
                ) : null}
                {initialsUrl ? (
                  <ApercuTrace
                    titre="Vos initiales"
                    url={initialsUrl}
                    onModifier={() => {
                      setPadErr(null);
                      setPad({ kind: "initiales", fieldId: null });
                    }}
                  />
                ) : null}
              </div>
            ) : null}

            <label className="flex items-start gap-2.5 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                className="mt-0.5 h-4 w-4"
              />
              <span>
                Je consens à signer ce document électroniquement et je
                reconnais que ma signature électronique a la même valeur
                qu&apos;une signature manuscrite. Mon adresse IP, la date et
                l&apos;heure seront enregistrées.
              </span>
            </label>

            {error ? (
              <div className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                {error}
              </div>
            ) : null}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => setDeclineOpen(true)}
                className="text-xs font-medium text-rose-600 hover:underline"
              >
                Refuser de signer…
              </button>
              <button
                type="button"
                onClick={() => void submitSign()}
                disabled={signBusy}
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-6 py-3 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                {signBusy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                Signer le document
              </button>
            </div>
          </div>
        ) : null}

        <p className="pt-2 text-center text-[11px] text-slate-400">
          Signature électronique sécurisée · Horizon Services Immobiliers
        </p>
      </div>

      {/* Signature guidée : un seul gros bouton, toujours sous le pouce */}
      {canSign && obligatoires.length > 0 && !pad && !declineOpen ? (
        <div className="fixed inset-x-0 bottom-0 z-40 border-t border-slate-200 bg-white/95 px-4 py-3 shadow-[0_-4px_16px_rgba(15,23,42,0.10)] backdrop-blur">
          <div className="mx-auto flex max-w-4xl items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-slate-900">
                {nbFaits} sur {obligatoires.length}
                {prochain ? "" : " · tout est rempli"}
              </p>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200">
                <div
                  className="h-full rounded-full bg-emerald-500 transition-all"
                  style={{
                    width: `${(nbFaits / obligatoires.length) * 100}%`
                  }}
                />
              </div>
              <p className="mt-1 truncate text-[11px] text-slate-500">
                {prochain
                  ? `Prochain : ${libelleEtape(prochain)}`
                  : "Il ne reste qu'à confirmer et signer."}
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                if (!prochain) {
                  allerA(null);
                  return;
                }
                // Premier appui : la page amène à l'endroit. Une fois dessus, l'appui le remplit.
                if (courant !== prochain.id) allerA(prochain);
                else apposer(prochain);
              }}
              className="shrink-0 rounded-lg bg-blue-700 px-5 py-3 text-sm font-semibold text-white shadow hover:bg-blue-800"
            >
              {!prochain
                ? "Terminer"
                : courant !== prochain.id
                  ? nbFaits === 0
                    ? "Commencer"
                    : "Suivant"
                  : actionEtape(prochain)}
            </button>
          </div>
        </div>
      ) : null}

      {/* Fenêtre du tracé : la signature (ou les initiales) se fait une seule fois */}
      {pad ? (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 sm:items-center sm:p-4"
          onClick={() => setPad(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-lg rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl"
          >
            <InkPad
              key={pad.kind}
              label={pad.kind === "signature" ? "Votre signature" : "Vos initiales"}
              onChange={() => setPadErr(null)}
              lecteur={lirePad}
            />
            <p className="mt-2 text-[11px] text-slate-500">
              {pad.kind === "signature"
                ? "Vous la tracez une seule fois. Ensuite, un clic sur chaque « Signer ici » suffit."
                : "Vous les tracez une seule fois. Ensuite, un clic sur chaque case « Initiales » suffit."}
            </p>
            {padErr ? (
              <p className="mt-2 rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-700">
                {padErr}
              </p>
            ) : null}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPad(null)}
                className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={adopter}
                className="rounded-lg bg-blue-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-800"
              >
                {pad.fieldId != null ? "Adopter et apposer" : "Adopter"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Modal refus */}
      {declineOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => !signBusy && setDeclineOpen(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl"
          >
            <h2 className="text-sm font-semibold text-slate-900">
              Refuser de signer ce document ?
            </h2>
            <p className="mt-1 text-xs text-slate-600">
              L&apos;émetteur sera notifié. Vous pouvez préciser la raison
              (facultatif).
            </p>
            <textarea
              value={declineReason}
              onChange={(e) => setDeclineReason(e.target.value)}
              rows={3}
              placeholder="Raison du refus…"
              className="mt-3 w-full rounded-lg border border-slate-300 p-2 text-sm text-slate-900 outline-none focus:border-blue-600"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeclineOpen(false)}
                disabled={signBusy}
                className="rounded-lg border border-slate-300 px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-100"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void submitDecline()}
                disabled={signBusy}
                className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
              >
                {signBusy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : null}
                Confirmer le refus
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
