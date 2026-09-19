/** Olex2-style click measurements: 2 atoms = distance, 3 = angle at the
 * middle atom, 4 = torsion (values only; esd needs the covariance matrix,
 * which stays server-side). */

type V3 = [number, number, number];

function sub(a: V3, b: V3): V3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

function norm(a: V3): number {
  return Math.hypot(a[0], a[1], a[2]);
}

function dot(a: V3, b: V3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function cross(a: V3, b: V3): V3 {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

export function distance(a: V3, b: V3): number {
  return norm(sub(a, b));
}

/** angle a-b-c in degrees */
export function angle(a: V3, b: V3, c: V3): number {
  const u = sub(a, b);
  const v = sub(c, b);
  const d = dot(u, v) / (norm(u) * norm(v) || 1);
  return (Math.acos(Math.min(1, Math.max(-1, d))) * 180) / Math.PI;
}

/** torsion a-b-c-d in degrees, signed (IUPAC convention) */
export function torsion(a: V3, b: V3, c: V3, d: V3): number {
  const b1 = sub(b, a);
  const b2 = sub(c, b);
  const b3 = sub(d, c);
  const n1 = cross(b1, b2);
  const n2 = cross(b2, b3);
  const m1 = cross(n1, [
    b2[0] / (norm(b2) || 1),
    b2[1] / (norm(b2) || 1),
    b2[2] / (norm(b2) || 1),
  ]);
  const x = dot(n1, n2);
  const y = dot(m1, n2);
  return (Math.atan2(y, x) * 180) / Math.PI;
}

export interface MeasureReadout {
  /** e.g. "W1–C3 2.031 Å" / "C3–W1–C5 89.4°" */
  text: string;
  kind: "distance" | "angle" | "torsion";
}

export function measureReadout(
  labels: string[],
  sites: V3[],
): MeasureReadout | null {
  if (sites.length === 2) {
    return {
      kind: "distance",
      text: `${labels.join("–")}  ${distance(sites[0], sites[1]).toFixed(3)} Å`,
    };
  }
  if (sites.length === 3) {
    return {
      kind: "angle",
      text: `${labels.join("–")}  ${angle(sites[0], sites[1], sites[2]).toFixed(2)}°`,
    };
  }
  if (sites.length === 4) {
    return {
      kind: "torsion",
      text: `${labels.join("–")}  ${torsion(sites[0], sites[1], sites[2], sites[3]).toFixed(2)}°`,
    };
  }
  return null;
}
