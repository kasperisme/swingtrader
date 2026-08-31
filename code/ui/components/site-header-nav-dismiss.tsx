"use client";

import { useEffect } from "react";

/**
 * The desktop header menus are native `<details>` elements grouped under the
 * `desktop-main-nav` name, so the browser closes the others when you open one.
 * What it will not do is close them when you click somewhere else entirely —
 * a native `<details>` stays open until its own summary is clicked again.
 *
 * This mounts one document-level listener for the whole header that closes any
 * open menu on an outside pointer-down, and on Escape.
 */
const NAV_GROUP = 'details[name="desktop-main-nav"]';

export function SiteHeaderNavDismiss() {
  useEffect(() => {
    const closeAll = (except?: Element | null) => {
      document.querySelectorAll<HTMLDetailsElement>(NAV_GROUP).forEach((menu) => {
        if (menu !== except && menu.open) menu.open = false;
      });
    };

    const onPointerDown = (event: PointerEvent) => {
      const node = event.target;
      const element =
        node instanceof Element
          ? node
          : node instanceof Node
            ? node.parentElement
            : null;
      // Leave the menu the click landed in alone — the browser's own toggle
      // handles clicking its summary a second time.
      closeAll(element?.closest(NAV_GROUP) ?? null);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeAll();
    };

    // Capture phase so a menu still closes even if something inside the page
    // stops the event from bubbling.
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  return null;
}
