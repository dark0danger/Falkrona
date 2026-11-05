"""Prepare the pinned, separate Linux Hermes runtime at image build time."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]

def main():
    pin = json.loads((ROOT / 'infra/hermes/pin.json').read_text())
    checkout = ROOT / '.dependencies/hermes-agent'
    checkout.mkdir(parents=True)
    subprocess.run(['git', 'init', str(checkout)], check=True)
    subprocess.run(['git', 'remote', 'add', 'origin', pin['repository']], cwd=checkout, check=True)
    # Fetch only the pinned revision, avoiding a full history download at build time.
    subprocess.run(['git', '-c', 'http.version=HTTP/1.1', 'fetch', '--depth=1', 'origin', pin['commit']], cwd=checkout, check=True)
    subprocess.run(['git', 'checkout', '--detach', pin['commit']], cwd=checkout, check=True)
    environment = dict(os.environ, HERMES_HOME=str(ROOT / '.runtime/hermes/bootstrap'),
                       HERMES_RUNTIME_DIR=str(ROOT / '.runtime/hermes/tools'))
    # PM remains responsible for Hermes's Python/dependencies. No application venv mixing.
    subprocess.run(['bash', 'setup-hermes.sh', '--runtime-only', '--test-environment='],
                   cwd=checkout, env=environment, check=True)
    sys.path.insert(0, str(ROOT / 'scripts'))
    from local_setup import hermes_python
    python = hermes_python(ROOT)
    with TemporaryDirectory() as home:
        subprocess.run([str(python), '-I', '-c',
            'import sys; assert sys.prefix != sys.base_prefix, "Hermes must use its virtual environment"; '
            'import httpx; sys.path.insert(0, sys.argv[1]); from run_agent import AIAgent', str(checkout)],
            cwd=home, env=dict(environment, HERMES_HOME=home), check=True)
    (ROOT / '.runtime/hosted-hermes-python.txt').write_text(str(python))

if __name__ == '__main__':
    main()
