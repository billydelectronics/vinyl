<script lang="ts">
  import { goto } from '$app/navigation';
  import { onDestroy } from 'svelte';

  let imageFile: File | null = null;
  let imagePreviewUrl: string | null = null;

  let isUploading = false;
  let errorMsg = '';
  let infoMsg = '';

  type Candidate = {
    id: number;
    artist?: string | null;
    title?: string | null;
    score?: number | null;
  };

  type MatchResponse = {
    match: number | null;
    score?: number | null;
    candidates?: Candidate[];
  };

  let lastResponse: MatchResponse | null = null;

  function resetState() {
    imageFile = null;
    lastResponse = null;
    infoMsg = '';
    errorMsg = '';

    if (imagePreviewUrl) {
      URL.revokeObjectURL(imagePreviewUrl);
      imagePreviewUrl = null;
    }
  }

  function onFileChange(event: Event) {
    resetState();

    const input = event.currentTarget as HTMLInputElement;
    const files = input.files;
    if (!files || files.length === 0) {
      return;
    }

    const file = files[0];
    imageFile = file;
    imagePreviewUrl = URL.createObjectURL(file);

    void submitImage();
  }

  async function submitImage() {
    if (!imageFile) {
      errorMsg = 'Please select or capture a cover image first.';
      return;
    }

    errorMsg = '';
    infoMsg = 'Matching cover…';
    isUploading = true;

    try {
      const formData = new FormData();
      formData.append('file', imageFile);

      const res = await fetch('/api/cover-match', {
        method: 'POST',
        body: formData
      });

      if (!res.ok) {
        let detail = '';
        try {
          const data = await res.json();
          detail = typeof (data as any)?.detail === 'string' ? data.detail : '';
        } catch {
          // ignore JSON parse errors
        }
        throw new Error(detail || `Server error (${res.status})`);
      }

      const data = (await res.json()) as MatchResponse;
      lastResponse = data;

      if (data.match != null) {
        infoMsg = 'High confidence match. Opening record…';
        setTimeout(() => {
          goto(`/read/${data.match}`);
        }, 250);
        return;
      }

      infoMsg = '';
      if (data.candidates && data.candidates.length > 0) {
        errorMsg =
          'No confident single match. Tap the correct album below or try another photo.';
      } else {
        errorMsg =
          'No matching record found for this cover. Try a clearer, front-on photo filling the frame.';
      }
    } catch (err: unknown) {
      console.error(err);
      errorMsg =
        err instanceof Error
          ? `Failed to match cover: ${err.message}`
          : 'Failed to match cover. Please try again.';
      infoMsg = '';
    } finally {
      isUploading = false;
    }
  }

  function openCandidate(id: number) {
    goto(`/read/${id}`);
  }

  onDestroy(() => {
    if (imagePreviewUrl) {
      URL.revokeObjectURL(imagePreviewUrl);
    }
  });
</script>

<h2 class="text-xl font-semibold mb-3">Scan album cover</h2>

<p class="text-sm text-muted-foreground mb-4">
  Use your iPhone camera to capture the front cover of a record. For best results, fill the screen
  with the cover and hold the phone as straight-on as possible.
</p>

<div class="mb-4">
  <label
    for="cover-input"
    class="inline-flex items-center gap-2 px-3 py-2 rounded-md border border-border bg-surface-100 cursor-pointer hover:bg-surface-200 text-sm"
  >
    <span aria-hidden="true">📷</span>
    <span>{imageFile ? 'Retake cover photo' : 'Capture cover photo'}</span>
  </label>
  <input
    id="cover-input"
    type="file"
    accept="image/*"
    capture="environment"
    class="hidden"
    on:change={onFileChange}
  />
</div>

{#if imagePreviewUrl}
  <div class="mb-4">
    <p class="text-xs text-muted-foreground mb-1">Preview</p>
    <div class="max-w-xs border border-border rounded-lg overflow-hidden bg-black">
      <img src={imagePreviewUrl} alt="Selected album cover preview" class="w-full object-contain" />
    </div>
  </div>
{/if}

<div class="flex gap-2 mb-4">
  <button
    class="btn variant-filled"
    on:click={submitImage}
    disabled={isUploading || !imageFile}
  >
    {#if isUploading}
      Matching…
    {:else}
      Match cover
    {/if}
  </button>

  <button class="btn variant-ghost" type="button" on:click={resetState}>
    Clear
  </button>
</div>

{#if infoMsg}
  <div class="mb-3 rounded-md border border-blue-700 bg-blue-900/20 px-3 py-2 text-sm">
    {infoMsg}
  </div>
{/if}

{#if errorMsg}
  <div class="mb-3 rounded-md border border-red-700 bg-red-900/20 px-3 py-2 text-sm">
    {errorMsg}
  </div>
{/if}

{#if lastResponse && lastResponse.candidates && lastResponse.candidates.length > 0}
  <div class="mt-4 text-sm">
    <p class="font-semibold mb-2">Possible matches</p>
    <ul class="space-y-2">
      {#each lastResponse.candidates as c}
        <li>
          <button
            type="button"
            class="w-full flex items-center justify-between px-3 py-2 rounded-md border border-border bg-surface-100 hover:bg-surface-200 text-left"
            on:click={() => openCandidate(c.id)}
          >
            <div>
              <div>
                {#if c.artist || c.title}
                  {c.artist || 'Unknown artist'} — {c.title || 'Untitled'}
                {:else}
                  Record #{c.id}
                {/if}
              </div>
              {#if c.score != null}
                <div class="text-xs text-muted-foreground">
                  Match score: {c.score.toFixed(3)}
                </div>
              {/if}
            </div>
            <span class="text-xs text-muted-foreground">Open</span>
          </button>
        </li>
      {/each}
    </ul>
  </div>
{/if}