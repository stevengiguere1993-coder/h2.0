import type { MetadataRoute } from "next";

const BASE = process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/connexion", "/login", "/admin", "/api/"]
      }
    ],
    sitemap: `${BASE}/sitemap.xml`,
    host: BASE
  };
}
