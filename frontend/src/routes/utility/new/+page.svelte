<script lang="ts">
  import { goto } from '$app/navigation';

  // Core record fields with defaults
  let draft: Record<string, unknown> = {
    artist: '',
    title: '',
    year: null,
    label: '',
    format: 'LP',    // default
    country: 'US',   // default
    catalog_number: '',
    barcode: '',
    cover_url: ''
  };

  const NON_EDITABLE = new Set(['id', 'created_at', 'updated_at']);
  const CORE_KEYS = new Set([
    'artist',
    'title',
    'year',
    'label',
    'format',
    'country',
    'catalog_number',
    'barcode',
    'cover_url'
  ]);

  let saving = false;

  // Only show non-core, non-system fields in the dynamic section
  function extraFields() {
    return Object.entries(draft).filter(
      ([k]) => !NON_EDITABLE.has(k) && !CORE_KEYS.has(k)
    );
  }

  function addField() {
    const key = prompt('New field key (snake_case):');
    if (!key) return;
    if (key in draft) {
      alert('Field exists.');
      return;
    }
    draft = { ...draft, [key]: '' };
  }

  async function save() {
    saving = true;
    try {
      const payload: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(draft)) {
        if (NON_EDITABLE.has(k)) continue;
        payload[k] = v;
      }
      const res = await fetch('/api/records', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(await res.text());
      alert('Created.');
      goto('/utility');
    } catch (e) {
      alert(`Create failed: ${(e as Error).message}`);
    } finally {
      saving = false;
    }
  }
</script>

<div class="max-w-4xl mx-auto px-4 py-6 space-y-6">
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-semibold text-zinc-100">Add Record</h1>
    <div class="flex gap-2">
      <button
        type="button"
        class="px-3 py-1.5 rounded-lg border border-zinc-700 bg-zinc-900/70 hover:bg-zinc-800 text-sm text-zinc-100"
        on:click={() => history.back()}
      >
        Cancel
      </button>
      <button
        type="button"
        class="px-3 py-1.5 rounded-lg border border-zinc-700 bg-zinc-900/70 hover:bg-zinc-800 text-sm text-zinc-100"
        on:click={addField}
      >
        Add Field
      </button>
      <button
        type="button"
        class="px-3 py-1.5 rounded-lg border border-zinc-700 bg-zinc-100 text-zinc-900 hover:bg-white text-sm disabled:opacity-60 disabled:cursor-not-allowed"
        disabled={saving}
        on:click={save}
      >
        {saving ? 'Saving…' : 'Create'}
      </button>
    </div>
  </div>

  <div class="rounded-xl border border-zinc-800 bg-zinc-950/70 p-4 sm:p-6 space-y-6">
    <!-- Core fields: Artist, Title, Year, Label, Format, Country, Catalog_number, Barcode, Cover_url -->
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <!-- Artist -->
      <label class="flex flex-col gap-1">
        <span class="text-xs font-medium uppercase tracking-wide text-zinc-400">
          artist
        </span>
        <input
          class="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-500/70"
          type="text"
          bind:value={(draft['artist'] as any)}
        />
      </label>

      <!-- Title -->
      <label class="flex flex-col gap-1">
        <span class="text-xs font-medium uppercase tracking-wide text-zinc-400">
          title
        </span>
        <input
          class="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-500/70"
          type="text"
          bind:value={(draft['title'] as any)}
        />
      </label>

      <!-- Year -->
      <label class="flex flex-col gap-1">
        <span class="text-xs font-medium uppercase tracking-wide text-zinc-400">
          year
        </span>
        <input
          class="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-500/70"
          type="number"
          bind:value={(draft['year'] as any)}
        />
      </label>

      <!-- Label -->
      <label class="flex flex-col gap-1">
        <span class="text-xs font-medium uppercase tracking-wide text-zinc-400">
          label
        </span>
        <input
          class="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-500/70"
          type="text"
          bind:value={(draft['label'] as any)}
        />
      </label>

      <!-- Format (default LP) -->
      <label class="flex flex-col gap-1">
        <span class="text-xs font-medium uppercase tracking-wide text-zinc-400">
          format
        </span>
        <input
          class="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-500/70"
          type="text"
          bind:value={(draft['format'] as any)}
        />
      </label>

      <!-- Country (default US) -->
      <label class="flex flex-col gap-1">
        <span class="text-xs font-medium uppercase tracking-wide text-zinc-400">
          country
        </span>
        <input
          class="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-500/70"
          type="text"
          bind:value={(draft['country'] as any)}
        />
      </label>

      <!-- Catalog_number -->
      <label class="flex flex-col gap-1">
        <span class="text-xs font-medium uppercase tracking-wide text-zinc-400">
          catalog_number
        </span>
        <input
          class="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-500/70"
          type="text"
          bind:value={(draft['catalog_number'] as any)}
        />
      </label>

      <!-- Barcode -->
      <label class="flex flex-col gap-1">
        <span class="text-xs font-medium uppercase tracking-wide text-zinc-400">
          barcode
        </span>
        <input
          class="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-500/70"
          type="text"
          bind:value={(draft['barcode'] as any)}
        />
      </label>

      <!-- Cover_url -->
      <label class="flex flex-col gap-1 sm:col-span-2">
        <span class="text-xs font-medium uppercase tracking-wide text-zinc-400">
          cover_url
        </span>
        <input
          class="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-500/70"
          type="text"
          bind:value={(draft['cover_url'] as any)}
        />
      </label>
    </div>

    <!-- Extra custom fields (added via Add Field) -->
    {#if extraFields().length}
      <div class="pt-4 border-t border-zinc-800">
        <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-3">
          Additional fields
        </p>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {#each extraFields() as [key, value]}
            <label class="flex flex-col gap-1">
              <span class="text-xs font-medium uppercase tracking-wide text-zinc-400">
                {key}
              </span>

              {#if typeof value === 'number'}
                <input
                  class="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-500/70"
                  type="number"
                  bind:value={(draft[key] as any)}
                />
              {:else if typeof value === 'boolean'}
                <select
                  class="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-500/70"
                  bind:value={(draft[key] as any)}
                >
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              {:else}
                <input
                  class="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-500/70"
                  type="text"
                  bind:value={(draft[key] as any)}
                />
              {/if}
            </label>
          {/each}
        </div>
      </div>
    {/if}
  </div>
</div>