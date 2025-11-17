// Run this load only in the browser so /api goes through Caddy
export const ssr = false;
export const prerender = false;

import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
  const res = await fetch('/api/records', { headers: { accept: 'application/json' } });
  if (!res.ok) return { records: [] };
  const data = await res.json();
  // Accept both shapes: array OR { items: [...] }
  const records = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : []);
  return { records };
};