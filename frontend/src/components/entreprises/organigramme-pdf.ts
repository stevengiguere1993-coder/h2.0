/**
 * Export PDF de l'organigramme (Phil 2026-10-08) — dessin VECTORIEL
 * avec jsPDF : bulles, flèches de détention avec quotes-parts, légende,
 * bulle mise en évidence (ex. la compagnie acquéreuse montrée à la
 * banque). Pas de capture d'écran : net à toute échelle, fond blanc
 * imprimable, fichier léger.
 *
 * Le dessin reprend exactement ce que le canvas affiche (périmètre
 * Complet / Nos INCs, positions des bulles, mise en évidence) ; les
 * options ne touchent que la feuille : orientation, format, échelle.
 */
import type { jsPDF } from "jspdf";

export type PdfNature = "inc" | "externe" | "person" | "autre";
export type PdfOrientation = "portrait" | "paysage";
export type PdfFormat = "lettre" | "legal" | "tabloid";
export type PdfEchelle = "page" | "largeur" | "manuelle";

export type PdfBulle = {
  id: number;
  label: string;
  nature: PdfNature;
  societeMere: boolean;
  enEvidence: boolean;
  // Coordonnées canvas (px, coin haut-gauche).
  x: number;
  y: number;
};

export type PdfFleche = {
  fromId: number; // détenteur
  toId: number; // détenu
  pct: number | null;
};

export type PdfOptions = {
  orientation: PdfOrientation;
  format: PdfFormat;
  echelle: PdfEchelle;
  // Échelle manuelle en % (100 = même taille qu'à l'écran à 100 %).
  zoom: number;
  titre: string;
  sousTitre: string;
  // Libellé de la légende pour la bulle mise en évidence (null = aucune
  // bulle en évidence → pas d'entrée de légende).
  legendeEvidence: string | null;
};

export const FORMATS_PDF: Record<
  PdfFormat,
  { label: string; pts: [number, number] }
> = {
  lettre: { label: "Lettre (8½ × 11)", pts: [612, 792] },
  legal: { label: "Légal (8½ × 14)", pts: [612, 1008] },
  tabloid: { label: "Tabloïd (11 × 17)", pts: [792, 1224] }
};

type RGB = [number, number, number];
const COULEURS: Record<PdfNature | "evidence", { fond: RGB; bord: RGB }> = {
  inc: { fond: [254, 243, 199], bord: [217, 119, 6] },
  externe: { fond: [224, 242, 254], bord: [2, 132, 199] },
  person: { fond: [237, 233, 254], bord: [124, 58, 237] },
  autre: { fond: [243, 244, 246], bord: [107, 114, 128] },
  evidence: { fond: [209, 250, 229], bord: [5, 150, 105] }
};
const BADGES: Record<PdfNature, string> = {
  inc: "INC DU GROUPE",
  externe: "COMPAGNIE HORS GROUPE",
  person: "PERSONNE",
  autre: "AUTRE"
};
const LEGENDE: Array<[PdfNature, string]> = [
  ["inc", "INC du groupe"],
  ["externe", "Compagnie hors groupe"],
  ["person", "Personne"]
];

const ENCRE: RGB = [17, 24, 39];
const GRIS: RGB = [107, 114, 128];
const BLANC: RGB = [255, 255, 255];
// 1 px canvas = 0,75 pt (= taille écran à 100 %).
const BASE = 0.75;

// Helvetica (WinAnsi) ne connaît pas les guillemets typographiques,
// les tirets longs ni « œ » : on les ramène à des équivalents sûrs.
function txt(s: string): string {
  return (s || "")
    .replace(/[‘’‚]/g, "'")
    .replace(/[“”„]/g, '"')
    .replace(/[–—]/g, "-")
    .replace(/…/g, "...")
    .replace(/œ/g, "oe")
    .replace(/Œ/g, "OE")
    .replace(/[  ]/g, " ");
}

function formatPct(p: number): string {
  const r = Math.round(p * 100) / 100;
  return `${String(r).replace(".", ",")} %`;
}

type XY = { x: number; y: number };

// Point sur le bord du rectangle (centre `c`, demi-tailles hw/hh) en
// direction de `vers` — même géométrie que le canvas.
function bord(c: XY, vers: XY, hw: number, hh: number): XY {
  const dx = vers.x - c.x;
  const dy = vers.y - c.y;
  if (dx === 0 && dy === 0) return c;
  const sx = dx !== 0 ? hw / Math.abs(dx) : Infinity;
  const sy = dy !== 0 ? hh / Math.abs(dy) : Infinity;
  const k = Math.min(sx, sy);
  return { x: c.x + dx * k, y: c.y + dy * k };
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

function etoile(doc: jsPDF, cx: number, cy: number, r: number, c: RGB) {
  // Étoile à 5 branches (société mère) — polygone fermé en segments
  // relatifs comme l'attend doc.lines.
  const pts: XY[] = [];
  for (let i = 0; i < 10; i += 1) {
    const ang = -Math.PI / 2 + (i * Math.PI) / 5;
    const rr = i % 2 === 0 ? r : r * 0.45;
    pts.push({ x: cx + Math.cos(ang) * rr, y: cy + Math.sin(ang) * rr });
  }
  const segs: number[][] = [];
  for (let i = 1; i < pts.length; i += 1)
    segs.push([pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y]);
  doc.setFillColor(c[0], c[1], c[2]);
  doc.lines(segs, pts[0].x, pts[0].y, [1, 1], "F", true);
}

export async function construirePdfOrganigramme(input: {
  bulles: PdfBulle[];
  fleches: PdfFleche[];
  options: PdfOptions;
  bulleW: number;
  bulleH: number;
}): Promise<jsPDF> {
  const { bulles, fleches, options, bulleW: W, bulleH: H } = input;
  // Import dynamique : le blob jspdf (~150 kB) ne charge qu'à l'export.
  const { jsPDF } = await import("jspdf");
  const [fw, fh] = FORMATS_PDF[options.format].pts;
  const doc = new jsPDF({
    orientation: options.orientation === "paysage" ? "landscape" : "portrait",
    unit: "pt",
    format: [fw, fh],
    compress: true
  });
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  const marge = 36;
  const enteteH = 60;
  const piedH = 16;
  const zone = {
    x: marge,
    y: marge + enteteH,
    w: pageW - 2 * marge,
    h: pageH - marge - enteteH - marge - piedH
  };

  let echelle = BASE;
  if (bulles.length > 0) {
    const pad = 16;
    const minX = Math.min(...bulles.map((b) => b.x)) - pad;
    const minY = Math.min(...bulles.map((b) => b.y)) - pad;
    const maxX = Math.max(...bulles.map((b) => b.x + W)) + pad;
    const maxY = Math.max(...bulles.map((b) => b.y + H)) + pad;
    const bw = Math.max(1, maxX - minX);
    const bh = Math.max(1, maxY - minY);
    if (options.echelle === "page") echelle = Math.min(zone.w / bw, zone.h / bh);
    else if (options.echelle === "largeur") echelle = zone.w / bw;
    else echelle = BASE * (clamp(options.zoom, 10, 400) / 100);
    echelle = clamp(echelle, 0.05, 4);
    const s = echelle;
    // Centré quand ça rentre ; aligné en haut / à gauche quand ça
    // déborde (le débordement est masqué par les bandeaux).
    const ox =
      zone.x + (bw * s <= zone.w ? (zone.w - bw * s) / 2 : 0) - minX * s;
    const oy =
      zone.y + (bh * s <= zone.h ? (zone.h - bh * s) / 2 : 0) - minY * s;
    const X = (px: number) => ox + px * s;
    const Y = (py: number) => oy + py * s;
    const parId = new Map(bulles.map((b) => [b.id, b]));

    // ── Flèches (sous les bulles) ────────────────────────────────
    const traitW = clamp((1.6 * s) / BASE, 0.5, 2.4);
    for (const f of fleches) {
      const a = parId.get(f.fromId);
      const b = parId.get(f.toId);
      if (!a || !b) continue;
      const fc = { x: a.x + W / 2, y: a.y + H / 2 };
      const tc = { x: b.x + W / 2, y: b.y + H / 2 };
      const start = bord(fc, tc, W / 2, H / 2);
      const end = bord(tc, fc, W / 2, H / 2);
      const x1 = X(start.x);
      const y1 = Y(start.y);
      const x2 = X(end.x);
      const y2 = Y(end.y);
      doc.setDrawColor(GRIS[0], GRIS[1], GRIS[2]);
      doc.setLineWidth(traitW);
      doc.line(x1, y1, x2, y2);
      // Pointe
      const ang = Math.atan2(y2 - y1, x2 - x1);
      const len = clamp((9 * s) / BASE, 4, 11);
      doc.setFillColor(GRIS[0], GRIS[1], GRIS[2]);
      doc.triangle(
        x2,
        y2,
        x2 - len * Math.cos(ang - 0.42),
        y2 - len * Math.sin(ang - 0.42),
        x2 - len * Math.cos(ang + 0.42),
        y2 - len * Math.sin(ang + 0.42),
        "F"
      );
      // Quote-part au milieu, sur un cartouche blanc.
      if (f.pct != null) {
        const fs = clamp((11 * s) / BASE, 4.5, 12);
        doc.setFont("helvetica", "bold");
        doc.setFontSize(fs);
        const t = formatPct(f.pct);
        const tw = doc.getTextWidth(t);
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2 - fs * 0.45;
        doc.setFillColor(BLANC[0], BLANC[1], BLANC[2]);
        doc.roundedRect(mx - tw / 2 - 2, my - fs * 0.85, tw + 4, fs * 1.15, 2, 2, "F");
        doc.setTextColor(ENCRE[0], ENCRE[1], ENCRE[2]);
        doc.text(t, mx, my, { align: "center" });
      }
    }

    // ── Bulles ───────────────────────────────────────────────────
    for (const b of bulles) {
      const c = b.enEvidence ? COULEURS.evidence : COULEURS[b.nature];
      const x = X(b.x);
      const y = Y(b.y);
      const w = W * s;
      const h = H * s;
      const r = 8 * s;
      if (b.enEvidence) {
        // Halo : deux anneaux translucides pour « sortir du lot ».
        doc.saveGraphicsState();
        doc.setFillColor(c.bord[0], c.bord[1], c.bord[2]);
        doc.setGState(doc.GState({ opacity: 0.14 }));
        doc.roundedRect(x - 11, y - 11, w + 22, h + 22, r + 8, r + 8, "F");
        doc.setGState(doc.GState({ opacity: 0.3 }));
        doc.roundedRect(x - 5, y - 5, w + 10, h + 10, r + 4, r + 4, "F");
        doc.restoreGraphicsState();
      }
      doc.setFillColor(c.fond[0], c.fond[1], c.fond[2]);
      doc.setDrawColor(c.bord[0], c.bord[1], c.bord[2]);
      doc.setLineWidth(b.enEvidence ? clamp(2.4 * s / BASE, 1.2, 3) : clamp(1.2 * s / BASE, 0.5, 1.6));
      doc.roundedRect(x, y, w, h, r, r, "FD");
      // Badge de nature (+ étoile société mère)
      let bx = x + 10 * s;
      if (b.societeMere) {
        etoile(doc, bx + 4 * s, y + 11 * s, 4.5 * s, COULEURS.inc.bord);
        bx += 12 * s;
      }
      doc.setFont("helvetica", "bold");
      doc.setFontSize(Math.max(2.5, 7.5 * s));
      doc.setTextColor(c.bord[0], c.bord[1], c.bord[2]);
      doc.text(BADGES[b.nature], bx, y + 14 * s);
      // Nom (2 lignes max)
      doc.setFontSize(Math.max(3, 13 * s));
      doc.setTextColor(ENCRE[0], ENCRE[1], ENCRE[2]);
      const lignes = doc.splitTextToSize(txt(b.label), w - 20 * s) as string[];
      let affichees = lignes.slice(0, 2);
      if (lignes.length > 2) {
        const derniere = affichees[1];
        affichees = [affichees[0], `${derniere.slice(0, Math.max(1, derniere.length - 3))}...`];
      }
      affichees.forEach((l, i) => {
        doc.text(l, x + 10 * s, y + 32 * s + i * 15 * s);
      });
    }
  }

  // ── Masques (débordement) + en-tête + légende + pied ───────────
  doc.setFillColor(BLANC[0], BLANC[1], BLANC[2]);
  doc.rect(0, 0, pageW, zone.y - 6, "F");
  doc.rect(0, zone.y + zone.h + 6, pageW, pageH - zone.y - zone.h - 6, "F");
  doc.rect(0, 0, marge - 6, pageH, "F");
  doc.rect(pageW - marge + 6, 0, marge, pageH, "F");

  doc.setFont("helvetica", "bold");
  doc.setFontSize(15);
  doc.setTextColor(ENCRE[0], ENCRE[1], ENCRE[2]);
  doc.text(txt(options.titre), marge, marge + 13);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(9);
  doc.setTextColor(GRIS[0], GRIS[1], GRIS[2]);
  doc.text(txt(options.sousTitre), marge, marge + 27);

  // Légende
  let lx = marge;
  const ly = marge + 44;
  doc.setFontSize(8);
  const entrees: Array<[PdfNature | "evidence", string]> = [...LEGENDE];
  if (options.legendeEvidence) entrees.push(["evidence", options.legendeEvidence]);
  for (const [nat, lbl] of entrees) {
    const c = COULEURS[nat];
    doc.setFillColor(c.fond[0], c.fond[1], c.fond[2]);
    doc.setDrawColor(c.bord[0], c.bord[1], c.bord[2]);
    doc.setLineWidth(0.8);
    doc.roundedRect(lx, ly - 7, 10, 8, 2, 2, "FD");
    doc.setTextColor(ENCRE[0], ENCRE[1], ENCRE[2]);
    doc.text(txt(lbl), lx + 14, ly);
    lx += 14 + doc.getTextWidth(txt(lbl)) + 16;
  }
  // Filet sous l'en-tête
  doc.setDrawColor(229, 231, 235);
  doc.setLineWidth(0.6);
  doc.line(marge, zone.y - 8, pageW - marge, zone.y - 8);

  // Pied de page
  const date = new Date().toLocaleDateString("fr-CA", {
    year: "numeric",
    month: "long",
    day: "numeric"
  });
  doc.setFontSize(7.5);
  doc.setTextColor(GRIS[0], GRIS[1], GRIS[2]);
  doc.text(
    txt(`Kratos · généré le ${date} · échelle ${Math.round((echelle / BASE) * 100)} %`),
    pageW - marge,
    pageH - marge + 8,
    { align: "right" }
  );
  if (bulles.length === 0) {
    doc.setFontSize(11);
    doc.text("Aucune bulle à exporter dans ce périmètre.", pageW / 2, pageH / 2, {
      align: "center"
    });
  }
  return doc;
}

export function nomFichierPdf(version: string, perimetre: string): string {
  const slug = (s: string) =>
    s
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^a-zA-Z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .toLowerCase();
  const jour = new Date().toISOString().slice(0, 10);
  return `organigramme-${slug(version) || "principal"}-${slug(perimetre)}-${jour}.pdf`;
}
