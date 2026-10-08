"""Prepare manifest-selected Words sources and pinned Gist examples inside the VM image."""
import json
import subprocess
import sys
from pathlib import Path


def main():
    workspace = Path('/app')
    manifest = json.loads((workspace / 'plugins/words-net/plugin.json').read_text())
    revisions = {}
    for kind, source in manifest['sources'].items():
        destination = workspace / source['path']
        if not destination.exists():
            subprocess.run([
                'git', 'clone', '--depth', '1', '--filter=blob:none', '--sparse',
                '--branch', source['branch'], source['url'], str(destination),
            ], check=True)
            subprocess.run(['git', '-C', str(destination), 'sparse-checkout', 'set',
                            source['prefix']], check=True)
        def git(*args):
            return subprocess.check_output(['git', '-C', str(destination), *args], text=True).strip()
        if git('remote', 'get-url', 'origin') != source['url']:
            raise RuntimeError(f'Unexpected source origin: {destination}')
        if git('status', '--porcelain'):
            raise RuntimeError(f'Source checkout must be clean: {destination}')
        if not (destination / source['prefix']).is_dir():
            raise RuntimeError(f'Source prefix missing: {destination}')
        revisions[kind] = git('rev-parse', 'HEAD')
    # Use the source package so its default cache resolves to the mounted sources volume.
    sys.path.insert(0, str(workspace / 'plugins/words-net/src'))
    from adcs_words_net.gist_examples import DEFAULT_CACHE, prepare
    result = prepare(workspace / manifest['sources']['docs']['path'] / 'net', DEFAULT_CACHE)
    record = {'revisions': revisions, 'gist_examples': result}
    (workspace / 'plugins/words-net/sources/preparation.json').write_text(
        json.dumps(record, indent=2) + '\n'
    )
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
