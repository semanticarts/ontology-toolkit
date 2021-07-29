from onto_tool import onto_tool
import glob
import pydot


def test_local_instance():
    onto_tool.main([
                       'graphic', '--predicate-threshold', '0', '--data',
                       '-o', 'tests/graphic'
                   ] + glob.glob('tests/graphic/*.ttl'))
