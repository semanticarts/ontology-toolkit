import ntpath
from types import SimpleNamespace

import pytest

from onto_tool import bundle

# Windows style tree used by all tests, as glob would return it on Windows
SOURCE_DIR = 'C:\\data\\source'
TARGET_DIR = 'C:\\data\\target'
MATCHES = [
    'C:\\data\\source\\top.ttl',
    'C:\\data\\source\\sub\\a.ttl',
    'C:\\data\\source\\sub\\deeper\\c.ttl',
]


@pytest.fixture
def windows(monkeypatch):
    """
    Make bundle behave as if running on Windows, regardless of the actual OS.

    os.name and os.path are replaced only inside the bundle module, globbing
    returns the fixed list of Windows paths above, and no directories are
    created; the directories that would have been created are recorded instead.
    """
    created = []
    fake_os = SimpleNamespace(
        name='nt',
        path=ntpath,
        makedirs=lambda path, *args, **kwargs: created.append(path))
    monkeypatch.setattr(bundle, 'os', fake_os)
    monkeypatch.setattr(bundle, 'isdir', lambda path: False)
    monkeypatch.setattr(bundle, '__glob_files', lambda src_dir, pattern: list(MATCHES))
    return created


def file_list(action):
    bundle_file_list = getattr(bundle, '__bundle_file_list')
    return [(in_out['inputFile'], in_out['outputFile'])
            for in_out in bundle_file_list(action, {})]


@pytest.mark.parametrize('source, target', [
    pytest.param(SOURCE_DIR, TARGET_DIR, id='no-slash'),
    pytest.param(SOURCE_DIR + '\\', TARGET_DIR + '\\', id='backslash'),
    pytest.param('C:/data/source', 'C:/data/target', id='forward-slash'),
])
def test_rename_extension(windows, source, target):
    result = file_list({
        'source': source,
        'target': target,
        'includes': ['**/*.ttl'],
        'rename': {'from': r'(.*)\.ttl', 'to': r'\g<1>.owl'}
    })

    # Output paths use native separators, and subdirectories are preserved
    assert [ntpath.relpath(output, TARGET_DIR) for _, output in result] == [
        'top.owl', 'sub\\a.owl', 'sub\\deeper\\c.owl']
    assert [input_file for input_file, _ in result] == MATCHES
    assert all(ntpath.normcase(output).startswith(ntpath.normcase(TARGET_DIR))
               for _, output in result)


def test_rename_directory_forward_slash_pattern(windows):
    result = file_list({
        'source': SOURCE_DIR,
        'target': TARGET_DIR,
        'includes': ['**/*.ttl'],
        'rename': {'from': r'^sub/', 'to': 'renamed/'}
    })

    # Rename patterns are written with '/', which must match Windows separators
    assert [output for _, output in result] == [
        'C:\\data\\target\\top.ttl',
        'C:\\data\\target\\renamed\\a.ttl',
        'C:\\data\\target\\renamed\\deeper\\c.ttl',
    ]
    # Renamed subdirectories are created on the output side
    assert 'C:\\data\\target\\renamed' in windows
    assert 'C:\\data\\target\\renamed\\deeper' in windows


def test_rename_is_case_insensitive(windows):
    result = file_list({
        'source': SOURCE_DIR,
        'target': TARGET_DIR,
        'includes': ['**/*.ttl'],
        'rename': {'from': r'^SUB/(.*)\.TTL$', 'to': r'other/\g<1>.owl'}
    })

    # Windows file names are case insensitive, and so is renaming
    assert [output for _, output in result] == [
        'C:\\data\\target\\top.ttl',
        'C:\\data\\target\\other\\a.owl',
        'C:\\data\\target\\other\\deeper\\c.owl',
    ]


def test_no_rename(windows):
    result = file_list({
        'source': SOURCE_DIR,
        'target': TARGET_DIR,
        'includes': ['**/*.ttl'],
    })

    assert [output for _, output in result] == [
        'C:\\data\\target\\top.ttl',
        'C:\\data\\target\\sub\\a.ttl',
        'C:\\data\\target\\sub\\deeper\\c.ttl',
    ]

