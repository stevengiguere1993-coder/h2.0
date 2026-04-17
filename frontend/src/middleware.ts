import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // Match every path except:
  //   - /api, /_next, /_vercel, files with an extension, and sitemap/robots
  matcher: ["/((?!api|_next|_vercel|.*\\..*|sitemap.xml|robots.txt).*)"]
};
