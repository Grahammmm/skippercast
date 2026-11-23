type SaveProgressState = {done: number; total: number; fraction: number; finished: boolean};

export function gpxSaveProgress(): {
  update(done: number, total: number): void;
  state(): SaveProgressState;
} {
  const lastByTotal = new Map<number, number>();
  let current: SaveProgressState = {done: 0, total: 0, fraction: 0, finished: false};

  return {
    update(done, total) {
      if (!Number.isInteger(done) || !Number.isInteger(total) || done < 0 || total <= 0 || done > total) return;
      if (done < (lastByTotal.get(total) ?? 0)) return;

      lastByTotal.set(total, done);
      current = {done, total, fraction: done / total, finished: done === total};
    },
    state() {
      return {...current};
    },
  };
}
