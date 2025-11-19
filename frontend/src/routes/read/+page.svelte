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

  // ---------- State ----------
  let allRecords: RecordRow[] = data?.records ?? [];
  // Default sort is artist
  let sortKey: 'title' | 'artist' | 'year' = data?.sortKey ?? 'artist';
  let sortDir: 'asc' | 'desc' = data?.sortDir ?? 'asc';
  let search = '';
  let view: 'grid' | 'list' = 'grid';
  let page = 1;
  let pageSize: 'ALL' | '24' | '48' | '96' = 'ALL';

  const STATE_KEY = 'readSearchState_v3';
  const PAGE_SIZES: Record<'24' | '48' | '96', number> = {
    '24': 24,
    '48': 48,
    '96': 96
  };

  let loading = false;
  let err = '';

  // ---------- Data sync from load() ----------
  $: if (data?.records && data.records !== allRecords) {
    allRecords = data.records;
  }

  function coverUrl(r: RecordRow): string | null {
    return r.cover_url || r.cover_local || r.cover_url_auto || r.discogs_thumb || null;
  }

  async function ensureData() {
    if (allRecords.length) return;
    loading = true;
    err = '';
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

  // Strip leading "the " (case-insensitive) for artist sort
  function normalizeArtistForSort(name: unknown): string {
    const v = s(name);
    return v.startsWith('the ') ? v.slice(4) : v;
  }

  function baseCmp(a: RecordRow, b: RecordRow) {
    // Use normalized artist for tie-breaking too
    const aA = normalizeArtistForSort(a.artist);
    const bA = normalizeArtistForSort(b.artist);
    if (aA !== bA) return aA > bA ? 1 : -1;
    const aT = s(a.title);
    const bT = s(b.title);
    if (aT !== bT) return aT > bT ? 1 : -1;
    return 0;
  }

  function filtered(
    records: RecordRow[],
    q: string,
    key: 'title' | 'artist' | 'year',
    dir: 'asc' | 'desc'
  ): RecordRow[] {
    const query = q.trim().toLowerCase();
    let rows = records.filter((r) => {
      if (!query) return true;
      return [r.artist, r.title, r.label, r.catalog_number, r.barcode]
        .map((v) => (v || '').toLowerCase())
        .some((v) => v.includes(query));
    });

    rows = rows.slice().sort((a, b) => {
      let A: string;
      let B: string;

      if (key === 'artist') {
        // Ignore leading "The " when sorting by artist
        A = normalizeArtistForSort(a.artist);
        B = normalizeArtistForSort(b.artist);
      } else {
        A = s((a as any)[key]);
        B = s((b as any)[key]);
      }

      if (A !== B) {
        return dir === 'asc' ? (A > B ? 1 : -1) : A < B ? 1 : -1;
      }
      return baseCmp(a, b);
    });

    return rows;
  }

  // ---------- Derived rows / pagination ----------
  $: rows = filtered(allRecords, search, sortKey, sortDir);
  $: total = rows.length;
  $: pageSizeNum = pageSize === 'ALL' ? null : PAGE_SIZES[pageSize];
  $: totalPages = pageSizeNum == null ? 1 : Math.max(1, Math.ceil(total / pageSizeNum));
  $: page = Math.min(Math.max(1, page), totalPages);
  $: paged =
    pageSizeNum == null
      ? rows
      : rows.slice((page - 1) * pageSizeNum, (page - 1) * pageSizeNum + pageSizeNum);

  // ---------- Persistence helpers ----------
  function saveState() {
    if (typeof localStorage === 'undefined') return;
    try {
      const state = { search, sortKey, sortDir, view, pageSize, page };
      localStorage.setItem(STATE_KEY, JSON.stringify(state));
    } catch {
      // ignore
    }
  }

  function loadState() {
    if (typeof localStorage === 'undefined') return;
    try {
      const raw = localStorage.getItem(STATE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);

      if (typeof saved.search === 'string') search = saved.search;
      if (saved.sortKey === 'artist' || saved.sortKey === 'title' || saved.sortKey === 'year') {
        sortKey = saved.sortKey;
      }
      if (saved.sortDir === 'asc' || saved.sortDir === 'desc') {
        sortDir = saved.sortDir;
      }
      if (saved.view === 'grid' || saved.view === 'list') {
        view = saved.view;
      }
      if (
        saved.pageSize === 'ALL' ||
        saved.pageSize === '24' ||
        saved.pageSize === '48' ||
        saved.pageSize === '96'
      ) {
        pageSize = saved.pageSize;
      }
      if (typeof saved.page === 'number' && saved.page > 0) {
        page = saved.page;
      }
    } catch {
      // ignore bad JSON
    }
  }

  function resetPagination() {
    page = 1;
  }

  function openRecord(rid: number) {
    // ensure we persist before navigating away
    saveState();
    goto(`/read/${rid}`);
  }

  function onKeyNav(e: KeyboardEvent, rid: number) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openRecord(rid);
    }
  }

  // ---------- Input / control handlers ----------
  function handleSearchInput(event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    search = target.value;
    resetPagination();
    saveState();
  }

  function clearSearch() {
    search = '';
    resetPagination();
    saveState();
  }

  function handleSortKeyChange(event: Event) {
    const target = event.currentTarget as HTMLSelectElement;
    sortKey = target.value as 'artist' | 'title' | 'year';
    resetPagination();
    saveState();
  }

  function handleSortDirChange(event: Event) {
    const target = event.currentTarget as HTMLSelectElement;
    sortDir = target.value as 'asc' | 'desc';
    resetPagination();
    saveState();
  }

  function setView(next: 'grid' | 'list') {
    if (view === next) return;
    view = next;
    saveState();
  }

  function handlePageSizeChange(event: Event) {
    const target = event.currentTarget as HTMLSelectElement;
    const val = target.value as 'ALL' | '24' | '48' | '96';
    pageSize = val;
    resetPagination();
    saveState();
  }

  function gotoPrevPage() {
    if (page <= 1) return;
    page = Math.max(1, page - 1);
    saveState();
  }

  function gotoNextPage() {
    if (page >= totalPages) return;
    page = Math.min(totalPages, page + 1);
    saveState();
  }

  onMount(() => {
    loadState();
    ensureData();
  });
</script>

<div
  id="read-controls"
  data-role="read-controls"
  class="flex flex-col gap-3 md:flex-row md:flex-nowrap md:items-end md:justify-between mb-4"
>
  <!-- Search -->
  <div class="flex-1 flex flex-col gap-2 min-w-[14rem]">
    <label class="text-sm opacity-80" for="searchInput">Search</label>
    <div class="relative">
      <input
        id="searchInput"
        class="w-full rounded-md bg-zinc-900 border border-zinc-800 px-3 py-2 pr-8 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        placeholder="Artist, title, label, catalog #, barcode…"
        value={search}
        on:input={handleSearchInput}
      />
      {#if search.trim().length > 0}
        <button
          type="button"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition"
          on:click={clearSearch}
          aria-label="Clear search"
          title="Clear search"
        >
          <!-- Lucide x-circle icon -->
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
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
          value={sortKey}
          on:change={handleSortKeyChange}
        >
          <option value="artist">Artist</option>
          <option value="title">Title</option>
          <option value="year">Year</option>
        </select>

        <select
          id="sortDir"
          class="rounded-md bg-zinc-900 border border-zinc-800 h-full px-2 w-20 text-sm"
          value={sortDir}
          on:change={handleSortDirChange}
        >
          <option value="asc">Asc</option>
          <option value="desc">Desc</option>
        </select>
      </div>
    </div>

    <div class="flex flex-col gap-1">
      <span class="text-sm opacity-80">View</span>
      <div class="flex items-center h-9 gap-2">
        <button
          type="button"
          class="flex items-center justify-center h-9 w-9 rounded-md border text-sm {view === 'grid'
            ? 'border-indigo-500 bg-indigo-500/20'
            : 'border-zinc-800 hover:border-zinc-600'}"
          on:click={() => setView('grid')}
          aria-pressed={view === 'grid'}
        >
          <!-- Grid icon -->
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <rect x="3" y="3" width="7" height="7"></rect>
            <rect x="14" y="3" width="7" height="7"></rect>
            <rect x="14" y="14" width="7" height="7"></rect>
            <rect x="3" y="14" width="7" height="7"></rect>
          </svg>
        </button>

        <button
          type="button"
          class="flex items-center justify-center h-9 w-9 rounded-md border text-sm {view === 'list'
            ? 'border-indigo-500 bg-indigo-500/20'
            : 'border-zinc-800 hover:border-zinc-600'}"
          on:click={() => setView('list')}
          aria-pressed={view === 'list'}
        >
          <!-- List icon -->
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <rect x="3" y="5" width="18" height="2" rx="1"></rect>
            <rect x="3" y="11" width="18" height="2" rx="1"></rect>
            <rect x="3" y="17" width="18" height="2" rx="1"></rect>
          </svg>
        </button>
      </div>
    </div>

    <div class="flex flex-col gap-1">
      <label class="text-sm opacity-80" for="pageSize">#</label>
      <div class="flex items-center h-9 gap-2">
        <select
          id="pageSize"
          class="rounded-md bg-zinc-900 border border-zinc-800 h-full px-2 w-20 text-center text-sm"
          value={pageSize}
          on:change={handlePageSizeChange}
        >
          <option value="ALL">ALL</option>
          <option value="24">24</option>
          <option value="48">48</option>
          <option value="96">96</option>
        </select>
      </div>
    </div>
  </div>
</div>

{#if err}
  <div class="text-red-400 text-sm mb-4">
    {err}
  </div>
{:else if loading && !allRecords.length}
  <div class="text-sm text-zinc-400">Loading records…</div>
{:else}
  {#if !allRecords.length}
    <div class="text-sm text-zinc-400">No records found.</div>
  {:else}
    <!-- Results summary + pagination -->
    <div class="flex items-center justify-between mb-3 text-xs text-zinc-400 gap-2 flex-wrap">
      <div>
        Showing
        {#if pageSize === 'ALL'}
          {total}
        {:else}
          {Math.min(
            total,
            (page - 1) * (pageSizeNum ?? total) + (pageSizeNum ?? total)
          )}
        {/if}
        of {total} record{total === 1 ? '' : 's'}
      </div>
      {#if pageSize !== 'ALL' && totalPages > 1}
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="px-2 py-1 rounded border border-zinc-800 disabled:opacity-40"
            on:click={gotoPrevPage}
            disabled={page <= 1}
          >
            Prev
          </button>
          <span>Page {page} / {totalPages}</span>
          <button
            type="button"
            class="px-2 py-1 rounded border border-zinc-800 disabled:opacity-40"
            on:click={gotoNextPage}
            disabled={page >= totalPages}
          >
            Next
          </button>
        </div>
      {/if}
    </div>

    <!-- Grid / list render -->
    {#if view === 'grid'}
      <div class="grid gap-3 grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
        {#each paged as r}
          <button
            type="button"
            class="group flex flex-col text-left rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 hover:border-indigo-500/70 hover:bg-zinc-800/70 transition focus:outline-none focus:ring-2 focus:ring-indigo-500"
            on:click={() => openRecord(r.id)}
            on:keydown={(e) => onKeyNav(e, r.id)}
          >
            <div class="aspect-square bg-black/40 overflow-hidden">
              {#if coverUrl(r)}
                <img
                  src={coverUrl(r) ?? ''}
                  alt={`${r.artist} – ${r.title}`}
                  class="w-full h-full object-cover"
                  loading="lazy"
                />
              {:else}
                <div class="w-full h-full flex items-center justify-center text-zinc-600 text-xs">
                  No cover
                </div>
              {/if}
            </div>
            <div class="p-2">
              <div class="font-semibold text-xs line-clamp-2 group-hover:text-indigo-300">
                {r.title}
              </div>
              <div class="text-[0.7rem] text-zinc-400 line-clamp-1">
                {r.artist}{#if r.year} · {r.year}{/if}
              </div>
              {#if r.label}
                <div class="text-[0.65rem] text-zinc-500 line-clamp-1 mt-0.5">
                  {r.label}
                </div>
              {/if}
            </div>
          </button>
        {/each}
      </div>
    {:else}
      <div class="border border-zinc-800 rounded-md overflow-hidden">
        <table class="w-full text-sm border-collapse">
          <thead class="bg-zinc-900/80 text-xs text-zinc-400">
            <tr>
              <th class="text-left p-2 w-16">Cover</th>
              <th class="text-left p-2">Title</th>
              <th class="text-left p-2">Artist</th>
              <th class="text-left p-2 w-16">Year</th>
            </tr>
          </thead>
          <tbody>
            {#each paged as r}
              <tr
                class="border-t border-zinc-800 hover:bg-zinc-900 cursor-pointer"
                on:click={() => openRecord(r.id)}
                on:keydown={(e) => onKeyNav(e, r.id)}
                tabindex="0"
              >
                <td class="p-2">
                  <div class="w-12 h-12 bg-black/40 overflow-hidden rounded">
                    {#if coverUrl(r)}
                      <img
                        src={coverUrl(r) ?? ''}
                        alt={`${r.artist} – ${r.title}`}
                        class="w-full h-full object-cover"
                        loading="lazy"
                      />
                    {:else}
                      <div class="w-full h-full flex items-center justify-center text-zinc-600 text-[0.65rem]">
                        No cover
                      </div>
                    {/if}
                  </div>
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
{/if}

<style>
  .line-clamp-2 {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
</style>