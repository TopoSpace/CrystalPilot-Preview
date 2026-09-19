/** Shared ReactMarkdown link renderer.
 *
 * The agent's final answers link local deliverables by absolute path
 * ("H:/.../final.cif"). A browser treats "H:" as an (invalid) URL scheme,
 * so those links render dead. Rewrite drive-letter / file:// hrefs to the
 * artifact endpoint (which serves deliverables + checkCIF/SHELXL outputs
 * of open projects) and open everything in a new tab.
 */
import type { AnchorHTMLAttributes } from "react";
import { defaultUrlTransform, type Components } from "react-markdown";

export function resolveMdHref(raw: string): string {
  let h = raw;
  const fileUri = h.startsWith("file:///");
  if (fileUri) h = h.slice(7).replace(/^\/([a-zA-Z]:[\\/])/, "$1");
  const posixFile = /^\/(?:home|Users|Volumes|mnt|media|srv|opt|tmp|var|data|work|workspace)\//.test(h);
  if (fileUri || posixFile || /^[a-zA-Z]:[\\/]/.test(h)) {
    // remark already percent-encodes link destinations ("%20" for spaces);
    // decode before re-encoding or the path double-encodes to %2520
    try {
      h = decodeURIComponent(h);
    } catch {
      /* stray % - keep as-is */
    }
    return `/api/wb/artifact?path=${encodeURIComponent(h)}`;
  }
  return raw;
}

/** ReactMarkdown sanitizes unknown URL schemes ("H:" reads as one) to an
 * EMPTY href before components ever see it - the rewrite must happen in
 * urlTransform. Local absolute paths route through the artifact endpoint;
 * everything else gets the default sanitizer. */
export function mdUrlTransform(url: string): string {
  const local = resolveMdHref(url);
  if (local !== url) return local;
  return defaultUrlTransform(url);
}

export function MdLink(props: AnchorHTMLAttributes<HTMLAnchorElement>) {
  const { href, children, ...rest } = props;
  const resolved = resolveMdHref(href ?? "");
  return (
    <a
      {...rest}
      href={resolved}
      target="_blank"
      rel="noreferrer noopener"
      className="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent"
    >
      {children}
    </a>
  );
}

export const mdComponents: Components = { a: MdLink };

/** Variant for previews of on-disk markdown (e.g. VALIDATION.md): plain
 * relative hrefs ("final.cif") resolve against the document's own
 * directory, then through the artifact endpoint. */
export function mdComponentsWithBase(docPath: string): Components {
  const dir = docPath.replace(/[\\/][^\\/]*$/, "");
  function BasedLink(props: AnchorHTMLAttributes<HTMLAnchorElement>) {
    const { href, children, ...rest } = props;
    let resolved = resolveMdHref(href ?? "");
    if (
      resolved === (href ?? "") &&
      href &&
      !/^[a-z][a-z0-9+.-]*:/i.test(href) &&
      !href.startsWith("/") &&
      !href.startsWith("#")
    ) {
      resolved = `/api/wb/artifact?path=${encodeURIComponent(`${dir}/${decodeURIComponent(href)}`)}`;
    }
    return (
      <a
        {...rest}
        href={resolved}
        target="_blank"
        rel="noreferrer noopener"
        className="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent"
      >
        {children}
      </a>
    );
  }
  return { a: BasedLink };
}
