/** Native <details> may leave focus inside content it just hid. Move focus
 * back to the owning summary so collapsing a process fold never strands a
 * keyboard or screen-reader user. */
export function keepFocusOnSummary(details: HTMLDetailsElement): void {
  if (details.open || !details.contains(document.activeElement)) return;
  details.querySelector<HTMLElement>(":scope > summary")?.focus({ preventScroll: true });
}
