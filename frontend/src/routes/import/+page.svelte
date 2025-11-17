<script>
  import { goto } from '$app/navigation';

  // ---- Config ----
  const MAX_BYTES = 5 * 1024 * 1024; // 5 MB

  // ---- State ----
  let fileEl;
  let fileMeta = { name: '', size: 0 };
  let busy = false;
  let importSuccess = false;

  // Toast
  let toast = { show: false, kind: 'ok', text: '' };
  let tTimer;
  function showToast(kind, text, ms = 1600) {
    clearTimeout(tTimer);
    toast = { show: true, kind, text };
    tTimer = setTimeout(() => (toast.show = false), ms);
  }

  // Helpers
  const fmt = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n/1024).toFixed(1)} KB` : `${(n/1048576).toFixed(1)} MB`);

  function onPick() {
    const f = fileEl?.files?.[0];
    fileMeta = { name: f?.name ?? '', size: f?.size ?? 0 };
    importSuccess = false; // reset success badge when picking a new file
  }

  async function upload() {
    const f = fileEl?.files?.[0];
    if (!f) { showToast('err', 'Choose a CSV first.'); return; }

    // Light validation (Safari-friendly): rely on .csv extension; allow empty MIME
    if (!f.name?.toLowerCase().endsWith('.csv')) {
      showToast('err', 'Please select a .csv file.');
      return;
    }
    if (f.size > MAX_BYTES) {
      showToast('err', `File too large (${fmt(f.size)}). Max ${fmt(MAX_BYTES)}.`);
      return;
    }

    busy = true;
    try {
      const fd = new FormData();
      fd.append('file', f); // field name must be "file"
      const res = await fetch('/api/import.csv', { method: 'POST', body: fd });
      if (!res.ok) { showToast('err', `Import failed (${res.status})`); return; }
      const json = await res.json().catch(() => ({}));
      const n = json?.imported ?? '';
      importSuccess = true;
      showToast('ok', `Imported ${n} record${n === 1 ? '' : 's'}.`);
      // brief pause to show badge/toast, then go home
      setTimeout(() => goto('/'), 900);
    } catch {
      showToast('err', 'Import failed (network error).');
    } finally {
      busy = false;
    }
  }

  function clearPick() {
    if (fileEl) fileEl.value = '';
    fileMeta = { name: '', size: 0 };
    importSuccess = false;
  }
</script>

<h1 class="text-xl font-semibold mb-4">Import Records</h1>

<div class="space-y-4 max-w-lg">
  <div>
    <label class="block mb-2">CSV file</label>

    <!-- Hidden file input; label acts as the button for consistent styling -->
    <input
      bind:this={fileEl}
      type="file"
      accept=".csv,text/csv"
      on:change={onPick}
      class="hidden"
      id="fileInput"
    />
    <div class="flex items-center gap-3 flex-wrap">
      <label
        for="fileInput"
        class="cursor-pointer px-3 py-2 rounded border border-gray-300 text-gray-700"
      >
        {fileMeta.name || "Choose CSV"}
      </label>

      {#if fileMeta.name}
        <span class="text-green-600 flex items-center gap-1">
          <span aria-hidden="true">✔</span>
          <span class="text-xs text-green-700">Selected ({fmt(fileMeta.size)})</span>
        </span>
      {/if}

      {#if importSuccess}
        <span class="ml-2 rounded bg-green-100 text-green-800 text-xs px-2 py-1">
          Imported ✓
        </span>
      {/if}
    </div>
  </div>

  <div class="flex items-center gap-3">
    <button
      type="button"
      class="px-3 py-2 rounded bg-black text-white disabled:opacity-50"
      on:click={upload}
      disabled={busy}
    >
      {#if busy}Uploading…{:else}Upload{/if}
    </button>

    <button
      type="button"
      class="px-3 py-2 rounded border border-gray-300 text-gray-700 disabled:opacity-50"
      on:click={clearPick}
      disabled={busy || !fileMeta.name}
    >
      Clear
    </button>
  </div>
</div>

{#if toast.show}
  <div
    class="fixed bottom-4 left-1/2 -translate-x-1/2 rounded-lg px-4 py-3 shadow-lg
           text-white text-sm
           {toast.kind === 'ok' ? 'bg-green-600' : 'bg-red-600'}
           animate-in"
    role="status" aria-live="polite"
  >
    {toast.text}
  </div>
{/if}

<style>
  .animate-in { animation: fadeInUp 180ms ease-out; }
  @keyframes fadeInUp {
    from { opacity: 0; transform: translate(-50%, 6px); }
    to   { opacity: 1; transform: translate(-50%, 0); }
  }
</style>
