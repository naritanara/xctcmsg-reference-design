from cocotb.handle import SimHandleBase

from adapters.openpiton import OpenpitonInterfaceDriver
from adapters.tb_generic import AbstractAdapterTB


class OpenpitonAdapterTB(AbstractAdapterTB[OpenpitonInterfaceDriver]):
    def __init__(self, dut: SimHandleBase):
        super().__init__(dut, OpenpitonInterfaceDriver(dut))

# TODO: Set the necessary defines for a 16 bit address check
OpenpitonAdapterTB.test_factory(max_addr_bits=8).generate_tests()