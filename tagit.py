"""
When the tagging is invoked:
1. commit message is a pure semantic version
2. version in pyproject.toml is newer than the latest tag
"""
import sys
import re
from pathlib import Path
import toml
from prompt_toolkit import prompt
from cmdy import git, poetry, CmdyReturnCodeException
from pyparam import commands
from simpleconf import Config

commands.completion        = 'Tab-completions for the program.'
commands.completion.s      = 'auto'
commands.completion.s.desc = 'The shell. Detect from `os.environ["SHELL"]` if `auto`.'
commands.completion.shell  = commands.completion.s
commands.completion.a      = False
commands.completion.a.desc = 'Automatically write the completion scripts'
commands.completion.auto   = commands.completion.a

# commands.install = [
# 	'Install a git-receive hook.',
# 	'So tagging will be triggered after `git push`']
# commands.install._hbald   = False
# commands.install.dir      = './'
# commands.install.dir.desc = [
# 	'The git project directory to install.',
# 	'Will install to `<dir>/.git/hooks`']

commands.generate             = 'Generate a rcfile.'
commands.generate.i           = True
commands.generate.i.desc      = 'Using interactive mode.'
commands.generate.interactive = commands.generate.i
commands.generate.rcfile      = './.tagitrc'
commands.generate.c           = {}
commands.generate.c.desc      = 'The configurations for the rcfile'
commands.generate.config      = commands.generate.c

commands.generate._helpx = lambda helps: helps.select('optional').before('-h',
	[('-c.changelog', '[AUTO]',
	  'Path to the changelog file to check if new version is mentioned.'),
	 ('-c.source', '[AUTO]',
	  ['Path of the source file to check "__version__" of the module.',
	   'You could also specify the module name.']),
	 ('-c.publish', '[BOOL]',
	  'Whether publish the tag using poetry.'),
	 ('-c.checktoml', '[BOOL]',
	  'Check `pyproject.toml` has the new version.'),
	 ('-c.i, -c.increment', '<STR>',
	  'Which part of the version to be incremented.\nDefault: patch')])

commands.tag             = 'Do the tagging.'
commands.tag._hbald      = False
commands.tag.rcfile      = './.tagitrc'
commands.tag.rcfile.desc = 'Use the configurations from the rcfile'
commands.tag._.type      = str
commands.tag._.desc      = 'The version to tag.'
commands.tag.c           = {}
commands.tag.c.desc      = 'Overwrite the configurations from the rcfile'
commands.tag.c.callback  = lambda param: param.value.update(dict(
	i = param.value.get('i', param.value.get('increment', 'patch')),
	increment = param.value.get('i', param.value.get('increment', 'patch')),
))
commands.tag.config      = commands.tag.c
commands.tag._helpx      = lambda helps: helps.select('optional').before('-h',
	[('-c.changelog', '[AUTO]',
	  'Path to the changelog file to check if new version is mentioned.'),
	 ('-c.source', '[AUTO]',
	  ['Path of the source file to check "__version__" of the module.',
	   'You could also specify the module name.']),
	 ('-c.publish', '[BOOL]',
	  'Whether publish the tag using poetry.'),
	 ('-c.checktoml', '[BOOL]',
	  'Check `pyproject.toml` has the new version.'),
	 ('-c.i, -c.increment', '<STR>',
	  'Which part of the version to be incremented.\nDefault: patch')])

commands.status = 'Show current status of the project.'
commands.status._hbald = False

commands.version        = 'Show current version of tagit'
commands.version._hbald = False

class Tag:
	def __init__(self, atag):
		# TODO: check tag
		self.major, self.minor, self.patch = atag if isinstance(atag, tuple) \
			else (atag.major, atag.minor, atag.patch) if isinstance(atag, Tag) \
			else tuple(int(x) for x in atag.split('.'))
	def __str__(self):
		return '%s.%s.%s' % self.tuple()
	def __repr__(self):
		return 'Tag(%r)' % str(self)
	def tuple(self):
		return self.major, self.minor, self.patch
	def increment(self, part):
		if part == 'patch':
			return Tag((self.major, self.minor, self.patch + 1))
		if part == 'minor':
			return Tag((self.major, self.minor + 1, 0))
		if part == 'major':
			return Tag((self.major + 1, 0, 0))
	def __eq__(self, other):
		return self.tuple() == (other.tuple() if isinstance(other, Tag) else other)
	def __ne__(self, other):
		return not self.__eq__(other)
	def __gt__(self, other):
		return self.tuple() > (other.tuple() if isinstance(other, Tag) else other)
	def __lt__(self, other):
		return self.tuple() < (other.tuple() if isinstance(other, Tag) else other)

def _color(msg, color = '\x1b[31m'):
	return color + msg + '\x1b[0m'

def _log(msg, color = '\x1b[32m'):
	print('%s' % _color('[TAGIT] ' + msg, color = color))

class QuietException(Exception):
	def __init__(self, msg):
		super(QuietException, self).__init__(_color(msg))

class TomlVersionBehindException(QuietException):
	pass

class NoVersionInChangeLogException(QuietException):
	pass

class UncleanRepoException(QuietException):
	pass

class NoChangesSinceLastTagException(QuietException):
	pass

def quiet_hook(kind, message, traceback):
	if QuietException in kind.__bases__:
		print('{0}: {1}'.format(kind.__name__, message))  # Only print Error Type and Message
	else:
		sys.__excepthook__(kind, message, traceback)  # Print Error Type, Message and Traceback

sys.excepthook = quiet_hook

def _get_version_from_gittag():
	try:
		lastag = git.describe(tags = True, abbrev = 0, _sep = '=').strip()
	except CmdyReturnCodeException:
		lastag = None
	if not lastag:
		return None
	return Tag(lastag)

def _get_version_from_toml():
	tomlfile = Path('.') / 'pyproject.toml'
	if not tomlfile.exists():
		return None
	parsed = toml.load(tomlfile)
	if not parsed.get('tool', {}).get('poetry', {}).get('version'):
		return None
	return Tag(parsed['tool']['poetry']['version'])

def _update_version_to_toml(ver):
	tomlfile = Path('.') / 'pyproject.toml'
	if not tomlfile.exists():
		return
	parsed = toml.load(tomlfile)
	parsed['tool']['poetry']['version'] = str(ver)
	with open(tomlfile, 'w') as ftoml:
		toml.dump(parsed, ftoml)

def _get_version_from_source(source):
	with open(source) as fsrc:
		for line in fsrc:
			if line.startswith('__version__'):
				return line[13:].strip('= "\'\n')
	return None

def _update_version_to_source(source, version):
	srcfile = Path(source)
	lines   = srcfile.read_text().splitlines()
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
	if not srcfile.is_file() and not module.endswith('.py'): # assuming module name
		srcfile = Path(__import__(module).__file__)
		srcfile = srcfile.with_suffix('.py')
	return srcfile

def _checkver(version, changelog, checksrc, checktoml = False):
	goodtogo = True
	if changelog:
		try:
			_version_in_changelog(version, changelog)
		except NoVersionInChangeLogException:
			goodtogo = False
			_log('  This version is not mentioned in CHANGELOG!', color = '\x1b[33m')

	if checksrc:
		source = _getsrcfile(checksrc)
		srcver = _get_version_from_source(source)
		if str(version) != srcver:
			goodtogo = False
			_log('  This version is not updated in source file.', color = '\x1b[33m')

	if checktoml:
		if _get_version_from_toml() != version:
			goodtogo = False
			_log('  Version is not updated in pyproject.toml.', color = '\x1b[33m')
	return goodtogo

def status(options, specver = None, ret = False):
	lastmsg = git.log('-1', pretty = "format:%s", _sep = '=').strip()
	tagver = _get_version_from_gittag()

	if lastmsg == str(tagver):
		raise NoChangesSinceLastTagException('No changes since last tag.')

	gitstatus = git.status(s = True).str()
	cherry = git.cherry(v = True).str()
	if gitstatus or cherry:
		raise UncleanRepoException(
			'You have changes uncommitted or unpushed.\n\n' + git.status().str())
	lastmsg = git.log('-1', pretty = "format:%s", _sep = '=').strip()
	tagver = _get_version_from_gittag()

	if lastmsg == str(tagver):
		raise NoChangesSinceLastTagException('No changes since last tag.')

	tomlver = _get_version_from_toml()
	tomlver = tomlver or (0, 0, 0)
	tagver  = tagver or (0, 0, 0)
	maxver  = max(tomlver, tagver)

	options = Config()
	options._load('./.tagitrc')
	options._use('TAGIT')
	changelog = options.get('changelog')
	increment = options.get('increment', 'patch')
	checksrc  = options.get('source')

	_log('Current version: %s' % tagver)

	if ret:
		nextver = maxver.increment(increment)
		_log('New version received: %r' % (specver or nextver))
		return _checkver(specver or nextver, changelog, checksrc, bool(specver))

	nextver = maxver.increment('patch')
	_log('Next auto patch version is: %s' % nextver)

	if _checkver(nextver, changelog, checksrc):
		_log('  You are good to go with this version.')
		shortcmd = '`tagit tag`, ' if increment == 'patch' else ''
		_log('  Run %s`tagit tag -c.i patch` or `tagit tag %s`' % (shortcmd, nextver))

	nextver = maxver.increment('minor')
	_log('Next auto minor version is: %s' % nextver)

	if _checkver(nextver, changelog, checksrc):
		_log('  You are good to go with this version.')
		shortcmd = '`tagit tag`, ' if increment == 'patch' else ''
		_log('  Run %s`tagit tag -c.i patch` or `tagit tag %s`' % (shortcmd, nextver))

	nextver = maxver.increment('major')
	_log('Next auto major version is: %s' % nextver)

	if _checkver(nextver, changelog, checksrc):
		_log('  You are good to go with this version.')
		shortcmd = '`tagit tag`, ' if increment == 'patch' else ''
		_log('  Run %s`tagit tag -c.i patch` or `tagit tag %s`' % (shortcmd, nextver))

def version(options):
	ver = _get_version_from_toml()
	_log('Current version: %s' % ver)

def generate_interactive(options):
	changelog = prompt('Check new mentioned in changelog?: []', default='')
	publish   = prompt('Use poetry to publish the tag? [T|F]: ', default='True')
	checksrc  = prompt('Check source file for the new version? [T|F]: ', default='False')
	checktoml = prompt('Check `pyproject.toml` for the new version? [T|F]: ', default='True')
	increment = prompt(
		'Default part of version to increment? [major|minor|patch]: ', default='patch')
	generate_rcfile({
		'changelog': changelog,
		'publish'  : publish in ('T', 'True'),
		'source'   : True if checksrc is True else checksrc,
		'checktoml': checktoml in ('T', 'True'),
		'increment': increment,
	}, options['rcfile'])

def generate_rcfile(options, rcfile):
	checktoml = options.get('checktoml', True)
	publish   = options.get('publish', True)
	changelog = options.get('changelog', False)
	source    = options.get('source', False)
	increment = options.get('increment', 'patch')
	with open(rcfile, 'w') as frc:
		frc.write('[TAGIT]\n')
		frc.write('changelog = py:%r\n' % changelog)
		frc.write('publish = py:%r\n' % publish)
		frc.write('source = py:%r\n' % source)
		frc.write('checktoml = py:%r\n' % checktoml)
		frc.write('increment = %s\n' % increment)
	_log('rcfile saved to %r' % rcfile)

def generate(options):
	interactive = options['i']
	if interactive:
		generate_interactive(options)
	else:
		generate_rcfile(options['c'], options['rcfile'])

def completion(options):
	ret = commands._complete(options['shell'], options['auto'])
	if not options['auto']:
		print(ret)

def tag(options):
	default_options = Config()
	default_options._load('./.tagitrc')
	default_options._use('TAGIT')
	default_options.update(options['c'])
	publish   = default_options.get('publish', True)
	changelog = default_options.get('changelog')
	increment = default_options.get('increment', 'patch')
	checksrc  = default_options.get('source', False)

	specver = options['_'] or None
	ret = status(options, specver, True)

	if not ret:
		return

	tomlver = _get_version_from_toml() or (0, 0, 0)
	tagver  = _get_version_from_gittag() or (0, 0, 0)
	specver = specver or max(tomlver, tagver).increment(increment)

	_version_in_changelog(specver, changelog)
	_log('Updating version in pyproject.toml ...')
	if checksrc:
		_update_version_to_source(_getsrcfile(checksrc), specver)
	_update_version_to_toml(specver)
	_log('Committing the change ...')
	git.commit(a = True, m = str(specver), _fg = True)
	_log('Pushing the commit to remote ...')
	git.push(_fg = True)

	_log('Adding tag %r ...' % specver)
	git.tag(str(specver), _fg = True)
	_log('Pushing the tag to remote ...')
	git.push(tag = True, _fg = True)

	if publish:
		_log('Building the release ...')
		poetry.build(_fg = True)
		_log('Publishing the release ...')
		poetry.publish(_fg = True)
	_log('Done!')

def main():
	command, options, _ = commands._parse()
	globals()[command](options)

if __name__ == '__main__':
	main()
