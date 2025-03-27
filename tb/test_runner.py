#!/usr/bin/env python3

from typing import List
from pathlib import Path

from dataclasses import dataclass
import os
import shutil

import pytest

from cocotb.runner import get_runner, Simulator

SIMULATORS: List[str] = ["verilator", "questa"]

class ResolvableFile:
    def resolve(self, project_path: Path) -> Path:
        raise NotImplementedError

@dataclass
class ProjectFile(ResolvableFile):
    filename: str
    
    def resolve(self, project_path: Path) -> Path:
        return project_path.parent / "rtl" / self.filename

@dataclass
class ProjectIncludesDir(ResolvableFile):
    def resolve(self, project_path: Path) -> Path:
        return project_path.parent / "includes"

@dataclass
class CommonCellsFile(ResolvableFile):
    filename: str
    
    def resolve(self, project_path: Path) -> Path:
        return project_path.parents[5] / "common_cells" / "src" / self.filename

@dataclass
class CocotbTest:
    sources: List[ResolvableFile]
    hdl_toplevel: str

    def __str__(self):
        return f"{self.hdl_toplevel}"
    
    @property
    def test_module(self):
        return f"tb_{self.hdl_toplevel}"

TESTS: List[CocotbTest] = [
    CocotbTest([ProjectFile("bus_communication_interface.sv")], "bus_communication_interface"),
    CocotbTest([ProjectFile("mbox.sv")], "mbox"),
    CocotbTest([ProjectFile("request_decoder.sv")], "request_decoder"),
    CocotbTest([ProjectFile("postoffice.sv")], "postoffice"),
    CocotbTest(
        [
            ProjectFile("bus_communication_interface.sv"),
            ProjectFile("mbox.sv"),
            ProjectFile("postoffice.sv"),
            ProjectFile("request_decoder.sv"),
            CommonCellsFile("fifo_v3.sv"),
            ProjectFile("send_queue.sv"),
            ProjectFile("receive_queue.sv"),
            CommonCellsFile("rr_arb_tree.sv"),
            ProjectFile("writeback_arbiter.sv"),
            ProjectFile("commit_safety_unit.sv"),
            ProjectFile("xctcmsg.sv")
        ],
        "xctcmsg"
    )
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

    sources: List[Path] = [source.resolve(project_path) for source in cocotb_test.sources]

    runner.build(
        sources=sources,
        includes=[ProjectIncludesDir().resolve(project_path)],
        hdl_toplevel=cocotb_test.hdl_toplevel,
        waves=True
    )

    runner.test(
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