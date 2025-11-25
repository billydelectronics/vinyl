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

  type BestMatch = {
    id: number;
    score: number;
    gap_to_second: number;
  };

  // Support both legacy and newer response shapes
  type MatchResponse = {
    // legacy shape
    match?: number | null;
    score?: number | null;

    // newer shape
    best?: BestMatch | null;
    confident?: boolean;
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

  /**
   * Crop an image file to a centered square on the client.
   * If anything fails, fall back to the original file.
   */
  function cropToSquare(file: File): Promise<File> {
    return new Promise((resolve) => {
      const img = new Image();
      const url = URL.createObjectURL(file);

      img.onload = () => {
        try {
          const size = Math.min(img.width, img.height);
          const sx = (img.width - size) / 2;
          const sy = (img.height - size) / 2;

          const canvas = document.createElement('canvas');
          canvas.width = size;
          canvas.height = size;
          const ctx = canvas.getContext('2d');

          if (!ctx) {
            URL.revokeObjectURL(url);
            resolve(file);
            return;
          }

          ctx.drawImage(img, sx, sy, size, size, 0, 0, size, size);

          const mimeType = file.type && file.type.startsWith('image/') ? file.type : 'image/jpeg';
          canvas.toBlob(
            (blob) => {
              URL.revokeObjectURL(url);
              if (!blob) {
                resolve(file);
                return;
              }
              const cropped = new File([blob], file.name, { type: mimeType });
              resolve(cropped);
            },
            mimeType,
            0.9
          );
        } catch (e) {
          console.error('cropToSquare failed, using original file', e);
          URL.revokeObjectURL(url);
          resolve(file);
        }
      };

      img.onerror = () => {
        console.error('Image load error in cropToSquare');
        URL.revokeObjectURL(url);
        resolve(file);
      };

      img.src = url;
    });
  }

  async function onFileChange(event: Event) {
    resetState();

    const input = event.currentTarget as HTMLInputElement;
    const files = input.files;
    if (!files || files.length === 0) {
      return;
    }

    const originalFile = files[0];

    // Crop to centered square before upload / preview
    const croppedFile = await cropToSquare(originalFile);

    imageFile = croppedFile;
    imagePreviewUrl = URL.createObjectURL(croppedFile);

    void submitImage();
  }

  async function submitImage() {
    if (!imageFile) {
      errorMsg = 'Please capture or select a cover image first.';
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

      // 1) Legacy behavior: backend sets "match" id when confident
      if (data.match != null) {
        infoMsg = 'High confidence match. Opening record…';
        setTimeout(() => {
          goto(`/read/${data.match}`);
        }, 250);
        return;
      }

      // 2) Normalize candidates and always auto-open top one if any exist
      const candidates: Candidate[] = (data.candidates ?? []).slice();

      if (candidates.length > 0) {
        // Sort by score descending (treat null/undefined as 0)
        const sorted = candidates
          .slice()
          .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

        const top = sorted[0];

        if (top) {
          infoMsg = 'Opening best match…';
          setTimeout(() => {
            goto(`/read/${top.id}`);
          }, 250);
          return;
        }
      }

      // 3) No candidates at all → show guidance
      infoMsg = '';
      errorMsg =
        'No matching record found for this cover. Try a clearer, front-on photo filling the frame.';
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
  Use your iPhone camera to capture the front cover of a record. For best results, fill the camera
  view with the cover and keep it as straight-on as possible. The image is cropped to a centered
  square before matching.
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
    <p class="text-xs text-muted-foreground mb-1">Preview (cropped to square)</p>
    <div class="max-w-xs border border-border rounded-lg overflow-hidden bg-black">
      <img
        src={imagePreviewUrl}
        alt="Selected album cover preview"
        class="w-full object-contain"
      />
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