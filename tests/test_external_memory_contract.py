from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def module(path: Path, name: str):
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class ExternalMemoryContractTest(unittest.TestCase):
    def test_valid_single_packet_is_accepted_by_both_adapters(self) -> None:
        packet = "<autodev-memory-task-context>\nx\n</autodev-memory-task-context>"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "packet"
            path.write_text(packet)
            for script, name in (("external-agent", "external_agent"),
                                 ("external-build", "external_build")):
                loaded = module(ROOT / "bin" / script, name)
                self.assertEqual(loaded.read_memory_context(str(path)), packet)

    def test_oversize_packet_is_rejected(self) -> None:
        loaded = module(ROOT / "bin/external-agent", "external_agent_oversize")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "packet"
            path.write_text("<autodev-memory-task-context>" + "x" * 3000
                            + "</autodev-memory-task-context>")
            with self.assertRaises(SystemExit):
                loaded.read_memory_context(str(path))


if __name__ == "__main__":
    unittest.main()
