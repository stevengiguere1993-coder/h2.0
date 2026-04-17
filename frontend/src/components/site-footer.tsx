import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";

export function SiteFooter() {
  const tNav = useTranslations("nav");
  const tFooter = useTranslations("footer");

  const year = new Date().getFullYear();

  return (
    <footer className="border-t border-brand-100 bg-brand-950 text-brand-100">
      <div className="container grid gap-10 py-12 md:grid-cols-4">
        <div>
          <div className="flex items-center gap-2 font-display text-lg font-bold text-white">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white text-brand-900">H</span>
            Horizon
          </div>
          <p className="mt-3 text-sm text-brand-200">{tFooter("service_zone")}</p>
          <p className="mt-1 text-xs text-brand-300">{tFooter("rbq")}</p>
        </div>

        <div>
          <p className="mb-3 text-sm font-semibold uppercase tracking-wider text-brand-300">{tNav("services")}</p>
          <ul className="space-y-2 text-sm">
            <li><Link href="/services/salle-de-bain" className="hover:text-white">Salle de bain</Link></li>
            <li><Link href="/services/cuisine" className="hover:text-white">Cuisine</Link></li>
            <li><Link href="/services/multilogement" className="hover:text-white">Multilogement</Link></li>
          </ul>
        </div>

        <div>
          <p className="mb-3 text-sm font-semibold uppercase tracking-wider text-brand-300">Entreprise</p>
          <ul className="space-y-2 text-sm">
            <li><Link href="/a-propos" className="hover:text-white">{tNav("about")}</Link></li>
            <li><Link href="/contact" className="hover:text-white">{tNav("contact")}</Link></li>
            <li><Link href="/connexion" className="hover:text-white">{tNav("login")}</Link></li>
          </ul>
        </div>

        <div>
          <p className="mb-3 text-sm font-semibold uppercase tracking-wider text-brand-300">Contact</p>
          <ul className="space-y-2 text-sm">
            <li><a href="mailto:info@immohorizon.com" className="hover:text-white">info@immohorizon.com</a></li>
            <li><a href="https://immohorizon.com" className="hover:text-white">immohorizon.com</a></li>
          </ul>
        </div>
      </div>

      <div className="border-t border-brand-800">
        <div className="container flex flex-col items-center justify-between gap-2 py-5 text-xs text-brand-300 md:flex-row">
          <p>© {year} Horizon Services Immobiliers. {tFooter("rights")}</p>
          <div className="flex gap-4">
            <Link href={"/mentions-legales" as "/mentions-legales"} className="hover:text-white">{tFooter("legal")}</Link>
            <Link href={"/confidentialite" as "/confidentialite"} className="hover:text-white">{tFooter("privacy")}</Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
