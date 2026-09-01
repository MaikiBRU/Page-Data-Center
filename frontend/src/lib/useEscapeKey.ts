"use client";

import { useEffect } from "react";

/**
 * Closes an overlay when Escape is pressed.
 *
 * Every modal in the app was mouse-only: a keyboard user who opened one had no
 * way out except tabbing to the close button, and on the case detail that
 * meant traversing the whole dialog first.
 */
export function useEscapeKey(active: boolean, onEscape: () => void) {
  useEffect(() => {
    if (!active) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onEscape();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [active, onEscape]);
}
