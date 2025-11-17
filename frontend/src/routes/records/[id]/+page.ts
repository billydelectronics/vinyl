// Loads the ID and (best-effort) the record so the component
// doesn't have to parse location or throw on fetch errors.
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
  const rid = Number(params.id);
  let record: any = null;

  if (Number.isFinite(rid) && rid > 0) {
    try {
      const r = await fetch(`/api/records/${rid}`);
      if (r.ok) record = await r.json();
    } catch {
      // ignore; component will show a friendly message
    }
  }

  return { rid, record };
};