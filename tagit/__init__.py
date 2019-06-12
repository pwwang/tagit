"""
When the tagging is invoked:
1. commit message is a pure semantic version
2. version in pyproject.toml is newer than the latest tag
"""
__version__ = '0.0.1'

import re
from pathlib import Path
import toml
from cmdy import git
from pyparam import commands
from simpleconf import Config
from prompt_toolkit import prompt

commands.completion        = 'Tab-completions for the program.'
commands.completion.s      = 'auto'
commands.completion.s.desc = 'The shell. Detect from `os.environ["SHELL"]` if `auto`.'
commands.completion.shell  = commands.completion.s
commands.completion.a      = False
commands.completion.a.desc = 'Automatically write the completion scripts'
commands.completion.autu   = commands.completion.a

commands.install = [
	'Install a git-receive hook.',
	'So tagging will be triggered after `git push`']
commands.install.dir = './'
commands.install.dir.desc = [
	'The git project directory to install.',
	'Will install to `<dir>/.git/hooks`']
commands.install.i           = True
commands.install.i.desc      = 'Interactive mode for tagging'
commands.install.interactive = commands.install.i

commands.generate             = 'Generate a rcfile.'
commands.generate.i           = True
commands.generate.i.desc      = 'Using interactive mode.'
commands.generate.interactive = commands.generate.i
commands.generate.rcfile      = './.tagitrc'
commands.generate.c           = {}
commands.generate.c.desc      = 'The configurations for the rcfile'
commands.generate.config      = commands.generate.c

commands.generate._helpx = lambda helps: helps.select('optional').add(
	[('-c.changelog', '[AUTO]',
	  'Path to the changelog file to check if new version is mentioned.'),
	 ('-c.interactive', '[BOOL]',
	  'Whether use interactive mode while tagging.'),
	 ('-c.checktoml', '[BOOL]',
	  'Check `pyproject.toml` has the new version.')])

commands.tag                    = 'Do the tagging.'
commands.tag.rcfile             = './.tagitrc'
commands.tag.rcfile.desc        = 'Use the configurations from the rcfile'
commands.tag.c                  = {}
commands.tag.c.desc             = 'Overwrite the configurations from the rcfile'
commands.tag.increment          = 'auto'
commands.tag.increment.callback = lambda param: 'Unexpected value.' \
	if param.value not in ('auto', 'patch', 'minor', 'major') else None
commands.tag.increment.desc  = [
	'Incrementing version.',
	'* auto:  first try to use the version from pyproject.toml',
	'         if the tag exists, increment the patch part.',
	'* patch: increment the patch part',
	'* minor: increment the minor part',
	'* major: increment the major part',
]
commands.tag._helpx = lambda helps: helps.select('optional').add(
	[('-c.changelog', '[AUTO]',
	  'Path to the changelog file to check if new version is mentioned.'),
	 ('-c.interactive', '[BOOL]',
	  'Whether use interactive mode while tagging.'),
	 ('-c.checktoml', '[BOOL]',
	  'Check `pyproject.toml` has the new version.')])

class Tag:
	def __init__(self, tag):
		# TODO: check tag
		self.major, self.minor, self.patch = tag if isinstance(tag, tuple) \
			else (tag.major, tag.minor, tag.patch) if isinstance(tag, Tag) \
			else tuple(int(x) for x in tag.split('.'))
	def __str__(self):
		return '%s.%s.%s' % self.tuple()
	def tuple(self):
		return self.major, self.minor, self.patch
	def increment(self, part):
		if part == 'patch':
			return Tag((self.major, self.minor, self.patch + 1))
		if part == 'minor':
			return Tag((self.major, self.minor + 1, self.patch))
		if part == 'major':
			return Tag((self.major + 1, self.minor, self.patch))
	def __eq__(self, other):
		return self.tuple() == (other.tuple() if isinstance(other, Tag) else other)
	def __ne__(self, other):
		return not self.__eq__(other)
	def __gt__(self, other):
		return self.tuple() > (other.tuple() if isinstance(other, Tag) else other)
	def __lt__(self, other):
		return self.tuple() < (other.tuple() if isinstance(other, Tag) else other)

class TomlVersionBehindException(Exception):
	pass

class NoVersionInChangeLogException(Exception):
	pass

def _get_version_from_gittag():
	tags = git.tag().splitlines()
	if not tags:
		return None
	return Tag(tags[-1])

def _get_version_from_toml():
	tomlfile = Path('.') / 'pyproject.toml'
	if not tomlfile.exists():
		return None
	parsed = toml.load(tomlfile)
	if not parsed.get('tool', {}).get('poetry', {}).get('version'):
		return None
	return Tag(parsed['tool']['poetry']['version'])

def generate_interactive(options):
	changelog = prompt('Check new mentioned in changelog?: []', default='')
	interactive = prompt('Use interactive mode while tagging? [T|F]: ', default='True')
	checktoml = prompt('Check `pyproject.toml` has the new version? [T|F]: ', default='True')
	generate_rcfile({'c': {
		'changelog'  : changelog,
		'interactive': interactive in ('T', 'True'),
		'checktoml'  : checktoml in ('T', 'True'),
	}, 'rcfile': options['rcfile']})

def generate_rcfile(options):
	with open(options['rcfile'], 'w') as frc:
		frc.write('[TAGIT]\n')
		frc.write('changelog = %s\n' % changelog)
		frc.write('interactive = py:%r\n' % interactive)
		frc.write('checktoml = py:%r\n' % checktoml)
	print('rcfile saved to %r\n' % options['rcfile'])

def generate(options):
	interactive = options['i']
	if interactive:
		generate_interactive(options)
	else:
		generate_rcfile(options)

def completion(optoins):
	ret = commands._complete(options['shell'], options['auto'])
	if not auto:
		print(ret)

def tag(options):
	ver1 = _get_version_from_toml()
	ver2 = _get_version_from_gittag()
	if not ver1 and not ver2:
		ver = Tag((0,0,1))
	elif not ver1:
		ver = ver2
	elif not ver2:
		ver = ver1
	else:
		ver = Tag(max(ver1, ver2))
	if options.get('checktoml') and ver > ver2:
		raise TomlVersionBehindException('Excpetion %r in pyproject.toml, but got %r' % (ver, ver2))
	if options.get('changelog'):
		with open(options['changelog']) as fcl:
			if not re.search(r'[^\d]%s[^\d]' % ver, fcl.read()):
				raise NoVersionInChangeLogException('Verion %r not mentioned in %r' % (ver, options['changelog']))
	git.tag(str(ver), _fg = True)
	git.push(tag = True, _fg = True)

def main():
	command, options, _ = commands._parse()
	globals()[command](options)

if __name__ == '__main__':
	main()
