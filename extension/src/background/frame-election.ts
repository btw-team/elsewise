export class FrameElection {
  readonly #elected = new Map<number, number>();

  acceptStatus(
    tabId: number,
    frameId: number,
    captionsStatus: string,
    confidence: number,
  ): boolean {
    const current = this.#elected.get(tabId);
    const hasCaptionSurface =
      ["on_empty", "capturing"].includes(captionsStatus) && confidence >= 0.5;
    if (hasCaptionSurface) {
      if (current !== undefined && current !== frameId) return false;
      this.#elected.set(tabId, frameId);
      return true;
    }
    if (current !== undefined && current !== frameId) return false;
    if (current === undefined && frameId !== 0) return false;
    if (current === frameId && captionsStatus === "off")
      this.#elected.delete(tabId);
    return true;
  }

  acceptUtterance(tabId: number, frameId: number): boolean {
    const current = this.#elected.get(tabId);
    if (current === undefined) {
      this.#elected.set(tabId, frameId);
      return true;
    }
    return current === frameId;
  }

  disconnected(tabId: number, frameId: number): void {
    if (this.#elected.get(tabId) === frameId) this.#elected.delete(tabId);
  }

  frameFor(tabId: number): number | undefined {
    return this.#elected.get(tabId);
  }

  clear(tabId: number): void {
    this.#elected.delete(tabId);
  }
}
