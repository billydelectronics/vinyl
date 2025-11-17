<script lang="ts">
  import { onMount } from 'svelte';

  // ------- Types -------
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
    cover_url_auto?: string | null;      // readonly (derived)
    discogs_thumb?: string | null;       // readonly (derived)
    album_notes?: string | null;
    personal_notes?: string | null;
  };

  type Track = {
    id?: number;          // may be missing for new/unsaved
    side: string;         // e.g. "A", "B"
    position?: string;    // e.g. "A1"
    title: string;
    duration?: string;
  };

  // ------- State -------
  let rid = 0;

  let record: RecordRow | null = null;
  let originalRecord: RecordRow | null = null;

  let tracks: Track[] = [];
  let originalTracksKey = ''; // for dirty compare

  let loading = false;
  let loadErr = '';

  let savingRecord = false;
  let saveRecordMsg = '';
  let savingTracks = false;
  let saveTracksMsg = '';

  // ------- Helpers -------
  function coverSrc(r: RecordRow | null): string {
    if (!r) return '';
    return (
      r.cover_local ||
      r.cover_url ||
      r.cover_url_auto ||
      r.discogs_thumb ||
      ''
    );
  }

  function hideOnImgError(e: Event) {
    const el = e.currentTarget as HTMLImageElement | null;
    if (el) el.style.visibility = 'hidden';
  }

  function pickRidFromPath(): number {
    const last = (typeof window !== 'undefined') ? window.location.pathname.split('/').pop() : '';
    return Number(last ?? 0);
  }

  function deepKey(v: unknown) {
    return JSON.stringify(v ?? null);
  }

  function makeDiff<T extends Record<string, any>>(before: T, after: T) {
    const out: Partial<T> = {};
    for (const k of Object.keys(after)) {
      if (deepKey((before as any)[k]) !== deepKey((after as any)[k])) {
        (out as any)[k] = (after as any)[k];
      }
    }
    return out;
  }

  // ------- Loaders -------
  async function loadRecord() {
    rid = pickRidFromPath();
    loading = true;
    loadErr = '';
    try {
      const res = await fetch(`/api/records/${rid}`);
      if (!res.ok) throw new Error(`Failed to load record (${res.status})`);
      record = await res.json() as RecordRow;
      // clone snapshot for diff
      originalRecord = JSON.parse(JSON.stringify(record));
    } catch (e: any) {
      loadErr = e?.message ?? 'Failed to load record';
    } finally {
      loading = false;
    }
  }

  async function loadSavedTracks() {
    // Uses existing endpoint: /api/records/{rid}/tracks/saved -> { sides: {A:[...],B:[...]} }
    try {
      const res = await fetch(`/api/records/${rid}/tracks/saved`);
      if (!res.ok) {
        tracks = [];
        originalTracksKey = deepKey(tracks);
        return;
      }
      const j = await res.json();
      const sides = (j?.sides ?? {}) as Record<string, Array<{ position?: string; title: string; duration?: string }>>;
      const flat: Track[] = [];
      for (const s of Object.keys(sides)) {
        const list = sides[s] ?? [];
        for (const t of list) {
          flat.push({
            side: s,
            position: t.position ?? '',
            title: t.title ?? '',
            duration: t.duration ?? ''
          });
        }
      }
      tracks = flat;
      originalTracksKey = deepKey(tracks);
    } catch {
      tracks = [];
      originalTracksKey = deepKey(tracks);
    }
  }

  onMount(async () => {
    await loadRecord();
    await loadSavedTracks();
  });

  // ------- Actions: Record PATCH -------
  async function saveRecord() {
    if (!record || !originalRecord) return;
    // Do not allow editing server-managed fields:
    const editable: Record<string, any> = (({ artist, title, year, label, catalog_number, barcode, cover_local, cover_url, album_notes, personal_notes }) =>
      ({ artist, title, year, label, catalog_number, barcode, cover_local, cover_url, album_notes, personal_notes })
    )(record);

    const before: Record<string, any> = (({ artist, title, year, label, catalog_number, barcode, cover_local, cover_url, album_notes, personal_notes }) =>
      ({ artist, title, year, label, catalog_number, barcode, cover_local, cover_url, album_notes, personal_notes })
    )(originalRecord);

    const diff = makeDiff(before, editable);

    if (Object.keys(diff).length === 0) {
      saveRecordMsg = 'No changes to save.';
      setTimeout(() => (saveRecordMsg = ''), 2000);
      return;
    }

    savingRecord = true;
    saveRecordMsg = '';
    try {
      const res = await fetch(`/api/records/${rid}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(diff)
      });
      if (!res.ok) throw new Error(`Save failed (${res.status})`);
      const updated = await res.json() as RecordRow;
      record = updated;
      originalRecord = JSON.parse(JSON.stringify(updated));
      saveRecordMsg = 'Record saved.';
    } catch (e: any) {
      saveRecordMsg = e?.message ?? 'Failed to save record.';
    } finally {
      savingRecord = false;
      setTimeout(() => (saveRecordMsg = ''), 2200);
    }
  }

  // ------- Actions: Tracks PUT (replace set) -------
  function addTrack() {
    tracks = [
      ...tracks,
      { side: 'A', position: '', title: '', duration: '' }
    ];
  }

  function removeTrack(idx: number) {
    const next = [...tracks];
    next.splice(idx, 1);
    tracks = next;
  }

  function tracksDirty(): boolean {
    return deepKey(tracks) !== originalTracksKey;
  }

  async function saveTracks() {
    savingTracks = true;
    saveTracksMsg = '';
    try {
      // Expecting your new backend endpoint that replaces all tracks for the record:
      //   PUT /api/records/{rid}/tracks
      // Body: { tracks: [{ id?, side, position, title, duration }, ...] }
      const payload = { tracks };
      const res = await fetch(`/api/records/${rid}/tracks`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `Failed to save tracks (${res.status})`);
      }
      // Re-fetch saved tracks for canonical state (and to get any DB-assigned IDs)
      await loadSavedTracks();
      saveTracksMsg = 'Tracks saved.';
    } catch (e: any) {
      saveTracksMsg = e?.message ?? 'Failed to save tracks.';
    } finally {
      savingTracks = false;
      setTimeout(() => (saveTracksMsg = ''), 2200);
    }
  }

  async function fetchCover() {
    if (!rid) return;
    try {
      const res = await fetch(`/api/records/${rid}/cover/fetch`, { method: 'POST' });
      if (!res.ok) throw new Error(`Cover fetch failed (${res.status})`);
      await loadRecord();
      // ping library page to refresh (if you wired it)
      try {
        localStorage.setItem('vinyl-cover-updated', String(Date.now()));
        localStorage.removeItem('vinyl-cover-updated');
      } catch {}
    } catch (e) {
      // best-effort; message shown in title area if needed
    }
  }
</script>

<div class="p-6 space-y-6">
  <div class="flex items-center justify-between">
    <a href="/" class="px-3 py-1.5 text-sm rounded-md border border-zinc-700 hover:bg-zinc-800">← Back</a>
    <h1 class="text-xl font-semibold">Edit Record</h1>
    <div></div>
  </div>

  {#if loading}
    <div class="text-zinc-400">Loading…</div>
  {:else if loadErr}
    <div class="text-red-400">{loadErr}</div>
  {:else if !record}
    <div class="text-zinc-400">Not found.</div>
  {:else}
    <!-- Header block -->
    <div class="grid grid-cols-1 md:grid-cols-[180px_1fr] gap-6">
      <div class="space-y-3">
        <img
          class="w-44 h-44 object-cover rounded-md border border-zinc-800"
          src={coverSrc(record)}
          alt={coverSrc(record) ? 'Cover' : 'No cover'}
          on:error={hideOnImgError}
        />
        <button
          type="button"
          class="w-44 rounded-md border border-zinc-700 px-3 py-1.5 text-sm hover:bg-zinc-800"
          on:click={fetchCover}
        >
          Fetch cover (Discogs)
        </button>
      </div>

      <div class="space-y-1">
        <div class="text-lg font-medium">
          {(record.artist || 'Unknown Artist')} — {(record.title || 'Untitled')}
        </div>
        <div class="text-sm text-zinc-400">
          {#if record.year}{record.year}{/if}
          {#if record.label} • {record.label}{/if}
        </div>
      </div>
    </div>

    <!-- Editable fields -->
    <section class="space-y-5">
      <h2 class="text-base font-semibold">Record Details</h2>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label for="artist" class="text-sm opacity-80">Artist</label>
          <input id="artist" class="w-full rounded-md border border-zinc-700 bg-transparent p-2"
            bind:value={record.artist} />
        </div>

        <div>
          <label for="title" class="text-sm opacity-80">Title</label>
          <input id="title" class="w-full rounded-md border border-zinc-700 bg-transparent p-2"
            bind:value={record.title} />
        </div>

        <div>
          <label for="year" class="text-sm opacity-80">Year</label>
          <input id="year" inputmode="numeric" pattern="[0-9]*"
            class="w-full rounded-md border border-zinc-700 bg-transparent p-2"
            bind:value={record.year} />
        </div>

        <div>
          <label for="label" class="text-sm opacity-80">Label</label>
          <input id="label" class="w-full rounded-md border border-zinc-700 bg-transparent p-2"
            bind:value={record.label} />
        </div>

        <div>
          <label for="catno" class="text-sm opacity-80">Catalog #</label>
          <input id="catno" class="w-full rounded-md border border-zinc-700 bg-transparent p-2"
            bind:value={record.catalog_number} />
        </div>

        <div>
          <label for="barcode" class="text-sm opacity-80">Barcode</label>
          <input id="barcode" class="w-full rounded-md border border-zinc-700 bg-transparent p-2"
            bind:value={record.barcode} />
        </div>

        <div>
          <label for="cover_local" class="text-sm opacity-80">Cover (local path)</label>
          <input id="cover_local" class="w-full rounded-md border border-zinc-700 bg-transparent p-2"
            bind:value={record.cover_local} />
        </div>

        <div>
          <label for="cover_url" class="text-sm opacity-80">Cover (URL)</label>
          <input id="cover_url" class="w-full rounded-md border border-zinc-700 bg-transparent p-2"
            bind:value={record.cover_url} />
        </div>
      </div>

      <div>
        <label for="album_notes" class="text-sm opacity-80">Album Notes</label>
        <textarea id="album_notes"
          class="w-full rounded-md border border-zinc-700 bg-transparent p-2 min-h-[110px]"
          bind:value={record.album_notes}></textarea>
      </div>

      <div>
        <label for="personal_notes" class="text-sm opacity-80">Personal Notes</label>
        <textarea id="personal_notes"
          class="w-full rounded-md border border-zinc-700 bg-transparent p-2 min-h-[110px]"
          bind:value={record.personal_notes}></textarea>
      </div>

      <div class="flex items-center gap-2">
        <button
          type="button"
          class="rounded-md border border-zinc-700 px-3 py-1.5 text-sm hover:bg-zinc-800 disabled:opacity-60"
          on:click={saveRecord}
          disabled={savingRecord}
        >
          {#if savingRecord}Saving…{:else}Save record{/if}
        </button>
        {#if saveRecordMsg}
          <div class="text-xs text-amber-400">{saveRecordMsg}</div>
        {/if}
      </div>
    </section>

    <!-- Tracks editor -->
    <section class="space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-base font-semibold">Tracks</h2>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="rounded-md border border-emerald-700 px-3 py-1.5 text-sm hover:bg-emerald-900/30"
            on:click={addTrack}
          >
            + Add track
          </button>

          <button
            type="button"
            class="rounded-md border px-3 py-1.5 text-sm
              {tracksDirty()
                ? 'border-amber-600 bg-amber-900/20'
                : 'border-zinc-700 text-zinc-400 cursor-not-allowed'}"
            on:click={saveTracks}
            disabled={!tracksDirty() || savingTracks}
          >
            {#if savingTracks}Saving…{:else}Save tracks{/if}
          </button>
        </div>
      </div>

      {#if tracks.length === 0}
        <div class="text-sm text-zinc-400">No tracks. Add some above.</div>
      {:else}
        <div class="overflow-x-auto">
          <table class="w-full text-sm border-collapse">
            <thead>
              <tr class="text-left border-b border-zinc-800">
                <th class="py-2 pr-2">Side</th>
                <th class="py-2 pr-2">Pos</th>
                <th class="py-2 pr-2">Title</th>
                <th class="py-2 pr-2">Duration</th>
                <th class="py-2 pr-2"></th>
              </tr>
            </thead>
            <tbody>
              {#each tracks as t, i}
                <tr class="border-b border-zinc-900">
                  <td class="py-2 pr-2">
                    <input
                      aria-label="Side"
                      class="w-14 rounded-md border border-zinc-700 bg-transparent p-1"
                      bind:value={t.side}
                      on:input={(e) => { tracks[i].side = (e.target as HTMLInputElement).value.toUpperCase(); }}
                    />
                  </td>
                  <td class="py-2 pr-2">
                    <input
                      aria-label="Position"
                      class="w-20 rounded-md border border-zinc-700 bg-transparent p-1"
                      bind:value={t.position}
                    />
                  </td>
                  <td class="py-2 pr-2">
                    <input
                      aria-label="Title"
                      class="w-full rounded-md border border-zinc-700 bg-transparent p-1"
                      bind:value={t.title}
                    />
                  </td>
                  <td class="py-2 pr-2">
                    <input
                      aria-label="Duration"
                      class="w-28 rounded-md border border-zinc-700 bg-transparent p-1"
                      bind:value={t.duration}
                      placeholder="3:45"
                    />
                  </td>
                  <td class="py-2 pr-2">
                    <button
                      type="button"
                      class="rounded-md border border-red-600 text-red-400 px-2 py-1 hover:bg-red-900/20"
                      on:click={() => removeTrack(i)}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}

      {#if saveTracksMsg}
        <div class="text-xs text-amber-400">{saveTracksMsg}</div>
      {/if}
    </section>
  {/if}
</div>

<style>
  a { text-decoration: none; }
</style>