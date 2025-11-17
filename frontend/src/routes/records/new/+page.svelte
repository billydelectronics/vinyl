<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  type Field = {
    name: string;
    type?: 'text' | 'number' | 'date' | 'checkbox' | 'textarea';
    nullable?: boolean;
    default?: unknown;
    max_length?: number | null;
  };

  const NON_EDITABLE = new Set(['id','created_at','updated_at']);
  // We keep discogs_id VISIBLE here (manual user input).
  // Hide derived/system fields.
  const HIDE_FIELDS = new Set(['discogs_release_id','discogs_thumb','cover_url_auto']);

  const FALLBACK_FIELDS: Field[] = [
    { name: 'artist', type: 'text' },
    { name: 'title', type: 'text' },
    { name: 'year', type: 'number' },
    { name: 'label', type: 'text' },
    { name: 'format', type: 'text' },
    { name: 'country', type: 'text' },
    { name: 'catalog_number', type: 'text' },
    { name: 'barcode', type: 'text' },
    { name: 'discogs_id', type: 'number' },        // ← manual override
    { name: 'cover_url', type: 'text' },
    { name: 'cover_local', type: 'text' },
    { name: 'album_notes', type: 'textarea' },
    { name: 'personal_notes', type: 'textarea' }
  ];

  let fields: Field[] = [];
  let form: Record<string, any> = {};
  let loading = true;
  let loadErr: string | null = null;
  let saving = false;
  let saveErr: string | null = null;

  function readable(name: string): string {
    return name
      .replace(/_/g, ' ')
      .replace(/\bid\b/gi, 'ID')
      .replace(/\burl\b/gi, 'URL')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function placeholderFor(name: string): string {
    if (/artist/i.test(name)) return 'e.g. The Beatles';
    if (/title/i.test(name)) return 'e.g. Rubber Soul';
    if (/year/i.test(name)) return 'e.g. 1965';
    if (/label/i.test(name)) return 'e.g. Capitol Records';
    if (/format/i.test(name)) return 'e.g. LP, Album';
    if (/catalog/i.test(name)) return 'e.g. T 2442';
    if (/barcode/i.test(name)) return 'Optional';
    if (/discogs_id/i.test(name)) return 'Optional Discogs release # (e.g. 123456)';
    if (/notes?/i.test(name)) return 'Optional notes…';
    return '';
  }

  async function fetchSchema(): Promise<Field[]> {
    try {
      const r = await fetch('/api/meta/records/schema');
      if (!r.ok) throw new Error();
      const js = await r.json();
      let fs: Field[] = js.fields || [];
      // Show discogs_id if present in schema; hide derived ones
      fs = fs.filter(f => !NON_EDITABLE.has(f.name) && !HIDE_FIELDS.has(f.name));
      // If schema lacks discogs_id, append it so the input appears
      if (!fs.some(f => f.name === 'discogs_id')) {
        fs = [...fs, { name: 'discogs_id', type: 'number' }];
      }
      return fs;
    } catch {
      return FALLBACK_FIELDS;
    }
  }

  onMount(async () => {
    try {
      fields = await fetchSchema();
      // initialize defaults
      form = {};
      for (const f of fields) {
        form[f.name] = f.type === 'number' ? null : '';
      }
    } catch (e: any) {
      loadErr = e?.message || 'Failed to load form schema.';
    } finally {
      loading = false;
    }
  });

  async function onSubmit(e: Event) {
    e.preventDefault();
    saveErr = null;
    saving = true;

    try {
      // 1) Create the record
      const payload: Record<string, any> = {};
      for (const f of fields) payload[f.name] = form[f.name];

      const res = await fetch('/api/records', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const msg = await res.text().catch(() => '');
        throw new Error(`Create failed (${res.status} ${res.statusText}${msg ? ` – ${msg}` : ''})`);
      }
      const created = await res.json();
      const newId = created?.id;
      if (!newId) throw new Error('Create returned no id');

      // 2) If user provided Discogs Id, immediately apply cover & tracks using that release
      const manual = form?.discogs_id ? Number(form.discogs_id) : null;
      if (manual) {
        const body = JSON.stringify({ release_id: manual });
        const headers = { 'Content-Type': 'application/json' };

        const c = await fetch(`/api/records/${newId}/cover/fetch`, { method: 'POST', body, headers });
        if (!c.ok) {
          // If backend isn’t patched yet, this might 400. Fall back to best-match to keep flow smooth.
          await fetch(`/api/records/${newId}/cover/fetch`, { method: 'POST' });
        }
        const s = await fetch(`/api/records/${newId}/tracks/save`, { method: 'POST', body, headers });
        if (!s.ok) {
          await fetch(`/api/records/${newId}/tracks/save`, { method: 'POST' });
        }
      }

      // 3) Go straight to the new edit page
      await goto(`/records/edit/${newId}`);
    } catch (e: any) {
      saveErr = e?.message || 'Failed to add record.';
    } finally {
      saving = false;
    }
  }
</script>

<svelte:head>
  <title>Add a new record</title>
</svelte:head>

<div class="mx-auto max-w-3xl p-4 space-y-6">
  <header class="flex items-center justify-between">
    <h1 class="text-2xl font-semibold">Add a new record</h1>
    <nav class="flex items-center gap-3 text-sm">
      <a class="underline opacity-80 hover:opacity-100" href="/">Home</a>
      <a class="underline opacity-80 hover:opacity-100" href="/read">Read-Only</a>
    </nav>
  </header>

  {#if loading}
    <div class="text-zinc-400">Loading…</div>
  {:else if loadErr}
    <div class="rounded-md border border-red-900 bg-red-950/30 p-3 text-red-300">{loadErr}</div>
  {:else}
    <form class="space-y-6" on:submit|preventDefault={onSubmit}>
      {#if saveErr}
        <div class="rounded-md border border-red-900 bg-red-950/30 p-3 text-red-300">{saveErr}</div>
      {/if}

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        {#each fields as f}
          <div class="space-y-1">
            <label class="text-xs uppercase tracking-wide opacity-70" for={f.name}>
              {readable(f.name)}
            </label>

            {#if f.type === 'textarea'}
              <textarea id={f.name} class="w-full min-h-[120px] rounded-md border border-zinc-700 bg-transparent p-2"
                        bind:value={form[f.name]} placeholder={placeholderFor(f.name)} />
            {:else if f.type === 'number'}
              <input id={f.name} type="number"
                     class="w-full rounded-md border border-zinc-700 bg-transparent p-2"
                     bind:value={form[f.name]} placeholder={placeholderFor(f.name)} />
            {:else if f.type === 'date'}
              <input id={f.name} type="date"
                     class="w-full rounded-md border border-zinc-700 bg-transparent p-2"
                     bind:value={form[f.name]} />
            {:else if f.type === 'checkbox'}
              <div class="flex items-center gap-2 py-2">
                <input id={f.name} type="checkbox" class="h-4 w-4 rounded border border-zinc-700"
                       bind:checked={form[f.name]} />
                <span class="text-sm opacity-80">{readable(f.name)}</span>
              </div>
            {:else}
              <input id={f.name} type="text"
                     class="w-full rounded-md border border-zinc-700 bg-transparent p-2"
                     bind:value={form[f.name]} placeholder={placeholderFor(f.name)}
                     maxlength={(f.max_length && f.max_length > 0) ? f.max_length : undefined} />
            {/if}
          </div>
        {/each}
      </div>

      <div class="pt-2 flex items-center gap-3">
        <button type="submit"
                class="rounded-lg px-4 py-2 border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 disabled:opacity-60"
                disabled={saving}>
          {saving ? 'Saving…' : 'Create'}
        </button>
        <a class="text-sm underline opacity-80 hover:opacity-100" href="/">Cancel</a>
      </div>

      <p class="text-xs opacity-60">
        Tip: If you know the exact Discogs <em>release</em> number, put it in <strong>Discogs Id</strong>.
        After create, the app will fetch the cover and track list using that exact release.
        Otherwise, you can let the editor derive it via “Fetch from Discogs (best match)”.
      </p>
    </form>
  {/if}
</div>

<style>
  a { text-decoration: none; }
</style>