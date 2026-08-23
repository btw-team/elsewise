import { RECONNECT_MAX_DELAY_SECONDS } from "../protocol/limits";

export class ReconnectBackoff {
  #attempt = 0;

  constructor(
    private readonly random: () => number = Math.random,
    private readonly baseMilliseconds = 500,
    private readonly maximumMilliseconds = RECONNECT_MAX_DELAY_SECONDS * 1000,
  ) {}

  nextDelay(): number {
    const ceiling = Math.min(
      this.maximumMilliseconds,
      this.baseMilliseconds * 2 ** this.#attempt,
    );
    this.#attempt += 1;
    return Math.floor(ceiling / 2 + this.random() * (ceiling / 2));
  }

  reset(): void {
    this.#attempt = 0;
  }
}
