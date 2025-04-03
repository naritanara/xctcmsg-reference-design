#!/usr/bin/env python3

from typing import List, Optional
from pathlib import Path
from dataclasses import dataclass

import os
import shutil
import pytest

from cocotb.runner import get_runner, Simulator

SIMULATORS: List[str] = ["verilator", "questa"]

@dataclass
class CocotbTest:
    hdl_toplevel: str

    def __str__(self):
        return f"{self.hdl_toplevel}"
    
    @property
    def test_module(self):
        return f"tb_{self.hdl_toplevel}"
    
    def resolve_test_filelist(self, project_path: Path) -> Path:
        return project_path / "tb_filelist.f"

TESTS: List[CocotbTest] = [
    CocotbTest("bus_communication_interface"),
    CocotbTest("mbox"),
    CocotbTest("request_decoder"),
    CocotbTest("postoffice"),
    CocotbTest("xctcmsg"),
]

def get_runners(candidates: List[str]) -> tuple[List[str], List[Simulator]]:
    simulators: List[str] = []
    runners: List[Simulator] = []

    for sim in candidates:
        try:
            if sim == 'verilator' and shutil.which('verilator') is None:
                continue
            runner: Simulator = get_runner(sim)
            simulators.append(sim)
            runners.append(runner)
        except:
            pass

    return simulators, runners

@pytest.fixture
def project_path() -> Path:
    return Path(__file__).resolve().parent

def test_runner(runner: Simulator, project_path: Path, cocotb_test: CocotbTest):
    hdl_toplevel_lang: str = "verilog"

    runner.build(
        build_dir=f"sim_build/{runner.__class__.__name__}/{cocotb_test.hdl_toplevel}",
        build_args=['-F', str(cocotb_test.resolve_test_filelist(project_path))],
        hdl_toplevel=cocotb_test.hdl_toplevel,
        waves=True,
        verilog_sources=["dummy.sv"], # We NEED to pass some source outside the filelist
    )

    runner.test(
        build_dir=f"sim_build/{runner.__class__.__name__}/{cocotb_test.hdl_toplevel}",
        hdl_toplevel=cocotb_test.hdl_toplevel,
        test_module=cocotb_test.test_module,
        waves=True
    )

def pytest_generate_tests(metafunc: pytest.Metafunc):
    if "cocotb_test" in metafunc.fixturenames:
        metafunc.parametrize("cocotb_test", TESTS, ids=str)
    if "runner" in metafunc.fixturenames:
        simulators, runners = get_runners(SIMULATORS)
        metafunc.parametrize("runner", runners, ids=simulators)

if __name__ == "__main__":
    pytest.main()