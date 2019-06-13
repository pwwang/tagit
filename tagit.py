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
	 ('-c.publish', '[BOOL]',
	  'Whether publish the tag using poetry.'),
	 ('-c.checktoml', '[BOOL]',
	  'Check `pyproject.toml` has the new version.'),
	 ('-c.i, -c.increment', '<STR>',
	  'Which part of the version to be incremented.\nDefault: patch')])

commands.test = 'Test if anything new added and I can tag next version.'
commands.test._hbald = False

commands.version        = 'Show current version of tagit'
commands.version._hbald = False

class Tag:
	def __init__(self, tag):
		# TODO: check tag
		self.major, self.minor, self.patch = tag if isinstance(tag, tuple) \
			else (tag.major, tag.minor, tag.patch) if isinstance(tag, Tag) \
			else tuple(int(x) for x in tag.split('.'))
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

def _log(msg):
	print('%s\n' % _color('[TAGIT] ' + msg, color = '\x1b[32m'))

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

def _version_in_changelog(ver, changelog):
	if not changelog:
		return
	with open(changelog) as fcl:
		if not re.search(r'[^\d]%s[^\d]' % ver, fcl.read()):
			raise NoVersionInChangeLogException(
				'Verion %r not mentioned in %r' % (ver, changelog))

def test(options):
	status = git.status(s = True).str()
	cherry = git.cherry(v = True).str()
	if status or cherry:
		raise UncleanRepoException(
			'You have changes uncommitted or unpushed.\n\n' + git.status().str())
	lastmsg = git.log('-1', pretty = "format:%s", _sep = '=').strip()
	ver2 = _get_version_from_gittag()

	if lastmsg == str(ver2):
		raise NoChangesSinceLastTagException('No changes since last tag.')

	ver1 = _get_version_from_toml()
	ver1 = ver1 or (0, 0, 0)
	ver2 = ver2 or (0, 0, 0)
	ver3 = max(ver1, ver2)
	_log('You are good to go.')
	_log('Next auto patch version is: %s' % vers.increment('patch'))
	_log('Next auto minor version is: %s' % vers.increment('minor'))
	_log('Next auto major version is: %s' % vers.increment('major'))

def version(options):
	ver = _get_version_from_toml()
	_log('Current version: %s' % ver)

def generate_interactive(options):
	changelog = prompt('Check new mentioned in changelog?: []', default='')
	publish   = prompt('Use poetry to publish the tag? [T|F]: ', default='True')
	checktoml = prompt('Check `pyproject.toml` has the new version? [T|F]: ', default='True')
	increment = prompt(
		'Default part of version to increment? [major|minor|patch]: ', default='patch')
	generate_rcfile({'c': {
		'changelog': changelog,
		'publish'  : publish in ('T', 'True'),
		'checktoml': checktoml in ('T', 'True'),
		'increment': increment,
	}}, options['rcfile'])

def generate_rcfile(options, rcfile):
	checktoml = options.get('checktoml', True)
	publish   = options.get('publish', True)
	changelog = options.get('changelog', False)
	increment = options.get('increment', 'patch')
	with open(rcfile, 'w') as frc:
		frc.write('[TAGIT]\n')
		frc.write('changelog = py:%r\n' % changelog)
		frc.write('publish = py:%r\n' % publish)
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
	lastmsg = git.log('-1', pretty = "format:%s", _sep = '=').strip()
	ver2 = _get_version_from_gittag()

	if lastmsg == str(ver2):
		raise NoChangesSinceLastTagException('No changes since last tag.')

	ver1 = _get_version_from_toml()
	ver3 = options['_'] # force tag

	default_options = Config()
	default_options._load('./.tagitrc')
	default_options._use('TAGIT')
	default_options.update(options['c'])
	checktoml = default_options.get('checktoml', True)
	publish   = default_options.get('publish', True)
	changelog = default_options.get('changelog')
	increment = default_options.get('increment', 'patch')

	status = git.status(s = True).str()
	cherry = git.cherry(v = True).str()
	if status or cherry:
		raise UncleanRepoException(
			'You have changes uncommitted or unpushed.\n\n' + git.status().str())

	if ver3:
		_log('New version received: %r' % ver3)
		if checktoml and str(ver1) != ver3:
			raise TomlVersionBehindException(
				'Expect %r in pyproject.toml, but got %r' % (ver3, ver1))
		_version_in_changelog(ver3, changelog)
	else:
		ver1 = ver1 or (0, 0, 0)
		ver2 = ver2 or (0, 0, 0)
		ver3 = max(ver1, ver2).increment(increment)
		_log('New version received: %r' % ver3)
		_version_in_changelog(ver3, changelog)
		_log('Updating version in pyproject.toml ...')
		_update_version_to_toml(ver3)
		_log('Committing the change ...')
		git.commit(a = True, m = str(ver3), _fg = True)
		_log('Pushing the commit to remote ...')
		git.push(_fg = True)

	_log('Adding tag %r ...' % ver3)
	git.tag(str(ver3), _fg = True)
	_log('Pushing the tag to remote ...')
	git.push(tag = True, _fg = True)

	if publish:
		_log('Publishing the release ...')
		poetry.publish(build = True, _fg = True)
	_log('Done!')

def main():
	command, options, _ = commands._parse()
	globals()[command](options)

if __name__ == '__main__':
	main()
