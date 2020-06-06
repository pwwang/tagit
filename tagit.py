"""
When the tagging is invoked:
1. commit message is a pure semantic version
2. version in pyproject.toml is newer than the latest tag
"""
__version__ = "0.0.7"
import sys
import re
from pathlib import Path
import toml
from prompt_toolkit import prompt
from cmdy import git, poetry, CmdyReturnCodeError, bash
from pyparam import commands
from simpleconf import Config

commands.completion = 'Tab-completions for the program.'
commands.completion.s = 'auto'
commands.completion.s.desc = ('The shell. Detect from `os.environ["SHELL"]`'
                              ' if `auto`.')
commands.completion.shell = commands.completion.s
commands.completion.a = False
commands.completion.a.desc = 'Automatically write the completion scripts'
commands.completion.auto = commands.completion.a

commands.generate = 'Generate a rcfile.'
commands.generate.i = True
commands.generate.i.desc = 'Using interactive mode.'
commands.generate.interactive = commands.generate.i
commands.generate.rcfile = './.tagitrc'
commands.generate.c = {}
commands.generate.c.desc = 'The configurations for the rcfile'
commands.generate.config = commands.generate.c

commands.generate._helpx = lambda helps: helps.select('optional').before(
    '-h',
    [('-c.changelog', '[AUTO]',
      'Path to the changelog file to check if new version is mentioned.'),
     ('-c.versource', '[AUTO]',
      ['Path of the source file to check "__version__" of the module.',
       'You could also specify the module name.',
       'Then <module>.py or <module>/__init__.py will be used.']),
     ('-c.checksource', '[BOOL]',
      'Should we check the version in source file or just update?'),
     ('-c.publish', '[BOOL]',
      'Whether publish the tag using poetry.'),
     ('-c.vertoml', '[BOOL]',
      'Path of toml with version defined. Typically ./pyproject.toml'),
     ('-c.checktoml', '[BOOL]',
      'Should we check the version in toml file or just update?'),
     ('-c.extra', '<STR>',
      'Extra commands to run before commit and push the tag.'),
     ('-c.i, -c.increment', '<STR>',
      'Which part of the version to be incremented.\nDefault: patch')]
)

commands.tag = 'Do the tagging.'
commands.tag._hbald = False
commands.tag.rcfile = './.tagitrc'
commands.tag.rcfile.desc = 'Use the configurations from the rcfile'
commands.tag._.type = str
commands.tag._.desc = 'The version to tag.'
commands.tag.c = {}
commands.tag.c.desc = 'Overwrite the configurations from the rcfile'
commands.tag.c.callback = lambda param: param.value.update(dict(
    i=param.value.get('i', param.value.get('increment', 'patch')),
    increment=param.value.get('i', param.value.get('increment', 'patch')),
))
commands.tag.config = commands.tag.c
commands.tag._helpx = commands.generate._helpx

commands.status = 'Show current status of the project.'
commands.status._hbald = False

commands.version = 'Show current version of tagit'
commands.version._hbald = False


class Tag:
    """Class of tag"""
    def __init__(self, atag):
        if isinstance(atag, str):
            if atag.count('.') != 2:
                raise ValueError('Invalid semantic tag: %s' % atag)
            self.major, self.minor, self.patch = atag.split('.')
            if (not self.major.isdigit()
                    or not self.minor.isdigit()
                    or not self.patch.isdigit()):
                raise ValueError('Invalid semantic tag: %s' % atag)
            self.major, self.minor, self.patch = \
                int(self.major), int(self.minor), int(self.patch)
        elif isinstance(atag, Tag):
            self.major, self.minor, self.patch = \
                atag.major, atag.minor, atag.patch
        elif isinstance(atag, (tuple, list)):
            if len(atag) != 3:
                raise ValueError('Invalid semantic tag: %s' % atag)
            self.major, self.minor, self.patch = atag
            try:
                self.major, self.minor, self.patch = \
                    int(self.major), int(self.minor), int(self.patch)
            except (ValueError, TypeError):
                raise ValueError('Invalid semantic tag: %s' % atag)

    def __str__(self):
        return '%s.%s.%s' % self.tuple()

    def __repr__(self):
        return 'Tag(%r)' % str(self)

    def tuple(self):
        """Return a tuple of the version"""
        return self.major, self.minor, self.patch

    def increment(self, part):
        """Increment the version"""
        if part == 'patch':
            return Tag((self.major, self.minor, self.patch + 1))
        if part == 'minor':
            return Tag((self.major, self.minor + 1, 0))
        if part == 'major':
            return Tag((self.major + 1, 0, 0))

    def __eq__(self, other):
        return self.tuple() == (other.tuple()
                                if isinstance(other, Tag)
                                else other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __gt__(self, other):
        return self.tuple() > (other.tuple()
                               if isinstance(other, Tag)
                               else other)

    def __lt__(self, other):
        return self.tuple() < (other.tuple()
                               if isinstance(other, Tag)
                               else other)


def _color(msg, color='\x1b[31m'):
    return color + msg + '\x1b[0m'


def _log(msg, color='\x1b[32m'):
    print('%s' % _color('[TAGIT] ' + msg, color=color))


class QuietException(Exception):
    """Just print the exception message"""
    def __init__(self, msg):
        super(QuietException, self).__init__(_color(msg))


class TomlVersionBehindException(QuietException):
    """When toml version is behind"""


class NoVersionInChangeLogException(QuietException):
    """When no version mentioned in change log"""


class UncleanRepoException(QuietException):
    """When the repository is not clean"""


class NoChangesSinceLastTagException(QuietException):
    """When no changes since last tag"""


def quiet_hook(kind, message, traceback):
    """Don't print stacktrace for exceptions"""
    if QuietException in kind.__bases__:
        # Only print Error Type and Message
        print('{0}: {1}'.format(kind.__name__, message))
    else:
        # Print Error Type, Message and Traceback
        sys.__excepthook__(kind, message, traceback)


sys.excepthook = quiet_hook


def _get_version_from_gittag():
    try:
        lastag = git.describe(tags=True, abbrev=0, _sep='=').strip()
    except CmdyReturnCodeError:
        lastag = None
    if not lastag:
        return None
    return Tag(lastag)


def _get_version_from_toml(vertoml):
    tomlfile = Path(vertoml)
    if not tomlfile.exists():
        return None
    parsed = toml.load(tomlfile)
    if not parsed.get('tool', {}).get('poetry', {}).get('version'):
        return None
    return Tag(parsed['tool']['poetry']['version'])


def _update_version_to_toml(ver, vertoml):
    tomlfile = Path(vertoml)
    if not tomlfile.exists():
        return
    tomlfile.with_suffix('.toml.bak').write_text(tomlfile.read_text())
    oldver = _get_version_from_toml(vertoml)
    updated = []
    with open(vertoml, 'rt') as ftml:
        for line in ftml:
            if (line.rstrip('\r\n')
                    .replace(' ', '')
                    .replace('\'', '"') == 'version="%s"' % oldver):
                updated.append('version = "%s"' % ver)
            else:
                updated.append(line.rstrip('\r\n'))
    with open(vertoml, 'wt') as ftml:
        ftml.write("\n".join(updated) + "\n")

def _get_version_from_source(versource):
    with open(versource) as fsrc:
        for line in fsrc:
            if line.startswith('__version__'):
                return line[13:].strip('= "\'\n')
    return None


def _update_version_to_source(versource,
                              version): # pylint: disable=redefined-outer-name
    srcfile = Path(versource)
    lines = srcfile.read_text().splitlines()
    srcfile.with_suffix('.py.bak').write_text('\n'.join(lines))
    for i, line in enumerate(lines):
        if line.startswith('__version__'):
            lines[i] = '__version__ = "%s"' % version
    if lines[-1]:
        lines.append('')
    srcfile.write_text('\n'.join(lines))


def _version_in_changelog(ver, changelog):
    if not changelog:
        return
    with open(changelog) as fcl:
        if not re.search(r'[^\d]%s[^\d]' % ver, fcl.read()):
            raise NoVersionInChangeLogException(
                'Verion %r not mentioned in %r' % (ver, changelog))


def _getsrcfile(module):
    srcfile = Path(module)
    # assuming module name
    if not srcfile.is_file() and not module.endswith('.py'):
        srcfile = Path(__import__(module).__file__)
        srcfile = srcfile.with_suffix('.py')
    return srcfile


def _checkver(version,  # pylint: disable=redefined-outer-name
              changelog,
              versource,
              vertoml,
              checksource,
              checktoml):
    goodtogo = True
    if changelog:
        try:
            _version_in_changelog(version, changelog)
        except NoVersionInChangeLogException:
            goodtogo = False
            _log('  This version is not mentioned in CHANGELOG!',
                 color='\x1b[33m')

    if versource and checksource:
        versource = _getsrcfile(versource)
        srcver = _get_version_from_source(versource)
        if str(version) != srcver:
            goodtogo = False
            _log('  This version is not updated in versource file.',
                 color='\x1b[33m')

    if vertoml and checktoml:
        tomlver = _get_version_from_toml(vertoml)
        if str(tomlver) != str(version):
            goodtogo = False
            _log('  Version is not updated in pyproject.toml (%s).' %
                 tomlver, color='\x1b[33m')
    return goodtogo


def status(options, specver=None, ret=False):
    """Get the status of the project"""
    tagver = _get_version_from_gittag()

    exception = None
    gitstatus = git.status(s=True).str()
    cherry = git.cherry(v=True).str()
    if gitstatus or cherry:
        exception = UncleanRepoException(
            'You have changes uncommitted or unpushed.\n\n' +
            git.status().str()
        )
    lastmsg = git.log('-1', pretty="format:%s", _sep='=').strip()

    if lastmsg == str(tagver):
        raise NoChangesSinceLastTagException('No changes since last tag.')

    tagver = tagver or Tag((0, 0, 0))

    rcoptions = Config()
    rcoptions._load('./.tagitrc')
    rcoptions._use('TAGIT')
    rcoptions.update(options)
    changelog = rcoptions.get('changelog', '')
    increment = rcoptions.get('increment', 'patch')
    versource = rcoptions.get('versource', '')
    vertoml = rcoptions.get('vertoml', '')
    checksource = rcoptions.get('checksource', True)
    checktoml = rcoptions.get('checktoml', True)

    _log('Current version: %s' % str(tagver))

    if ret:
        nextver = tagver.increment(increment)
        _log('New version received: %r' % (specver or nextver))
        if exception:
            raise exception
        return _checkver(specver or nextver, changelog, versource,
                         vertoml, checksource, checktoml)

    nextver = tagver.increment('patch')
    _log('Next auto patch version is: %s' % nextver)

    if _checkver(nextver, changelog, versource, vertoml,
                 checksource, checktoml):
        _log('  You are good to go with this version.')
        shortcmd = '`tagit tag`, ' if increment == 'patch' else ''
        _log('  Run %s`tagit tag -c.i patch` or `tagit tag %s`' %
             (shortcmd, nextver))

    nextver = tagver.increment('minor')
    _log('Next auto minor version is: %s' % nextver)

    if _checkver(nextver, changelog, versource, vertoml,
                 checksource, checktoml):
        _log('  You are good to go with this version.')
        shortcmd = '`tagit tag`, ' if increment == 'minor' else ''
        _log('  Run %s`tagit tag -c.i minor` or `tagit tag %s`' %
             (shortcmd, nextver))

    nextver = tagver.increment('major')
    _log('Next auto major version is: %s' % nextver)

    if _checkver(nextver, changelog, versource, vertoml,
                 checksource, checktoml):
        _log('  You are good to go with this version.')
        shortcmd = '`tagit tag`, ' if increment == 'major' else ''
        _log('  Run %s`tagit tag -c.i major` or `tagit tag %s`' %
             (shortcmd, nextver))

    if exception:
        raise exception


def version(options): # pylint: disable=unused-argument
    """Get current local version"""
    default_options = Config()
    default_options._load('./.tagitrc')
    default_options._use('TAGIT')
    vertoml = options.get('vertoml', '')
    ver = _get_version_from_toml(vertoml)
    _log('Current version: %s' % ver)


def generate_interactive(options):
    """Generate rcfile interactively"""
    changelog = prompt('Check new mentioned in changelog?: [] ', default='')
    publish = prompt('Use poetry to publish the tag? [T|F] ', default='False')
    versource = prompt(
        'Check source file for the new version? [] ', default='')
    vertoml = prompt(
        'Check `pyproject.toml` for the new version? [./pyproject.toml] ',
        default='./pyproject.toml')
    checksource = prompt(
        'Check version in source file? [T|F] ', default='True')
    checktoml = prompt('Check version in toml file? [T|F] ', default='True')
    increment = prompt(
        'Default part of version to increment? [major|minor|patch] ',
        default='patch'
    )
    extra = prompt(
        'Extra commands to run before commit and push the tag [] ', default='')
    generate_rcfile({
        'changelog': changelog,
        'publish': publish in ('T', 'True'),
        'checksource': checksource in ('T', 'True'),
        'checktoml': checktoml in ('T', 'True'),
        'versource': versource,
        'vertoml': vertoml,
        'increment': increment,
        'extra': extra,
    }, options['rcfile'])


def generate_rcfile(options, rcfile):
    """Generate rcfile"""
    vertoml = options.get('vertoml', '')
    publish = options.get('publish', False)
    checksource = options.get('checksource', True)
    checktoml = options.get('checktoml', True)
    changelog = options.get('changelog', '')
    versource = options.get('versource', '')
    increment = options.get('increment', 'patch')
    extra = options.get('extra', '')
    with open(rcfile, 'w') as frc:
        frc.write('[TAGIT]\n')
        frc.write('; The change log file to check when version is mentioned.\n')
        frc.write('changelog = %s\n\n' % changelog)
        frc.write('; Whether publish the package after '
                  'the tag pushed to server.\n')
        frc.write('publish = py:%r\n\n' % publish)
        frc.write('; Whether check the version (__version__) in source file.\n')
        frc.write('checksource = py:%r\n\n' % checksource)
        frc.write('; Whether check the version in pyproject.toml file.\n')
        frc.write('checktoml = py:%r\n\n' % checktoml)
        frc.write('; The source file or the package name.\n')
        frc.write('versource = %s\n\n' % versource)
        frc.write('; The toml file, typically pyproject.toml.\n')
        frc.write('vertoml = %s\n\n' % vertoml)
        frc.write('; Which part of the version to '
                  'increment for auto-tagging.\n')
        frc.write('increment = %s\n\n' % increment)
        frc.write('; Extra commands to run before tag committed and pushed.\n')
        frc.write('extra = py:%r\n\n' % extra)
    _log('rcfile saved to %r' % rcfile)


def generate(options):
    """Generate rcfile interactively or directly"""
    interactive = options['i']
    if interactive:
        generate_interactive(options)
    else:
        generate_rcfile(options['c'], options['rcfile'])


def completion(options):
    """Completions for the command line tool"""
    ret = commands._complete(options['shell'], options['auto'])
    if not options['auto']:
        print(ret)


def tag(options):
    """Tag the version"""
    default_options = Config()
    default_options._load('./.tagitrc')
    default_options._use('TAGIT')
    default_options.update(options['c'])
    publish = default_options.get('publish', False)
    #changelog = default_options.get('changelog', '')
    increment = default_options.get('increment', 'patch')
    versource = default_options.get('versource', '')
    vertoml = default_options.get('vertoml', '')
    #checksource = default_options.get('checksource', True)
    #checktoml = default_options.get('checktoml', True)
    extra = default_options.get('extra', '')

    specver = options['_'] or None
    ret = status(default_options, specver, True)

    if not ret:
        return

    tagver = _get_version_from_gittag() or Tag((0, 0, 0))
    specver = specver or tagver.increment(increment)

    if versource:
        _log('Updating version in source file ...')
        _update_version_to_source(_getsrcfile(versource), specver)

    if vertoml:
        _log('Updating version in pyproject.toml ...')
        _update_version_to_toml(specver, vertoml)

    if extra:
        cmd = bash(c=extra).fg
        if cmd.rc != 0:
            raise RuntimeError('Failed to run %r' % extra)
    _log('Committing the change ...')
    try:
        git.commit({'allow-empty': True}, a=True, m=str(specver)).fg
    except CmdyReturnCodeError:
        # pre-commit fails, do it again
        _log('Pre-commit failed, try again ...')
        git.add('.')
        git.commit({'allow-empty': True}, a=True, m=str(specver)).fg

    _log('Pushing the commit to remote ...')
    git.push().fg

    _log('Adding tag %r ...' % specver)
    git.tag(str(specver)).fg
    _log('Pushing the tag to remote ...')
    git.push(tag=True).fg

    if publish:
        _log('Building the release ...')
        poetry.build().fg
        _log('Publishing the release ...')
        poetry.publish().fg
    _log('Done!')


def main():
    """Main function"""
    command, options, _ = commands._parse()
    globals()[command](options)


if __name__ == '__main__':
    main()
