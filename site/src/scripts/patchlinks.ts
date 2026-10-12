// Patch ids → their entry in the patch reference (docs/PATCHES.md → /docs/patches/). The map is written by
// scripts/patch_docs.py next to the markdown, so the site needs no Python to build.
import map from '../data/patches.json';
import { url } from '../data/site';

export interface PatchInfo { anchor: string; title: string; group: string }
const PATCHES = map as Record<string, PatchInfo>;
/** The patch reference page itself. */
export const PATCH_DOC = url('docs/patches/');

/** The registry id behind a recipe reference: "overport.patch_x" (the board's OVRPort prefix) → "patch_x", lepton_env
 *  keys ("env.X") → device.lepton_env, "adapter.scale=0.85" → "adapter.scale". */
export function patchId(ref: string): string {
  const id = ref.trim().split('=')[0];
  if (id.startsWith('overport.')) return id.slice('overport.'.length);
  if (id.startsWith('env.')) return 'device.lepton_env';
  return id;
}

export function patchInfo(ref: string): PatchInfo | undefined {
  return PATCHES[patchId(ref)];
}

/** The site link to a patch's entry, or null for an id the reference doesn't know. */
export function patchHref(ref: string): string | null {
  const info = patchInfo(ref);
  return info ? `${PATCH_DOC}#${info.anchor}` : null;
}
