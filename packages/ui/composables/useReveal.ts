import { onBeforeUnmount, onMounted, ref } from "vue";

// Scroll-triggered entrance, once. Landing pages only — a console screen whose data
// moves while someone is reading it is worse than one that never moves. Unobserves on
// first intersection so a section never re-animates on scroll-by.
export function useReveal() {
  const el = ref<HTMLElement | null>(null);
  const shown = ref(false);
  let observer: IntersectionObserver | null = null;

  onMounted(() => {
    if (!el.value) return;
    if (typeof IntersectionObserver === "undefined") {
      shown.value = true;
      return;
    }
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          observer?.unobserve(entry.target);
          shown.value = true;
        }
      },
      { threshold: 0.15, rootMargin: "0px 0px -10% 0px" },
    );
    observer.observe(el.value);
  });

  onBeforeUnmount(() => observer?.disconnect());

  return { el, shown };
}
