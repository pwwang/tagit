# tagit
[![pypi][1]][2] [![tag][3]][4]

Automation of git tagging

## Why?
While publishing a python package, we need to:
- Check if CHANGELOG has been updated,
- Check if version in source file has been updated,
- Check if version in meta file (e.g. `pyproject.toml`) has been updated
- If not, update it, commit and push the changes, and then
- Build and publish the new version

## Application senario
It is applicable only when you are:
- Using strict semantic versioning
- Using pure version as tag label
- Publishing your packaging using `poetry`

## What it does:
- In all modes:
	- Checks if there is any changes after last tagging, if so, skip.
- In manual version mode (you specify a tag while tagging):
	- Checks if right version has been placed in `pyproject.toml` in manual version mode.
	- Checks if the version has been mentioned in CHANGELOG file in manual version mode.
	- Checks if the version has been updated in source code.
- In auto version mode (version auto-increments)
	- Checks if the new version has been mentioned in CHANGELOG
	- Updates version in `pyproject.toml`
	- Updates version in source code
	- Extra commands before changed being committed and pushed
	- Commits and pushes the changes
- Then, in all modes:
	- Tags the version (`git tag <version>`)
	- Pushs the tag to the remote (`git push --tags`)
	- Builds and publishs the release (`poetry publish --build`)

## Snapshot
![tagit][5]

[1]: https://img.shields.io/pypi/v/tagit.svg?style=flat-square
[2]: https://pypi.org/project/tagit/
[3]: https://img.shields.io/github/tag/pwwang/tagit.svg?style=flat-square
[4]: https://github.com/pwwang/tagit
[5]: https://raw.githubusercontent.com/pwwang/tagit/master/tagit.png
