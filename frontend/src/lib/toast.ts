import { writable } from 'svelte/store';

export type ToastKind = 'success' | 'error' | 'info';
export type Toast = {
  id: number;
  kind: ToastKind;
  message: string;
  duration: number; // ms
};

function createToastStore() {
  const { subscribe, update } = writable<Toast[]>([]);
  let nextId = 1;

  function push(kind: ToastKind, message: string, duration = 3500) {
    const id = nextId++;
    const t: Toast = { id, kind, message, duration };
    update((list) => [...list, t]);
    // auto-remove after duration
    setTimeout(() => {
      update((list) => list.filter((x) => x.id !== id));
    }, duration);
  }

  function remove(id: number) {
    update((list) => list.filter((x) => x.id !== id));
  }

  return {
    subscribe,
    success: (m: string, d?: number) => push('success', m, d),
    error: (m: string, d?: number) => push('error', m, d),
    info: (m: string, d?: number) => push('info', m, d),
    remove
  };
}

export const toasts = createToastStore();