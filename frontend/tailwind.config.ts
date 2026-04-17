import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}"
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
        brand: {
          50: "#f2f7fb",
          100: "#e2ecf5",
          200: "#bfd5e9",
          300: "#8fb4d6",
          400: "#5a8ebe",
          500: "#3a6fa3",
          600: "#2d588a",
          700: "#254772",
          800: "#1f3a5e",
          900: "#15283f",
          950: "#0b1726"
        },
        accent: {
          500: "#d89b3c",
          600: "#b97e24"
        }
      },
      fontFamily: {
        sans: ["'Inter'", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["'Plus Jakarta Sans'", "'Inter'", "sans-serif"]
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,23,42,0.05), 0 8px 24px -12px rgba(15,23,42,0.15)"
      }
    }
  },
  plugins: []
};

export default config;
