#!/usr/bin/env python3

from enum import StrEnum, auto
import os
from typing import List
from pathlib import Path
from dataclasses import dataclass, field

import shutil
import pytest
import logging

from cocotb.runner import get_runner, Simulator

from tools import generate_flat_top

LOGGER = logging.getLogger(__name__)

class SimulatorName(StrEnum):
    VERILATOR = auto()
    QUESTA = auto()

class NetworkImplementation(StrEnum):
    BUS = auto()
    OPENPITON = auto()
    
    def as_define(self) -> str:
        return f'XCTCMSG_NETWORK_{self.upper()}'
    
    def extra_defines(self) -> dict[str, object]:
        match self:
            case NetworkImplementation.OPENPITON:
                return {
                    'PITON_XCTCMSG_NOC_WIDTH': 192,
                    'PITON_X_TILES': 1,
                    'PITON_Y_TILES': 1,
                }
            case _:
                return {}
    
    def as_defines(self) -> dict[str, object]:
        return {
            self.as_define(): 1,
            **self.extra_defines(),
        }
    
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

@pytest.fixture
def tb_path() -> Path:
    return Path(__file__).resolve().parent

@pytest.fixture
def rtl_path(tb_path: Path) -> Path:
    return tb_path.parent / "rtl"

@dataclass
class CocotbTest:
    hdl_toplevel: str
    network_agnostic: bool = True
    compatible_networks: List[NetworkImplementation] = field(default_factory=lambda: NETWORK_IMPLEMENTATIONS)

    def __str__(self):
        return f"{self.hdl_toplevel}"
    
    @property
    def hdl_flat_top(self):
        return self.hdl_toplevel + "__flat_top"
    
    def generate_flat_top(self, top_path: Path, flat_top_path: Path):
        with open(top_path, 'r') as top, open(flat_top_path, 'w') as flat_top:
            generate_flat_top.process_file_and_write(top, flat_top)
    
    @property
    def test_module(self):
        return f"tb_{self.hdl_toplevel}"
    
    def resolve_test_build_dir(self, tb_path: Path, network: NetworkImplementation, simulator: str) -> Path:
        path = tb_path / "sim_build" / simulator / self.hdl_toplevel
        
        if not self.network_agnostic and len(self.compatible_networks) != 1:
            path /= network
        
        return path
    
    def resolve_test_filelist(self, tb_path: Path) -> Path:
        return tb_path / "tb_filelist.f"
    
    def resolve_test_top(self, rtl_path: Path, network: NetworkImplementation) -> Path:
        def file_contains_top(file: Path) -> bool:
            with open(file, 'r') as f:
                code = f.read()
            if 'module' not in code or 'endmodule' not in code:
                return False
            _, after_module = code.split('module', 1)
            return after_module.lstrip().startswith(self.hdl_toplevel)
        
        for root, dirs, files in os.walk(rtl_path):
            for file in files:
                file_path = Path(os.path.join(root, file))
                if file_contains_top(file_path):
                    return Path(file_path)
        
        raise FileNotFoundError(f"Top-level module '{self.hdl_toplevel}' not found in {rtl_path}")
    
    def resolve_test_flat_top(self, tb_path: Path, network: NetworkImplementation, simulator: str) -> Path:
        return self.resolve_test_build_dir(tb_path, network, simulator) / f"{self.hdl_flat_top}.sv"

TESTS: List[CocotbTest] = [
    CocotbTest("bus_adapter", network_agnostic=False, compatible_networks=[NetworkImplementation.BUS]),
    CocotbTest("openpiton_adapter", network_agnostic=False, compatible_networks=[NetworkImplementation.OPENPITON]),
    CocotbTest("mbox"),
    CocotbTest("request_decoder"),
    CocotbTest("postoffice"),
    CocotbTest("xctcmsg", network_agnostic=False),
]

def test_runner(runner: Simulator, tb_path: Path, rtl_path: Path, cocotb_test: CocotbTest, network_implementation: NetworkImplementation):
    if cocotb_test.network_agnostic and network_implementation != NETWORK_IMPLEMENTATIONS[0]:
        pytest.skip("Test is network agnostic, no need to run it for multiple networks")
    if network_implementation not in cocotb_test.compatible_networks:
        pytest.skip(f"Test is not compatible with {network_implementation} network")
    
    simulator_name = runner.__class__.__name__
    
    build_dir = cocotb_test.resolve_test_build_dir(tb_path, network_implementation, simulator_name)
    if not build_dir.exists():
        build_dir.mkdir(parents=True)
    
    hdl_toplevel_lang: str = "verilog"
    
    top_path = cocotb_test.resolve_test_top(rtl_path, network_implementation)
    flat_top_path = cocotb_test.resolve_test_flat_top(tb_path, network_implementation, simulator_name)
    cocotb_test.generate_flat_top(top_path, flat_top_path)

    runner.build(
        build_dir=build_dir,
        build_args=['-F', str(cocotb_test.resolve_test_filelist(tb_path))],
        defines={
            'XCTCMSG_CORE_UNIT_TEST': 1,
            **network_implementation.as_defines()
        },
        includes=network_implementation.extra_include_paths(tb_path),
        hdl_toplevel=cocotb_test.hdl_flat_top,
        waves=True,
        verilog_sources=[flat_top_path],
    )

    runner.test(
        build_dir=build_dir,
        hdl_toplevel=cocotb_test.hdl_flat_top,
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