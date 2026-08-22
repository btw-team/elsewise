import type browser from "webextension-polyfill";

export interface StorageAreaLike {
  get(
    keys?: string | string[] | Record<string, unknown> | null,
  ): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
}

export class BrowserStorageArea implements StorageAreaLike {
  constructor(private readonly area: browser.Storage.StorageArea) {}

  get(
    keys?: string | string[] | Record<string, unknown> | null,
  ): Promise<Record<string, unknown>> {
    return this.area.get(keys ?? null);
  }

  set(items: Record<string, unknown>): Promise<void> {
    return this.area.set(items);
  }
}
