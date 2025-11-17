export const ssr = false;
export const prerender = false;

import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
  const r = await fetch('/api/records', { headers: { accept: 'application/json' } });
  const data = r.ok ? await r.json() : [];
  const arr = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : []);

  const sortKey = (url.searchParams.get('sort') ?? 'title') as 'title' | 'artist' | 'year';
  const sortDir = url.searchParams.get('dir') === 'desc' ? 'desc' : 'asc';

  const sorted = [...arr].sort((a: any, b: any) => {
    const A = (a?.[sortKey] ?? '').toString().toLowerCase();
    const B = (b?.[sortKey] ?? '').toString().toLowerCase();
    return sortDir === 'asc' ? (A > B ? 1 : A < B ? -1 : 0) : (A < B ? 1 : A > B ? -1 : 0);
  });

  return { records: sorted, sortKey, sortDir };
};