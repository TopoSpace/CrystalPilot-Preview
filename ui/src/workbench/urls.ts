/** Route helpers - the project path always rides in ?project= and is always
 * encodeURIComponent'd (Windows paths). */

export function projectHomeUrl(project: string): string {
  return `/?project=${encodeURIComponent(project)}`;
}

export function threadUrl(threadId: string, project: string | null): string {
  const base = `/thread/${encodeURIComponent(threadId)}`;
  return project ? `${base}?project=${encodeURIComponent(project)}` : base;
}

/** The project's display name when it has one, else the last path segment
 * of a Windows/POSIX path. */
export function projectLabel(path: string, displayName?: string | null): string {
  const name = displayName?.trim();
  if (name) return name;
  const parts = path.replaceAll("\\", "/").split("/").filter(Boolean);
  return parts.at(-1) ?? path;
}

/** One cap for every "recent projects" list (sidebar, status board). */
export const RECENT_PROJECTS_LIMIT = 8;
