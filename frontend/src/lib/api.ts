export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  const ct = res.headers.get('content-type') || '';
  if (!res.ok) throw new Error(await res.text());
  if (ct.includes('text/csv')) return (await res.text()) as unknown as T;
  return (await res.json()) as T;
}

export type RecordOut = {
  id: string;
  artist: string; title: string; label?: string | null; year?: number | null;
  format?: string | null; catalog_number?: string | null; barcode?: string | null;
  country?: string | null; condition_media?: string | null; condition_cover?: string | null;
  notes?: string | null; location?: string | null;
  added_at: string; updated_at: string; cover_url?: string | null; cover_local?: string | null;
  discogs_id?: string | null; musicbrainz_release_id?: string | null; owned: boolean;
};

export type RecordIn = Omit<RecordOut,'id'|'added_at'|'updated_at'|'cover_local'|'discogs_id'|'musicbrainz_release_id'>;
