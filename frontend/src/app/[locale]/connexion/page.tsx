import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";

import { LoginForm } from "@/components/login-form";

export const metadata: Metadata = {
  title: "Connexion / Sign in",
  robots: { index: false, follow: false }
};

type Props = { params: Promise<{ locale: string }> };

export default async function LoginPage({ params }: Props) {
  const { locale } = await params;
  setRequestLocale(locale);

  return (
    <section className="section">
      <div className="container max-w-md">
        <div className="card">
          <h1 className="text-2xl font-bold text-brand-950">Connexion</h1>
          <p className="mt-1 text-sm text-brand-700">
            Zone réservée aux employés et administrateurs.
          </p>
          <div className="mt-6">
            <LoginForm />
          </div>
        </div>
      </div>
    </section>
  );
}
