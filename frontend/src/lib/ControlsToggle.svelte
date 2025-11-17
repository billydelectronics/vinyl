<script lang="ts">
  // Which element to show/hide (a container you mark in +page.svelte)
  export let targetSelector = '[data-role="read-controls"]';

  const STORE_KEY = 'readControlsVisible';
  let visible = true;

  function applyState(state: boolean) {
    const el = document.querySelector<HTMLElement>(targetSelector);
    if (!el) return;
    el.style.display = state ? '' : 'none';
    el.setAttribute('aria-hidden', state ? 'false' : 'true');
  }

  function toggle() {
    visible = !visible;
    try { localStorage.setItem(STORE_KEY, JSON.stringify(visible)); } catch {}
    applyState(visible);
  }

  // Initialize from saved preference
  if (typeof window !== 'undefined') {
    try {
      const saved = localStorage.getItem(STORE_KEY);
      visible = saved ? JSON.parse(saved) : true;
    } catch {}
    queueMicrotask(() => applyState(visible));
  }
</script>

<!-- Sticky bar under the top nav -->
<div class="max-w-5xl mx-auto px-6 sticky top-[2rem] z-20 bg-black/90 backdrop-blur-sm py-0 -mt-px">
  <button
    type="button"
    on:click={toggle}
    class="inline-flex items-center gap-2 px-3 py-1.5 rounded-md border border-zinc-700 hover:bg-zinc-800 text-sm"
    aria-pressed={visible}
    aria-controls="read-controls"
    title={visible ? 'Hide search & filters' : 'Show search & filters'}
  >
    <span class="text-base leading-none">🔎</span>
    <span class="hidden sm:inline align-middle">{visible ? 'Hide' : 'Show'} controls</span>
  </button>
</div>