/** "SHEL lo hi" -> hi (the working high-resolution cutoff), or null. */
export function shelWorkingCutoff(
  shel: string | undefined | null,
): number | null {
  if (!shel) return null;
  const nums = shel.match(/-?\d+(?:\.\d+)?/g);
  if (!nums || nums.length < 2) return null;
  const hi = Number(nums[nums.length - 1]);
  return Number.isFinite(hi) && hi > 0 ? hi : null;
}
