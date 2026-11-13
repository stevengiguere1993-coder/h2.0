import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    // Inclure lib/ — les fichiers qui définissent des classes
    // dynamiques (profile-colors.ts par ex.) doivent être scannés
    // sinon le JIT ne génère pas les bg-rose-500, bg-amber-400…
    "./src/lib/**/*.{js,ts,jsx,tsx}"
  ],
  theme: {
    container: {
      center: true,
      padding: {
        DEFAULT: "1rem",
        sm: "1.5rem",
        lg: "2rem"
      },
      screens: {
        "2xl": "1280px"
      }
    },
    extend: {
      colors: {
        // Monochrome palette aligned with the Horizon logo (pure black bg).
        // brand-950 is pure black so the site background matches the logo
        // exactly. The rest of the scale stays dark but slightly lifted
        // so cards and borders remain readable against pure black.
        brand: {
          50: "#f5f5f5",
          100: "#e5e5e5",
          200: "#cfcfcf",
          300: "#a3a3a3",
          400: "#737373",
          500: "#525252",
          600: "#3d3d3d",
          700: "#2b2b2b",
          800: "#1a1a1a",
          900: "#0f0f0f",
          950: "#000000"
        },
        accent: {
          // Design system (Phase 4) : nuances ajoutées pour donner de
          // la portée (survols, bordures, titres). 500/600 inchangés.
          300: "#e8c382",
          400: "#e0af5f",
          500: "#d89b3c",
          600: "#b97e24",
          700: "#98651c"
        }
      },
      fontFamily: {
        sans: ["'Inter'", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["'Plus Jakarta Sans'", "'Inter'", "sans-serif"]
      },
      boxShadow: {
        // Échelle d'élévation du design system (Phase 4). `card` inchangé.
        soft: "0 1px 3px rgba(0,0,0,0.4)",
        card: "0 1px 2px rgba(0,0,0,0.5), 0 8px 24px -12px rgba(0,0,0,0.7)",
        lift: "0 6px 20px -4px rgba(0,0,0,0.5), 0 14px 40px -12px rgba(0,0,0,0.65)"
      }
    }
  },
  plugins: []
};

export default config;
