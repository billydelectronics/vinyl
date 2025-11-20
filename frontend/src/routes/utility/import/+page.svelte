<script lang="ts">
  import { goto } from '$app/navigation';

  // All template columns (for display)
  const TEMPLATE_HEADERS = [
    'Artist',
    'Title',
    'Year',
    'Label',
    'Format',
    'Country',
    'Catalog #',
    'Barcode',
    'Discogs ID (manual)',
    'Manual Cover URL',
    'Album Notes',
    'Personal Notes'
  ];

  // Only these are *required* for import to run
  const REQUIRED_FOR_IMPORT = ['Artist', 'Title'];

  let fileInput: HTMLInputElement | null = null;
  let selectedFile: File | null = null;

  let headers: string[] = [];
  let busy = false;
  let status = '';
  let successMessage = '';
  let errorMessage = '';

  // Missing required fields (Artist + Title only)
  $: missingRequiredHeaders = REQUIRED_FOR_IMPORT.filter(
    (h) => !headers.some((hdr) => hdr.toLowerCase() === h.toLowerCase())
  );

  // Extra columns not in the template list (informational only)
  $: extraHeaders =
    headers.length === 0
      ? []
      : headers.filter(
          (hdr) => !TEMPLATE_HEADERS.some((req) => req.toLowerCase() === hdr.toLowerCase())
        );

  function resetMessages() {
    status = '';
    successMessage = '';
    errorMessage = '';
  }

  async function onFileChange(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    resetMessages();
    headers = [];
    selectedFile = input.files?.[0] ?? null;

    if (!selectedFile) {
      return;
    }

    try {
      const text = await selectedFile.text();
      const firstLine = text.split(/\r?\n/).find((line) => line.trim().length > 0) ?? '';
      const rawHeaders = firstLine.split(',');
      headers = rawHeaders
        .map((h) => h.trim().replace(/^"|"$/g, ''))
        .filter((h) => h.length > 0);

      if (!headers.length) {
        status = 'Could not detect any header columns in the first row.';
      } else {
        status = `Detected ${headers.length} column(s) in header row.`;
      }
    } catch (err: any) {
      errorMessage = err?.message ?? 'Failed to read CSV file.';
    }
  }

  async function runImport() {
    resetMessages();

    if (!selectedFile) {
      errorMessage = 'Please select a CSV file first.';
      return;
    }

    if (missingRequiredHeaders.length > 0) {
      errorMessage =
        'The CSV is missing required columns (Artist and Title). Please fix the header row and try again.';
      return;
    }

    busy = true;
    status = 'Uploading and processing file…';

    try {
      const fd = new FormData();
      fd.append('file', selectedFile);

      const res = await fetch('/api/import/csv', {
        method: 'POST',
        body: fd,
        credentials: 'same-origin'
      });

      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || `Import failed with status ${res.status}.`);
      }

      const json = await res.json();

      const added = json?.added ?? json?.created ?? json?.count ?? 0;
      const skipped = json?.skipped ?? json?.duplicates ?? 0;
      const updated = json?.updated ?? 0;

      const parts: string[] = [];
      parts.push(`${added} added`);
      if (updated) parts.push(`${updated} updated`);
      if (skipped) parts.push(`${skipped} skipped`);

      successMessage = `Import complete: ${parts.join(', ')}.`;
      status = '';
    } catch (err: any) {
      errorMessage = err?.message ?? 'Import failed.';
      status = '';
    } finally {
      busy = false;
    }
  }

  function clearFile() {
    if (fileInput) {
      fileInput.value = '';
    }
    selectedFile = null;
    headers = [];
    resetMessages();
  }
</script>

<div class="min-h-screen bg-gray-950 text-gray-100">
  <!-- Top Bar -->
  <div class="w-full border-b border-gray-800 bg-gray-900">
    <div class="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between gap-3">
      <div>
        <div class="text-sm uppercase tracking-wide text-gray-400">Utility</div>
        <div class="text-xl font-semibold text-gray-100">Import CSV</div>
      </div>
      <!-- Back button only shown after success (see bottom section) -->
    </div>
  </div>

  <!-- Main Content -->
  <div class="mx-auto max-w-3xl px-4 py-8 space-y-6">
    <section class="space-y-3">
      <p class="text-gray-300">
        Use this page to import records in bulk from a CSV file. The CSV should use the standard
        template. Only <span class="font-semibold">Artist</span> and <span class="font-semibold">Title</span> are required; the other
        columns are optional.
      </p>

      <div class="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
        <div class="text-xs uppercase tracking-wide text-gray-400 mb-2">
          Template columns (header row)
        </div>
        <ul class="grid grid-cols-1 sm:grid-cols-2 gap-1 text-sm text-gray-100">
          {#each TEMPLATE_HEADERS as col}
            <li class="flex items-center gap-2">
              <span
                class="inline-flex h-4 w-4 items-center justify-center rounded-full border text-[10px]
                {headers.some((h) => h.toLowerCase() === col.toLowerCase())
                  ? 'border-emerald-500 text-emerald-400'
                  : 'border-gray-600 text-gray-500'}"
              >
                {headers.some((h) => h.toLowerCase() === col.toLowerCase()) ? '✓' : '•'}
              </span>
              <span>
                {col}
                {#if REQUIRED_FOR_IMPORT.some((r) => r.toLowerCase() === col.toLowerCase())}
                  <span class="text-[11px] text-amber-300 ml-1">(required)</span>
                {/if}
              </span>
            </li>
          {/each}
        </ul>

        <div class="mt-4 text-xs text-gray-400">
          Need a fresh template?{' '}
          <a
            href="/api/meta/import-template"
            class="text-emerald-400 hover:underline"
          >
            Download CSV template
          </a>
          
        </div>
      </div>
    </section>

    <section class="space-y-4">
      <div class="space-y-2">
        <label class="block text-sm font-medium text-gray-200">Choose CSV file</label>
        <input
          type="file"
          accept=".csv,text/csv"
          class="block w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-100 file:mr-3 file:rounded-md file:border-0 file:bg-gray-700 file:px-3 file:py-2 file:text-sm file:text-gray-100 hover:file:bg-gray-600"
          bind:this={fileInput}
          on:change={onFileChange}
        />
        {#if selectedFile}
          <div class="flex items-center justify-between text-xs text-gray-400 mt-1">
            <div>
              Selected:{' '}
              <span class="text-gray-200">{selectedFile.name}</span> (
              {Math.round(selectedFile.size / 1024)} KB)
            </div>
            <button
              type="button"
              class="text-xs text-red-300 hover:text-red-200 underline"
              on:click={clearFile}
            >
              Clear
            </button>
          </div>
        {/if}
      </div>

      {#if headers.length}
        <div class="rounded-lg border border-gray-800 bg-gray-900/70 p-3 text-sm">
          <div class="font-medium text-gray-200 mb-1">Detected header columns</div>
          <div class="flex flex-wrap gap-2">
            {#each headers as h}
              <span class="rounded-full bg-gray-800 px-2 py-1 text-xs text-gray-100 border border-gray-700">
                {h}
              </span>
            {/each}
          </div>

          {#if missingRequiredHeaders.length}
            <div class="mt-3 text-xs text-amber-300">
              Missing required columns: {missingRequiredHeaders.join(', ')}.
              Please update the CSV header row before importing.
            </div>
          {/if}

          {#if extraHeaders.length}
            <div class="mt-2 text-xs text-gray-400">
              Extra columns (may be ignored by the importer if not recognized):{' '}
              {extraHeaders.join(', ')}.
            </div>
          {/if}
        </div>
      {/if}
    </section>

    <section class="space-y-3">
      <button
        type="button"
        class="px-4 py-2 rounded-lg border border-emerald-600 bg-emerald-600 hover:bg-emerald-500 text-sm font-medium text-white disabled:opacity-50 disabled:cursor-not-allowed"
        on:click={runImport}
        disabled={busy || !selectedFile || missingRequiredHeaders.length > 0}
      >
        {busy ? 'Importing…' : 'Run Import'}
      </button>

      {#if status}
        <div class="text-sm text-gray-300">{status}</div>
      {/if}

      {#if successMessage}
        <div class="space-y-2">
          <div class="text-sm text-emerald-300">{successMessage}</div>
          <button
            type="button"
            class="px-3 py-1.5 rounded-lg border border-gray-600 bg-gray-800 hover:bg-gray-700 text-sm"
            on:click={() => goto('/utility')}
          >
            Back to Utility
          </button>
        </div>
      {/if}

      {#if errorMessage}
        <div class="text-sm text-red-300">{errorMessage}</div>
      {/if}
    </section>
  </div>
</div>