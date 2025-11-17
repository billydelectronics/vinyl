<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';

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
    discogs_thumb?: string | null;
  };

  export let data:
    | { records?: RecordRow[]; sortKey?: 'title' | 'artist' | 'year'; sortDir?: 'asc' | 'desc' }
    | undefined;

  let allRecords: RecordRow[] = data?.records ?? [];
  let sortKey: 'title' | 'artist' | 'year' = 'artist';
  let sortDir: 'asc' | 'desc' = 'asc';
  let search = '';
  let view: 'grid' | 'list' = 'grid';
  let page = 1;
  let pageSize: number | 'ALL' = 'ALL'; // Default to ALL

  let loading = false;
  let err = '';

  $: if (data?.records && data.records !== allRecords) {
    allRecords = data.records;
  }

  function coverUrl(r: RecordRow): string | null {
    return r.cover_url || r.cover_local || r.cover_url_auto || r.discogs_thumb || null;
  }

  async function ensureData() {
    if (allRecords.length) return;
    loading = true; err = '';
    try {
      const res = await fetch('/api/records');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      allRecords = await res.json();
    } catch (e: any) {
      err = e?.message ?? 'Failed to load records';
    } finally {
      loading = false;
    }
  }

  const s = (v: unknown) => (v ?? '').toString().toLowerCase();

  function baseCmp(a: RecordRow, b: RecordRow) {
    const aA = s(a.artist), bA = s(b.artist);
    if (aA !== bA) return aA > bA ? 1 : -1;
    const aT = s(a.title), bT = s(b.title);
    if (aT !== bT) return aT > bT ? 1 : -1;
    return 0;
  }

  function filtered(records: RecordRow[], q: string, key: 'title'|'artist'|'year', dir: 'asc'|'desc'): RecordRow[] {
    const query = q.trim().toLowerCase();
    let rows = records.filter(r => {
      if (!query) return true;
      return [r.artist, r.title, r.label, r.catalog_number, r.barcode]
        .map(v => (v || '').toLowerCase())
        .some(v => v.includes(query));
    });

    rows = rows.slice().sort((a, b) => {
      const A = s((a as any)[key]), B = s((b as any)[key]);
      if (A !== B) return dir === 'asc' ? (A > B ? 1 : -1) : (A < B ? 1 : -1);
      return baseCmp(a, b);
    });

    return rows;
  }

  $: rows = filtered(allRecords, search, sortKey, sortDir);
  $: total = rows.length;
  $: totalPages = pageSize === 'ALL' ? 1 : Math.max(1, Math.ceil(total / (pageSize as number)));
  $: page = Math.min(Math.max(1, page), totalPages);
  $: paged = pageSize === 'ALL' ? rows : rows.slice((page - 1) * (pageSize as number), (page - 1) * (pageSize as number) + (pageSize as number));

  function resetPagination() { page = 1; }
  function openRecord(rid: number) { goto(`/read/${rid}`); }

  function onKeyNav(e: KeyboardEvent, rid: number) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openRecord(rid);
    }
  }

  onMount(() => { ensureData(); });
</script>

<div
  id="read-controls"
  data-role="read-controls"
  class="flex flex-col gap-3 md:flex-row md:flex-nowrap md:items-end md:justify-between mb-4"
>
  <!-- Search with Lucide x-circle clear button -->
  <div class="flex-1 flex flex-col gap-2 min-w-[14rem]">
    <label class="text-sm opacity-80" for="searchInput">Search</label>
    <div class="relative">
      <input
        id="searchInput"
        class="w-full rounded-md bg-zinc-900 border border-zinc-800 px-3 py-2 pr-8 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        placeholder="Artist, title, label, catalog #, barcode…"
        bind:value={search}
        on:input={resetPagination}
      />
      {#if search.trim().length > 0}
        <button
          type="button"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition"
          on:click={() => { search = ''; resetPagination(); }}
          aria-label="Clear search"
          title="Clear search"
        >
          <!-- Lucide x-circle icon -->
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="15" y1="9" x2="9" y2="15"></line>
            <line x1="9" y1="9" x2="15" y2="15"></line>
          </svg>
        </button>
      {/if}
    </div>
  </div>

  <!-- Right group: Sort by / View / # -->
  <div class="flex flex-wrap md:flex-nowrap gap-4 shrink-0">
    <div class="flex flex-col gap-1">
      <label class="text-sm opacity-80" for="sortKey">Sort by</label>
      <div class="flex items-center h-9 gap-2">
        <select
          id="sortKey"
          class="rounded-md bg-zinc-900 border border-zinc-800 h-full px-2 w-24 text-sm"
          bind:value={sortKey}
          on:change={resetPagination}>
          <option value="artist">Artist</option>
          <option value="title">Title</option>
          <option value="year">Year</option>
        </select>

        <select
          id="sortDir"
          class="rounded-md bg-zinc-900 border border-zinc-800 h-full px-2 w-20 text-sm"
          bind:value={sortDir}
          on:change={resetPagination}>
          <option value="asc">Asc</option>
          <option value="desc">Desc</option>
        </select>
      </div>
    </div>

    <div class="flex flex-col gap-1">
      <label class="text-sm opacity-80">View</label>
      <div class="flex items-center h-9 gap-2">
        <div class="inline-flex h-full rounded-md border border-zinc-800 overflow-hidden" role="group" aria-label="Toggle view">
          <button
            class={`px-2.5 inline-flex items-center h-full ${view==='grid' ? 'bg-zinc-800' : ''}`}
            on:click={() => { view='grid'; resetPagination(); }}
            aria-label="Grid view"
            title="Grid view">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <rect x="3" y="3" width="8" height="8" rx="1"></rect>
              <rect x="13" y="3" width="8" height="8" rx="1"></rect>
              <rect x="3" y="13" width="8" height="8" rx="1"></rect>
              <rect x="13" y="13" width="8" height="8" rx="1"></rect>
            </svg>
          </button>
          <button
            class={`px-2.5 inline-flex items-center h-full ${view==='list' ? 'bg-zinc-800' : ''}`}
            on:click={() => { view='list'; resetPagination(); }}
            aria-label="List view"
            title="List view">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <rect x="3" y="5" width="18" height="2" rx="1"></rect>
              <rect x="3" y="11" width="18" height="2" rx="1"></rect>
              <rect x="3" y="17" width="18" height="2" rx="1"></rect>
            </svg>
          </button>
        </div>
      </div>
    </div>

    <div class="flex flex-col gap-1">
      <label class="text-sm opacity-80" for="pageSize">#</label>
      <div class="flex items-center h-9 gap-2">
        <select
          id="pageSize"
          class="rounded-md bg-zinc-900 border border-zinc-800 h-full px-2 w-20 text-center text-sm"
          bind:value={pageSize}
          on:change={() => {
            pageSize = pageSize === 'ALL' ? 'ALL' : parseInt(String(pageSize)) || 24;
            resetPagination();
          }}>
          <option value="ALL">ALL</option>
          <option value="12">12</option>
          <option value="24">24</option>
          <option value="48">48</option>
          <option value="96">96</option>
        </select>
      </div>
    </div>
  </div>
</div>

{#if loading}
  <div class="py-24 text-center opacity-80">Loading records…</div>
{:else if err}
  <div class="py-24 text-center text-red-400">{err}</div>
{:else}
  <div class="flex items-center justify-between mb-3">
    <div class="text-sm opacity-80">{total} {total === 1 ? 'record' : 'records'}</div>
    {#if totalPages > 1}
      <div class="flex items-center gap-2">
        <button class="px-2 py-1 rounded border border-zinc-800 disabled:opacity-50" on:click={() => page = 1} disabled={page===1}>⏮</button>
        <button class="px-2 py-1 rounded border border-zinc-800 disabled:opacity-50" on:click={() => page = Math.max(1, page-1)} disabled={page===1}>‹ Prev</button>
        <div class="text-sm">Page {page} / {totalPages}</div>
        <button class="px-2 py-1 rounded border border-zinc-800 disabled:opacity-50" on:click={() => page = Math.min(totalPages, page+1)} disabled={page===totalPages}>Next ›</button>
        <button class="px-2 py-1 rounded border border-zinc-800 disabled:opacity-50" on:click={() => page = totalPages} disabled={page===totalPages}>⏭</button>
      </div>
    {/if}
  </div>

  {#if view === 'grid'}
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
      {#each paged as r}
        <div
          class="group relative rounded-lg overflow-hidden border border-zinc-800 bg-zinc-950 hover:border-indigo-600 transition cursor-pointer"
          role="button"
          tabindex="0"
          on:click={() => openRecord(r.id)}
          on:keydown={(e) => onKeyNav(e, r.id)}>
          <div class="aspect-square bg-zinc-900 flex items-center justify-center overflow-hidden">
            {#if coverUrl(r)}
              <img src={coverUrl(r)!} alt={`${r.artist} – ${r.title}`} class="w-full h-full object-cover" />
            {:else}
              <div class="w-12 h-12 rounded border border-dashed border-zinc-700 flex items-center justify-center text-xs text-zinc-500">No Cover</div>
            {/if}
          </div>
          <div class="p-3 space-y-1">
            <div class="text-base font-semibold leading-tight line-clamp-2">{r.title || 'Untitled'}</div>
            <div class="text-sm opacity-80 leading-tight line-clamp-2">{r.artist || 'Unknown Artist'}</div>
            <div class="text-xs opacity-60">{r.year ?? ''}</div>
          </div>
        </div>
      {/each}
    </div>
  {:else}
    <div class="rounded-md border border-zinc-800 overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-zinc-900">
          <tr class="text-left">
            <th class="p-3 w-16">Cover</th>
            <th class="p-3">Title</th>
            <th class="p-3">Artist</th>
            <th class="p-3">Year</th>
          </tr>
        </thead>
        <tbody>
          {#each paged as r}
            <tr class="border-t border-zinc-800 hover:bg-zinc-900/60">
              <td class="p-2">
                {#if coverUrl(r)}
                  <img
                    src={coverUrl(r)!}
                    alt="Open record"
                    class="w-12 h-12 object-cover rounded cursor-pointer"
                    on:click={() => openRecord(r.id)} />
                {:else}
                  <button class="w-12 h-12 rounded border border-dashed border-zinc-700 text-[10px] text-zinc-500" on:click={() => openRecord(r.id)}>
                    Open
                  </button>
                {/if}
              </td>
              <td class="p-2 font-medium">{r.title}</td>
              <td class="p-2">{r.artist}</td>
              <td class="p-2">{r.year ?? ''}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
{/if}

<style>
  .line-clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
</style>