import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? 'https://immohorizon.com'),
  title: {
    default: 'Horizon Services Immobiliers',
    template: '%s | Horizon Services Immobiliers',
  },
  description:
    "Rénovations résidentielles et multilogements dans le Grand Montréal. Rigueur, qualité, résultats.",
  verification: {
    google:
      process.env.NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION ??
      'df-YUga-WwjKVQGNgHeqbykIibgxiav5Wq4WbetFrMc',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return children;
}
