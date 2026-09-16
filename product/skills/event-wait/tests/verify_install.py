#!/usr/bin/env python3
"""Rerunnable isolated-home install check. Never install into the user's home."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[4]
SKILL = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='event-wait-install-') as temporary:
        isolated = Path(temporary)
        env = dict(os.environ, HOME=str(isolated),
                   XDG_CONFIG_HOME=str(isolated / '.config'),
                   XDG_CACHE_HOME=str(isolated / '.cache'))
        # Installation tools use HOME; remove inherited harness-home overrides.
        env.pop('CODEX_HOME', None)
        result = subprocess.run(['./install.sh'], cwd=REPO, env=env,
                                capture_output=True, text=True)
        print(f'isolated ./install.sh exit={result.returncode}')
        if result.returncode:
            print((result.stdout + result.stderr)[-6000:])
            return result.returncode
        parity = subprocess.run([sys.executable, 'scripts/ci/check_skills_three_harnesses.py',
                                 '--home', '--home-dir', str(isolated)], cwd=REPO,
                                env=env, capture_output=True, text=True)
        print(parity.stdout.strip())
        if parity.returncode:
            print(parity.stderr)
            return parity.returncode
        for harness in ('claude', 'cursor', 'codex'):
            link = isolated / f'.{harness}' / 'skills/event-wait'
            if not link.is_symlink() or link.resolve() != SKILL:
                raise RuntimeError(f'{harness}: link does not resolve to this skill')
            cli = subprocess.run([sys.executable, str(link / 'scripts/wait_event.py'), '--help'],
                                 env=env, capture_output=True, text=True)
            if cli.returncode or '{wait,ack-wake}' not in cli.stdout:
                raise RuntimeError(f'{harness}: CLI failed with exit {cli.returncode}')
            print(f'PASS {harness}: same skill source; CLI --help exit=0')
        print('PASS isolated install: all three skill links resolve to the same source; real home untouched')
    return 0


if __name__ == '__main__':
    sys.exit(main())
