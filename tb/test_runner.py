#!/usr/bin/env python3

from enum import StrEnum, auto
from typing import List
from pathlib import Path
from dataclasses import dataclass, field

import shutil
import pytest
import logging

from cocotb.runner import get_runner, Simulator

LOGGER = logging.getLogger(__name__)

class SimulatorName(StrEnum):
    VERILATOR = auto()
    QUESTA = auto()

class NetworkImplementation(StrEnum):
    BUS = auto()
    OPENPITON = auto()
    
    def as_define(self) -> str:
        return f'NETWORK_IMPLEMENTATION_{self.upper()}'
    
    def extra_include_paths(self, project_path: Path) -> List[Path]:
        match self:
            case NetworkImplementation.OPENPITON:
                return [project_path.parents[12] / "include" / ""]
            case _:
                return []
    
NETWORK_IMPLEMENTATIONS = [x for x in NetworkImplementation]
SIMULATORS = [x for x in SimulatorName]

@pytest.fixture
def runner(request) -> Simulator:
    assert request.param in SimulatorName
    sim = request.param
    
    if sim == SimulatorName.VERILATOR and shutil.which('verilator') is None:
        pytest.skip("Verilator binary (verilator) not found in PATH")
    
    try:
        return get_runner(sim)
    except:
        pytest.skip(f"Simulator {sim} not found")

@dataclass
class CocotbTest:
    hdl_toplevel: str
    network_agnostic: bool = True
    compatible_networks: List[NetworkImplementation] = field(default_factory=lambda: NETWORK_IMPLEMENTATIONS)

    def __str__(self):
        return f"{self.hdl_toplevel}"
    
    def build_dir(self, network: NetworkImplementation) -> str:
        if self.network_agnostic or len(self.compatible_networks) == 1:
            return self.hdl_toplevel
        else:
            return self.hdl_toplevel + "/" + network
    
    @property
    def test_module(self):
        return f"tb_{self.hdl_toplevel}"
    
    def resolve_test_filelist(self, project_path: Path) -> Path:
        return project_path / "tb_filelist.f"

TESTS: List[CocotbTest] = [
    CocotbTest("bus_adapter", network_agnostic=False, compatible_networks=[NetworkImplementation.BUS]),
    CocotbTest("openpiton_adapter", network_agnostic=False, compatible_networks=[NetworkImplementation.OPENPITON]),
    CocotbTest("mbox"),
    CocotbTest("request_decoder"),
    CocotbTest("postoffice"),
    CocotbTest("xctcmsg", network_agnostic=False),
]

@pytest.fixture
def project_path() -> Path:
    return Path(__file__).resolve().parent

def test_runner(runner: Simulator, project_path: Path, cocotb_test: CocotbTest, network_implementation: NetworkImplementation):
    if cocotb_test.network_agnostic and network_implementation != NETWORK_IMPLEMENTATIONS[0]:
        pytest.skip("Test is network agnostic, no need to run it for multiple networks")
    if network_implementation not in cocotb_test.compatible_networks:
        pytest.skip(f"Test is not compatible with {network_implementation} network")
    
    hdl_toplevel_lang: str = "verilog"

    runner.build(
        build_dir=f"sim_build/{runner.__class__.__name__}/{cocotb_test.build_dir(network_implementation)}",
        build_args=['-F', str(cocotb_test.resolve_test_filelist(project_path))],
        defines={network_implementation.as_define(): 1},
        includes=network_implementation.extra_include_paths(project_path),
        hdl_toplevel=cocotb_test.hdl_toplevel,
        waves=True,
        verilog_sources=[project_path / "dummy.sv"], # We NEED to pass some source outside the filelist
    )

    runner.test(
        build_dir=f"sim_build/{runner.__class__.__name__}/{cocotb_test.build_dir(network_implementation)}",
        hdl_toplevel=cocotb_test.hdl_toplevel,
        test_module=cocotb_test.test_module,
        extra_env={'XCTCMSG_NETWORK_IMPLEMENTATION': network_implementation},
        waves=True
    )

def pytest_generate_tests(metafunc: pytest.Metafunc):
    if "cocotb_test" in metafunc.fixturenames:
        metafunc.parametrize("cocotb_test", TESTS, ids=str)
    if "network_implementation" in metafunc.fixturenames:
        metafunc.parametrize("network_implementation", NETWORK_IMPLEMENTATIONS)
    if "runner" in metafunc.fixturenames:
        metafunc.parametrize("runner", SIMULATORS, indirect=True)

if __name__ == "__main__":
    pytest.main()