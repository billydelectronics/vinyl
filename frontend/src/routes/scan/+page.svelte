<script lang="ts">
  import { onDestroy } from 'svelte';
  import {
    BrowserMultiFormatReader,
    type Result,
    type Exception
  } from '@zxing/library';

  let videoEl: HTMLVideoElement | null = null;
  let resultEl: HTMLPreElement | null = null;

  let reader: BrowserMultiFormatReader | null = null;
  let stream: MediaStream | null = null;

  let starting = false;
  let lastCode = '';
  let errorMsg = '';

  async function start() {
    if (starting) return;
    starting = true;
    errorMsg = '';
    lastCode = '';

    try {
      reader = new BrowserMultiFormatReader();

      const constraints: MediaStreamConstraints = {
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 720 }
        },
        audio: false
      };

      stream = await navigator.mediaDevices.getUserMedia(constraints);

      if (!videoEl) throw new Error('Video element not ready');
      videoEl.srcObject = stream;
      await videoEl.play().catch(() => { /* iOS autoplay quirks */ });

      // NOTE: 'error' is optional in ZXing’s DecodeContinuouslyCallback
      reader.decodeFromVideoDevice(
        null,
        videoEl,
        async (res: Result | null, err?: Exception) => {
          if (res) {
            const code = res.getText().trim();
            if (!code || code === lastCode) return;
            lastCode = code;

            if (resultEl) {
              resultEl.textContent = `Barcode: ${code}\nLooking up…`;
            }

            try {
              const resp = await fetch(`/api/lookup/barcode/${encodeURIComponent(code)}`);
              if (!resp.ok) {
                const body = await resp.text();
                throw new Error(body || `Lookup failed (${resp.status})`);
              }
              const json = await resp.json();
              if (resultEl) resultEl.textContent = JSON.stringify(json, null, 2);
            } catch (e: any) {
              if (resultEl) {
                resultEl.textContent = `Barcode: ${code}\nError: ${e?.message ?? 'Lookup error'}`;
              }
            }
          }

          // Ignore transient decode errors; they are expected between frames
          void err;
        }
      );
    } catch (e: any) {
      errorMsg = e?.message ?? 'Could not start camera';
      await stop();
    } finally {
      starting = false;
    }
  }

  async function stop() {
    if (reader) {
      try { reader.reset(); } catch {}
      reader = null;
    }
    if (stream) {
      try { stream.getTracks().forEach((t) => t.stop()); } catch {}
      stream = null;
    }
    if (videoEl && videoEl.srcObject) {
      try { (videoEl.srcObject as MediaStream).getTracks().forEach((t) => t.stop()); } catch {}
      videoEl.srcObject = null;
    }
  }

  onDestroy(() => {
    stop();
  });
</script>

<h2 class="text-xl font-semibold mb-2">Scan</h2>

{#if errorMsg}
  <div class="mb-3 rounded-md border border-red-700 bg-red-900/20 px-3 py-2 text-sm text-red-200">
    {errorMsg}
  </div>
{/if}

<video
  bind:this={videoEl}
  autoplay
  muted
  playsinline
  class="w-full max-w-md bg-black rounded"
></video>

<div class="flex gap-2 my-2">
  <button class="btn variant-filled" on:click={start} disabled={starting}>
    {starting ? 'Starting…' : 'Start'}
  </button>
  <button class="btn variant-ghost" on:click={stop}>Stop</button>
</div>

<pre class="p-2 bg-surface-100 rounded whitespace-pre-wrap break-words" bind:this={resultEl}></pre>