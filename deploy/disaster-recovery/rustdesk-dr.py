#!/usr/bin/env python3
"""Cold backup/restore of Joey's Linux RustDesk Compose stack. Run via sudo."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import signal
import stat
from contextlib import contextmanager
from datetime import datetime, timezone


def run(args, cwd=None, capture=False):
    # Capture first: loss of the SSH stderr pipe must not interrupt restart.
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for text in [result.stderr, '' if capture else result.stdout]:
        if text:
            try:
                sys.stderr.write(text)
                sys.stderr.flush()
            except OSError:
                pass
    result.check_returncode()
    return result.stdout.strip() if capture else None


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def compose(directory, files, project=None, override=None):
    result = ['docker', 'compose']
    if project:
        result += ['-p', project]
    for filename in files:
        result += ['-f', str(directory / filename)]
    if override:
        result += ['-f', str(override)]
    return result


def wait_running(directory, command, services):
    if not services:
        return
    for attempt in range(30):
        running = set(run(command + ['ps', '--status', 'running', '--services'], directory, True).splitlines())
        if set(services) <= running:
            return
        time.sleep(1)
    raise RuntimeError('Niet alle oorspronkelijk actieve containers draaien; controleer docker compose ps/logs.')


@contextmanager
def stack_lock(directory):
    import fcntl
    name = hashlib.sha256(str(directory).encode()).hexdigest()[:24]
    with open('/var/lock/joey-rustdesk-' + name + '.lock', 'a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Er loopt al een back-up/herstelactie voor deze stackmap.')
        yield


def snapshot(directory, command, running, destination):
    previous = {}
    for value in [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]:
        previous[value] = signal.signal(value, signal.SIG_IGN)
    # Marked before stop: a partial stop failure must also trigger a restart.
    try:
        if running:
            run(command + ['stop', '--timeout', '30'] + running, directory)
        run(['tar', '--acls', '--xattrs', '--numeric-owner', '--hard-dereference', '-cpf', str(destination), '-C', str(directory), '.'])
    finally:
        try:
            if running:
                run(command + ['start'] + running, directory)
                wait_running(directory, command, running)
        finally:
            for value, handler in previous.items():
                signal.signal(value, handler)


def backup(directory):
    directory = directory.resolve(strict=True)
    if not (directory / '.env').is_file() or not (directory / 'data/id_ed25519').is_file():
        raise RuntimeError('Verwacht de bestaande stackmap met .env en data/id_ed25519; geen nieuwe lege stack.')
    if not (directory / 'data/id_ed25519.pub').is_file():
        raise RuntimeError('Publieke serverkey ontbreekt.')
    # This bundle promises a complete directory backup, not copies of external mounts.
    for root, folders, files in os.walk(directory):
        for name in folders + files:
            path = Path(root) / name
            mode = path.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise RuntimeError('Symlink of bijzonder bestand gevonden; gebruik gewone bestanden binnen de stackmap: ' + str(path))
            if mode & 0o6000:
                raise RuntimeError('Setuid/setgid-bestand of map niet ondersteund: ' + str(path))
    initial = ['docker', 'compose']
    ids = run(initial + ['ps', '-a', '-q'], directory, True).splitlines()
    if not ids:
        raise RuntimeError('Geen bestaande Compose-containers gevonden in deze map.')
    containers = json.loads(run(['docker', 'inspect'] + ids, capture=True))
    labels = containers[0]['Config']['Labels']
    project = labels['com.docker.compose.project']
    config_paths = labels['com.docker.compose.project.config_files'].split(',')
    files = []
    for filename in config_paths:
        path = Path(filename).resolve(strict=True)
        files.append(str(path.relative_to(directory)))
    command = compose(directory, files, project)
    config = json.loads(run(command + ['config', '--format', 'json'], directory, True))
    for service in config['services'].values():
        if service.get('env_file'):
            for entry in service['env_file']:
                filename = entry.get('path') if isinstance(entry, dict) else entry
                Path(filename).resolve().relative_to(directory)
        for mount in service.get('volumes', []):
            if mount['type'] == 'bind':
                Path(mount['source']).resolve(strict=True).relative_to(directory)
            elif mount['type'] == 'volume':
                raise RuntimeError('Named/anonymous Docker-volume gevonden; dit script ondersteunt alleen bind-mounts binnen de stackmap.')
    images = {}
    running = []
    for container in containers:
        item = container['Config']['Labels']
        if item['com.docker.compose.project'] != project:
            raise RuntimeError('Containers van meerdere Compose-projecten gevonden.')
        if item.get('com.docker.compose.oneoff', '').lower() == 'true':
            if container['State']['Running']:
                raise RuntimeError('Er loopt nog een one-off taak, bijvoorbeeld prepare-client. Wacht tot die klaar is.')
            continue
        service = item['com.docker.compose.service']
        if container['State'].get('Paused'):
            raise RuntimeError('Een container is gepauzeerd; hervat deze voor de back-up.')
        if service in images and images[service] != container['Image']:
            raise RuntimeError('Meerdere imageversies voor dezelfde service; niet ondersteund.')
        images[service] = container['Image']
        if container['State']['Running']:
            running.append(service)
        # Inspect actual mounts too: these may differ from an edited Compose file.
        for mount in container.get('Mounts', []):
            if mount['Type'] == 'bind':
                Path(mount['Source']).resolve(strict=True).relative_to(directory)
            elif mount['Type'] == 'volume':
                raise RuntimeError('Bestaande container gebruikt een Docker-volume buiten de stackmap.')
    if not images or not {'hbbs', 'hbbr'} <= images.keys():
        raise RuntimeError('De bestaande hbbs/hbbr-containers ontbreken.')
    # Prevent accidental restore-time use of a hardcoded primary bind path.
    raw_compose = '\n'.join((directory / name).read_text() for name in files)
    if str(directory) in raw_compose:
        raise RuntimeError('Compose bevat het absolute bronpad. Gebruik relatieve bind-mounts voor herstel op een andere host.')
    with tempfile.TemporaryDirectory(prefix='rustdesk-dr-', dir='/var/tmp') as work:
        work = Path(work)
        snapshot(directory, command, sorted(set(running)), work / 'stack.tar')
        # Containers are already back up while immutable Docker images are exported.
        run(['docker', 'image', 'save', '-o', str(work / 'images.tar')] + sorted(set(images.values())))
        manifest = {
            'format': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
            'project': project, 'compose_files': files, 'images': images,
            'running_services': sorted(set(running)),
            'public_key_sha256': digest(directory / 'data/id_ed25519.pub'),
            'stack_sha256': digest(work / 'stack.tar'), 'images_sha256': digest(work / 'images.tar'),
            'source_directory': str(directory), 'source_hostname': os.uname().nodename,
        }
        (work / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        shutil.copyfile(__file__, work / 'rustdesk-dr.py')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        fd, output = tempfile.mkstemp(prefix='rustdesk-backup-' + stamp + '-', suffix='.tar.gz', dir='/var/tmp')
        os.close(fd)
        output = Path(output)
        try:
            run(['tar', '-czf', str(output), '-C', str(work), 'manifest.json', 'stack.tar', 'images.tar', 'rustdesk-dr.py'])
            checksum = digest(output)
            if 'SUDO_UID' in os.environ:
                os.chown(output, int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID']))
            output.chmod(0o600)
            print(json.dumps({'archive': str(output), 'sha256': checksum, 'bytes': output.stat().st_size}))
        except BaseException:
            output.unlink(missing_ok=True)
            raise


def extract_checked(archive, destination, expected=None):
    with tarfile.open(archive, 'r:*') as handle:
        members = handle.getmembers()
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or not (member.isfile() or member.isdir()):
                raise RuntimeError('Onveilig of niet ondersteund tar-item: ' + member.name)
            if member.mode & 0o6000:
                raise RuntimeError('Setuid/setgid-item geweigerd: ' + member.name)
        if expected is not None and {item.name for item in members} != expected:
            raise RuntimeError('Onverwachte bestanden in het back-uppakket.')
        # Preserve Linux ownership, ACLs and xattrs after validating every header.
        run(['tar', '--acls', '--xattrs', '--numeric-owner', '-xpf', str(archive), '-C', str(destination)])


def load_manifest(path):
    manifest = json.loads(path.read_text())
    if manifest.get('format') != 1:
        raise RuntimeError('Onbekend back-upformaat.')
    project = manifest['project']
    import re
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', project):
        raise RuntimeError('Ongeldige Compose-projectnaam.')
    for name in manifest['compose_files']:
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts:
            raise RuntimeError('Ongeldig Compose-pad.')
    for service, image in manifest['images'].items():
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', service) or not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
            raise RuntimeError('Ongeldige service/image in manifest.')
    if not isinstance(manifest['running_services'], list) or not set(manifest['running_services']) <= manifest['images'].keys():
        raise RuntimeError('Ongeldige lijst met actieve services.')
    return manifest


def activate(directory):
    manifest = load_manifest(directory / '.rustdesk-dr-manifest.json')
    existing = run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + manifest['project']], capture=True)
    if existing:
        raise RuntimeError('Dit Compose-project bestaat al op deze host. Controleer het handmatig; geen bestaande containers overschreven.')
    override = directory / '.rustdesk-dr-images.yml'
    command = compose(directory, manifest['compose_files'], manifest['project'], override)
    validate_restored_mounts(directory, command)
    services = manifest['running_services']
    if not services:
        raise RuntimeError('De bronstack was gestopt; kies handmatig welke services je wilt activeren.')
    run(command + ['up', '-d', '--pull', 'never', '--no-build'] + services, directory)
    wait_running(directory, command, services)
    print(json.dumps({'activated': str(directory), 'project': manifest['project'], 'services': services}))


def validate_restored_mounts(directory, command):
    config = json.loads(run(command + ['config', '--format', 'json'], directory, True))
    for service in config['services'].values():
        for mount in service.get('volumes', []):
            if mount['type'] == 'bind':
                Path(mount['source']).resolve(strict=True).relative_to(directory.resolve())
            elif mount['type'] == 'volume':
                raise RuntimeError('Herstelde Compose verwijst naar een Docker-volume buiten de back-up.')


def restore(archive, directory, expected):
    if digest(archive) != expected.lower():
        raise RuntimeError('SHA256 van de back-up klopt niet.')
    if directory.exists():
        raise RuntimeError('Herstelmap bestaat al. Kies een nieuwe lege locatie; niets wordt overschreven.')
    with tempfile.TemporaryDirectory(prefix='rustdesk-restore-', dir='/var/tmp') as work:
        work = Path(work)
        extract_checked(archive, work, {'manifest.json', 'stack.tar', 'images.tar', 'rustdesk-dr.py'})
        manifest = load_manifest(work / 'manifest.json')
        for name, key in [('stack.tar', 'stack_sha256'), ('images.tar', 'images_sha256')]:
            if digest(work / name) != manifest[key]:
                raise RuntimeError('Intern bestand beschadigd: ' + name)
        directory.mkdir(parents=True, mode=0o700)
        extract_checked(work / 'stack.tar', directory)
        directory.chmod(0o700)
        if digest(directory / 'data/id_ed25519.pub') != manifest['public_key_sha256']:
            raise RuntimeError('Publieke serverkey verschilt van de back-up.')
        if not (directory / 'data/id_ed25519').is_file():
            raise RuntimeError('Private serverkey ontbreekt.')
        (directory / '.rustdesk-dr-manifest.json').write_text(json.dumps(manifest, indent=2))
        text = 'services:\n'
        for service, image in manifest['images'].items():
            text += f'  {service}:\n    image: "{image}"\n    pull_policy: never\n'
        override = directory / '.rustdesk-dr-images.yml'
        override.write_text(text)
        shutil.copyfile(__file__, directory / 'rustdesk-dr.py')
        (directory / '.rustdesk-dr-manifest.json').chmod(0o600)
        run(['docker', 'image', 'load', '-i', str(work / 'images.tar')])
        command = compose(directory, manifest['compose_files'], manifest['project'], override)
        validate_restored_mounts(directory, command)
        # Staging never creates containers: reboot cannot auto-start a second primary.
        print(json.dumps({'staged': str(directory), 'project': manifest['project'], 'containers_started': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    item = sub.add_parser('backup')
    item.add_argument('--stack-dir', required=True, type=Path)
    item = sub.add_parser('restore')
    item.add_argument('--archive', required=True, type=Path)
    item.add_argument('--sha256', required=True)
    item.add_argument('--target-dir', required=True, type=Path)
    item = sub.add_parser('activate')
    item.add_argument('--stack-dir', required=True, type=Path)
    args = parser.parse_args()
    if os.name != 'posix' or os.geteuid() != 0:
        raise RuntimeError('Voer dit op de Linux-server uit als root of via sudo -n.')
    for program in ['docker', 'tar']:
        if not shutil.which(program):
            raise RuntimeError('Ontbrekend programma: ' + program)
    os.umask(0o077)
    if 'GNU tar' not in run(['tar', '--version'], capture=True):
        raise RuntimeError('GNU tar is vereist voor Linux-ACLs en xattrs.')
    directory = (args.target_dir if args.operation == 'restore' else args.stack_dir).resolve()
    if not directory.is_absolute() or str(directory) == '/':
        raise RuntimeError('Gebruik een expliciete stackmap, nooit /.')
    def interrupted(signum, frame):
        # Only handle the first signal; allow the finally restart to finish.
        for value in [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]:
            signal.signal(value, signal.SIG_IGN)
        raise RuntimeError('Onderbroken; broncontainers worden waar mogelijk herstart.')
    for value in [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]:
        signal.signal(value, interrupted)
    with stack_lock(directory):
        if args.operation == 'backup':
            backup(directory)
        elif args.operation == 'restore':
            restore(args.archive.resolve(strict=True), directory, args.sha256)
        else:
            activate(directory.resolve(strict=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('FOUT: ' + str(error), file=sys.stderr)
        sys.exit(1)
