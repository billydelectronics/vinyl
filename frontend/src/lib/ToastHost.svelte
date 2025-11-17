<script lang="ts">
  import { toasts, type Toast } from './toast';
  import { fly, fade } from 'svelte/transition';

  let items: Toast[] = [];
  const unsub = toasts.subscribe((v) => (items = v));
  $: items;
  // unsub auto-handled by Svelte on destroy
</script>

<div class="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2">
  {#each items as t (t.id)}
    <div
      in:fly={{ x: 24, duration: 150 }}
      out:fade={{ duration: 150 }}
      class="min-w-[220px] max-w-[360px] rounded-lg border px-3 py-2 shadow-lg
             bg-zinc-900/95 border-zinc-700 text-sm text-zinc-200 flex items-start gap-2"
    >
      <div class="mt-0.5">
        {#if t.kind === 'success'}
          <span class="inline-block h-2.5 w-2.5 rounded-full bg-green-500"></span>
        {:else if t.kind === 'error'}
          <span class="inline-block h-2.5 w-2.5 rounded-full bg-red-500"></span>
        {:else}
          <span class="inline-block h-2.5 w-2.5 rounded-full bg-blue-500"></span>
        {/if}
      </div>
      <div class="flex-1 leading-snug pr-2">{t.message}</div>
      <button
        class="text-zinc-400 hover:text-zinc-200"
        on:click={() => toasts.remove(t.id)}
        aria-label="Dismiss"
        title="Dismiss"
      >
        ×
      </button>
    </div>
  {/each}
</div>