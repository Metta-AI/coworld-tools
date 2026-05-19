export class SeededRandom {
  private state: number;

  constructor(seed = 0xdecafbad) {
    this.state = seed >>> 0;
  }

  stateValue(): number {
    return this.state;
  }

  setState(state: number): void {
    this.state = state >>> 0;
  }

  next(): number {
    this.state = (1664525 * this.state + 1013904223) >>> 0;
    return this.state / 0x100000000;
  }

  int(maxExclusive: number): number {
    return Math.floor(this.next() * maxExclusive);
  }

  choice<T>(values: readonly T[]): T {
    if (values.length === 0) {
      throw new Error("Cannot choose from an empty array");
    }

    return values[this.int(values.length)];
  }
}
