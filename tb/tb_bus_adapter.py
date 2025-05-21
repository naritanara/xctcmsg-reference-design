import cocotb
from cocotb.handle import SimHandleBase
from cocotb.triggers import RisingEdge

from adapters.bus import BusInterfaceDriver
from adapters.tb_generic import AbstractAdapterTB

class BusAdapterTB(AbstractAdapterTB[BusInterfaceDriver]):
    def __init__(self, dut: SimHandleBase):
        super().__init__(dut, BusInterfaceDriver(dut))


@cocotb.test
async def reset_state(dut):
    async with BusAdapterTB(dut):
        assert dut.holding_valid.value == 0

BusAdapterTB.test_factory().generate_tests()