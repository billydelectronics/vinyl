<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';

  // Seed a minimal shape; once you POST it, your backend will persist whatever fields it accepts.
  // Add or remove defaults as you like.
  let draft: Record<string, unknown> = {
    artist: '',
    title: '',
    year: null,
    label: '',
    catalog_number: '',
    barcode: '',
    cover_url: ''
  };

  const NON_EDITABLE = new Set(['id', 'created_at', 'updated_at']);
  let saving = false;

  function fields() {
    return Object.entries(draft).filter(([k]) => !NON_EDITABLE.has(k));
  }

  function addField() {
    const key = prompt('New field key (snake_case):');
    if (!key) return;
    if (key in draft) { alert('Field exists.'); return; }
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

<div class="max-w-3xl mx-auto px-4 py-6">
  <div class="flex items-center justify-between mb-4">
    <h1 class="text-2xl font-semibold">Add Record</h1>
    <div class="flex gap-2">
      <button class="px-3 py-1.5 rounded-lg border" on:click={() => history.back()}>Cancel</button>
      <button class="px-3 py-1.5 rounded-lg border" on:click={addField}>Add Field</button>
      <button class="px-3 py-1.5 rounded-lg border" disabled={saving} on:click={save}>{saving ? 'Saving…' : 'Create'}</button>
    </div>
  </div>

  <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
    {#each fields() as [key, value]}
      <label class="flex flex-col gap-1">
        <span class="text-sm text-gray-600">{key}</span>
        {#if typeof value === 'number'}
          <input class="border rounded-lg px-3 py-2" type="number" bind:value={(draft[key] as any)} />
        {:else if typeof value === 'boolean'}
          <select class="border rounded-lg px-2 py-2" bind:value={(draft[key] as any)}>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        {:else}
          <input class="border rounded-lg px-3 py-2" type="text" bind:value={(draft[key] as any)} />
        {/if}
      </label>
    {/each}
  </div>
</div>