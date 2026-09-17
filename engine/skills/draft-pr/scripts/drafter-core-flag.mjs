import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const DRAFTER_CORE_FLAG = 'CATSTACK_DRAFTER_CORE';
const FLAGS_PY = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'hooks', '_flags', 'flags.py');

export function drafterCoreFlag(cwd = process.cwd()) {
  if (!existsSync(FLAGS_PY)) {
    console.error(`drafter-core-flag: ${FLAGS_PY} not found; treating ${DRAFTER_CORE_FLAG} as off.`);
    return 'unchecked';
  }
  const res = spawnSync('python3', [FLAGS_PY, DRAFTER_CORE_FLAG, '--cwd', cwd], { encoding: 'utf-8' });
  if (res.error || res.status !== 0) {
    const reason = res.error ? res.error.message : `exit ${res.status}: ${res.stderr.trim()}`;
    console.error(`drafter-core-flag: could not look up ${DRAFTER_CORE_FLAG} (${reason}); treating it as off.`);
    return 'unchecked';
  }
  if (res.stderr) process.stderr.write(res.stderr);
  return res.stdout.trim();
}

export function drafterCoreSkippedLine(state) {
  return `UNCHECKED: drafter-core rules skipped (${DRAFTER_CORE_FLAG} is ${state}; set ${DRAFTER_CORE_FLAG}=1 to run them)`;
}

export async function loadDrafterCore(cwd = process.cwd()) {
  const state = drafterCoreFlag(cwd);
  if (state !== 'on') {
    console.log(drafterCoreSkippedLine(state));
    return null;
  }
  return import('@neko-catpital-labs/drafter-core');
}
