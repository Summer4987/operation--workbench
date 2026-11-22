import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class NodeRuntimeTest(unittest.TestCase):
    def test_runtime_survives_removal_of_hermes(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            source = home / '.hermes/node/bin/node'
            source.parent.mkdir(parents=True)
            source.write_text('#!/bin/sh\necho v22.23.5\n')
            source.chmod(0o700)
            link = home / '.local/bin/node'
            link.parent.mkdir(parents=True)
            link.symlink_to(source)
            env = dict(os.environ, HOME=folder)
            env.pop('WECOM_NODE', None)
            script = str(Path(__file__).with_name('prepare_node.zsh'))
            first = subprocess.check_output(['/bin/zsh', script], env=env, text=True).strip()
            source.unlink()
            self.assertFalse(Path(first).is_symlink())
            self.assertEqual(subprocess.check_output([first, '--version'], text=True).strip(), 'v22.23.5')
            self.assertEqual(subprocess.check_output(['/bin/zsh', script], env=env, text=True).strip(), first)

    def test_invalid_runtime_does_not_replace_good_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            target = home / '.local/share/xiong-wecom-assistant/runtime/node'
            target.parent.mkdir(parents=True)
            target.write_text('existing runtime')
            old = home / 'old-node'
            old.write_text('#!/bin/sh\necho v20.0.0\n')
            old.chmod(0o700)
            script = str(Path(__file__).with_name('prepare_node.zsh'))
            for candidate in (str(old), str(home / 'missing-node')):
                result = subprocess.run(['/bin/zsh', script], env=dict(os.environ, HOME=folder, WECOM_NODE=candidate), capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(target.read_text(), 'existing runtime')


if __name__ == '__main__':
    unittest.main()
