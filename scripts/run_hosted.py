"""One hosted service: API plus isolated workspace workers sharing one volume.

New workspaces receive workers automatically. Fail the service if a child exits
so Railway restarts it instead of serving a silently broken generation queue.
"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

def main():
    os.chdir(ROOT)
    if not os.environ.get('BRANDPILOT_DATABASE_URL') and os.environ.get('DATABASE_URL'):
        os.environ['BRANDPILOT_DATABASE_URL'] = os.environ['DATABASE_URL']
    from brandpilot.settings import AppSettings
    settings = AppSettings.from_env()
    os.environ['BRANDPILOT_DATABASE_URL'] = settings.database_url
    if not os.environ.get('BRANDPILOT_HERMES_PYTHON'):
        os.environ['BRANDPILOT_HERMES_PYTHON'] = (ROOT / '.runtime/hosted-hermes-python.txt').read_text().strip()
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True)
    from brandpilot.database import build_engine
    from sqlalchemy import text
    engine = build_engine(settings.database_url, role='brandpilot_app')
    children = []
    workspaces = set()
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    def spawn(args, env=None):
        child = subprocess.Popen([sys.executable, *args], env=env)
        children.append(child)
    try:
        spawn(['-m', 'uvicorn', 'apps.api.main:app', '--host', '0.0.0.0', '--port', os.environ.get('PORT', '8000')])
        while not stopping:
            if any(child.poll() is not None for child in children):
                raise RuntimeError('A backend process exited; restarting the service is required.')
            with engine.connect() as connection:
                ids = set(connection.execute(text('SELECT id FROM workspaces')).scalars())
            for workspace in ids - workspaces:
                env = dict(os.environ, BRANDPILOT_WORKSPACE_ID=str(workspace))
                spawn(['-m', 'apps.worker.main'], env)
                spawn(['-m', 'apps.worker.main', '--publishing-only'], env)
                workspaces.add(workspace)
            for _ in range(10):
                if stopping: break
                time.sleep(0.5)
    finally:
        for child in children:
            if child.poll() is None: child.terminate()
        deadline = time.monotonic() + 15
        for child in children:
            try: child.wait(timeout=max(0.1, deadline-time.monotonic()))
            except subprocess.TimeoutExpired: child.kill(); child.wait()
        engine.dispose()

if __name__ == '__main__':
    main()
