/** Outside-click test for popovers that close on `document` mousedown /
 * pointerdown.
 *
 * The naive `!el.contains(e.target)` misfires on the very event that opened
 * the popover: React 18 commits state and effects synchronously for
 * discrete input events, so a menu opened from a mousedown handler
 * registers its document listener while that same mousedown is still
 * bubbling; when the event reaches `document`, the element it hit (a slash
 * palette button that the state change just unmounted) is no longer in the
 * DOM, `contains` says "outside", and the menu closes in the same tick it
 * opened (2026-09-16: `/model`, `/effort`, `/permissions`, `/subagents`
 * did nothing when clicked, worked from the keyboard). A target that is no
 * longer connected to the document cannot be an outside click. */
export function clickedOutside(el: Element | null, e: Event): boolean {
  const target = e.target as Node | null;
  if (!el || !target) return false;
  if (!target.isConnected) return false;
  return !el.contains(target);
}
