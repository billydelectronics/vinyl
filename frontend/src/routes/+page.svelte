<script lang="ts">
  import { onMount } from 'svelte';
  import { toasts } from '$lib/toast';

  type RecordRow = {
    id: number;
    artist: string;
    title: string;
    year?: number | null;
    label?: string | null;
    format?: string | null;
    discogs_thumb?: string | null;
    cover_url?: string | null;
    cover_local?: string | null;
    cover_url_auto?: string | null;
    updated_at?: string;
  };

  // UI state
  let loading = false;
  let error: string | null = null;
  let items: RecordRow[] = [];
  let count = 0;

  // defaults: Artist / Asc
  let q = '';
  let sort: 'updated_at' | 'artist' | 'title' | 'year' | 'label' | 'id' = 'artist';
  let order: 'asc' | 'desc' = 'asc';

  // bulk delete state
  let bulkMode = false;
  let selected: Set<number> = new Set();
  $: selectedCount = selected.size;

  const coverUrl = (r: RecordRow) =>
    r.cover_url || r.cover_local || r.cover_url_auto || r.discogs_thumb || null;

  async function load() {
    loading = true;
    error = null;
    try {
      const url = new URL('/api/records', window.location.origin);
      if (q.trim()) url.searchParams.set('q', q.trim());
      url.searchParams.set('sort', sort);
      url.searchParams.set('order', order);
      url.searchParams.set('limit', '100');
      const res = await fetch(url.toString());
      if (!res.ok) throw new Error(`Failed to load records (${res.status})`);
      const data = await res.json();
      items = data.items || [];
      count = data.count || 0;
      selected = new Set(); // reassign to trigger reactivity
    } catch (e: any) {
      error = e?.message ?? 'Failed to load records';
    } finally {
      loading = false;
    }
  }

  function enterBulk() { bulkMode = true; selected = new Set(); }
  function exitBulk()  { bulkMode = false; selected = new Set(); }
  function toggleSelect(id: number, checked: boolean) {
    const ns = new Set(selected);
    if (checked) ns.add(id); else ns.delete(id);
    selected = ns;
  }
  function selectAll() { selected = new Set(items.map((r) => r.id)); }
  function clearSelection() { selected = new Set(); }

  async function bulkDelete() {
    if (selected.size === 0) return;
    if (!confirm(`Delete ${selected.size} record(s)? This cannot be undone.`)) return;

    const ids = Array.from(selected);
    try {
      const resp = await fetch('/api/records/bulk/delete', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ids })
      });

      if (!resp.ok) {
        // make the error obvious (405/404 = backend route missing)
        throw new Error(`POST /api/records/bulk/delete -> ${resp.status}`);
      }

      toasts.success('Deleted selected records');
      await load();
      exitBulk();
    } catch (e: any) {
      toasts.error(e?.message ?? 'Bulk delete failed');
    }
  }

  function cardHref(id: number) {
    return `/records/edit/${id}`;
  }

  onMount(load);
</script>

<div class="flex items-center justify-between mb-4">
  <h1 class="text-xl font-semibold">Library</h1>

  <div class="flex items-center gap-2">
    <a href="/read" class="px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800">Read-Only</a>
    <a href="/records/new" class="px-3 py-1.5 text-sm rounded-md bg-emerald-600 hover:bg-emerald-700 text-white">Add Record</a>
    {#if !bulkMode}
      <button class="px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800" on:click={enterBulk}>
        Delete (bulk)
      </button>
    {:else}
      <div class="flex items-center gap-2">
        <button class="px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800" on:click={clearSelection}>Clear</button>
        <button class="px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800" on:click={selectAll}>Select All</button>
        <button class="px-3 py-1.5 text-sm rounded-md bg-red-600 hover:bg-red-700 text-white disabled:opacity-50" on:click={bulkDelete} disabled={selectedCount === 0}>
          Delete selected
        </button>
        <button class="px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800" on:click={exitBulk}>Done</button>
      </div>
    {/if}
  </div>
</div>

<!-- Search & Sort -->
<div class="flex flex-wrap items-end gap-3 mb-4">
  <label class="text-sm">
    <div class="mb-1 text-zinc-400">Search</div>
    <input
      class="w-64 max-w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700"
      bind:value={q}
      placeholder="artist, title, label, barcode…"
      on:keydown={(e) => (e.key === 'Enter' ? load() : null)}
    />
  </label>

  <label class="text-sm">
    <div class="mb-1 text-zinc-400">Sort by</div>
    <select class="px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700" bind:value={sort} on:change={load}>
      <option value="artist">Artist</option>
      <option value="title">Title</option>
      <option value="year">Year</option>
      <option value="label">Label</option>
      <option value="updated_at">Recently updated</option>
      <option value="id">ID</option>
    </select>
  </label>

  <label class="text-sm">
    <div class="mb-1 text-zinc-400">Order</div>
    <select class="px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700" bind:value={order} on:change={load}>
      <option value="asc">Asc</option>
      <option value="desc">Desc</option>
    </select>
  </label>

  <button class="px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800" on:click={load}>
    Apply
  </button>
</div>

{#if loading}
  <p class="text-zinc-400">Loading…</p>
{:else if error}
  <p class="text-red-500">{error}</p>
{:else if items.length === 0}
  <p class="text-zinc-400">No records found</p>
{:else}
  <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
    {#each items as r}
      <div class="group relative rounded-lg border border-zinc-800 overflow-hidden">
        {#if coverUrl(r)}
          <a href={bulkMode ? undefined : cardHref(r.id)} class="block" on:click={(e) => bulkMode && e.preventDefault()}>
            <img src={coverUrl(r)!} alt="cover" class="aspect-square w-full object-cover" />
          </a>
        {:else}
          <a href={bulkMode ? undefined : cardHref(r.id)} class="block" on:click={(e) => bulkMode && e.preventDefault()}>
            <div class="aspect-square w-full grid place-items-center text-xs text-zinc-500 bg-zinc-900">no cover</div>
          </a>
        {/if}
        <div class="p-2">
          <div class="text-sm font-semibold truncate">{r.artist || '—'}</div>
          <div class="text-xs text-zinc-400 truncate">{r.title || '—'}</div>
          {#if r.year}<div class="text-xs text-zinc-500">{r.year}</div>{/if}
        </div>

        {#if bulkMode}
          <label class="absolute top-2 left-2 bg-black/70 rounded px-1.5 py-0.5 text-xs border border-zinc-700 flex items-center gap-1">
            <input
              type="checkbox"
              on:change={(e) => toggleSelect(r.id, (e.currentTarget as HTMLInputElement).checked)}
              checked={selected.has(r.id)}
            />
            Select
          </label>
        {/if}
      </div>
    {/each}
  </div>
{/if}