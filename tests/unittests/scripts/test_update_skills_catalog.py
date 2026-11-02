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

"""Unit tests for update_skills_catalog.py."""

from __future__ import annotations

import pathlib

from scripts import update_skills_catalog

_MARKERS = '<!-- skills-catalog:start -->\n<!-- skills-catalog:end -->\n'


def write(path: pathlib.Path, text: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(text, encoding='utf-8')


def write_skill(root: pathlib.Path, directory: str, frontmatter: str) -> None:
  write(
      root / '.agents' / 'skills' / directory / 'SKILL.md',
      f'---\n{frontmatter}\n---\n\n# Body\n',
  )


def details(problems: list[update_skills_catalog.Problem]) -> list[str]:
  return [problem.detail for problem in problems]


def test_valid_skill_is_listed_in_the_catalog(tmp_path: pathlib.Path) -> None:
  write(tmp_path / 'AGENTS.md', '# Agents\n\n' + _MARKERS)
  write_skill(
      tmp_path,
      'pdf-tools',
      'name: pdf-tools\ndescription: >-\n  Merges PDFs.\n  Use for PDFs &'
      ' forms.',
  )

  assert not update_skills_catalog.run(str(tmp_path), check=False)

  text = (tmp_path / 'AGENTS.md').read_text(encoding='utf-8')
  assert text.startswith('# Agents\n\n')
  assert '<name>pdf-tools</name>' in text
  assert (
      '<description>Merges PDFs. Use for PDFs &amp; forms.</description>'
      in (text)
  )
  assert '<location>.agents/skills/pdf-tools/SKILL.md</location>' in text


def test_check_reports_a_stale_catalog_without_writing(
    tmp_path: pathlib.Path,
) -> None:
  write(tmp_path / 'AGENTS.md', _MARKERS)
  write_skill(tmp_path, 'a', 'name: a\ndescription: Does a.')

  problems = update_skills_catalog.run(str(tmp_path), check=True)

  assert any('out of date' in detail for detail in details(problems))
  assert (tmp_path / 'AGENTS.md').read_text(encoding='utf-8') == _MARKERS


def test_check_passes_once_the_catalog_is_written(
    tmp_path: pathlib.Path,
) -> None:
  write(tmp_path / 'AGENTS.md', _MARKERS)
  write_skill(tmp_path, 'a', 'name: a\ndescription: Does a.')

  update_skills_catalog.run(str(tmp_path), check=False)

  assert not update_skills_catalog.run(str(tmp_path), check=True)


def test_user_only_skill_is_left_out_of_the_catalog(
    tmp_path: pathlib.Path,
) -> None:
  write(tmp_path / 'AGENTS.md', _MARKERS)
  write_skill(
      tmp_path,
      'setup',
      'name: setup\ndescription: Sets up.\ndisable-model-invocation: true',
  )

  assert not update_skills_catalog.run(str(tmp_path), check=False)

  text = (tmp_path / 'AGENTS.md').read_text(encoding='utf-8')
  assert 'setup' not in text
  assert '<available_skills>' not in text


def test_name_must_match_its_directory(tmp_path: pathlib.Path) -> None:
  write(tmp_path / 'AGENTS.md', _MARKERS)
  write_skill(tmp_path, 'right', 'name: wrong\ndescription: Does it.')

  problems = update_skills_catalog.run(str(tmp_path), check=True)

  assert "`name` is 'wrong' but the directory is 'right'" in details(problems)


def test_name_character_rules_are_enforced(tmp_path: pathlib.Path) -> None:
  write(tmp_path / 'AGENTS.md', _MARKERS)
  write_skill(tmp_path, 'Bad--Name', 'name: Bad--Name\ndescription: Does it.')

  problems = update_skills_catalog.run(str(tmp_path), check=True)

  assert any('lowercase letters' in detail for detail in details(problems))


def test_missing_description_keeps_the_skill_out(
    tmp_path: pathlib.Path,
) -> None:
  write(tmp_path / 'AGENTS.md', _MARKERS)
  write_skill(tmp_path, 'a', 'name: a')

  problems = update_skills_catalog.run(str(tmp_path), check=False)

  assert '`description` is missing' in details(problems)
  assert '<name>a</name>' not in (tmp_path / 'AGENTS.md').read_text(
      encoding='utf-8'
  )


def test_overlong_description_is_reported(tmp_path: pathlib.Path) -> None:
  write(tmp_path / 'AGENTS.md', _MARKERS)
  write_skill(tmp_path, 'a', 'name: a\ndescription: ' + 'x' * 1025)

  problems = update_skills_catalog.run(str(tmp_path), check=True)

  assert '`description` is longer than 1024 characters' in details(problems)


def test_unknown_field_is_reported(tmp_path: pathlib.Path) -> None:
  write(tmp_path / 'AGENTS.md', _MARKERS)
  write_skill(tmp_path, 'a', 'name: a\ndescription: Does a.\nversion: 2')

  problems = update_skills_catalog.run(str(tmp_path), check=True)

  assert (
      '`version` is not a field the Agent Skills specification defines'
      in details(problems)
  )


def test_numeric_metadata_value_is_reported(tmp_path: pathlib.Path) -> None:
  write(tmp_path / 'AGENTS.md', _MARKERS)
  write_skill(
      tmp_path, 'a', 'name: a\ndescription: Does a.\nmetadata:\n  version: 1.0'
  )

  problems = update_skills_catalog.run(str(tmp_path), check=True)

  assert any('`metadata`' in detail for detail in details(problems))


def test_file_without_frontmatter_is_reported(tmp_path: pathlib.Path) -> None:
  write(tmp_path / 'AGENTS.md', _MARKERS)
  write(
      tmp_path / '.agents' / 'skills' / 'a' / 'SKILL.md', '# No frontmatter\n'
  )

  problems = update_skills_catalog.run(str(tmp_path), check=True)

  assert any('frontmatter' in detail for detail in details(problems))


def test_missing_markers_are_reported(tmp_path: pathlib.Path) -> None:
  write(tmp_path / 'AGENTS.md', '# Agents\n')

  problems = update_skills_catalog.run(str(tmp_path), check=False)

  assert any('skills-catalog:start' in detail for detail in details(problems))


def test_repo_catalog_is_current() -> None:
  root = pathlib.Path(__file__).resolve().parents[3]

  assert not update_skills_catalog.run(str(root), check=True)
