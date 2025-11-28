<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';

  // ---- Types (aligned with /records/edit) ----
  type Track = {
    id?: number;
    record_id?: number;
    side?: string;
    position?: string;
    title: string;
    duration?: string;
  };
  type RecordRow = {
    id: number;
    artist: string;
    title: string;
    year?: number | null;
    label?: string | null;
    format?: string | null;
    country?: string | null;
    location?: string | null;
    catalog_number?: string | null;
    barcode?: string | null;
    discogs_id?: number | null;
    discogs_release_id?: number | null;
    discogs_thumb?: string | null;
    cover_url?: string | null;       // manual
    cover_local?: string | null;     // uploaded/managed by server
    cover_url_auto?: string | null;  // auto from Discogs
    album_notes?: string | null;
    personal_notes?: string | null;
    sort_mode?: string | null;
  };

  // ---- Route param ----
  let rid = 0;
  $: rid = Number($page.params.id);

  // ---- State ----
  let loading = false;
  let saving = false;
  let fetchingCover = false; // NEW: specifically tracks best-match cover fetch

  let rec: RecordRow | null = null;    // server truth
  let draft: RecordRow | null = null;  // editable copy

  let tracks: Track[] = [];            // server truth
  let editTracks: Track[] = [];        // editable copy

  $: dirty = JSON.stringify(rec) !== JSON.stringify(draft);
  $: tracksDirty = JSON.stringify(tracks) !== JSON.stringify(editTracks);

  // ---- Discogs picker state (mirrors /records/edit) ----
  type DiscogsResult = {
    id: number;
    title?: string;
    year?: number;
    country?: string;
    label?: string | string[];
    format?: string | string[];
    thumb?: string | null;
  };
  let showPicker = false;
  let searching = false;
  let results: DiscogsResult[] = [];
  let searchError: string | null = null;
  let previewId: number | null = null;
  let previewLoading = false;
  let previewImages: string[] = [];
  let previewTracks: { position?: string; title?: string; duration?: string }[] = [];

  // ---- Helpers ----
  function coverUrl(r: RecordRow | null): string | null {
    if (!r) return null;
    return r.cover_url || r.cover_local || r.cover_url_auto || r.discogs_thumb || null;
  }
  const nice = (v: unknown) => (Array.isArray(v) ? v.join(', ') : (v ?? '') as string);

  function cloneRecord(r: RecordRow): RecordRow {
    const t = (val: any) => (val === null || val === undefined ? '' : val);
    return {
      ...r,
      artist: t(r.artist),
      title: t(r.title),
      year: r.year ?? null,
      label: t(r.label),
      format: t(r.format),
      country: t(r.country),
      location: t(r.location),
      catalog_number: t(r.catalog_number),
      barcode: t(r.barcode),
      discogs_id: r.discogs_id ?? null,
      discogs_release_id: r.discogs_release_id ?? null,
      discogs_thumb: t(r.discogs_thumb),
      cover_url: t(r.cover_url),
      cover_local: t(r.cover_local),
      cover_url_auto: t(r.cover_url_auto),
      album_notes: t(r.album_notes),
      personal_notes: t(r.personal_notes),
      sort_mode: t(r.sort_mode)
    };
  }
  function normalizeForPatch(d: RecordRow): Partial<RecordRow> {
    const nz = (s: any) => (s === '' ? null : s);
    const num = (v: any) => (v === '' || v === null || Number.isNaN(Number(v)) ? null : Number(v));
    return {
      artist: nz(d.artist),
      title: nz(d.title),
      year: num(d.year as any),
      label: nz(d.label),
      format: nz(d.format),
      country: nz(d.country),
      location: nz(d.location),
      catalog_number: nz(d.catalog_number),
      barcode: nz(d.barcode),
      discogs_id: num(d.discogs_id as any),
      discogs_release_id: num(d.discogs_release_id as any),
      discogs_thumb: nz(d.discogs_thumb),
      cover_url: nz(d.cover_url),
      cover_local: nz(d.cover_local),
      cover_url_auto: nz(d.cover_url_auto),
      album_notes: nz(d.album_notes),
      personal_notes: nz(d.personal_notes),
      sort_mode: nz(d.sort_mode)
    };
  }
  function diffPatch(before: RecordRow, after: RecordRow) {
    const b = normalizeForPatch(cloneRecord(before));
    const a = normalizeForPatch(after);
    const out: any = {};
    for (const k of Object.keys(a) as (keyof typeof a)[]) if (b[k] !== a[k]) out[k] = a[k];
    return out;
  }

  // ---- Load record + tracks ----
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
      alert(e?.message ?? 'Failed to load');
    } finally {
      loading = false;
    }
  }
  onMount(loadAll);

  // ---- Save record fields (PATCH diff) ----
  async function saveFields() {
    if (!rec || !draft) return;
    const payload = diffPatch(rec, draft);
    if (Object.keys(payload).length === 0) {
      alert('No changes to save');
      return;
    }
    saving = true;
    try {
      const r = await fetch(`/api/records/${rid}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!r.ok) throw new Error(`Save failed (${r.status})`);
      rec = await r.json();
      draft = cloneRecord(rec);
      alert('Record fields saved');
    } catch (e: any) {
      alert(e?.message ?? 'Save failed');
    } finally {
      saving = false;
    }
  }
  function resetDraft() {
    if (rec) {
      draft = cloneRecord(rec);
      alert('Record field changes discarded');
    }
  }

  // ---- Cover: best match ----
  async function fetchBestMatch() {
    saving = true;
    fetchingCover = true;
    try {
      const r1 = await fetch(`/api/records/${rid}/cover/fetch`, { method: 'POST' });
      if (!r1.ok) throw new Error(`Cover fetch failed (${r1.status})`);
      await loadAll();
      alert('Cover updated (best match)');
    } catch (e: any) {
      alert(e?.message ?? 'Cover fetch failed');
    } finally {
      fetchingCover = false;
      saving = false;
    }
  }

  // ---- Discogs picker: search / preview / apply ----
  async function openPicker() {
    searchError = null; results = []; previewId = null; previewImages = []; previewTracks = [];
    showPicker = true;
    await doSearch();
  }
  async function doSearch() {
    searching = true; searchError = null; results = [];
    try {
      const r = await fetch(`/api/records/${rid}/discogs/search`);
      if (!r.ok) throw new Error(`Search failed (${r.status})`);
      const data = await r.json();
      results = Array.isArray(data?.results) ? data.results : [];
      if (results.length === 0) searchError = 'No matches found. Edit fields and refresh.';
    } catch (e: any) {
      searchError = e?.message ?? 'Search failed';
    } finally {
      searching = false;
    }
  }
  async function previewRelease(id: number) {
    previewId = id; previewImages = []; previewTracks = []; previewLoading = true;
    try {
      const r = await fetch(`/api/discogs/release/${id}`);
      if (!r.ok) throw new Error(`Preview failed (${r.status})`);
      const data = await r.json();
      previewImages = (data.images || []).map((i: any) => i?.uri).filter(Boolean);
      previewTracks = data.tracklist || [];
    } catch (e: any) {
      alert(e?.message ?? 'Preview failed');
    } finally {
      previewLoading = false;
    }
  }
  async function applyReleaseAll(id: number) {
    saving = true;
    try {
      const r1 = await fetch(`/api/records/${rid}/cover/fetch`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ release_id: id })
      });
      if (!r1.ok) throw new Error(`Cover update failed (${r1.status})`);

      const r2 = await fetch(`/api/records/${rid}/tracks/save`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ release_id: id })
      });
      if (!r2.ok) throw new Error(`Track import failed (${r2.status})`);

      await loadAll();
      showPicker = false;
      alert('Applied release (cover + tracks)');
    } catch (e: any) {
      alert(e?.message ?? 'Failed to apply release');
    } finally {
      saving = false;
    }
  }
  function selectedResultThumb(): string | null {
    if (!previewId) return null;
    const hit = results.find(r => r.id === previewId);
    return hit?.thumb ?? null;
  }
  function applyPreviewCoverOnly() {
    if (!draft) return;
    const chosen = previewImages[0] || selectedResultThumb();
    if (!chosen) { alert('No image available'); return; }
    draft.cover_url = chosen; // manual field; user still clicks Save
    alert('Staged preview image to Manual cover (click “Save changes”)');
  }

  // ---- Tracks: manual edit / replace ----
  function addTrackRow() {
    editTracks = [...editTracks, { position: '', title: '', duration: '', side: '' }];
  }
  function deleteTrackRow(idx: number) {
    editTracks = editTracks.filter((_, i) => i !== idx);
  }
  function moveTrack(idx: number, dir: -1 | 1) {
    const j = idx + dir;
    if (j < 0 || j >= editTracks.length) return;
    const arr = editTracks.slice();
    const tmp = arr[idx]; arr[idx] = arr[j]; arr[j] = tmp;
    editTracks = arr;
  }
  function resetTracksEdits() {
    editTracks = JSON.parse(JSON.stringify(tracks));
    alert('Track edits discarded');
  }
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
      alert('Tracks saved');
    } catch (e: any) {
      alert(e?.message ?? 'Saving tracks failed');
    } finally {
      saving = false;
    }
  }

  // ---- Nav ----
  function backToUtility() { goto('/utility'); }
</script>

<div class="min-h-screen bg-gray-950 text-gray-100">
  <!-- Sticky action bar -->
  <div class="w-full border-b border-gray-800 bg-gray-900 text-white sticky top-0 z-10">
    <div class="max-w-7xl mx-auto px-4 py-3 flex items-center gap-2">
      <div class="font-semibold flex-1">Utility • Edit record</div>
      <span class="text-xs text-gray-400 mr-2">{dirty ? 'Unsaved changes' : ''}</span>
      <button type="button" class="px-3 py-1.5 text-sm rounded-md border border-gray-700 hover:bg-gray-800"
              on:click={resetDraft} disabled={!dirty || saving}>Reset</button>
      <button type="button" class="px-3 py-1.5 text-sm rounded-md bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50"
              on:click={saveFields} disabled={!dirty || saving}>Save changes</button>
      <button type="button" class="px-3 py-1.5 text-sm rounded-md border border-gray-700 hover:bg-gray-800"
              on:click={backToUtility}>Back</button>
    </div>
  </div>

  {#if loading}
    <div class="max-w-7xl mx-auto px-4 py-6 text-gray-400">Loading…</div>
  {:else if !draft}
    <div class="max-w-7xl mx-auto px-4 py-6 text-red-400">Record not found.</div>
  {:else}
    <div class="max-w-7xl mx-auto px-4 py-6">
      <!-- Top row -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div>
          <div class="mb-3">
            {#if coverUrl(draft)}
              <img class="w-full aspect-square object-cover rounded-md border border-gray-800" src={coverUrl(draft)!} alt="cover" />
            {:else}
              <div class="w-full aspect-square rounded-md border border-dashed border-gray-700 grid place-items-center text-xs text-gray-500">no cover</div>
            {/if}
          </div>

          <div class="grid grid-cols-1 gap-2">
            <button
              type="button"
              class="w-full px-3 py-2 rounded-md bg-gray-800 hover:bg-gray-700 border border-gray-700"
              on:click={fetchBestMatch}
              disabled={saving}
            >
              {#if fetchingCover}
                Fetching cover...
              {:else}
                Fetch cover (best match)
              {/if}
            </button>
            <button type="button" class="w-full px-3 py-2 rounded-md bg-gray-900 hover:bg-gray-800 border border-gray-700"
                    on:click={openPicker} disabled={saving}>
              Open Discogs picker
            </button>
          </div>

          <!-- Manual cover URL -->
          <div class="mt-3 text-sm">
            <label class="mb-1 text-gray-400" for="manual-cover-url">Manual cover URL</label>
            <input id="manual-cover-url" class="w-full px-3 py-1.5 rounded-md bg-gray-900 border border-gray-700" bind:value={draft.cover_url} />
            <div class="mt-2 flex gap-2">
              <button type="button" class="px-3 py-1.5 text-sm rounded-md border border-gray-700 hover:bg-gray-800"
                      on:click={() => (draft!.cover_url = '')}>Clear</button>
            </div>
            <p class="mt-2 text-xs text-gray-500">
              Display order: <code>cover_url</code> → <code>cover_local</code> → <code>cover_url_auto</code> → <code>discogs_thumb</code>
            </p>
          </div>
        </div>

        <!-- All record fields (same as /records/edit) -->
        <div class="md:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-3">
          <label class="text-sm" for="artist">
            <div class="mb-1 text-gray-400">Artist</div>
            <input id="artist" class="w-full px-3 py-1.5 rounded-md bg-gray-900 border border-gray-700" bind:value={draft.artist} />
          </label>
          <label class="text-sm" for="title">
            <div class="mb-1 text-gray-400">Title</div>
            <input id="title" class="w-full px-3 py-1.5 rounded-md bg-gray-900 border border-gray-700" bind:value={draft.title} />
          </label>
          <label class="text-sm" for="year">
            <div class="mb-1 text-gray-400">Year</div>
            <input id="year" type="number" class="w-full px-3 py-1.5 rounded-md bg-gray-900 border border-gray-700" bind:value={draft.year as any} />
          </label>
          <label class="text-sm" for="label">
            <div class="mb-1 text-gray-400">Label</div>
            <input id="label" class="w-full px-3 py-1.5 rounded-md bg-gray-900 border border-gray-700" bind:value={draft.label} />
          </label>
          <label class="text-sm" for="format">
            <div class="mb-1 text-gray-400">Format</div>
            <input id="format" class="w-full px-3 py-1.5 rounded-md bg-gray-900 border border-gray-700"
                   bind:value={draft.format} placeholder={'LP, 12", 45 RPM…'} />
          </label>
          <label class="text-sm" for="country">
            <div class="mb-1 text-gray-400">Country</div>
            <input id="country" class="w-full px-3 py-1.5 rounded-md bg-gray-900 border border-gray-700" bind:value={draft.country} />
          </label>
          <label class="text-sm" for="location">
            <div class="mb-1 text-gray-400">Location</div>
            <input
              id="location"
              class="w-full px-3 py-1.5 rounded-md bg-gray-900 border border-gray-700"
              bind:value={draft.location}
              placeholder="Shelf, box, room…"
            />
          </label>
          <label class="text-sm" for="catno">
            <div class="mb-1 text-gray-400">Catalog #</div>
            <input id="catno" class="w-full px-3 py-1.5 rounded-md bg-gray-900 border border-gray-700" bind:value={draft.catalog_number} />
          </label>
          <label class="text-sm" for="barcode">
            <div class="mb-1 text-gray-400">Barcode</div>
            <input id="barcode" class="w-full px-3 py-1.5 rounded-md bg-gray-900 border border-gray-700" bind:value={draft.barcode} />
          </label>
          <label class="text-sm md:col-span-2" for="discogs-id">
            <div class="mb-1 text-gray-400">Discogs ID (manual)</div>
            <input id="discogs-id" type="number" class="w-full px-3 py-1.5 rounded-md bg-gray-900 border border-gray-700" bind:value={draft.discogs_id as any} />
          </label>
          <div class="text-xs text-gray-500 md:col-span-2">
            Derived Discogs Release ID: <span class="text-gray-300">{draft.discogs_release_id ?? '—'}</span>
          </div>

          <!-- Notes -->
          <label class="text-sm md:col-span-2" for="album-notes">
            <div class="mb-1 text-gray-400">Album notes</div>
            <textarea id="album-notes" class="w-full min-h-[120px] rounded-md border border-gray-700 bg-gray-900 p-2"
            bind:value={draft.album_notes}></textarea>
          </label>
          <label class="text-sm md:col-span-2" for="personal-notes">
            <div class="mb-1 text-gray-400">Personal notes</div>
            <textarea id="personal-notes" class="w-full min-h-[120px] rounded-md border border-gray-700 bg-gray-900 p-2"
            bind:value={draft.personal_notes}></textarea>
          </label>
          <label class="text-sm md:col-span-2" for="sort-mode">
            <div class="mb-1 text-gray-400">Sort mode</div>
            <input
              id="sort-mode"
              class="w-full px-3 py-1.5 rounded-md bg-gray-900 border border-gray-700"
              bind:value={draft.sort_mode}
              placeholder="Optional per-record sort override"
            />
          </label>
        </div>
      </div>

      <!-- TRACKS -->
      <div class="mt-8">
        <div class="flex items-center justify-between mb-2">
          <div class="text-lg font-semibold">Tracks</div>
          <div class="flex gap-2">
            <button type="button" class="px-3 py-1.5 text-sm rounded-md border border-gray-700 hover:bg-gray-800"
                    on:click={() => openPicker()} disabled={saving}>
              Open Discogs picker
            </button>
            <button type="button" class="px-3 py-1.5 text-sm rounded-md border border-gray-700 hover:bg-gray-800"
                    on:click={resetTracksEdits} disabled={!tracksDirty || saving}>
              Reset edits
            </button>
            <button type="button" class="px-3 py-1.5 text-sm rounded-md bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50"
                    on:click={saveTracksEdits} disabled={!tracksDirty || saving}>
              Save tracks
            </button>
          </div>
        </div>

        <div class="mb-2">
          <button type="button" class="px-2 py-1 text-xs rounded-md border border-gray-700 hover:bg-gray-800"
                  on:click={addTrackRow}>+ Add row</button>
        </div>

        <div class="overflow-x-auto rounded-md border border-gray-800">
          <table class="min-w-full text-sm">
            <thead class="bg-gray-900/40 text-gray-400">
              <tr>
                <th class="text-left px-3 py-2 w-20">Pos</th>
                <th class="text-left px-3 py-2">Title</th>
                <th class="text-left px-3 py-2 w-24">Dur</th>
                <th class="text-left px-3 py-2 w-16">Side</th>
                <th class="px-3 py-2 w-28"></th>
              </tr>
            </thead>
            <tbody>
              {#each editTracks as t, i}
                <tr class="border-t border-gray-800">
                  <td class="px-3 py-2">
                    <input class="w-full px-2 py-1 rounded bg-gray-900 border border-gray-700" bind:value={t.position} placeholder="A1" />
                  </td>
                  <td class="px-3 py-2">
                    <input class="w-full px-2 py-1 rounded bg-gray-900 border border-gray-700" bind:value={t.title} placeholder="Track title" />
                  </td>
                  <td class="px-3 py-2">
                    <input class="w-full px-2 py-1 rounded bg-gray-900 border border-gray-700" bind:value={t.duration} placeholder="3:45" />
                  </td>
                  <td class="px-3 py-2">
                    <input class="w-full px-2 py-1 rounded bg-gray-900 border border-gray-700" bind:value={t.side} placeholder="A" />
                  </td>
                  <td class="px-3 py-2 text-right space-x-2">
                    <button type="button" class="px-2 py-1 text-xs rounded-md border border-gray-700 hover:bg-gray-800"
                            on:click={() => moveTrack(i, -1)}>↑</button>
                    <button type="button" class="px-2 py-1 text-xs rounded-md border border-gray-700 hover:bg-gray-800"
                            on:click={() => moveTrack(i, 1)}>↓</button>
                    <button type="button" class="px-2 py-1 text-xs rounded-md border border-rose-700 bg-rose-900/30 hover:bg-rose-800/50"
                            on:click={() => deleteTrackRow(i)}>Delete</button>
                  </td>
                </tr>
              {/each}
              {#if editTracks.length === 0}
                <tr><td class="px-3 py-6 text-gray-500" colspan="5">No tracks yet. Click “+ Add row” or “Open Discogs picker”.</td></tr>
              {/if}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  {/if}
</div>

<!-- Discogs Picker Modal -->
{#if showPicker}
  <div class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
    <div class="max-w-5xl mx-auto bg-zinc-950 border border-zinc-800 rounded-xl">
      <div class="flex items-center justify-between p-3 border-b border-zinc-800">
        <div class="font-semibold">Choose a Discogs release</div>
        <div class="flex items-center gap-2">
          <button type="button" class="px-2 py-1 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800"
                  on:click|preventDefault|stopPropagation={doSearch} disabled={searching}>Refresh</button>
          <button type="button" class="px-2 py-1 rounded-md border border-zinc-700 hover:bg-zinc-800"
                  on:click={() => (showPicker = false)}>Close</button>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-0">
        <div class="md:col-span-2 p-3">
          <div class="text-sm text-zinc-400 mb-2">
            {#if searching}Searching…{:else}{results.length} result{results.length === 1 ? '' : 's'}{/if}
          </div>
          {#if searchError}<div class="text-red-500 text-sm mb-2">{searchError}</div>{/if}
          <div class="space-y-2">
            {#each results as r}
              <div class="flex gap-3 p-2 rounded-lg border border-zinc-800 hover:border-zinc-600">
                <img src={r.thumb || ''} alt="thumb" class="w-16 h-16 object-cover rounded border border-zinc-800"
                     on:error={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = 'hidden')} />
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
              <img src={(previewImages[0] || selectedResultThumb())!}
                   class="w-full rounded border border-zinc-800 mb-2 object-cover" alt="cover" />
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
                <thead class="bg-zinc-900/40 text-zinc-400">
                  <tr><th class="text-left px-2 py-1">Pos</th><th class="text-left px-2 py-1">Title</th><th class="text-left px-2 py-1">Dur</th></tr>
                </thead>
                <tbody>
                  {#each previewTracks as t}
                    <tr class="border-t border-zinc-800">
                      <td class="px-2 py-1">{t.position}</td>
                      <td class="px-2 py-1">{t.title}</td>
                      <td class="px-2 py-1">{t.duration}</td>
                    </tr>
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