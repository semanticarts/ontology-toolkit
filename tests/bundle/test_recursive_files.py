import os

import pytest
import yaml

from onto_tool import onto_tool

# Source tree used by all tests:
#   top.ttl, top.txt
#   sub/a.ttl, sub/b.txt
#   sub/deeper/c.ttl
SOURCE_FILES = {
    'top.ttl': 'top',
    'top.txt': 'top text',
    'sub/a.ttl': 'a',
    'sub/b.txt': 'b text',
    'sub/deeper/c.ttl': 'c',
}

# Patterns descending into subdirectories
TTL_PATTERNS = ['*.ttl', '*/*.ttl', '*/*/*.ttl']

SLASH_VARIANTS = [
    pytest.param('', '', id='no-slash'),
    pytest.param('/', '', id='source-slash'),
    pytest.param('', '/', id='target-slash'),
    pytest.param('/', '/', id='both-slash'),
]


def make_source_tree(root):
    for path, content in SOURCE_FILES.items():
        full_path = os.path.join(root, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)


def run_copy(tmp_path, action):
    bundle_file = tmp_path / 'bundle.yaml'
    bundle_file.write_text(yaml.safe_dump({
        'bundle': 'recursive',
        'variables': {},
        'actions': [dict(action='copy', **action)]
    }))
    onto_tool.main(['bundle', str(bundle_file)])


def relative_files(root):
    """Return all files under root, as paths relative to root."""
    return sorted(
        os.path.relpath(os.path.join(dir_path, name), root).replace(os.sep, '/')
        for dir_path, _, names in os.walk(root)
        for name in names)


def read(root, path):
    with open(os.path.join(root, path)) as f:
        return f.read()


@pytest.mark.parametrize('source_slash, target_slash', SLASH_VARIANTS)
def test_recursive_copy(tmp_path, source_slash, target_slash):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    make_source_tree(source)

    run_copy(tmp_path, {
        'source': str(source) + source_slash,
        'target': str(target) + target_slash,
        'includes': TTL_PATTERNS
    })

    # Subdirectory structure is preserved, rather than flattened
    assert relative_files(target) == ['sub/a.ttl', 'sub/deeper/c.ttl', 'top.ttl']
    for path in relative_files(target):
        assert read(target, path) == SOURCE_FILES[path]


@pytest.mark.parametrize('source_slash, target_slash', SLASH_VARIANTS)
def test_recursive_copy_with_rename(tmp_path, source_slash, target_slash):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    make_source_tree(source)

    run_copy(tmp_path, {
        'source': str(source) + source_slash,
        'target': str(target) + target_slash,
        'includes': TTL_PATTERNS,
        'rename': {'from': r'(.*)\.ttl', 'to': r'\g<1>.owl'}
    })

    # Renaming applies to the path relative to source, keeping subdirectories
    assert relative_files(target) == ['sub/a.owl', 'sub/deeper/c.owl', 'top.owl']
    for path in relative_files(target):
        assert read(target, path) == SOURCE_FILES[path[:-len('.owl')] + '.ttl']


@pytest.mark.parametrize('source_slash, target_slash', SLASH_VARIANTS)
def test_recursive_copy_rename_directory(tmp_path, source_slash, target_slash):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    make_source_tree(source)

    run_copy(tmp_path, {
        'source': str(source) + source_slash,
        'target': str(target) + target_slash,
        'includes': TTL_PATTERNS,
        'rename': {'from': r'^sub/', 'to': 'renamed/'}
    })

    # The rename pattern sees subdirectory names, so they can be renamed too
    assert relative_files(target) == ['renamed/a.ttl', 'renamed/deeper/c.ttl', 'top.ttl']


@pytest.mark.parametrize('source_slash, target_slash', SLASH_VARIANTS)
def test_recursive_glob(tmp_path, source_slash, target_slash):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    make_source_tree(source)

    run_copy(tmp_path, {
        'source': str(source) + source_slash,
        'target': str(target) + target_slash,
        'includes': ['**/*.ttl']
    })

    # '**' matches zero or more directories, so top level files are included
    assert relative_files(target) == ['sub/a.ttl', 'sub/deeper/c.ttl', 'top.ttl']
    for path in relative_files(target):
        assert read(target, path) == SOURCE_FILES[path]


@pytest.mark.parametrize('source_slash, target_slash', SLASH_VARIANTS)
def test_recursive_glob_with_rename(tmp_path, source_slash, target_slash):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    make_source_tree(source)

    run_copy(tmp_path, {
        'source': str(source) + source_slash,
        'target': str(target) + target_slash,
        'includes': ['**/*.ttl'],
        'rename': {'from': r'(.*)\.ttl', 'to': r'\g<1>.owl'}
    })

    assert relative_files(target) == ['sub/a.owl', 'sub/deeper/c.owl', 'top.owl']
    for path in relative_files(target):
        assert read(target, path) == SOURCE_FILES[path[:-len('.owl')] + '.ttl']


@pytest.mark.parametrize('source_slash, target_slash', SLASH_VARIANTS)
def test_recursive_glob_excludes(tmp_path, source_slash, target_slash):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    make_source_tree(source)

    run_copy(tmp_path, {
        'source': str(source) + source_slash,
        'target': str(target) + target_slash,
        'includes': ['**/*.ttl'],
        'excludes': ['**/deeper/*']
    })

    # Recursive patterns are also applied to excludes
    assert relative_files(target) == ['sub/a.ttl', 'top.ttl']


@pytest.mark.parametrize('source_slash, target_slash', SLASH_VARIANTS)
def test_recursive_glob_files_only(tmp_path, source_slash, target_slash):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    make_source_tree(source)

    run_copy(tmp_path, {
        'source': str(source) + source_slash,
        'target': str(target) + target_slash,
        'includes': ['**']
    })

    # '**' also matches directories (including source itself), which are skipped;
    # every file is copied exactly once, preserving structure
    assert relative_files(target) == sorted(SOURCE_FILES.keys())
    for path in relative_files(target):
        assert read(target, path) == SOURCE_FILES[path]


def test_directory_pattern_skipped(tmp_path):
    source = tmp_path / 'source'
    target = tmp_path / 'target'
    make_source_tree(source)

    run_copy(tmp_path, {
        'source': str(source),
        'target': str(target),
        'includes': ['*']
    })

    # The 'sub' directory matches '*' but only top level files are copied
    assert relative_files(target) == ['top.ttl', 'top.txt']
