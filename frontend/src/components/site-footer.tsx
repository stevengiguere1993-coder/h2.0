import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";

export function SiteFooter() {
  const tNav = useTranslations("nav");
  const tFooter = useTranslations("footer");
  const tServices = useTranslations("services.items");

  const year = new Date().getFullYear();

  return (
    <footer className="border-t border-brand-800 bg-brand-950 text-white">
      <div className="container grid gap-10 py-12 md:grid-cols-4">
        <div>
          <div className="flex items-center gap-3">
            <span className="logo-badge" aria-hidden="true">H</span>
            <span className="font-display text-sm font-bold uppercase tracking-[0.2em] text-white">Horizon</span>
          </div>
          <p className="mt-4 text-sm text-white/80">{tFooter("service_zone")}</p>
          <p className="mt-1 text-xs text-white/60">{tFooter("rbq")}</p>
        </div>

        <div>
          <p className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
            {tNav("services")}
          </p>
          <ul className="space-y-2 text-sm text-white/80">
            <li>
              <Link href="/services/salle-de-bain" className="hover:text-accent-500">
                {tServices("bathroom.title")}
              </Link>
            </li>
            <li>
              <Link href="/services/cuisine" className="hover:text-accent-500">
                {tServices("kitchen.title")}
              </Link>
            </li>
            <li>
              <Link href="/services/multilogement" className="hover:text-accent-500">
                {tServices("multi.title")}
              </Link>
            </li>
          </ul>
        </div>

        <div>
          <p className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
            {tNav("home")}
          </p>
          <ul className="space-y-2 text-sm text-white/80">
            <li>
              <Link href="/a-propos" className="hover:text-accent-500">
                {tNav("about")}
              </Link>
            </li>
            <li>
              <Link href="/contact" className="hover:text-accent-500">
                {tNav("contact")}
              </Link>
            </li>
            <li>
              <Link href="/connexion" className="hover:text-accent-500">
                {tNav("login")}
              </Link>
            </li>
          </ul>
        </div>

        <div>
          <p className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">Contact</p>
          <ul className="space-y-2 text-sm text-white/80">
            <li><a href="mailto:info@immohorizon.com" className="hover:text-accent-500">info@immohorizon.com</a></li>
            <li><a href="https://immohorizon.com" className="hover:text-accent-500">immohorizon.com</a></li>
          </ul>
        </div>
      </div>

      <div className="border-t border-brand-800">
        <div className="container flex flex-col items-center justify-between gap-2 py-5 text-xs text-white/60 md:flex-row">
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
