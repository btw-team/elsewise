import { type RefObject, useEffect, useRef } from "react";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export function useModalFocus(
  onClose: () => void,
  busy = false,
  initialFocus?: RefObject<HTMLElement | null>,
): RefObject<HTMLElement | null> {
  const container = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  const busyRef = useRef(busy);
  closeRef.current = onClose;
  busyRef.current = busy;

  useEffect(() => {
    const modal = container.current;
    if (!modal) return;
    const previous = document.activeElement as HTMLElement | null;
    const backdrop = modal.parentElement;
    const siblings = backdrop?.parentElement
      ? [...backdrop.parentElement.children].filter((item) => item !== backdrop)
      : [];
    const priorInert = siblings.map((item) => item.hasAttribute("inert"));
    siblings.forEach((item) => item.setAttribute("inert", ""));

    const focusInitial = () => {
      const target =
        initialFocus?.current ??
        modal.querySelector<HTMLElement>(FOCUSABLE) ??
        modal;
      target.focus();
    };
    focusInitial();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [
        ...modal.querySelectorAll<HTMLElement>(FOCUSABLE),
      ].filter(
        (item) => !item.hidden && item.getAttribute("aria-hidden") !== "true",
      );
      if (focusable.length === 0) {
        event.preventDefault();
        modal.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      siblings.forEach((item, index) => {
        if (!priorInert[index]) item.removeAttribute("inert");
      });
      previous?.focus();
    };
  }, [initialFocus]);

  useEffect(() => {
    if (busy) container.current?.focus();
  }, [busy]);

  return container;
}
