#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Validates the repo's agent skills and writes their catalog into AGENTS.md.

Every directory under .agents/skills/ that holds a SKILL.md is a skill in the
Agent Skills format (https://agentskills.io/specification). This script:

1. Validates each SKILL.md frontmatter against the specification: `name` and
   `description` are present and within their limits, `name` matches the
   directory, and no field outside the specification appears unless it is a
   known client extension.
2. Renders the catalog, the name, description and location of every skill the
   model may activate on its own, and writes it between the catalog markers in
   AGENTS.md. Agents that read AGENTS.md but do not scan .agents/skills/ learn
   from it which skills exist and which file to read for each. A skill that
   sets `disable-model-invocation` runs only when a user asks for it, so it is
   left out, as the specification's client guide recommends.

Usage:
  python scripts/update_skills_catalog.py [--check] [--root DIR]

With --check nothing is written; the script fails if a skill is invalid or the
catalog in AGENTS.md is out of date.

Exit codes: 0 = ok, 1 = problems found, 2 = usage/setup error.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import re
import sys
from xml.sax.saxutils import escape

import yaml

_SKILLS_RELPATH = os.path.join('.agents', 'skills')
_AGENTS_MD_RELPATH = 'AGENTS.md'
_SKILL_FILENAME = 'SKILL.md'

_CATALOG_START = '<!-- skills-catalog:start -->'
_CATALOG_END = '<!-- skills-catalog:end -->'

_EXIT_OK = 0
_EXIT_PROBLEMS = 1
_EXIT_SETUP_ERROR = 2

_SPEC_FIELDS = frozenset({
    'name',
    'description',
    'license',
    'compatibility',
    'metadata',
    'allowed-tools',
})
# Fields some clients read that the specification does not define.
_EXTENSION_FIELDS = frozenset({'disable-model-invocation'})

_NAME_MAX = 64
_DESCRIPTION_MAX = 1024
_COMPATIBILITY_MAX = 500
_BODY_MAX_LINES = 500
_NAME_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
_FRONTMATTER_RE = re.compile(r'\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z', re.S)

_INSTRUCTIONS = """\
The following skills provide specialized instructions for specific tasks.
When a task matches a skill's description, read the SKILL.md at the listed
location before proceeding. Resolve relative paths in a skill against its
directory, the parent of SKILL.md."""


@dataclass(frozen=True)
class Problem:
  """One thing wrong with a skill or the catalog.

  Attributes:
    path: Repo-relative path of the file the problem is in.
    detail: What is wrong, phrased so the fix is obvious.
  """

  path: str
  detail: str


@dataclass(frozen=True)
class Skill:
  """The catalog entry for one skill.

  Attributes:
    name: The `name` from the frontmatter.
    description: The `description` from the frontmatter.
    location: Repo-relative path of the SKILL.md, with forward slashes.
    model_invocable: False when the skill runs only at a user's request.
  """

  name: str
  description: str
  location: str
  model_invocable: bool


def skill_files(root: str) -> list[str]:
  """Returns the absolute path of every SKILL.md one level under the skills dir."""
  skills_dir = os.path.join(root, _SKILLS_RELPATH)
  if not os.path.isdir(skills_dir):
    return []
  return sorted(
      os.path.join(skills_dir, entry, _SKILL_FILENAME)
      for entry in os.listdir(skills_dir)
      if os.path.isfile(os.path.join(skills_dir, entry, _SKILL_FILENAME))
  )


def parse_skill(root: str, path: str) -> tuple[Skill | None, list[Problem]]:
  """Parses and validates one SKILL.md.

  Returns:
    The catalog entry, or None when the file is too broken to list, and every
    problem found in it.
  """
  display = os.path.relpath(path, root)
  with open(path, encoding='utf-8') as f:
    text = f.read()

  match = _FRONTMATTER_RE.match(text)
  if not match:
    return None, [
        Problem(
            display, "does not start with YAML frontmatter between '---' lines"
        )
    ]
  try:
    frontmatter = yaml.safe_load(match.group(1))
  except yaml.YAMLError as e:
    return None, [Problem(display, f'frontmatter is not valid YAML: {e}')]
  if not isinstance(frontmatter, dict):
    return None, [Problem(display, 'frontmatter is not a YAML mapping')]

  problems: list[Problem] = []

  def report(detail: str) -> None:
    problems.append(Problem(display, detail))

  name = frontmatter.get('name')
  directory = os.path.basename(os.path.dirname(path))
  if not isinstance(name, str) or not name:
    report('`name` is missing')
  else:
    if len(name) > _NAME_MAX:
      report(f'`name` is longer than {_NAME_MAX} characters')
    if not _NAME_RE.match(name):
      report(
          '`name` may only hold lowercase letters, digits and single hyphens,'
          ' and may not start or end with a hyphen'
      )
    if name != directory:
      report(f'`name` is {name!r} but the directory is {directory!r}')

  description = frontmatter.get('description')
  if not isinstance(description, str) or not description.strip():
    report('`description` is missing')
  elif len(description) > _DESCRIPTION_MAX:
    report(f'`description` is longer than {_DESCRIPTION_MAX} characters')

  compatibility = frontmatter.get('compatibility')
  if compatibility is not None and (
      not isinstance(compatibility, str)
      or not 1 <= len(compatibility) <= _COMPATIBILITY_MAX
  ):
    report(f'`compatibility` must be 1 to {_COMPATIBILITY_MAX} characters')

  metadata = frontmatter.get('metadata')
  if metadata is not None and (
      not isinstance(metadata, dict)
      or not all(
          isinstance(k, str) and isinstance(v, str) for k, v in metadata.items()
      )
  ):
    report('`metadata` must map strings to strings; quote numeric values')

  allowed_tools = frontmatter.get('allowed-tools')
  if allowed_tools is not None and not isinstance(allowed_tools, str):
    report('`allowed-tools` must be a space-separated string')

  disable = frontmatter.get('disable-model-invocation', False)
  if not isinstance(disable, bool):
    report('`disable-model-invocation` must be true or false')

  for field in sorted(set(frontmatter) - _SPEC_FIELDS - _EXTENSION_FIELDS):
    report(f'`{field}` is not a field the Agent Skills specification defines')

  body_lines = len(match.group(2).splitlines())
  if body_lines > _BODY_MAX_LINES:
    report(
        f'the body is {body_lines} lines; keep it under {_BODY_MAX_LINES} and'
        ' move detail into references/'
    )

  if not isinstance(name, str) or not isinstance(description, str):
    return None, problems
  skill = Skill(
      name=name,
      description=' '.join(description.split()),
      location=display.replace(os.sep, '/'),
      model_invocable=disable is not True,
  )
  return skill, problems


def render_catalog(skills: list[Skill]) -> str:
  """Returns the catalog block, markers included, for the given skills."""
  listed = [skill for skill in skills if skill.model_invocable]
  lines = [
      _CATALOG_START,
      '<!-- Generated by scripts/update_skills_catalog.py; do not edit. -->',
      '',
  ]
  if listed:
    lines += [_INSTRUCTIONS, '', '```xml', '<available_skills>']
    for skill in listed:
      lines += [
          '  <skill>',
          f'    <name>{escape(skill.name)}</name>',
          f'    <description>{escape(skill.description)}</description>',
          f'    <location>{escape(skill.location)}</location>',
          '  </skill>',
      ]
    lines += ['</available_skills>', '```', '']
  lines.append(_CATALOG_END)
  return '\n'.join(lines)


def splice_catalog(text: str, catalog: str) -> str | None:
  """Returns `text` with the catalog block replaced, or None without markers."""
  start = text.find(_CATALOG_START)
  end = text.find(_CATALOG_END, start)
  if start == -1 or end == -1:
    return None
  return text[:start] + catalog + text[end + len(_CATALOG_END) :]


def run(root: str, check: bool) -> list[Problem]:
  """Validates every skill and updates, or with `check` verifies, the catalog."""
  problems: list[Problem] = []
  skills: list[Skill] = []
  names: dict[str, str] = {}
  for path in skill_files(root):
    skill, found = parse_skill(root, path)
    problems += found
    if skill is None:
      continue
    if skill.name in names:
      problems.append(
          Problem(
              skill.location,
              f'`name` {skill.name!r} is already used by {names[skill.name]}',
          )
      )
      continue
    names[skill.name] = skill.location
    skills.append(skill)

  agents_md = os.path.join(root, _AGENTS_MD_RELPATH)
  with open(agents_md, encoding='utf-8') as f:
    current = f.read()
  updated = splice_catalog(current, render_catalog(skills))
  if updated is None:
    problems.append(
        Problem(
            _AGENTS_MD_RELPATH,
            f'add a {_CATALOG_START} line and a {_CATALOG_END} line where the'
            ' skills catalog belongs',
        )
    )
  elif updated != current:
    if check:
      problems.append(
          Problem(
              _AGENTS_MD_RELPATH,
              'the skills catalog is out of date; run'
              ' python scripts/update_skills_catalog.py',
          )
      )
    else:
      with open(agents_md, 'w', encoding='utf-8') as f:
        f.write(updated)
  return problems


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
      '--check',
      action='store_true',
      help='report a stale catalog instead of rewriting it',
  )
  parser.add_argument(
      '--root',
      default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
      help='repository root (default: the repo this script is in)',
  )
  namespace = parser.parse_args(argv)
  root = os.path.abspath(namespace.root)
  if not os.path.isfile(os.path.join(root, _AGENTS_MD_RELPATH)):
    print(f'No {_AGENTS_MD_RELPATH} under {root}', file=sys.stderr)
    return _EXIT_SETUP_ERROR

  problems = run(root, check=namespace.check)
  for problem in problems:
    print(f'{problem.path}: {problem.detail}')
  if problems:
    print(f'\n{len(problems)} skills problem(s).')
    return _EXIT_PROBLEMS
  return _EXIT_OK


if __name__ == '__main__':
  sys.exit(main())
