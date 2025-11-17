import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
  const rid = Number(params.id);
  let record: any = null;
  let tracks: any[] = [];

  if (Number.isFinite(rid) && rid > 0) {
    try {
      const r = await fetch(`/api/records/${rid}`);
      if (r.ok) record = await r.json();
    } catch {}
    try {
      const t = await fetch(`/api/records/${rid}/tracks`);
      if (t.ok) tracks = await t.json();
    } catch {}
  }

  return { rid, record, tracks };
};