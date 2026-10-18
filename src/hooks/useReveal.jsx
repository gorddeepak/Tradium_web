import { useEffect, useRef, useState } from "react";

/* Reveals children when their section scrolls into view. Gate each child with
   shown ? "animate-rise" : "opacity-0" — the opacity-0 half is required. */

/* Set in the initial state, not inside the effect. */
function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useReveal() {
  const ref = useRef(null);

  /* Reduced-motion users start revealed; no observer is built for them. */
  const [shown, setShown] = useState(() => prefersReducedMotion());

  useEffect(() => {
    if (prefersReducedMotion()) return;

    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          setShown(true);
          observer.disconnect();
        }
      },
      /* Fires only when a section is properly in view, not on its first pixel. */
      { rootMargin: "0px 0px -12% 0px" }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return [ref, shown];
}
