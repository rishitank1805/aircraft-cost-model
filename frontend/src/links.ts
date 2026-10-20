/** External links: only official public-agency sources are clickable. Company sources are shown as plain-text
 *  source names (no link, no URL) so the explorer never refers users to, or implies affiliation with, any company. */
const AGENCY_DOMAINS = ["faa.gov", "nasa.gov", "bts.gov", "bls.gov", "europa.eu"];

export function isAgencyUrl(url: string | null | undefined): boolean {
  if (!url || !/^https?:\/\//.test(url)) return false;
  try {
    const host = new URL(url).hostname;
    return AGENCY_DOMAINS.some((d) => host === d || host.endsWith(`.${d}`));
  } catch {
    return false;
  }
}

/** Remove company URLs from free text (keeps agency URLs and the surrounding citation text). */
export function stripCompanyUrls(text: string | null | undefined): string {
  if (!text) return "";
  return text
    .replace(/https?:\/\/[^\s),;]+/g, (url) => (isAgencyUrl(url) ? url : ""))
    .replace(/:\s*\(/g, " (").replace(/:\s*$/g, "").replace(/\s{2,}/g, " ").trim();
}
