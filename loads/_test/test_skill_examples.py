"""Run the offline example of the agent skill (`loads/skill/examples/`)"""

import importlib.util
import os

import loads.skill


def test_offline_demo(capsys):
    path = os.path.join(os.path.dirname(loads.skill.__file__), "examples", "offline_demo.py")
    spec = importlib.util.spec_from_file_location("offline_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()
    assert "conservation error" in capsys.readouterr().out
