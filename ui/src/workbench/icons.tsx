/** Small inline SVG icon set for the workbench chrome (stroke = currentColor). */
import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };

function base({ size = 16, ...rest }: P, children: React.ReactNode) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export function IconCompose(p: P) {
  return base(
    p,
    <>
      <path d="M12 4H6.8C5.1 4 4 5.1 4 6.8v10.4C4 18.9 5.1 20 6.8 20h10.4c1.7 0 2.8-1.1 2.8-2.8V12" />
      <path d="M17.3 3.7a2 2 0 0 1 2.9 2.9L12 14.8 8 16l1.2-4L17.3 3.7Z" />
    </>,
  );
}

export function IconPlus(p: P) {
  return base(p, <path d="M12 5v14M5 12h14" />);
}

export function IconX(p: P) {
  return base(p, <path d="M6 6l12 12M18 6L6 18" />);
}

export function IconFile(p: P) {
  return base(
    p,
    <>
      <path d="M14 3H7.5C6.1 3 5 4.1 5 5.5v13C5 19.9 6.1 21 7.5 21h9c1.4 0 2.5-1.1 2.5-2.5V8l-5-5Z" />
      <path d="M14 3v5h5" />
    </>,
  );
}

export function IconPlusCircle(p: P) {
  return base(
    p,
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 8.5v7M8.5 12h7" />
    </>,
  );
}

export function IconFolder(p: P) {
  return base(
    p,
    <path d="M3.5 7.2c0-1 .8-1.7 1.7-1.7h4l2 2.2h7.6c1 0 1.7.8 1.7 1.7v7.4c0 1-.8 1.7-1.7 1.7H5.2c-1 0-1.7-.8-1.7-1.7V7.2Z" />,
  );
}

export function IconSend(p: P) {
  return base(p, <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" />);
}

export function IconStop(p: P) {
  return base(
    p,
    <rect x="7" y="7" width="10" height="10" rx="1.6" fill="currentColor" stroke="none" />,
  );
}

export function IconChevronDown(p: P) {
  return base(p, <path d="M6 9.5 12 15l6-5.5" />);
}

export function IconChevronRight(p: P) {
  return base(p, <path d="M9.5 6 15 12l-5.5 6" />);
}

export function IconMenu(p: P) {
  return base(
    p,
    <>
      <path d="M4 7h16" />
      <path d="M4 12h16" />
      <path d="M4 17h16" />
    </>,
  );
}

/** 聚焦: four corners pushed outward. */
export function IconFocus(p: P) {
  return base(
    p,
    <>
      <path d="M9 4H4v5" />
      <path d="M15 4h5v5" />
      <path d="M9 20H4v-5" />
      <path d="M15 20h5v-5" />
    </>,
  );
}

export function IconPanelRight(p: P) {
  return base(
    p,
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2.2" />
      <path d="M14.5 4.5v15" />
    </>,
  );
}

export function IconPanelLeft(p: P) {
  return base(p, <><rect x="3.5" y="4.5" width="17" height="15" rx="2.2" /><path d="M9.5 4.5v15" /></>);
}

/** A small unit cell: the scientific tool marker, independent of outcome. */
export function IconCrystal(p: P) {
  return base(p, <><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z" /><path d="m4 7.5 8 4.5 8-4.5M12 12v9" /></>);
}

/** Activity glyphs share the chrome's 24-unit grid and 1.7-unit stroke.
 * Simple silhouettes remain legible at the transcript's 17px size. */
export function IconSolve(p: P) {
  return base(p, <><path d="m12 3 8 7-8 11-8-11 8-7Z" /><path d="M4 10h16M12 3l-3 7 3 11 3-11-3-7" /></>);
}

export function IconRefine(p: P) {
  return base(p, <><path d="M4 7h8m4 0h4M4 17h4m4 0h8" /><circle cx="14" cy="7" r="2" /><circle cx="10" cy="17" r="2" /></>);
}

export function IconDensity(p: P) {
  return base(p, <><path d="M20 12c0 5-3 8-8 8s-8-3-8-8 3-8 8-8c3 0 3 4 5 4s3 1 3 4Z" /><path d="M15.5 12.5c0 2-1.5 3.5-3.5 3.5s-4-1.5-4-4 1-4 3-4 1.5 2 3 2 1.5 1 1.5 2.5Z" /></>);
}

export function IconSymmetry(p: P) {
  return base(p, <><path d="M12 3v3m0 4v4m0 4v3M8 6l-5 6 5 6V6Zm8 0 5 6-5 6V6Z" /></>);
}

export function IconMolecule(p: P) {
  return base(p, <><path d="m7 7 9 3M6 9l3 8m7-4-4 4" /><circle cx="6" cy="6" r="3" /><circle cx="18" cy="11" r="3" /><circle cx="10" cy="19" r="2" /></>);
}

export function IconGeometry(p: P) {
  return base(p, <><path d="m6 4-2 16h16M5 13a7 7 0 0 1 6 7" /><circle cx="6" cy="4" r="1" /><circle cx="20" cy="20" r="1" /></>);
}

export function IconValidation(p: P) {
  return base(p, <><path d="M14 3H6v18h12V7l-4-4ZM14 3v4h4" /><path d="m8 13 3 3 5-6" /></>);
}

export function IconDiffraction(p: P) {
  return base(p, <><path d="M4 8V4h4m8 0h4v4M4 16v4h4m8 0h4v-4" /><circle cx="12" cy="12" r="1" /><path d="M8 8h.01M16 8h.01M8 16h.01M16 16h.01" strokeWidth="2.5" /></>);
}

/** Indexing assigns spots to a lattice; keep the oblique grid distinct
 * from the detector spots and the faceted structure-solution glyph. */
export function IconIndexing(p: P) {
  return base(p, <path d="M8 4h12l-4 16H4L8 4ZM6 12h12M14 4l-4 16" />);
}

/** A reflection profile with a few area strokes denotes integration. */
export function IconIntegration(p: P) {
  return base(p, <path d="M3 19h18M4 19c4 0 4-14 8-14s4 14 8 14M9 15v4m3-9v9m3-4v4" />);
}

export function IconPencil(p: P) {
  return base(p, <><path d="m15 4 5 5L9 20l-6 1 1-6L15 4Z" /><path d="m12 7 5 5M4 15l5 5" /></>);
}

export function IconChart(p: P) {
  return base(p, <><path d="M4 4v16h16M8 15v-4m5 4V7m5 8v-6" /></>);
}

export function IconBranch(p: P) {
  return base(p, <><circle cx="6" cy="5" r="2" /><circle cx="6" cy="19" r="2" /><circle cx="18" cy="5" r="2" /><path d="M6 7v10m0-5h5a7 7 0 0 0 7-5" /></>);
}

export function IconCompare(p: P) {
  return base(p, <><path d="M4 7h16l-3-3M20 17H4l3 3M8 4v6m8 4v6" /></>);
}

export function IconBook(p: P) {
  return base(p, <><path d="M12 6C9 4 6 4 3 5v14c3-1 6-1 9 1 3-2 6-2 9-1V5c-3-1-6-1-9 1Zm0 0v14" /></>);
}

export function IconSearch(p: P) {
  return base(p, <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></>);
}

export function IconGlobe(p: P) {
  return base(p, <><circle cx="12" cy="12" r="9" /><ellipse cx="12" cy="12" rx="4" ry="9" /><path d="M3 12h18" /></>);
}

export function IconList(p: P) {
  return base(p, <path d="m3 6 1 1 2-3m-3 9 1 1 2-3m-3 9 1 1 2-3M10 6h11M10 13h11M10 20h11" />);
}

export function IconActivityGroup(p: P) {
  return base(p, <path d="M4 5h16M4 12h10M4 19h13" />);
}

export function IconShield(p: P) {
  return base(
    p,
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 8v4.5M12 15.6v.2" />
    </>,
  );
}

export function IconCheck(p: P) {
  return base(p, <path d="M5 12.5 10 17.5 19 7" />);
}

export function IconUser(p: P) {
  return base(
    p,
    <>
      <circle cx="12" cy="8.5" r="3.5" />
      <path d="M5 19.5c1.3-2.9 4-4.5 7-4.5s5.7 1.6 7 4.5" />
    </>,
  );
}

export function IconTerminal(p: P) {
  return base(
    p,
    <>
      <path d="M5 8l4 4-4 4" />
      <path d="M11.5 16.5H19" />
    </>,
  );
}

export function IconCopy(p: P) {
  return base(
    p,
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5.5 15H5a1.8 1.8 0 0 1-1.8-1.8V5A1.8 1.8 0 0 1 5 3.2h8.2A1.8 1.8 0 0 1 15 5v.5" />
    </>,
  );
}

export function IconTool(p: P) {
  return base(
    p,
    <path d="M14.5 6.5a4 4 0 0 0-5.3 5L4 16.7V20h3.3l5.2-5.2a4 4 0 0 0 5-5.3l-2.8 2.8-2.5-.7-.7-2.5 3-2.6Z" />,
  );
}

export function IconSettings(p: P) {
  return base(
    p,
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
    </>,
  );
}

export function IconSun(p: P) {
  return base(
    p,
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>,
  );
}

export function IconMoon(p: P) {
  return base(p, <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />);
}

export function IconCamera(p: P) {
  return base(
    p,
    <>
      <path d="M4 8.5A1.5 1.5 0 0 1 5.5 7H8l1.2-2h5.6L16 7h2.5A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5v-9Z" />
      <circle cx="12" cy="13" r="3.2" />
    </>,
  );
}

export function IconDownload(p: P) {
  return base(p, <path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19h14" />);
}

export function IconRefresh(p: P) {
  return base(
    p,
    <>
      <path d="M20 12a8 8 0 1 1-2.4-5.7" />
      <path d="M20 4v5h-5" />
    </>,
  );
}

/** Four-point spark: the "working" mark (Anthropic/Claude manner), pulsed
 * by the .pulse-star class in index.css. */
export function IconSpark(p: P) {
  return base(
    p,
    <path
      d="M12 2.5c.6 4.2 3.3 6.9 7.5 7.5-4.2.6-6.9 3.3-7.5 7.5-.6-4.2-3.3-6.9-7.5-7.5 4.2-.6 6.9-3.3 7.5-7.5Z"
      fill="currentColor"
      stroke="none"
    />,
  );
}
