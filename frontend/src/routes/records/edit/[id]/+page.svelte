<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { toasts } from '$lib/toast';

  type Track = { id?: number; record_id?: number; side?: string; position?: string; title: string; duration?: string };
  type RecordRow = {
    id: number;
    artist: string;
    title: string;
    year?: number | null;
    label?: string | null;
    format?: string | null;
    country?: string | null;
    catalog_number?: string | null;
    barcode?: string | null;
    discogs_id?: number | null;
    discogs_release_id?: number | null;
    discogs_thumb?: string | null;
    cover_url?: string | null;
    cover_local?: string | null;
    cover_url_auto?: string | null;
    album_notes?: string | null;
    personal_notes?: string | null;
  };

  let rid = 0;
  $: rid = Number($page.params.id);

  let rec: RecordRow | null = null;      // server truth
  let draft: RecordRow | null = null;    // editable copy
  let tracks: Track[] = [];              // server truth
  let editTracks: Track[] = [];          // editable copy

  let loading = false;
  let saving = false;
  $: dirty = JSON.stringify(rec) !== JSON.stringify(draft);
  $: tracksDirty = JSON.stringify(tracks) !== JSON.stringify(editTracks);

  // -------- Discogs picker state --------
  type DiscogsResult = { id: number; title?: string; year?: number; country?: string; label?: string | string[]; format?: string | string[]; thumb?: string | null };
  let showPicker = false;
  let searching = false;
  let results: DiscogsResult[] = [];
  let searchError: string | null = null;
  let previewId: number | null = null;
  let previewLoading = false;
  let previewImages: string[] = [];
  let previewTracks: { position?: string; title?: string; duration?: string }[] = [];

  function coverUrl(r: RecordRow | null): string | null {
    if (!r) return null;
    return r.cover_url || r.cover_local || r.cover_url_auto || r.discogs_thumb || null;
  }
  const nice = (v: unknown) => (Array.isArray(v) ? v.join(', ') : (v ?? '') as string);

  function cloneRecord(r: RecordRow): RecordRow {
    const t = (val: any) => (val === null || val === undefined ? '' : val);
    return { ...r,
      artist: t(r.artist), title: t(r.title), year: r.year ?? null, label: t(r.label),
      format: t(r.format), country: t(r.country), catalog_number: t(r.catalog_number), barcode: t(r.barcode),
      discogs_id: r.discogs_id ?? null, discogs_release_id: r.discogs_release_id ?? null, discogs_thumb: t(r.discogs_thumb),
      cover_url: t(r.cover_url), cover_local: t(r.cover_local), cover_url_auto: t(r.cover_url_auto),
      album_notes: t(r.album_notes), personal_notes: t(r.personal_notes)
    };
  }
  function normalizeForPatch(d: RecordRow): Partial<RecordRow> {
    const nz = (s: any) => (s === '' ? null : s);
    const num = (v: any) => (v === '' || v === null || Number.isNaN(Number(v)) ? null : Number(v));
    return {
      artist: nz(d.artist), title: nz(d.title), year: num(d.year as any), label: nz(d.label),
      format: nz(d.format), country: nz(d.country), catalog_number: nz(d.catalog_number), barcode: nz(d.barcode),
      discogs_id: num(d.discogs_id as any), discogs_release_id: num(d.discogs_release_id as any),
      discogs_thumb: nz(d.discogs_thumb), cover_url: nz(d.cover_url), cover_local: nz(d.cover_local),
      cover_url_auto: nz(d.cover_url_auto), album_notes: nz(d.album_notes), personal_notes: nz(d.personal_notes)
    };
  }
  function diffPatch(before: RecordRow, after: RecordRow) {
    const b = normalizeForPatch(cloneRecord(before));
    const a = normalizeForPatch(after);
    const out: any = {};
    for (const k of Object.keys(a) as (keyof typeof a)[]) if (b[k] !== a[k]) out[k] = a[k];
    return out;
  }

  async function loadAll() {
    loading = true;
    try {
      const recRes = await fetch(`/api/records/${rid}`);
      if (!recRes.ok) throw new Error(`Failed to load record (${recRes.status})`);
      rec = await recRes.json();
      draft = cloneRecord(rec);

      const trRes = await fetch(`/api/records/${rid}/tracks`);
      tracks = trRes.ok ? await trRes.json() : [];
      editTracks = JSON.parse(JSON.stringify(tracks));
    } catch (e: any) {
      toasts.error(e?.message ?? 'Failed to load');
    } finally {
      loading = false;
    }
  }

  async function saveAll() {
    if (!rec || !draft) return;
    const payload = diffPatch(rec, draft);
    if (Object.keys(payload).length === 0) {
      toasts.info('No changes to save');
      return;
    }
    saving = true;
    try {
      const r = await fetch(`/api/records/${rid}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
      if (!r.ok) throw new Error(`Save failed (${r.status})`);
      rec = await r.json();
      draft = cloneRecord(rec);
      toasts.success('Record fields saved');
    } catch (e: any) {
      toasts.error(e?.message ?? 'Save failed');
    } finally {
      saving = false;
    }
  }
  function resetDraft() { if (rec) { draft = cloneRecord(rec); toasts.info('Record field changes discarded'); } }

  // -------- Cover: best-match & picker --------
  async function fetchBestMatch() {
    saving = true;
    try {
      const r1 = await fetch(`/api/records/${rid}/cover/fetch`, { method: 'POST' });
      if (!r1.ok) throw new Error(`Cover fetch failed (${r1.status})`);
      await loadAll();
      toasts.success('Cover updated (best match)');
    } catch (e: any) {
      toasts.error(e?.message ?? 'Cover fetch failed');
    } finally { saving = false; }
  }

  async function openPicker() {
    searchError = null; results = []; previewId = null; previewImages = []; previewTracks = [];
    showPicker = true; await doSearch();
  }
  async function doSearch() {
    searching = true; searchError = null; results = [];
    try {
      const r = await fetch(`/api/records/${rid}/discogs/search`);
      if (!r.ok) throw new Error(`Search failed (${r.status})`);
      const data = await r.json();
      results = Array.isArray(data?.results) ? data.results : [];
      if (results.length === 0) searchError = 'No matches found. Edit fields and refresh.';
    } catch (e: any) { searchError = e?.message ?? 'Search failed'; } finally { searching = false; }
  }
  async function previewRelease(id: number) {
    previewId = id; previewImages = []; previewTracks = []; previewLoading = true;
    try {
      const r = await fetch(`/api/discogs/release/${id}`);
      if (!r.ok) throw new Error(`Preview failed (${r.status})`);
      const data = await r.json();
      previewImages = (data.images || []).map((i: any) => i?.uri).filter(Boolean);
      previewTracks = data.tracklist || [];
    } catch (e: any) { toasts.error(e?.message ?? 'Preview failed'); } finally { previewLoading = false; }
  }
  async function applyReleaseAll(id: number) {
    saving = true;
    try {
      const r1 = await fetch(`/api/records/${rid}/cover/fetch`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ release_id: id }) });
      if (!r1.ok) throw new Error(`Cover update failed (${r1.status})`);
      const r2 = await fetch(`/api/records/${rid}/tracks/save`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ release_id: id }) });
      if (!r2.ok) throw new Error(`Track import failed (${r2.status})`);
      await loadAll(); showPicker = false; toasts.success('Applied release (cover + tracks)');
    } catch (e: any) { toasts.error(e?.message ?? 'Failed to apply release'); } finally { saving = false; }
  }
  function selectedResultThumb(): string | null { if (!previewId) return null; const hit = results.find(r => r.id === previewId); return hit?.thumb ?? null; }
  function applyPreviewCoverOnly() {
    if (!draft) return;
    const chosen = previewImages[0] || selectedResultThumb();
    if (!chosen) { toasts.info('No image available'); return; }
    draft.cover_url = chosen;
    toasts.success('Staged preview image to Manual cover (click “Save changes”)');
  }

  // -------- Tracks: separate fetch, edit, save --------
  async function fetchTracksOnly() {
    saving = true;
    try {
      const r = await fetch(`/api/records/${rid}/tracks/save`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ release_id: draft?.discogs_id || undefined })
      });
      if (!r.ok) throw new Error(`Track import failed (${r.status})`);
      await loadAll();
      toasts.success('Tracks fetched from Discogs');
    } catch (e: any) {
      toasts.error(e?.message ?? 'Track import failed');
    } finally { saving = false; }
  }

  function addTrackRow() { editTracks = [...editTracks, { position: '', title: '', duration: '', side: '' }]; }
  function deleteTrackRow(idx: number) { editTracks = editTracks.filter((_, i) => i !== idx); }
  function resetTracksEdits() { editTracks = JSON.parse(JSON.stringify(tracks)); toasts.info('Track edits discarded'); }
  async function saveTracksEdits() {
    saving = true;
    try {
      const payload = {
        tracks: editTracks
          .filter(t => (t.title ?? '').trim() !== '')
          .map(t => ({
            position: (t.position ?? '').trim() || null,
            title: (t.title ?? '').trim(),
            duration: (t.duration ?? '').trim() || null,
            side: (t.side ?? '').trim() || null
          }))
      };
      const r = await fetch(`/api/records/${rid}/tracks/replace`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!r.ok) throw new Error(`Saving tracks failed (${r.status})`);
      await loadAll();
      toasts.success('Tracks saved');
    } catch (e: any) {
      toasts.error(e?.message ?? 'Saving tracks failed');
    } finally { saving = false; }
  }

  onMount(loadAll);
</script>

{#if loading}
  <p class="text-zinc-400">Loading…</p>
{:else if !draft}
  <p class="text-red-500">Record not found.</p>
{:else}
  <!-- Sticky action bar -->
  <div class="sticky top-0 z-40 bg-black/70 backdrop-blur border-b border-zinc-900 mb-4">
    <div class="max-w-5xl mx-auto px-6 py-3 flex items-center gap-2">
      <h1 class="text-base font-semibold flex-1">Edit record</h1>
      <span class="text-xs text-zinc-400 mr-2">{dirty ? 'Unsaved changes' : ''}</span>
      <button type="button" class="px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800" on:click={resetDraft} disabled={!dirty || saving}>Reset</button>
      <button type="button" class="px-3 py-1.5 text-sm rounded-md bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50" on:click={saveAll} disabled={!dirty || saving}>Save changes</button>
      <a href="/" class="ml-2 px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800">Home</a>
      <a href="/read" class="px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800">Read-Only</a>
    </div>
  </div>

  <!-- Top row -->
  <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
    <div>
      <div class="mb-3">
        {#if coverUrl(draft)}
          <img class="w-full aspect-square object-cover rounded-md border border-zinc-800" src={coverUrl(draft)!} alt="cover" />
        {:else}
          <div class="w-full aspect-square rounded-md border border-dashed border-zinc-700 grid place-items-center text-xs text-zinc-500">no cover</div>
        {/if}
      </div>

      <div class="grid grid-cols-1 gap-2">
        <button type="button" class="w-full px-3 py-2 rounded-md bg-zinc-800 hover:bg-zinc-700 border border-zinc-700" on:click={fetchBestMatch} disabled={saving}>
          Fetch cover (best match)
        </button>
        <button type="button" class="w-full px-3 py-2 rounded-md bg-zinc-900 hover:bg-zinc-800 border border-zinc-700" on:click={openPicker} disabled={saving}>
          Open Discogs picker
        </button>
      </div>

      <!-- Manual cover URL -->
      <div class="mt-3 text-sm">
        <div class="mb-1 text-zinc-400">Manual cover URL</div>
        <input class="w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700" bind:value={draft.cover_url} />
        <div class="mt-2 flex gap-2">
          <button type="button" class="px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800" on:click={() => (draft.cover_url = '')}>Clear</button>
        </div>
        <p class="mt-2 text-xs text-zinc-500">This sets <code>cover_url</code>. Click <strong>Save changes</strong> to persist. Display order: <code>cover_url</code> → <code>cover_local</code> → <code>cover_url_auto</code> → <code>discogs_thumb</code></p>
      </div>
    </div>

    <div class="md:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-3">
      <label class="text-sm">
        <div class="mb-1 text-zinc-400">Artist</div>
        <input class="w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700" bind:value={draft.artist} />
      </label>
      <label class="text-sm">
        <div class="mb-1 text-zinc-400">Title</div>
        <input class="w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700" bind:value={draft.title} />
      </label>
      <label class="text-sm">
        <div class="mb-1 text-zinc-400">Year</div>
        <input type="number" class="w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700" bind:value={draft.year as any} />
      </label>
      <label class="text-sm">
        <div class="mb-1 text-zinc-400">Label</div>
        <input class="w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700" bind:value={draft.label} />
      </label>
      <label class="text-sm">
        <div class="mb-1 text-zinc-400">Format</div>
        <input class="w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700" bind:value={draft.format} />
      </label>
      <label class="text-sm">
        <div class="mb-1 text-zinc-400">Country</div>
        <input class="w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700" bind:value={draft.country} />
      </label>
      <label class="text-sm">
        <div class="mb-1 text-zinc-400">Catalog #</div>
        <input class="w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700" bind:value={draft.catalog_number} />
      </label>
      <label class="text-sm">
        <div class="mb-1 text-zinc-400">Barcode</div>
        <input class="w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700" bind:value={draft.barcode} />
      </label>
      <label class="text-sm md:col-span-2">
        <div class="mb-1 text-zinc-400">Discogs ID (manual)</div>
        <input type="number" class="w-full px-3 py-1.5 rounded-md bg-zinc-900 border border-zinc-700" bind:value={draft.discogs_id as any} />
      </label>
      <div class="text-xs text-zinc-500 md:col-span-2">
        Derived Discogs Release ID: <span class="text-zinc-300">{draft.discogs_release_id ?? '—'}</span>
      </div>
    </div>
  </div>

  <!-- TRACKS -->
  <div class="mt-8">
    <div class="flex items-center justify-between mb-2">
      <div class="text-lg font-semibold">Tracks</div>
      <div class="flex gap-2">
        <button type="button" class="px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800" on:click={fetchTracksOnly} disabled={saving}>
          Fetch tracks (Discogs)
        </button>
        <button type="button" class="px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800" on:click={resetTracksEdits} disabled={!tracksDirty || saving}>
          Reset edits
        </button>
        <button type="button" class="px-3 py-1.5 text-sm rounded-md bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50" on:click={saveTracksEdits} disabled={!tracksDirty || saving}>
          Save tracks
        </button>
      </div>
    </div>

    <div class="mb-2">
      <button type="button" class="px-2 py-1 text-xs rounded-md border border-zinc-700 hover:bg-zinc-800" on:click={addTrackRow}>+ Add row</button>
    </div>

    <div class="overflow-x-auto rounded-md border border-zinc-800">
      <table class="min-w-full text-sm">
        <thead class="bg-zinc-900/40 text-zinc-400">
          <tr>
            <th class="text-left px-3 py-2 w-20">Pos</th>
            <th class="text-left px-3 py-2">Title</th>
            <th class="text-left px-3 py-2 w-24">Dur</th>
            <th class="text-left px-3 py-2 w-16">Side</th>
            <th class="px-3 py-2 w-16"></th>
          </tr>
        </thead>
        <tbody>
          {#each editTracks as t, i}
            <tr class="border-t border-zinc-800">
              <td class="px-3 py-2"><input class="w-full px-2 py-1 rounded bg-zinc-900 border border-zinc-700" bind:value={t.position} /></td>
              <td class="px-3 py-2"><input class="w-full px-2 py-1 rounded bg-zinc-900 border border-zinc-700" bind:value={t.title} /></td>
              <td class="px-3 py-2"><input class="w-full px-2 py-1 rounded bg-zinc-900 border border-zinc-700" bind:value={t.duration} /></td>
              <td class="px-3 py-2"><input class="w-full px-2 py-1 rounded bg-zinc-900 border border-zinc-700" bind:value={t.side} /></td>
              <td class="px-3 py-2 text-right">
                <button type="button" class="px-2 py-1 text-xs rounded-md border border-zinc-700 hover:bg-zinc-800" on:click={() => deleteTrackRow(i)}>Delete</button>
              </td>
            </tr>
          {/each}
          {#if editTracks.length === 0}
            <tr><td class="px-3 py-6 text-zinc-500" colspan="5">No tracks yet. Click “+ Add row” or “Fetch tracks (Discogs)”.</td></tr>
          {/if}
        </tbody>
      </table>
    </div>
  </div>

  <!-- Discogs Picker Modal -->
  {#if showPicker}
    <div class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div class="max-w-5xl mx-auto bg-zinc-950 border border-zinc-800 rounded-xl">
        <div class="flex items-center justify-between p-3 border-b border-zinc-800">
          <div class="font-semibold">Choose a Discogs release</div>
          <div class="flex items-center gap-2">
            <button type="button" class="px-2 py-1 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800" on:click|preventDefault|stopPropagation={doSearch} disabled={searching}>Refresh</button>
            <button type="button" class="px-2 py-1 rounded-md border border-zinc-700 hover:bg-zinc-800" on:click={() => (showPicker = false)}>Close</button>
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-0">
          <div class="md:col-span-2 p-3">
            <div class="text-sm text-zinc-400 mb-2">{#if searching}Searching…{:else}{results.length} result{results.length === 1 ? '' : 's'}{/if}</div>
            {#if searchError}<div class="text-red-500 text-sm mb-2">{searchError}</div>{/if}
            <div class="space-y-2">
              {#each results as r}
                <div class="flex gap-3 p-2 rounded-lg border border-zinc-800 hover:border-zinc-600">
                  <img src={r.thumb || ''} alt="thumb" class="w-16 h-16 object-cover rounded border border-zinc-800" on:error={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = 'hidden')} />
                  <div class="flex-1">
                    <div class="font-semibold text-sm truncate">{r.title}</div>
                    <div class="text-xs text-zinc-400">{nice(r.label)}{#if r.year} • {r.year}{/if}{#if r.country} • {r.country}{/if}</div>
                    {#if r.format}<div class="text-xs text-zinc-500">{nice(r.format)}</div>{/if}
                  </div>
                  <div class="flex items-center gap-2">
                    <button
                      type="button"
                      class="px-2 py-1 text-xs rounded-md border border-zinc-700 hover:bg-zinc-800"
                      on:click|preventDefault|stopPropagation={() => previewRelease(Number(r.id))}
                    >Preview</button>
                    <button
                      type="button"
                      class="px-2 py-1 text-xs rounded-md bg-green-600 hover:bg-green-700 text-white"
                      on:click|preventDefault|stopPropagation={() => applyReleaseAll(Number(r.id))}
                      disabled={saving}
                    >Use this</button>
                  </div>
                </div>
              {/each}
            </div>
          </div>

          <div class="border-t md:border-t-0 md:border-l border-zinc-800 p-3">
            <div class="text-sm font-semibold mb-2">Preview</div>
            {#if previewLoading}
              <div class="text-zinc-400 text-sm">Loading preview…</div>
            {:else if !previewId}
              <div class="text-zinc-500 text-sm">Select “Preview” on a result.</div>
            {:else}
              {#if (previewImages.length > 0) || selectedResultThumb()}
                <img src={(previewImages[0] || selectedResultThumb())!} class="w-full rounded border border-zinc-800 mb-2 object-cover" alt="cover" />
              {/if}
              <div class="flex flex-wrap gap-2 mb-3">
                <button
                  type="button"
                  class="px-2 py-1 text-xs rounded-md border border-zinc-700 hover:bg-zinc-800"
                  on:click|preventDefault|stopPropagation={applyPreviewCoverOnly}
                  disabled={!previewImages.length && !selectedResultThumb()}
                >
                  Apply cover only (to Manual)
                </button>
                <button
                  type="button"
                  class="px-2 py-1 text-xs rounded-md bg-green-600 hover:bg-green-700 text-white"
                  on:click|preventDefault|stopPropagation={() => applyReleaseAll(previewId!)}
                  disabled={saving}
                >
                  Apply cover + tracks
                </button>
              </div>
              <div class="max-h-64 overflow-auto rounded border border-zinc-800">
                <table class="min-w-full text-xs">
                  <thead class="bg-zinc-900/40 text-zinc-400"><tr><th class="text-left px-2 py-1">Pos</th><th class="text-left px-2 py-1">Title</th><th class="text-left px-2 py-1">Dur</th></tr></thead>
                <tbody>
                  {#each previewTracks as t}
                    <tr class="border-t border-zinc-800"><td class="px-2 py-1">{t.position}</td><td class="px-2 py-1">{t.title}</td><td class="px-2 py-1">{t.duration}</td></tr>
                  {/each}
                </tbody>
                </table>
              </div>
            {/if}
          </div>
        </div>
      </div>
    </div>
  {/if}
{/if}