<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';

  type Track = {
    position?: string | null;
    title: string;
    duration?: string | null;
    side?: string | null;
  };

  type RecordRow = {
    id: number;
    artist: string;
    title: string;
    year?: number | null;
    label?: string | null;
    catalog_number?: string | null;
    barcode?: string | null;

    cover_local?: string | null;
    cover_url?: string | null;
    cover_url_auto?: string | null;
    discogs_id?: number | null;
    discogs_thumb?: string | null;

    album_notes?: string | null;
    personal_notes?: string | null;
  };

  $: rid = Number($page.params?.id ?? 0);

  let record: RecordRow | null = null;
  let savedSides: Record<string, Track[]> = {};
  let loading = false;
  let err = '';

  function coverUrl(r: RecordRow | null): string | null {
    if (!r) return null;
    return r.cover_url || r.cover_local || r.cover_url_auto || r.discogs_thumb || null;
  }

  async function fetchRecord(id: number) {
    err = '';
    loading = true;
    try {
      const r = await fetch(`/api/records/${id}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      record = (await r.json()) as RecordRow;
    } catch (e: any) {
      err = e?.message || 'Failed to load record';
    } finally {
      loading = false;
    }
  }

  async function fetchSavedTracks(id: number) {
    try {
      const r = await fetch(`/api/records/${id}/tracks?saved=1`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const list = (await r.json()) as Track[];
      const grouped: Record<string, Track[]> = {};
      for (const t of list) {
        const side = (t.side || t.position || '').toString().trim().slice(0, 1) || '?';
        (grouped[side] ||= []).push(t);
      }
      for (const s in grouped) {
        grouped[s].sort((a, b) => {
          const ap = (a.position || '').replace(/[^\d]/g, '');
          const bp = (b.position || '').replace(/[^\d]/g, '');
          const ai = ap ? parseInt(ap, 10) : Number.MAX_SAFE_INTEGER;
          const bi = bp ? parseInt(bp, 10) : Number.MAX_SAFE_INTEGER;
          return ai - bi;
        });
      }
      savedSides = grouped;
    } catch {
      savedSides = {};
    }
  }

  onMount(async () => {
    if (!rid) return;
    await Promise.all([fetchRecord(rid), fetchSavedTracks(rid)]);
  });

  const hasAlbumNotes = (r: RecordRow | null) => !!r?.album_notes?.trim();
  const hasPersonalNotes = (r: RecordRow | null) => !!r?.personal_notes?.trim();
</script>

<div class="mx-auto max-w-5xl p-4 md:p-6">
  {#if err}
    <div class="rounded-md border border-red-700 bg-red-950 text-red-200 p-3 mb-4">
      {err}
    </div>
  {/if}

  {#if loading}
    <div class="text-sm opacity-80">Loading…</div>
  {:else if !record}
    <div class="text-sm opacity-80">Record not found.</div>
  {:else}
    <section class="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-6 mb-8">
      <div class="w-full aspect-square overflow-hidden rounded-md border border-zinc-800 bg-zinc-950">
        {#if coverUrl(record)}
          <img
            class="w-full h-full object-cover"
            src={coverUrl(record)!}
            alt={`${record.artist} – ${record.title}`}
          />
        {:else}
          <div class="w-full h-full grid place-items-center text-zinc-500">No cover</div>
        {/if}
      </div>

      <div class="flex flex-col gap-3">
        <h1 class="text-xl md:text-2xl font-semibold">
          {record.artist} — {record.title}
        </h1>

        <div class="text-sm text-zinc-400 flex flex-wrap gap-x-2 gap-y-1">
          {#if record.year}<span>{record.year}</span>{/if}
          {#if record.label}<span>• {record.label}</span>{/if}
          {#if record.catalog_number}<span>• {record.catalog_number}</span>{/if}
          {#if record.barcode}<span>• {record.barcode}</span>{/if}
        </div>
      </div>
    </section>

    {#if hasAlbumNotes(record) || hasPersonalNotes(record)}
      <section class="space-y-4">
        {#if hasAlbumNotes(record)}
          <div>
            <div class="text-sm font-medium mb-1">Album Notes</div>
            <div class="whitespace-pre-wrap text-sm rounded-md border border-zinc-800 bg-zinc-950 p-3">
              {record.album_notes}
            </div>
          </div>
        {/if}

        {#if hasPersonalNotes(record)}
          <div>
            <div class="text-sm font-medium mb-1">Personal Notes</div>
            <div class="whitespace-pre-wrap text-sm rounded-md border border-zinc-800 bg-zinc-950 p-3">
              {record.personal_notes}
            </div>
          </div>
        {/if}
      </section>
    {/if}

    <section class="space-y-4 mt-8">
      <div class="text-sm opacity-80">Saved Tracks</div>
      {#if savedSides && Object.keys(savedSides).length > 0}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          {#each Object.entries(savedSides) as [side, tracks]}
            <div class="rounded-md border border-zinc-800">
              <div class="px-3 py-2 border-b border-zinc-800 text-sm opacity-80">Side {side}</div>
              <ul class="p-3 space-y-2">
                {#each tracks as t}
                  <li class="flex items-center justify-between gap-3 text-sm">
                    <span class="text-zinc-400 w-10 shrink-0">{t.position || ''}</span>
                    <span class="flex-1">{t.title}</span>
                    <span class="text-zinc-400 w-12 text-right shrink-0">{t.duration || ''}</span>
                  </li>
                {/each}
              </ul>
            </div>
          {/each}
        </div>
      {:else}
        <div class="text-sm text-zinc-400">No tracks have been saved for this record.</div>
      {/if}
    </section>
  {/if}
</div>

<style>
  a { text-decoration: none; }
</style>