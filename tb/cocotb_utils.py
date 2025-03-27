from typing import Awaitable, Optional, override
from cocotb.handle import SimHandleBase
from cocotb.triggers import Timer, _ParameterizedSingletonAndABC
from cocotb.utils import Decimal, ParametrizedSingleton
from cocotb import triggers
from cocotb import top

# make pyright happy :D (top is only undefined during test discovery)
assert isinstance(top, SimHandleBase)

async def reset():
    top._log.info("Asserting reset signal")
    top.rst_n.value = 0
    await SimulationUpdate()
    top.rst_n.value = 1
    await SimulationUpdate()

async def flush():
    top._log.info("Asserting flush signal")
    top.flush.value = 1
    await RisingEdge()
    top.flush.value = 0
    await RisingEdge()

class AwaitableWrapper[T: Awaitable]:
    inner: T
    
    def __init__(self):
        self.inner = self.build_inner()
    
    def build_inner(self) -> T:
        raise NotImplementedError
    
    async def do_await(self):
        await self.inner
    
    def __await__(self):
        yield from self.do_await().__await__()

class RisingEdges(AwaitableWrapper[triggers.RisingEdge]):
    count: int
    
    @override
    def __init__(self, count: int):
        self.count = count
        super().__init__()
        
    @override
    def build_inner(self) -> triggers.RisingEdge:
        return triggers.RisingEdge(top.clk)

    @override
    async def do_await(self):
        for _ in range(self.count):
            await self.inner

class RisingEdge(AwaitableWrapper[RisingEdges]):
    @override
    def build_inner(self) -> RisingEdges:
        return RisingEdges(1)

class SimulationUpdate(AwaitableWrapper[Timer]):
    @override
    def build_inner(self) -> Timer:
        return Timer(Decimal(1))