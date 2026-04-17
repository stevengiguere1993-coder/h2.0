import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f0f7ff',
          100: '#dcedff',
          200: '#bfdcff',
          300: '#92c3ff',
          400: '#5fa1fb',
          500: '#3a80f5',
          600: '#2463e8',
          700: '#1c4dd4',
          800: '#1d40ac',
          900: '#1d3a87',
          950: '#162451',
        },
        ink: {
          50: '#f6f7f9',
          100: '#ebedf2',
          200: '#d3d8e0',
          300: '#abb3c0',
          400: '#7d8798',
          500: '#5d6879',
          600: '#495164',
          700: '#3c4251',
          800: '#333846',
          900: '#13151b',
        },
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'system-ui', 'sans-serif'],
        display: ['var(--font-inter)', 'system-ui', 'sans-serif'],
      },
      container: {
        center: true,
        padding: {
          DEFAULT: '1rem',
          sm: '1.5rem',
          lg: '2rem',
        },
        screens: {
          '2xl': '1280px',
        },
      },
    },
  },
  plugins: [],
};

export default config;
