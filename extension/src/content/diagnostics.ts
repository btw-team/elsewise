const SENSITIVE_ATTRIBUTES = [
  "href",
  "src",
  "srcset",
  "data-participant-id",
  "data-user-id",
  "data-email",
];

export function sanitizeUrl(rawUrl: string): string {
  const url = new URL(rawUrl);
  url.search = "";
  url.hash = "";
  return `${url.origin}${url.pathname}`;
}

export function sanitizeSubtree(
  root: Element,
  options: { redactText?: boolean; redactNames?: boolean } = {},
): string {
  const clone = root.cloneNode(true) as Element;
  for (const element of [clone, ...Array.from(clone.querySelectorAll("*"))]) {
    for (const attribute of SENSITIVE_ATTRIBUTES)
      element.removeAttribute(attribute);
    for (const attribute of Array.from(element.attributes)) {
      if (
        /participant|person|mri|account|email|token|auth|session/i.test(
          attribute.name,
        )
      ) {
        element.removeAttribute(attribute.name);
      }
    }
    if (options.redactNames && element.hasAttribute("data-speaker")) {
      element.setAttribute("data-speaker", "[speaker]");
    }
    if (options.redactNames && element.hasAttribute("data-elsewise-speaker")) {
      element.setAttribute("data-elsewise-speaker", "[speaker]");
    }
    if (
      options.redactNames &&
      element.matches('[data-tid="author"], [data-speaker-label]')
    ) {
      element.textContent = "[speaker]";
    }
    if (
      options.redactText &&
      element.matches(
        '[data-caption-text], [data-tid="closed-caption-text"], .ygicle, .live-transcription-subtitle__item',
      )
    ) {
      element.textContent = "[caption text]";
    }
  }
  return clone.outerHTML.slice(0, 100_000);
}
