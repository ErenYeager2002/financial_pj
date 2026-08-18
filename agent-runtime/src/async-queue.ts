export class AsyncQueue<T> implements AsyncIterable<T>, AsyncIterator<T> {
  private readonly values: T[] = [];
  private readonly waiters: Array<{
    resolve: (result: IteratorResult<T>) => void;
    reject: (reason?: unknown) => void;
  }> = [];
  private closed = false;
  private failure: unknown = null;

  push(value: T): void {
    if (this.closed) return;
    const waiter = this.waiters.shift();
    if (waiter) {
      waiter.resolve({ value, done: false });
    } else {
      this.values.push(value);
    }
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    while (this.waiters.length) {
      this.waiters.shift()?.resolve({ value: undefined, done: true });
    }
  }

  fail(reason: unknown): void {
    if (this.closed) return;
    this.failure = reason;
    this.closed = true;
    while (this.waiters.length) {
      this.waiters.shift()?.reject(reason);
    }
  }

  next(): Promise<IteratorResult<T>> {
    if (this.values.length) {
      return Promise.resolve({ value: this.values.shift() as T, done: false });
    }
    if (this.failure !== null) return Promise.reject(this.failure);
    if (this.closed) return Promise.resolve({ value: undefined, done: true });
    return new Promise<IteratorResult<T>>((resolve, reject) => {
      this.waiters.push({ resolve, reject });
    });
  }

  [Symbol.asyncIterator](): AsyncIterator<T> {
    return this;
  }
}
