import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params }) => {
  const r = await fetch(`/api/records/${params.id}`);
  if (!r.ok) return { record: null };
  return { record: await r.json() };
};