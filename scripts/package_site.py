"""Build and package the exact SkipperCast Worker and client assets for Sites.

Run from the repository root after committing source changes. The output archive
contains the built Worker, not the unbuilt source ``dist`` directory.
"""
import argparse
from pathlib import Path
import subprocess
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default='node')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    subprocess.run([args.node, 'scripts/build-worker.mjs'], cwd=root, check=True)
    required = ['.openai/hosting.json', 'dist/.openai/hosting.json',
                'dist/server/index.js', 'dist/client/index.html']
    for name in required:
        if not (root / name).is_file():
            raise SystemExit(f'Missing built site asset: {name}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, 'w:gz') as bundle:
        for name in ('.openai/hosting.json', 'dist/.openai', 'dist/client', 'dist/server'):
            bundle.add(root / name, arcname=name)
    print(args.output)


if __name__ == '__main__':
    main()
