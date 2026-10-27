// This module alone may import the installed native SQLite constructor.
// No replacement database implementation: all SQL still runs in real SQLite.
import {DatabaseSync as NativeDatabase} from 'node:sqlite';
export class DatabaseSync extends NativeDatabase {
  constructor(location, ...args) {
    if (location !== ':memory:') throw Error('SP1603_LIVE_STORE_SENTINEL');
    super(location, ...args);
  }
}
