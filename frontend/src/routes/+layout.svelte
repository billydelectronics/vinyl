<script lang="ts">
  import '../app.postcss';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import ToastHost from '$lib/ToastHost.svelte';

  $: pathname = $page.url.pathname;
  // Robust: matches "/read", "/read/", and "/read/…"
  $: inRead = /^\/read(?:\/|$)/.test(pathname);

  const STORE_KEY = 'readControlsVisible';
  let controlsVisible = true;

  function applyControlsState(state: boolean) {
    if (typeof document === 'undefined') return;
    const el = document.querySelector<HTMLElement>('[data-role="read-controls"]');
    if (!el) return;
    el.style.display = state ? '' : 'none';
    el.setAttribute('aria-hidden', state ? 'false' : 'true');
  }

  function focusSearchInputSoon() {
    // Wait a tick so the element is on the page and visible
    requestAnimationFrame(() => {
      const input = document.getElementById('searchInput') as HTMLInputElement | null;
      if (input) {
        // preventScroll avoids fighting our window.scrollTo smooth animation
        try { input.focus({ preventScroll: true } as any); } catch { input.focus(); }
      }
    });
  }

  function toggleControls() {
    const next = !controlsVisible;
    controlsVisible = next;
    try { localStorage.setItem(STORE_KEY, JSON.stringify(controlsVisible)); } catch {}
    applyControlsState(next);

    // If we just made them visible while on /read, scroll to the top and focus search
    if (inRead && next && typeof window !== 'undefined') {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      focusSearchInputSoon();
    }
  }

  onMount(() => {
    try {
      const saved = localStorage.getItem(STORE_KEY);
      controlsVisible = saved ? JSON.parse(saved) : true;
    } catch {}
    applyControlsState(controlsVisible);
  });

  // Re-apply when navigating within /read so new pages pick up the state
  $: if (inRead) {
    queueMicrotask(() => applyControlsState(controlsVisible));
  }

  const isActive = (p: string) =>
    p === '/' ? pathname === '/' : pathname.startsWith(p);
</script>

<svelte:head>
  <title>Vinyl</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
</svelte:head>

<div class="min-h-screen bg-black text-white font-sans">
  <!-- Sticky universal nav bar (smaller/tighter) -->
  <header
    class="sticky top-0 z-30 bg-black/80 backdrop-blur supports-[backdrop-filter]:bg-black/70 border-b border-zinc-900">
    <div class="max-w-5xl mx-auto flex items-center justify-between gap-4 px-6 py-2">
      <!-- Brand -->
      <a href="/" class="flex items-center gap-2 text-xl font-bold hover:opacity-80">
        <span>🎵</span><span>Vinyl</span>
      </a>

      <!-- Nav: 🔎 (only on /read*), then 🏠 and 📖 -->
      <nav class="flex items-center gap-4 text-xl">
        {#if inRead}
          <button
            type="button"
            on:click={toggleControls}
            class="hover:opacity-80"
            aria-pressed={controlsVisible}
            aria-controls="read-controls"
            title={controlsVisible ? 'Hide search & filters' : 'Show search & filters'}
          >🔎</button>
        {/if}

        <a
          href="/"
          data-active={isActive('/')}
          class="hover:opacity-80 data-[active=true]:opacity-100"
          aria-current={isActive('/') ? 'page' : undefined}
        >🏠</a>

        <a
          href="/read"
          data-active={isActive('/read')}
          class="hover:opacity-80 data-[active=true]:opacity-100"
          aria-current={isActive('/read') ? 'page' : undefined}
        >📖</a>
      </nav>
    </div>
  </header>

  <!-- Content sits tight under sticky nav -->
  <main class="max-w-5xl mx-auto px-6 pt-0 pb-6">
    <slot />
  </main>
</div>

<ToastHost />

<style>
  a { text-decoration: none; transition: opacity 0.15s ease; }
  [data-active="false"] { opacity: 0.75; }
</style>