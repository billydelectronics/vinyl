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
      const A = s((a as any)[key]);
      const B = s((b as any)[key]);
      if (A !== B) return dir === 'asc' ? (A > B ? 1 : -1) : (A < B ? 1 : -1);
      return baseCmp(a, b);
    });
    return rows;
  }
  let rows: RecordRow[] = [];
  $: rows = filtered(allRecords, search, sortKey, sortDir);

  // ---------- Fetch ----------
  async function ensureData() {
    loading = true; err = '';
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
        try { body = await res.text(); } catch {}
        throw new Error(`HTTP ${res.status} ${res.statusText}${body ? ` — ${body.slice(0,200)}` : ''}`);
      }
      const json = await res.json() as any;
      let arr: unknown = json;
      const candidates = ['items','records','data','results','rows'];
      if (!Array.isArray(arr)) {
        for (const k of candidates) {
          if (json && typeof json === 'object' && Array.isArray(json[k])) {
            arr = json[k]; break;
          }
        }
      }
      if (!Array.isArray(arr)) {
        throw new Error('Response JSON is not an array.');
      }
      allRecords = (arr as unknown[]).map((r) => r as RecordRow);
    } catch (e: any) {
      err = e?.name === 'AbortError' ? 'Request timed out after 8s.' : (e?.message ?? 'Failed to load records');
    } finally {
      clearTimeout(timeout);
      loading = false;
    }
  }
  onMount(ensureData);

  // ---------- Bulk delete ----------
  let selectedIds = new Set<number>();
  function toggleAll(checked: boolean) { if (checked) rows.forEach((r) => selectedIds.add(r.id)); else selectedIds.clear(); selectedIds = new Set(selectedIds); }
  function toggleRow(id: number, checked: boolean) { if (checked) selectedIds.add(id); else selectedIds.delete(id); selectedIds = new Set(selectedIds); }

  let deleteBusy = false;
  async function bulkDelete() {
    if (!selectedIds.size) return;
    if (!confirm(`Delete ${selectedIds.size} record(s)? This cannot be undone.`)) return;
    deleteBusy = true;
    try {
      for (const id of Array.from(selectedIds)) {
        const res = await fetch(`/api/records/${id}`, { method: 'DELETE', credentials: 'same-origin' });
        if (!res.ok) throw new Error(await res.text());
      }
      selectedIds.clear();
      await ensureData();
    } catch (e: any) {
      alert(`Bulk delete failed: ${e?.message ?? e}`);
    } finally {
      deleteBusy = false;
    }
  }

  // ---------- Export (server-side) ----------
  let exportBusy = false;

  function filenameFromContentDisposition(hdr: string | null | undefined, fallback: string): string {
    if (!hdr) return fallback;
    const mStar = /filename\*\s*=\s*([^']*)'[^']*'([^;]+)/i.exec(hdr);
    if (mStar && mStar[2]) return decodeURIComponent(mStar[2]).replace(/["]/g, '');
    const m = /filename\s*=\s*("?)([^";]+)\1/i.exec(hdr);
    if (m && m[2]) return m[2];
    return fallback;
  }

  async function exportCsv() {
    exportBusy = true;
    try {
      const res = await fetch('/api/export/csv', { method: 'GET', credentials: 'same-origin' });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition');
      const defaultName = `records_export_${new Date().toISOString().slice(0,19).replace(/[:T]/g,'-')}.csv`;
      const fname = filenameFromContentDisposition(cd, defaultName);

      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = fname || defaultName;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(e?.message ?? 'Export failed.');
    } finally {
      exportBusy = false;
    }
  }

  // ---------- Import CSV ----------
  let importBusy = false;
  let fileEl: HTMLInputElement | null = null;
  let lastProcessedKey = '';
  let importFiring = false;

  function startImport() {
    fileEl?.click();
  }

  async function handlePickedFile() {
    const file = fileEl?.files?.[0];
    if (!file) return;
    const key = `${file.name}:${file.size}:${file.lastModified}`;
    if (importFiring || key === lastProcessedKey) return;
    importFiring = true;
    lastProcessedKey = key;

    importBusy = true;
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch('/api/import/csv', {
        method: 'POST',
        body: fd,
        credentials: 'same-origin'
      });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(`Import failed (${res.status}): ${msg}`);
      }
      const json = await res.json();
      const added = Number(json?.added ?? 0);
      const errs = Array.isArray(json?.errors) ? json.errors : [];
      if (errs.length > 0) {
        const preview = errs.slice(0, 3).map((e: any) => `Row ${e?.row}: ${e?.error}`).join('\n');
        alert(`Imported ${added} record(s).\n${errs.length} error(s).\n${preview}${errs.length > 3 ? '\n…' : ''}`);
      } else {
        alert(`Imported ${added} record(s).`);
      }
      if (fileEl) fileEl.value = '';
      await ensureData();
    } catch (e: any) {
      alert(e?.message ?? 'Import failed.');
    } finally {
      importBusy = false;
      importFiring = false;
    }
  }

  // ---------- Nav actions ----------
  function goAdd() { goto('/utility/new'); }
  function editRow(id: number) { goto(`/utility/${id}`); }
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
        <button class="px-3 py-1.5 rounded-lg border border-white/20 bg-transparent text-white hover:bg-white/5" on:click={goAdd}>
          Add Record
        </button>

        <input
          id="utilCsvFile"
          class="hidden"
          type="file"
          accept=".csv"
          bind:this={fileEl}
          on:change={handlePickedFile}
        />
        <button
          class="px-3 py-1.5 rounded-lg border border-emerald-400/40 bg-emerald-500/10 text-emerald-100 hover:bg-emerald-500/20 disabled:opacity-50"
          on:click={startImport}
          disabled={importBusy}
        >
          {importBusy ? 'Importing…' : 'Import CSV'}
        </button>

        <button
          class="px-3 py-1.5 rounded-lg border border-white/20 bg-transparent text-white hover:bg-white/5 disabled:opacity-50"
          disabled={exportBusy}
          on:click={exportCsv}
        >
          {exportBusy ? 'Exporting…' : 'Export CSV'}
        </button>
      </div>
    </div>
  </div>

  <!-- Controls Bar -->
  <div class="w-full border-b border-gray-800 bg-gray-900 text-white">
    <div class="max-w-7xl mx-auto px-4 py-3 flex flex-wrap items-center gap-3">
      {#if err}
        <div class="w-full p-3 rounded-lg bg-red-500/15 text-red-200 border border-red-500/30">{err}</div>
      {/if}

      <input
        class="border border-white/20 rounded-lg px-3 py-2 w-full sm:w-80 bg-gray-800 text-white placeholder-gray-400"
        placeholder="Search artist, title, label, barcode…"
        bind:value={search}
      />
      <div class="flex items-center gap-2">
        <label class="text-sm text-gray-300">Sort by</label>
        <select class="border border-white/20 rounded-lg px-2 py-2 bg-gray-800 text-white" bind:value={sortKey}>
          <option value="artist">Artist</option>
          <option value="title">Title</option>
          <option value="year">Year</option>
        </select>
        <label class="text-sm text-gray-300">Order</label>
        <select class="border border-white/20 rounded-lg px-2 py-2 bg-gray-800 text-white" bind:value={sortDir}>
          <option value="asc">Asc</option>
          <option value="desc">Desc</option>
        </select>
      </div>

      <button
        class="ml-auto px-3 py-2 rounded-lg border border-rose-400/40 bg-rose-500/10 text-rose-100 hover:bg-rose-500/20 disabled:opacity-50"
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
            <tr><td class="p-5 text-center text-gray-400" colspan="6">Loading…</td></tr>
          {:else if !allRecords || allRecords.length === 0}
            <tr><td class="p-6 text-center text-gray-400" colspan="6">
              No records yet. Use <span class="font-medium">Add Record</span> or <span class="font-medium">Import CSV</span>.
            </td></tr>
          {:else if rows.length === 0}
            <tr><td class="p-6 text-center text-gray-400" colspan="6">No records match your search.</td></tr>
          {:else}
            {#each rows as r}
              <tr class="border-t border-gray-800 hover:bg-gray-800/60">
                <td class="p-3 align-middle">
                  <input type="checkbox"
                    checked={selectedIds.has(r.id)}
                    on:change={(e)=>toggleRow(r.id, (e.target as HTMLInputElement).checked)} />
                </td>
                <td class="p-3 align-middle">
                  {#if coverUrl(r)}
                    <a href={`/utility/${r.id}`} class="inline-block rounded overflow-hidden focus:outline-none focus:ring">
                      <img class="w-10 h-10 object-cover rounded" src={coverUrl(r)!} alt={`${r.artist} – ${r.title}`} loading="lazy" />
                    </a>
                  {/if}
                </td>
                <td class="p-3 align-middle">
                  <a href={`/utility/${r.id}`} class="text-white hover:underline">{r.title}</a>
                </td>
                <td class="p-3 align-middle text-gray-300">{r.artist}</td>
                <td class="p-3 align-middle text-gray-300">{r.year ?? ''}</td>
                <td class="p-3 align-middle">
                  <button class="px-2 py-1 rounded-lg border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-100" on:click={() => editRow(r.id)}>Edit</button>
                </td>
              </tr>
            {/each}
          {/if}
        </tbody>
      </table>
    </div>
  </div>
</div>