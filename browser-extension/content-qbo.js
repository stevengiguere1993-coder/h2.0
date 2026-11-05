// Content script QuickBooks en ligne (*.qbo.intuit.com) — 1.3.3, Steven
// 2026-10-14 : « trouve-moi une solution pour convertir un sous-client en
// projet » sans le palier partenaire Silver qu'exige l'API Projets.
//
// Kratos crée le SOUS-CLIENT de chaque projet sous le client mère ; la
// conversion en PROJET (onglet Projets de QB) n'existe que dans l'écran de
// QuickBooks. Ce script la fait DANS le QuickBooks ouvert de la
// technicienne, avec sa session (aucun mot de passe dans Kratos) :
//
//   1. demande à Kratos la liste des sous-clients à convertir
//      (background.js → POST /api/v1/extension/qbo-conversions) ;
//   2. affiche un panneau (ouvert sur la page Projets, replié en pastille
//      ailleurs) : la liste, « Convertir maintenant » sur la page Projets
//      (ou « Aller à Projets » ailleurs), la case « Automatique »
//      (désactivée par défaut). 1.3.2 : il se pose dans un coin où il ne
//      cache aucun bouton de QuickBooks, se ferme par × jusqu'au
//      rechargement de la page ;
//   3. pilote l'écran : « Nouveau projet ▾ » → « Convertir depuis un
//      sous-client » → coche EXACTEMENT les noms attendus (jamais « tout
//      sélectionner ») → « Convertir » → confirmation ;
//   4. rend compte à Kratos (POST …/qbo-conversions/resultat), qui vérifie
//      par l'API que le sous-client est bien devenu un projet avant de
//      rayer la ligne.
//
// Tout repose sur les textes des boutons (FR et EN) et des noms exacts :
// si l'écran de QuickBooks ne ressemble pas à ce qui est attendu, le
// script S'ARRÊTE et le dit (panneau + compte rendu à Kratos) plutôt que
// de cliquer au hasard. Rien n'est converti sans correspondance exacte.

(function () {
  "use strict";

  if (window.top !== window) return; // jamais dans un iframe de QB

  const log = (...args) => console.log("[h2.0 QBO]", ...args);

  const AUTO_KEY = "h2_qbo_auto";
  const PANNEAU_ID = "h2-qbo-panneau";
  // Une tentative automatique par liste et par page chargée : si elle
  // échoue, on ne recommence pas en boucle (sessionStorage).
  const AUTO_FAIT_KEY = "h2_qbo_auto_fait";
  // QuickBooks en français (Canada) dit « Convertir à partir d'un client
  // rattaché » (2026-11-05 : l'extension s'arrêtait sur « introuvable ») ;
  // « sous-client » et l'anglais « sub-customer » restent reconnus.
  const RE_MENU_CONVERTIR =
    /convertir.*(sous[\s-]?client|client[\s-]+rattach)|convert.*sub[\s-]?customer/i;
  const RE_NOUVEAU_PROJET = /nouveau projet|new project/i;
  const RE_TOUT = /^(tout|tous|toutes|all|select all|tout s[ée]lectionner|s[ée]lectionner tout)/i;
  const RE_ANNULER = /annuler|cancel|fermer|close/i;
  const RE_CONFIRMER = /^(convertir|convert|oui|yes|continuer|continue|confirmer|confirm|ok)\b/i;
  const RE_CONTENEURS =
    '[role="dialog"], [aria-modal="true"], [class*="modal" i], [class*="dialog" i], ' +
    '[class*="drawer" i], [class*="trowser" i], [class*="panel" i], [class*="overlay" i]';

  // ── Petits utilitaires ─────────────────────────────────────────────

  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

  function norm(s) {
    return String(s || "")
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
  }

  function texte(el) {
    return norm((el && (el.innerText || el.textContent)) || "");
  }

  function visible(el) {
    if (!el || !(el instanceof Element)) return false;
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) return false;
    const st = getComputedStyle(el);
    return st.visibility !== "hidden" && st.display !== "none";
  }

  async function attendre(pred, ms, pas = 150) {
    const fin = Date.now() + ms;
    for (;;) {
      let v = null;
      try {
        v = pred();
      } catch (_) {
        v = null;
      }
      if (v) return v;
      if (Date.now() > fin) return null;
      await dormir(pas);
    }
  }

  function envoyer(message) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(message, (resp) => {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, error: chrome.runtime.lastError.message });
            return;
          }
          resolve(resp || { ok: false, error: "aucune réponse" });
        });
      } catch (exc) {
        resolve({ ok: false, error: "extension rechargée : recharge la page (" + exc.message + ")" });
      }
    });
  }

  // Page Kratos qui configure l'extension (adresse de production : tant que
  // l'extension n'est pas reliée, elle ne connaît pas encore le serveur).
  const PAGE_KRATOS_PROJETS =
    "https://immohorizon.com/entreprises/comptabilite/projets-quickbooks";

  function surPageProjets() {
    return /\/app\/projects(\/|$|\?)/.test(location.pathname + location.search);
  }

  function hoteSandbox() {
    return /sandbox/.test(location.hostname);
  }

  // ── État ───────────────────────────────────────────────────────────

  const etat = {
    liste: null, // {items, company_name, realm_id, environment, lien_projets}
    erreur: null,
    erreurCode: null, // NON_RELIEE / CLE_REFUSEE / HTTP (background.js)
    enCours: false,
    message: null, // dernière ligne d'état (texte, ton)
    auto: false,
    // 1.3.2 — replié d'office hors de la page Projets (la bulle ouverte
    // cachait le bouton « Enregistrer » d'une fiche client, Steven
    // 2026-11-02).
    replie: !surPageProjets(),
    // Fermé par × : plus rien jusqu'au rechargement de la page.
    ferme: false,
    // Ouvert à la demande sans place libre : se replie au premier clic
    // ailleurs dans QuickBooks.
    force: false,
    // Pastille sans place libre : simple languette au bord droit.
    languette: false,
    compagnieOk: null, // true / false / null (pas vérifiable)
  };

  async function chargerListe() {
    const r = await envoyer({ type: "QBO_CONVERSIONS_LIST" });
    if (!r || !r.ok) {
      etat.liste = null;
      etat.erreur = (r && r.error) || "Kratos injoignable";
      etat.erreurCode = (r && r.code) || null;
      return;
    }
    etat.erreur = null;
    etat.erreurCode = null;
    etat.liste = r.data || { items: [] };
    etat.compagnieOk = verifierCompagnie();
  }

  // La compagnie ouverte n'est pas lisible depuis un content script
  // (variables de la page hors de portée) : on cherche le nom de la
  // compagnie attendue dans l'en-tête de QuickBooks. Trouvé → vert ;
  // sinon → avertissement, et pas de conversion AUTOMATIQUE.
  function verifierCompagnie() {
    const voulu = norm(etat.liste && etat.liste.company_name);
    if (!voulu || voulu === norm("Horizon (Construction)")) return null;
    const envAttendu = (etat.liste.environment || "").toLowerCase();
    if (envAttendu === "sandbox" && !hoteSandbox()) return false;
    if (envAttendu === "production" && hoteSandbox()) return false;
    const corps = norm(document.body ? document.body.innerText : "");
    return corps.includes(voulu) ? true : false;
  }

  // ── Panneau ────────────────────────────────────────────────────────

  function el(tag, style, contenu) {
    const e = document.createElement(tag);
    if (style) e.setAttribute("style", style);
    if (typeof contenu === "string") e.textContent = contenu;
    return e;
  }

  const BOUTON =
    "font:inherit;font-weight:600;font-size:12px;border-radius:8px;padding:6px 10px;cursor:pointer;" +
    "border:1px solid #2c6b4f;background:#2c6b4f;color:#fff;";
  const BOUTON_SEC =
    "font:inherit;font-size:12px;border-radius:8px;padding:5px 9px;cursor:pointer;" +
    "border:1px solid #c9c4ba;background:#fff;color:#2a2a2a;";

  const STYLE_BASE =
    "position:fixed;z-index:2147483000;" +
    "font:13px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;" +
    "color:#1f1f1f;background:#fffdf8;border:1px solid #d9b26a;box-shadow:0 10px 30px rgba(0,0,0,.18);";

  function deplier() {
    etat.replie = false;
    etat.languette = false;
    etat.ouvertALaMain = true;
    rendre();
    etat.ouvertALaMain = false;
  }

  function rendre() {
    let p = document.getElementById(PANNEAU_ID);
    const items = (etat.liste && etat.liste.items) || [];
    const rien = !etat.erreur && !items.length && !etat.message && !etat.enCours;
    if (rien || (etat.ferme && !etat.enCours)) {
      if (p) p.remove();
      return;
    }
    if (etat.enCours) {
      // La conversion se regarde : panneau ouvert, jamais replié.
      etat.replie = false;
      etat.languette = false;
    }
    if (!p) {
      p = el("div", "");
      p.id = PANNEAU_ID;
      document.documentElement.appendChild(p);
    }
    p.textContent = "";
    const nbTexte = items.length ? `${items.length} à convertir` : "";

    // Languette : aucune place libre pour la pastille (tout le bord est
    // occupé par des boutons de QuickBooks) → un onglet étroit au bord
    // droit, qui s'ouvre au clic.
    if (etat.replie && etat.languette) {
      p.setAttribute(
        "style",
        STYLE_BASE +
          "right:0;top:38%;left:auto;bottom:auto;width:auto;padding:8px 5px;cursor:pointer;" +
          "border-right:0;border-radius:10px 0 0 10px;writing-mode:vertical-rl;" +
          "font-weight:700;font-size:12px;color:#5c4614;background:#f7efdd;"
      );
      p.title = "Horizon · projets QuickBooks" + (nbTexte ? " (" + nbTexte + ")" : "") + " — cliquer pour ouvrir";
      p.textContent = "Horizon" + (items.length ? " · " + items.length : "");
      p.onclick = deplier;
      return;
    }
    p.onclick = null;
    p.removeAttribute("title");
    p.setAttribute(
      "style",
      STYLE_BASE +
        (etat.replie
          ? "width:auto;max-width:calc(100vw - 32px);border-radius:999px;"
          : "width:340px;max-width:calc(100vw - 32px);border-radius:12px;")
    );

    // En-tête (seul visible quand c'est replié : la pastille)
    const tete = el(
      "div",
      "display:flex;align-items:center;justify-content:space-between;gap:8px;" +
        (etat.replie
          ? "padding:5px 6px 5px 12px;background:#f7efdd;border-radius:999px;"
          : "padding:10px 12px;border-bottom:1px solid #eadfc8;background:#f7efdd;border-radius:12px 12px 0 0;")
    );
    const titre = el(
      "div",
      "font-weight:700;font-size:13px;white-space:nowrap;",
      etat.replie ? "Horizon" : "Horizon · projets QuickBooks"
    );
    const nb = el("span", "margin-left:6px;font-weight:600;font-size:11px;color:#5c4614;", nbTexte);
    titre.appendChild(nb);
    const boutons = el("div", "display:flex;align-items:center;gap:4px;");
    const replier = el("button", BOUTON_SEC, etat.replie ? "Afficher" : "Réduire");
    replier.onclick = () => {
      if (etat.replie) {
        deplier();
      } else {
        etat.replie = true;
        etat.force = false;
        rendre();
      }
    };
    boutons.appendChild(replier);
    if (!etat.enCours) {
      const fermer = el(
        "button",
        BOUTON_SEC + "padding:5px 8px;font-weight:700;line-height:1;",
        "×"
      );
      fermer.title = "Fermer jusqu'au rechargement de la page";
      fermer.setAttribute("aria-label", "Fermer le panneau Horizon");
      fermer.onclick = () => {
        etat.ferme = true;
        etat.force = false;
        rendre();
      };
      boutons.appendChild(fermer);
    }
    tete.appendChild(titre);
    tete.appendChild(boutons);
    p.appendChild(tete);
    if (etat.replie) {
      placer(p);
      return;
    }

    const corps = el("div", "padding:10px 12px;max-height:50vh;overflow:auto;");
    p.appendChild(corps);

    if (etat.erreur) {
      if (etat.erreurCode === "NON_RELIEE" || etat.erreurCode === "CLE_REFUSEE") {
        // 1.3.1 — la configuration vient d'une page Kratos : on dit laquelle
        // ouvrir, avec le lien, au lieu de « clique l'icône extension ».
        corps.appendChild(
          el(
            "p",
            "margin:0 0 6px;color:#9a3412;font-weight:600;",
            etat.erreurCode === "NON_RELIEE"
              ? "L'extension n'est pas encore reliée à Kratos."
              : "Kratos refuse la clé de l'extension (elle a changé ?)."
          )
        );
        corps.appendChild(
          el(
            "p",
            "margin:0 0 6px;font-size:12px;color:#4a4a4a;",
            "1. Ouvre Kratos → Entreprises → Comptabilité → Projets QB dans ce navigateur, connecté : la page configure l'extension toute seule. 2. Reviens ici et clique Actualiser."
          )
        );
        const lien = el(
          "a",
          "display:inline-block;margin:0 0 8px;font-size:12px;font-weight:600;color:#1d4ed8;text-decoration:underline;",
          "Ouvrir la page Kratos ↗"
        );
        lien.href = PAGE_KRATOS_PROJETS;
        lien.target = "_blank";
        lien.rel = "noopener";
        corps.appendChild(lien);
      } else {
        corps.appendChild(
          el("p", "margin:0 0 8px;color:#9a3412;", "Kratos : " + etat.erreur)
        );
      }
    }

    if (etat.liste && etat.liste.company_name) {
      const c = el("p", "margin:0 0 8px;font-size:12px;color:#4a4a4a;");
      c.textContent = "Compagnie attendue : " + etat.liste.company_name + " ";
      const badge = el(
        "span",
        "font-weight:600;" +
          (etat.compagnieOk === true
            ? "color:#166534;"
            : etat.compagnieOk === false
              ? "color:#9a3412;"
              : "color:#6b6b6b;"),
        etat.compagnieOk === true
          ? "✓ c'est celle-ci"
          : etat.compagnieOk === false
            ? "✗ pas celle qui est ouverte ?"
            : "(non vérifiable)"
      );
      c.appendChild(badge);
      corps.appendChild(c);
    }

    if (items.length) {
      const ul = el("ul", "margin:0 0 10px;padding:0;list-style:none;");
      for (const it of items) {
        const li = el("li", "padding:6px 8px;margin:0 0 4px;background:#fff;border:1px solid #eee4d0;border-radius:8px;");
        const nom = el("div", "font-weight:600;", it.nom || "");
        const sous = el("div", "font-size:11px;color:#6b6b6b;", it.client ? "Client : " + it.client : "");
        li.appendChild(nom);
        if (it.client) li.appendChild(sous);
        ul.appendChild(li);
      }
      corps.appendChild(ul);
    } else if (!etat.erreur) {
      corps.appendChild(el("p", "margin:0 0 8px;color:#4a4a4a;", "Rien à convertir."));
    }

    if (etat.message) {
      corps.appendChild(
        el(
          "p",
          "margin:0 0 8px;padding:6px 8px;border-radius:8px;font-size:12px;" +
            (etat.message.ton === "ok"
              ? "background:#e7f5ec;color:#166534;"
              : etat.message.ton === "erreur"
                ? "background:#fdecec;color:#9a3412;"
                : "background:#f1efe9;color:#3a3a3a;"),
          etat.message.texte
        )
      );
    }

    const actions = el("div", "display:flex;flex-wrap:wrap;align-items:center;gap:6px;");
    if (items.length) {
      if (surPageProjets()) {
        const b = el("button", BOUTON, etat.enCours ? "Conversion en cours…" : "Convertir maintenant");
        b.disabled = etat.enCours;
        if (etat.enCours) b.style.opacity = "0.6";
        b.onclick = () => convertir("bouton");
        actions.appendChild(b);
      } else {
        const b = el("button", BOUTON, "Aller à Projets");
        b.onclick = () => {
          location.href = location.origin + "/app/projects";
        };
        actions.appendChild(b);
      }
    }
    const raf = el("button", BOUTON_SEC, "Actualiser");
    raf.onclick = async () => {
      etat.message = null;
      await chargerListe();
      rendre();
    };
    actions.appendChild(raf);

    const lab = el("label", "display:inline-flex;align-items:center;gap:5px;font-size:12px;cursor:pointer;margin-left:auto;");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!etat.auto;
    cb.onchange = async () => {
      etat.auto = cb.checked;
      try {
        await chrome.storage.local.set({ [AUTO_KEY]: etat.auto });
      } catch (_) {}
      if (etat.auto) {
        try {
          sessionStorage.removeItem(AUTO_FAIT_KEY);
        } catch (_) {}
        planifierAuto();
      }
    };
    lab.appendChild(cb);
    lab.appendChild(document.createTextNode("Automatique"));
    lab.title =
      "Convertit d'elle-même à l'ouverture de la page Projets (une fois par liste). " +
      "Désactivé par défaut : regarde la première conversion se faire.";
    actions.appendChild(lab);
    corps.appendChild(actions);
    placer(p);
  }

  // ── Placement hors des boutons de QuickBooks (1.3.2) ───────────────
  //
  // Steven 2026-11-02 : « l'extension ici m'empêche de sauvegarder » — la
  // bulle, fixée en bas à droite, cachait le bouton « Enregistrer » du
  // volet de modification d'une fiche client. La bulle se pose donc dans
  // le premier coin où elle ne recouvre AUCUN élément cliquable de
  // QuickBooks, et le vérifie de nouveau chaque seconde (un volet ou une
  // fenêtre de QB peut s'ouvrir dessous). Sans place libre : la pastille
  // devient une languette au bord droit ; le panneau ouvert se replie,
  // sauf s'il vient d'être ouvert à la main — il se replie alors au
  // premier clic ailleurs dans QuickBooks.

  const MARGE = 16;
  const COINS = ["bas-droite", "bas-gauche", "milieu-droite", "milieu-gauche"];
  const INTERACTIFS =
    'button, a[href], input:not([type="hidden"]), select, textarea, summary, ' +
    '[role="button"], [role="link"], [role="menuitem"], [role="tab"], [role="option"], ' +
    '[role="checkbox"], [role="radio"], [role="combobox"], [role="switch"], [role="textbox"], ' +
    '[contenteditable="true"]';

  function rectCoin(coin, l, h) {
    const W = document.documentElement.clientWidth || window.innerWidth;
    const H = document.documentElement.clientHeight || window.innerHeight;
    const droite = W - MARGE - l;
    const milieu = Math.max(MARGE, Math.round((H - h) / 2));
    switch (coin) {
      case "bas-gauche":
        return { left: MARGE, top: H - MARGE - h, width: l, height: h };
      case "milieu-droite":
        return { left: droite, top: milieu, width: l, height: h };
      case "milieu-gauche":
        return { left: MARGE, top: milieu, width: l, height: h };
      default:
        return { left: droite, top: H - MARGE - h, width: l, height: h };
    }
  }

  // Un élément cliquable de QuickBooks sous ce rectangle ? (grille de
  // points : document.elementsFromPoint renvoie toute la pile, la bulle
  // comprise, qu'on ignore.)
  function recouvreUnBouton(r, p) {
    const W = document.documentElement.clientWidth || window.innerWidth;
    const H = document.documentElement.clientHeight || window.innerHeight;
    if (r.left < 0 || r.top < 0 || r.left + r.width > W || r.top + r.height > H) return true;
    const xs = [0.03, 0.25, 0.5, 0.75, 0.97].map((f) => r.left + f * r.width);
    const ys = [0.1, 0.5, 0.9].map((f) => r.top + f * r.height);
    for (const x of xs) {
      for (const y of ys) {
        for (const e of document.elementsFromPoint(x, y)) {
          if (p.contains(e)) continue;
          const i = e.closest(INTERACTIFS);
          if (i && !p.contains(i) && visible(i)) return true;
        }
      }
    }
    return false;
  }

  function poser(p, r) {
    p.style.left = Math.round(r.left) + "px";
    p.style.top = Math.round(r.top) + "px";
    p.style.right = "auto";
    p.style.bottom = "auto";
  }

  function placer(p) {
    if (!p || !document.contains(p) || (etat.replie && etat.languette)) return;
    const taille = p.getBoundingClientRect();
    const l = taille.width;
    const h = taille.height;
    if (etat.replie) etat.taillePastille = { l, h };
    if (etat.enCours) {
      poser(p, rectCoin("bas-droite", l, h));
      return;
    }
    for (const coin of COINS) {
      const r = rectCoin(coin, l, h);
      if (!recouvreUnBouton(r, p)) {
        poser(p, r);
        return;
      }
    }
    if (etat.replie) {
      etat.languette = true;
      rendre();
    } else if (etat.force) {
      poser(p, rectCoin("bas-droite", l, h));
    } else if (etat.ouvertALaMain) {
      // Ouvert à la main sans place libre : visible, mais il se replie au
      // premier clic ailleurs (ex. « Modifier » d'une fiche).
      etat.ouvertALaMain = false;
      etat.force = true;
      poser(p, rectCoin("bas-droite", l, h));
    } else {
      etat.replie = true;
      rendre();
    }
  }

  // Chaque seconde : un volet de QuickBooks a pu s'ouvrir sous la bulle,
  // ou une place s'est libérée pour la pastille repliée en languette.
  function surveillerPlacement() {
    setInterval(() => {
      const p = document.getElementById(PANNEAU_ID);
      if (!p || etat.enCours) return;
      if (etat.replie && etat.languette) {
        // La languette redevient pastille dès qu'un coin se libère (à la
        // taille mesurée de la pastille : pas de va-et-vient).
        const t = etat.taillePastille || { l: 190, h: 38 };
        if (COINS.some((c) => !recouvreUnBouton(rectCoin(c, t.l, t.h), p))) {
          etat.languette = false;
          rendre();
        }
        return;
      }
      placer(p);
    }, 1000);
    // Ouvert de force : le premier vrai clic ailleurs le replie (avant que
    // QuickBooks n'ouvre son volet dessous).
    document.addEventListener(
      "mousedown",
      (ev) => {
        if (!ev.isTrusted || !etat.force || etat.enCours) return;
        const p = document.getElementById(PANNEAU_ID);
        if (p && p.contains(ev.target)) return;
        etat.force = false;
        etat.replie = true;
        rendre();
      },
      true
    );
  }

  function dire(texte_, ton) {
    etat.message = texte_ ? { texte: texte_, ton: ton || "info" } : null;
    rendre();
  }

  // ── Pilotage de l'écran QuickBooks ────────────────────────────────

  function candidatsCliquables(racine) {
    return Array.from(
      (racine || document).querySelectorAll(
        'button, [role="button"], [role="menuitem"], [role="option"], a, li'
      )
    ).filter((c) => visible(c) && !c.closest("#" + PANNEAU_ID));
  }

  // Élément cliquable dont le texte (court) répond à ``re`` ; le plus
  // profond quand plusieurs s'emboîtent (sinon on cliquerait un conteneur).
  function trouverTexte(re, racine) {
    const cands = candidatsCliquables(racine).filter((c) => {
      const t = texte(c);
      return t && t.length <= 80 && re.test(t);
    });
    if (!cands.length) return null;
    return cands.find((c) => !cands.some((o) => o !== c && c.contains(o))) || cands[0];
  }

  function conteneursActuels() {
    return new Set(Array.from(document.querySelectorAll(RE_CONTENEURS)).filter(visible));
  }

  function nouveauConteneur(avant, pred) {
    const maintenant = Array.from(document.querySelectorAll(RE_CONTENEURS)).filter(visible);
    for (const c of maintenant) {
      if (avant.has(c)) continue;
      if (!pred || pred(c)) return c;
    }
    return null;
  }

  // Ouvre le menu « Nouveau projet ▾ » puis clique « Convertir depuis un
  // sous-client ». Le bouton principal crée un projet vierge : on vise
  // d'abord un bouton à menu (aria-haspopup / aria-expanded), sinon la
  // flèche voisine du bouton « Nouveau projet ».
  async function ouvrirMenuConvertir() {
    const direct = trouverTexte(RE_MENU_CONVERTIR, document);
    if (direct) return direct;
    const boutons = candidatsCliquables(document).filter((b) => RE_NOUVEAU_PROJET.test(texte(b)));
    if (!boutons.length) throw new Error("bouton « Nouveau projet » introuvable sur cette page");
    const essais = [];
    for (const b of boutons) {
      const haspopup = b.getAttribute("aria-haspopup") || b.hasAttribute("aria-expanded");
      if (haspopup) essais.push(b);
    }
    for (const b of boutons) {
      const parent = b.parentElement;
      if (!parent) continue;
      for (const s of Array.from(parent.querySelectorAll("button, [role='button']"))) {
        if (s !== b && visible(s) && texte(s).length <= 2) essais.push(s);
      }
      const suivant = b.nextElementSibling;
      if (suivant && visible(suivant) && texte(suivant).length <= 2) essais.push(suivant);
    }
    if (!essais.length) essais.push(boutons[0]);
    for (const e of essais) {
      e.click();
      const item = await attendre(() => trouverTexte(RE_MENU_CONVERTIR, document), 2500);
      if (item) return item;
      // Menu ouvert sans l'option ? on le referme avant l'essai suivant.
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await dormir(300);
    }
    throw new Error("« Convertir à partir d'un client rattaché » introuvable dans le menu « Nouveau projet »");
  }

  function etiquetteCase(cb, conteneur) {
    const morceaux = [];
    if (cb.id) {
      const l = conteneur.querySelector(`label[for="${CSS.escape(cb.id)}"]`);
      if (l) morceaux.push(l.innerText || l.textContent || "");
    }
    const lab = cb.closest("label");
    if (lab) morceaux.push(lab.innerText || lab.textContent || "");
    const ids = cb.getAttribute("aria-labelledby");
    if (ids) {
      for (const id of ids.split(/\s+/)) {
        const n = document.getElementById(id);
        if (n) morceaux.push(n.innerText || n.textContent || "");
      }
    }
    if (cb.getAttribute("aria-label")) morceaux.push(cb.getAttribute("aria-label"));
    const ligne = cb.closest('tr, li, [role="row"], [role="option"], [class*="row" i], [class*="item" i]');
    if (ligne && ligne !== conteneur) morceaux.push(ligne.innerText || ligne.textContent || "");
    if (!morceaux.join("").trim()) {
      // Rien d'étiqueté : le plus petit ancêtre qui porte un texte court
      // (la ligne de la liste), sans remonter jusqu'à la fenêtre entière.
      let n = cb.parentElement;
      while (n && n !== conteneur && n !== document.body) {
        const t = (n.innerText || n.textContent || "").trim();
        if (t) {
          if (t.length <= 200) morceaux.push(t);
          break;
        }
        n = n.parentElement;
      }
    }
    return morceaux.join("\n");
  }

  // Un tableau rend ses cellules séparées par des tabulations (innerText).
  function lignesDe(etiquette) {
    return etiquette
      .split(/\n|\t|·|•|\|/)
      .map(norm)
      .filter(Boolean);
  }

  // Case qui correspond EXACTEMENT à un sous-client attendu : une des
  // lignes de son étiquette = « nom », ou = « client:nom ».
  function correspond(lignes, it) {
    const nom = norm(it.nom);
    if (!nom) return false;
    if (lignes.includes(nom)) return true;
    if (it.client && lignes.includes(norm(it.client + ":" + it.nom))) return true;
    if (it.client && lignes.includes(norm(it.client + " : " + it.nom))) return true;
    return false;
  }

  async function convertir(origine) {
    if (etat.enCours) return;
    const items = (etat.liste && etat.liste.items) || [];
    if (!items.length) return;
    if (!surPageProjets()) {
      dire("Ouvre d'abord la page Projets de QuickBooks.", "erreur");
      return;
    }
    etat.enCours = true;
    dire(origine === "auto" ? "Conversion automatique…" : "Conversion en cours…", "info");
    const resultats = [];
    let dialogue = null;
    try {
      // 1) Menu → « Convertir à partir d'un client rattaché »
      const item = await ouvrirMenuConvertir();
      // Le menu ouvert fait partie de l'« avant » : la nouveauté sera la
      // fenêtre de sélection, pas le menu.
      const avant = conteneursActuels();
      const casesAvant = new Set(document.querySelectorAll('input[type="checkbox"]'));
      item.click();

      // 2) La fenêtre de sélection (cases à cocher). Si QuickBooks ne la
      // rend pas comme un dialogue reconnaissable, on se rabat sur les
      // cases qui viennent d'apparaître dans la page.
      dialogue = await attendre(
        () => nouveauConteneur(avant, (c) => c.querySelector('input[type="checkbox"]')),
        8000
      );
      let nouvellesCases = null;
      if (!dialogue) {
        nouvellesCases = await attendre(() => {
          const n = Array.from(document.querySelectorAll('input[type="checkbox"]')).filter(
            (cb) => !casesAvant.has(cb)
          );
          return n.length ? n : null;
        }, 2000);
        if (!nouvellesCases) {
          throw new Error("la fenêtre « Convertir à partir d'un client rattaché » ne s'est pas ouverte");
        }
      }
      await dormir(400);
      const portee = dialogue || document.body;
      const cases = (
        dialogue ? Array.from(dialogue.querySelectorAll('input[type="checkbox"]')) : nouvellesCases
      ).filter((cb) => visible(cb) || visible(cb.closest("label")) || visible(cb.parentElement));
      if (!cases.length) throw new Error("aucune case à cocher dans la fenêtre de conversion");

      // 3) Cocher EXACTEMENT les sous-clients attendus
      const trouves = new Map(); // item → case
      const casesLignes = cases.map((cb) => ({ cb, lignes: lignesDe(etiquetteCase(cb, dialogue)) }));
      for (const it of items) {
        const m = casesLignes.filter(({ lignes }) => !lignes.some((l) => RE_TOUT.test(l)) && correspond(lignes, it));
        if (m.length === 1) trouves.set(it, m[0].cb);
        else if (m.length > 1) {
          resultats.push({ project_id: it.project_id, ok: false, detail: "plusieurs sous-clients portent ce nom : à faire à la main" });
        }
      }
      for (const it of items) {
        if (!trouves.has(it) && !resultats.some((r) => r.project_id === it.project_id)) {
          resultats.push({
            project_id: it.project_id,
            ok: false,
            detail:
              "absent de la liste « Convertir à partir d'un client rattaché » (déjà converti ? pas « facturer avec le client parent » ?)",
          });
        }
      }
      if (!trouves.size) throw new Error("aucun des sous-clients attendus n'est dans la liste de QuickBooks");

      // Rien d'autre ne doit être coché.
      const voulues = new Set(trouves.values());
      for (const { cb, lignes } of casesLignes) {
        if (cb.checked && !voulues.has(cb)) {
          if (lignes.some((l) => RE_TOUT.test(l))) continue;
          cb.click();
          await dormir(120);
        }
      }
      for (const cb of voulues) {
        if (!cb.checked) {
          cb.click();
          await dormir(150);
        }
        if (!cb.checked) {
          const lab = cb.closest("label") || cb.parentElement;
          if (lab) lab.click();
          await dormir(150);
        }
      }
      await dormir(300);
      const cochees = casesLignes.filter(({ cb, lignes }) => cb.checked && !lignes.some((l) => RE_TOUT.test(l)));
      const inattendues = cochees.filter(({ cb }) => !voulues.has(cb));
      const manquantes = Array.from(voulues).filter((cb) => !cb.checked);
      if (inattendues.length || manquantes.length) {
        throw new Error(
          inattendues.length
            ? "la sélection ne correspond pas aux sous-clients attendus : rien n'a été converti"
            : "impossible de cocher le sous-client dans QuickBooks"
        );
      }

      // 4) « Convertir » puis confirmation éventuelle
      const avantConfirm = conteneursActuels();
      const bConvertir = trouverTexte(/^(convertir|convert)\b/i, portee);
      if (!bConvertir || RE_MENU_CONVERTIR.test(texte(bConvertir))) {
        throw new Error("bouton « Convertir » introuvable dans la fenêtre");
      }
      bConvertir.click();
      const confirm = await attendre(
        () =>
          nouveauConteneur(avantConfirm, (c) => c !== dialogue && !!trouverTexte(RE_CONFIRMER, c)),
        3000
      );
      if (confirm) {
        const b = candidatsCliquables(confirm).find((x) => RE_CONFIRMER.test(texte(x)) && !RE_ANNULER.test(texte(x)));
        if (b) b.click();
      }
      // Fenêtre refermée (ou, sans dialogue reconnu, cases disparues).
      const fermee = await attendre(
        () =>
          dialogue
            ? !document.contains(dialogue) || !visible(dialogue)
            : cases.every((cb) => !document.contains(cb) || !(visible(cb) || visible(cb.parentElement))),
        25000,
        300
      );
      const faits = Array.from(trouves.keys());
      for (const it of faits) {
        resultats.push({
          project_id: it.project_id,
          ok: !!fermee,
          detail: fermee ? "conversion faite par l'extension" : "la fenêtre ne s'est pas refermée : vérifie dans QuickBooks",
        });
      }
      dire(
        fermee
          ? `${faits.length} sous-client${faits.length > 1 ? "s" : ""} converti${faits.length > 1 ? "s" : ""} — Kratos vérifie.`
          : "QuickBooks n'a pas confirmé : vérifie l'onglet Projets.",
        fermee ? "ok" : "erreur"
      );
    } catch (exc) {
      log("Conversion arrêtée :", exc);
      // Fenêtre laissée ouverte : on la ferme pour ne rien laisser coché.
      try {
        if (dialogue && document.contains(dialogue)) {
          const annuler = candidatsCliquables(dialogue).find((x) => RE_ANNULER.test(texte(x)));
          if (annuler) annuler.click();
          else document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
        } else {
          document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
        }
      } catch (_) {}
      for (const it of items) {
        if (!resultats.some((r) => r.project_id === it.project_id)) {
          resultats.push({ project_id: it.project_id, ok: false, detail: "arrêt : " + exc.message });
        }
      }
      dire("Arrêt : " + exc.message + ". Fais-la à la main ou réessaie.", "erreur");
    } finally {
      etat.enCours = false;
      try {
        sessionStorage.setItem(AUTO_FAIT_KEY, signatureListe());
      } catch (_) {}
    }
    const r = await envoyer({ type: "QBO_CONVERSIONS_RESULT", payload: { resultats } });
    if (!r || !r.ok) log("Compte rendu non reçu par Kratos :", r && r.error);
    await dormir(1500);
    await chargerListe();
    rendre();
  }

  function signatureListe() {
    const items = (etat.liste && etat.liste.items) || [];
    return items.map((i) => i.project_id).join(",");
  }

  let autoTimer = null;
  function planifierAuto() {
    if (!etat.auto || etat.enCours || !surPageProjets()) return;
    const items = (etat.liste && etat.liste.items) || [];
    if (!items.length) return;
    if (etat.compagnieOk === false) {
      dire("Automatique suspendu : ce n'est pas la compagnie attendue.", "erreur");
      return;
    }
    let deja = null;
    try {
      deja = sessionStorage.getItem(AUTO_FAIT_KEY);
    } catch (_) {}
    if (deja === signatureListe()) return;
    clearTimeout(autoTimer);
    autoTimer = setTimeout(() => convertir("auto"), 2500);
  }

  // ── Démarrage ──────────────────────────────────────────────────────

  async function demarrer() {
    try {
      const d = await chrome.storage.local.get([AUTO_KEY]);
      etat.auto = !!d[AUTO_KEY];
    } catch (_) {}
    await chargerListe();
    rendre();
    planifierAuto();
    surveillerPlacement();

    // Application monopage : l'URL change sans rechargement.
    let derniereUrl = location.href;
    setInterval(() => {
      if (location.href !== derniereUrl) {
        derniereUrl = location.href;
        etat.compagnieOk = verifierCompagnie();
        rendre();
        planifierAuto();
      }
    }, 1500);
    // Nouveaux projets Kratos pendant que QuickBooks reste ouvert.
    setInterval(async () => {
      if (etat.enCours) return;
      await chargerListe();
      rendre();
      planifierAuto();
    }, 90000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(demarrer, 1500));
  } else {
    setTimeout(demarrer, 1500);
  }
})();
