<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';

  // ---------- Types ----------
  type RecordRow = {
    id: number;
    artist: string;
    title: string;
    year?: number | null;
    label?: string | null;
    format?: string | null;
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
  let search = '';
  let sortKey: 'title' | 'artist' | 'year' = data?.sortKey ?? 'artist';
  let sortDir: 'asc' | 'desc' = data?.sortDir ?? 'asc';
  let loading = false;
  let err = '';

  $: if (data?.records && data.records !== allRecords) {
    allRecords = data.records;
  }

  // ---------- Helpers ----------
  function coverUrl(r: RecordRow): string | null {
    return r.cover_url || r.cover_local || r.cover_url_auto || r.discogs_thumb || null;
  }

  const s = (v: unknown) => (v ?? '').toString().toLowerCase();

  function baseCmp(a: RecordRow, b: RecordRow) {
    const aA = s(a.artist);
    const bA = s(b.artist);
    if (aA !== bA) return aA > bA ? 1 : -1;

    const aT = s(a.title);
    const bT = s(b.title);
    if (aT !== bT) return aT > bT ? 1 : -1;

    const aY = a.year ?? 0;
    const bY = b.year ?? 0;
    if (aY !== bY) return aY > bY ? 1 : -1;

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
      const A = s((a as any)[key]);
      const B = s((b as any)[key]);
      if (A !== B) {
        return dir === 'asc' ? (A > B ? 1 : -1) : (A < B ? 1 : -1);
      }
      return baseCmp(a, b);
    });

    return rows;
  }

  let rows: RecordRow[] = [];
  $: rows = filtered(allRecords, search, sortKey, sortDir);

  // ---------- Fetch ----------
  async function ensureData() {
    loading = true;
    err = '';
    const url = '/api/records';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);

    try {
      const res = await fetch(url, {
        method: 'GET',
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
        signal: controller.signal
      });

      if (!res.ok) {
        let body = '';
        try {
          body = await res.text();
        } catch {
          // ignore
        }
        throw new Error(
          `HTTP ${res.status} ${res.statusText}${body ? ` — ${body.slice(0, 200)}` : ''}`
        );
      }

      const json = (await res.json()) as any;
      let arr: unknown = json;
      const candidates = ['items', 'records', 'data', 'results', 'rows'];
      if (!Array.isArray(arr)) {
        for (const k of candidates) {
          if (json && typeof json === 'object' && Array.isArray(json[k])) {
            arr = json[k];
            break;
          }
        }
      }
      if (!Array.isArray(arr)) {
        throw new Error('Response JSON is not an array.');
      }

      allRecords = (arr as unknown[]).map((r) => r as RecordRow);
    } catch (e: any) {
      err =
        e?.name === 'AbortError'
          ? 'Request timed out after 8s.'
          : e?.message ?? 'Failed to load records';
    } finally {
      clearTimeout(timeout);
      loading = false;
    }
  }

  onMount(ensureData);

  // ---------- Bulk delete ----------
  let selectedIds = new Set<number>();

  function toggleAll(checked: boolean) {
    if (checked) {
      rows.forEach((r) => selectedIds.add(r.id));
    } else {
      selectedIds.clear();
    }
    // force reactivity
    selectedIds = new Set(selectedIds);
  }

  function toggleRow(id: number, checked: boolean) {
    if (checked) {
      selectedIds.add(id);
    } else {
      selectedIds.delete(id);
    }
    // force reactivity
    selectedIds = new Set(selectedIds);
  }

  let deleteBusy = false;

  async function bulkDelete() {
    if (!selectedIds.size) return;
    if (!confirm(`Delete ${selectedIds.size} record(s)? This cannot be undone.`)) return;

    deleteBusy = true;
    try {
      for (const id of Array.from(selectedIds)) {
        const res = await fetch(`/api/records/${id}`, {
          method: 'DELETE',
          credentials: 'same-origin'
        });
        if (!res.ok) {
          throw new Error(await res.text());
        }
      }
      selectedIds.clear();
      await ensureData();
    } catch (e: any) {
      alert(`Bulk delete failed: ${e?.message ?? e}`);
    } finally {
      deleteBusy = false;
    }
  }

  // ---------- Export CSV (client-side; all columns) ----------
  let exportBusy = false;

  async function exportCsv() {
    if (!allRecords || allRecords.length === 0) {
      alert('No records to export.');
      return;
    }

    exportBusy = true;

    try {
      const headerSet = new Set<string>();
      for (const row of allRecords) {
        if (row && typeof row === 'object') {
          for (const key of Object.keys(row as Record<string, unknown>)) {
            headerSet.add(key);
          }
        }
      }

      const headers = Array.from(headerSet);
      if (headers.length === 0) {
        alert('No columns to export.');
        return;
      }

      const escapeCsv = (value: unknown): string => {
        if (value === null || value === undefined) return '';
        const str = String(value);
        if (/[",\n]/.test(str)) {
          return `"${str.replace(/"/g, '""')}"`;
        }
        return str;
      };

      const lines: string[] = [];
      lines.push(headers.join(','));

      for (const row of allRecords) {
        const line = headers
          .map((key) => escapeCsv((row as Record<string, unknown>)[key]))
          .join(',');
        lines.push(line);
      }

      const csvContent = lines.join('\r\n');
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const defaultName = `records_full_export_${new Date()
        .toISOString()
        .slice(0, 19)
        .replace(/[:T]/g, '-')}.csv`;
      a.href = url;
      a.download = defaultName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e?.message ?? 'Export failed.');
    } finally {
      exportBusy = false;
    }
  }

  // ---------- Cover embedding tools ----------
  let coverRebuildBusy = false;
  let coverMissingBusy = false;

  const COVER_REBUILD_URL = '/api/cover-embeddings/rebuild';
  const COVER_BUILD_MISSING_URL = '/api/cover-embeddings/build-missing';

  async function rebuildAllCoverEmbeddings() {
    if (!confirm('Rebuild cover embeddings for ALL records? This may take a while.')) return;

    coverRebuildBusy = true;
    try {
      const res = await fetch(COVER_REBUILD_URL, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      });

      const text = await res.text();

      if (!res.ok) {
        throw new Error(`HTTP ${res.status} — ${text.slice(0, 200)}`);
      }

      // Attempt to parse JSON
      let data: any = null;
      try {
        data = JSON.parse(text);
      } catch {
        // If parsing fails, fall back to raw text
        alert(`Rebuild complete.\n\nRaw response:\n${text}`);
        return;
      }

      // Expected shape: { processed: N, skipped_no_image: M, errors: X }
      const { processed, skipped_no_image, errors } = data;

      alert(
        `Rebuild complete:\n\n` +
          `Processed: ${processed}\n` +
          `Skipped (no image): ${skipped_no_image}\n` +
          `Errors: ${errors}`
      );
    } catch (e: any) {
      alert(e?.message ?? 'Failed to rebuild cover embeddings.');
    } finally {
      coverRebuildBusy = false;
    }
  }

  async function buildMissingCoverEmbeddings() {
    if (!confirm('Build cover embeddings only for records that are missing them?')) return;

    coverMissingBusy = true;
    try {
      const res = await fetch(COVER_BUILD_MISSING_URL, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      });

      const text = await res.text();

      if (!res.ok) {
        throw new Error(`HTTP ${res.status} — ${text.slice(0, 200)}`);
      }

      // Try parsing JSON
      let data: any = null;
      try {
        data = JSON.parse(text);
      } catch {
        alert(`Build complete.\n\nRaw response:\n${text}`);
        return;
      }

      // Expected structure: { processed, skipped_no_image, errors }
      const { processed, skipped_no_image, errors } = data;

      alert(
        `Build missing cover embeddings complete:\n\n` +
          `Processed: ${processed}\n` +
          `Skipped (no image): ${skipped_no_image}\n` +
          `Errors: ${errors}`
      );
    } catch (e: any) {
      alert(e?.message ?? 'Failed to build missing cover embeddings.');
    } finally {
      coverMissingBusy = false;
    }
  }

  // ---------- Nav actions ----------
  function goAdd() {
    goto('/utility/new');
  }
  function editRow(id: number) {
    goto(`/utility/${id}`);
  }
  function goImport() {
    goto('/utility/import');
  }
</script>

<!-- FULL PAGE DARK THEME -->
<div class="min-h-screen bg-gray-950 text-gray-100">
  <!-- Top Nav -->
  <div class="w-full border-b border-gray-800 bg-gray-900 text-white sticky top-0 z-10">
    <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <a href="/" class="font-semibold text-xl text-white">Vinyl</a>
        <span class="text-sm text-gray-300">/ Utility</span>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <button
          class="px-3 py-1.5 rounded-lg border border-white/20 bg-transparent text-white hover:bg-white/5"
          on:click={goAdd}
        >
          Add Record
        </button>

        <button
          class="px-3 py-1.5 rounded-lg border border-emerald-400/40 bg-emerald-500/10 text-emerald-100 hover:bg-emerald-500/20"
          on:click={goImport}
        >
          Import CSV
        </button>

        <button
          class="px-3 py-1.5 rounded-lg border border-white/20 bg-transparent text-white hover:bg-white/5 disabled:opacity-50"
          disabled={exportBusy || loading || !allRecords.length}
          on:click={exportCsv}
        >
          {exportBusy ? 'Exporting…' : 'Export CSV'}
        </button>

        <!-- Embedding tools in nav bar -->
        <button
          class="px-3 py-1.5 rounded-lg border border-indigo-400/60 bg-indigo-500/10 text-indigo-100 hover:bg-indigo-500/20 disabled:opacity-50 text-sm"
          on:click={rebuildAllCoverEmbeddings}
          disabled={coverRebuildBusy || coverMissingBusy}
        >
          {coverRebuildBusy ? 'Rebuilding…' : 'Rebuild All'}
        </button>

        <button
          class="px-3 py-1.5 rounded-lg border border-sky-400/60 bg-sky-500/10 text-sky-100 hover:bg-sky-500/20 disabled:opacity-50 text-sm"
          on:click={buildMissingCoverEmbeddings}
          disabled={coverRebuildBusy || coverMissingBusy}
        >
          {coverMissingBusy ? 'Building…' : 'Build Missing'}
        </button>
      </div>
    </div>
  </div>

  <!-- Controls Bar -->
  <div class="w-full border-b border-gray-800 bg-gray-900 text-white">
    <div class="max-w-7xl mx-auto px-4 py-3 flex flex-wrap items-center gap-3">
      {#if err}
        <div class="w-full p-3 rounded-lg bg-red-500/15 text-red-200 border border-red-500/30">
          {err}
        </div>
      {/if}

      <input
        class="border border-white/20 rounded-lg px-3 py-2 w-full sm:w-80 bg-gray-800 text-white placeholder-gray-400"
        placeholder="Search artist, title, label, barcode…"
        bind:value={search}
      />

      <div class="flex items-center gap-2">
        <label class="text-sm text-gray-300">Sort by</label>
        <select
          class="border border-white/20 rounded-lg px-2 py-2 bg-gray-800 text-white"
          bind:value={sortKey}
        >
          <option value="artist">Artist</option>
          <option value="title">Title</option>
          <option value="year">Year</option>
        </select>

        <label class="text-sm text-gray-300">Order</label>
        <select
          class="border border-white/20 rounded-lg px-2 py-2 bg-gray-800 text-white"
          bind:value={sortDir}
        >
          <option value="asc">Asc</option>
          <option value="desc">Desc</option>
        </select>
      </div>

      <button
        class="ml-auto px-3 py-2 rounded-lg border border-rose-500/60 bg-rose-500/10 text-rose-100 hover:bg-rose-500/20 disabled:opacity-50"
        disabled={!rows.length || !selectedIds.size || deleteBusy}
        on:click={bulkDelete}
      >
        {deleteBusy ? 'Deleting…' : `Delete Selected (${selectedIds.size})`}
      </button>
    </div>
  </div>

  <!-- List -->
  <div class="max-w-7xl mx-auto px-4 py-4">
    <div class="border border-gray-800 rounded-xl overflow-hidden bg-gray-900">
      <table class="w-full text-sm">
        <thead class="bg-gray-800 text-white">
          <tr class="text-left">
            <th class="p-3 w-10">
              <input
                type="checkbox"
                on:change={(e) => toggleAll((e.target as HTMLInputElement).checked)}
                checked={rows.length > 0 && selectedIds.size === rows.length}
              />
            </th>
            <th class="p-3">Cover</th>
            <th class="p-3">Title</th>
            <th class="p-3">Artist</th>
            <th class="p-3">Year</th>
            <th class="p-3 w-28">Action</th>
          </tr>
        </thead>
        <tbody class="text-gray-100">
          {#if loading}
            <tr>
              <td class="p-5 text-center text-gray-400" colspan="6">Loading…</td>
            </tr>
          {:else if !allRecords || allRecords.length === 0}
            <tr>
              <td class="p-6 text-center text-gray-400" colspan="6">
                No records yet. Use <span class="font-medium">Add Record</span> or
                <span class="font-medium">Import CSV</span>.
              </td>
            </tr>
          {:else if rows.length === 0}
            <tr>
              <td class="p-6 text-center text-gray-400" colspan="6">
                No records match your search.
              </td>
            </tr>
          {:else}
            {#each rows as r}
              <tr class="border-t border-gray-800 hover:bg-gray-800/60">
                <td class="p-3 align-middle">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(r.id)}
                    on:change={(e) => toggleRow(r.id, (e.target as HTMLInputElement).checked)}
                  />
                </td>
                <td class="p-3 align-middle">
                  {#if coverUrl(r)}
                    <a
                      href={`/utility/${r.id}`}
                      class="inline-block rounded overflow-hidden focus:outline-none focus:ring"
                    >
                      <img
                        class="w-10 h-10 object-cover rounded-md border border-gray-700"
                        src={coverUrl(r) ?? ''}
                        alt={`${r.artist} – ${r.title}`}
                        loading="lazy"
                      />
                    </a>
                  {:else}
                    <div
                      class="w-10 h-10 flex items-center justify-center rounded-md border border-dashed border-gray-700 text-xs text-gray-500"
                    >
                      No cover
                    </div>
                  {/if}
                </td>
                <td class="p-3 align-middle">
                  <a href={`/utility/${r.id}`} class="text-white hover:underline">{r.title}</a>
                </td>
                <td class="p-3 align-middle text-gray-300">{r.artist}</td>
                <td class="p-3 align-middle text-gray-300">{r.year ?? ''}</td>
                <td class="p-3 align-middle">
                  <button
                    class="px-2 py-1 rounded-lg border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-100"
                    on:click={() => editRow(r.id)}
                  >
                    Edit
                  </button>
                </td>
              </tr>
            {/each}
          {/if}
        </tbody>
      </table>
    </div>
  </div>
</div>