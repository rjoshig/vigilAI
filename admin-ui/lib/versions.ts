/**
 * How a definition version reads on screen (ADR-029).
 *
 * Versions are counted from one in the store; people read them as `v1.0`, `v1.1`,
 * `v1.2`. A definition that has never been saved reads as unversioned.
 */
export function versionLabel(version: number): string {
  if (!Number.isFinite(version) || version < 1) return "unversioned";
  return `v1.${version - 1}`;
}
