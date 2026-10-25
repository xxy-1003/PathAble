"""Build the approved backend for Linux x86_64 Python 3.12 without Docker.

Uses PyPI binary wheels; does not run Linux native modules on Windows. No AWS
credentials, demo images, local databases or operator config enter the zip.
This prepares an artifact/template and does not provision AWS resources.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile
import yaml


class CfnLoader(yaml.SafeLoader):
    pass


def intrinsic(loader, tag, node):
    value = (loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else
             loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node))
    if tag == 'GetAtt' and isinstance(value, str):
        value = value.split('.', 1)
    return {tag if tag == 'Ref' else 'Fn::' + tag: value}


CfnLoader.add_multi_constructor('!', intrinsic)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--artifact-bucket', required=True)
    parser.add_argument('--requirements', type=Path,
                        help='Override the checked-in release dependency lock')
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    requirements = args.requirements or source / 'requirements-release.txt'
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='lambda-linux-', dir=args.output) as folder:
        staging = Path(folder)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
            '--only-binary=:all:', '--platform', 'manylinux2014_x86_64', '--platform', 'manylinux_2_28_x86_64',
            '--implementation', 'cp', '--python-version', '3.12', '--target', str(staging),
            '--no-compile', '-r', str(requirements)], check=True)
        app = staging / 'fixed_camera'
        app.mkdir()
        for name in ('__init__.py', 'app.py', 'models.py', 'storage.py', 'evidence.py', 'lambda_handler.py'):
            shutil.copyfile(source / name, app / name)
        versions = sorted(f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions(path=[str(staging)]))
        (args.output / 'requirements.resolved.txt').write_text('\n'.join(versions) + '\n', encoding='utf-8')
        bundle = args.output / 'backend.zip'
        with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as output:
            for path in sorted(staging.rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts:
                    output.write(path, path.relative_to(staging).as_posix())
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    key = f'pathable-fixed-camera-demo/{digest}.zip'
    template = yaml.load((source / 'template.yaml').read_text(encoding='utf-8'), Loader=CfnLoader)
    template['Resources']['ApiFunction']['Properties']['CodeUri'] = {'Bucket': args.artifact_bucket, 'Key': key}
    (args.output / 'packaged-template.json').write_text(json.dumps(template, indent=2), encoding='utf-8')
    manifest = {'sha256': digest, 'zip_bytes': bundle.stat().st_size, 'bucket': args.artifact_bucket,
                'key': key, 'runtime': 'python3.12', 'architecture': 'x86_64'}
    (args.output / 'package-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
