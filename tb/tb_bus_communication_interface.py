import cocotb
from cocotb.clock import Clock
from cocotb.queue import Queue
from cocotb.handle import SimHandleBase

from cocotb_utils import reset, flush, RisingEdge, RisingEdges, SimulationUpdate

class SingleBusEmulator:
    dut: SimHandleBase

    def __init__(self, dut):
        self.dut = dut

    async def start(self):
        while True:
            await SimulationUpdate()
            self.dut.bus_val_i.value = self.dut.bus_val_o.value and int(self.dut.bus_dst_o.value) == 0
            self.dut.bus_ack_i.value = self.dut.bus_val_i.value and self.dut.bus_rdy_o.value
            self.dut.bus_src_i.value = 0
            self.dut.bus_tag_i.value = self.dut.bus_tag_o.value
            self.dut.bus_msg_i.value = self.dut.bus_msg_o.value

class InterfaceController:
    dut: SimHandleBase
    send_queue: Queue
    recv_queue: Queue

    def __init__(self, dut):
        self.dut = dut
        self.send_queue = Queue()
        self.recv_queue = Queue()

    async def send(self, destination, tag, message):
        await self.send_queue.put([destination, tag, message])

    async def receive(self):
        return await self.recv_queue.get()

    async def start(self):
        self.dut.loopback_interface_valid.value = 0
        while True:
            await RisingEdge()

            if self.dut.loopback_interface_valid.value == 1:
                self.dut.loopback_interface_valid.value = not self.dut.interface_loopback_ready.value

            if self.dut.loopback_interface_valid.value == 0 and not self.send_queue.empty():
                [destination, tag, message] = self.send_queue.get_nowait()
                self.dut.loopback_interface_valid.value = 1
                self.dut.loopback_interface_data.message.meta.address.value = destination
                self.dut.loopback_interface_data.message.meta.tag.value = tag
                self.dut.loopback_interface_data.message.data.value = message
                self.dut._log.info(f"Sent: [{destination=}, {tag=}, {message=}]")

            if self.dut.interface_loopback_valid.value and not self.recv_queue.full():
                source = int(self.dut.interface_loopback_data.message.meta.address.value)
                tag = int(self.dut.interface_loopback_data.message.meta.tag.value)
                message = int(self.dut.interface_loopback_data.message.data.value)
                self.recv_queue.put_nowait([source, tag, message])
                self.dut._log.info(f"Received: [{source=}, {tag=}, {message=}]")

            self.dut.loopback_interface_ready.value = not self.recv_queue.full()

async def setup(dut):
    bus = SingleBusEmulator(dut)
    controller = InterfaceController(dut)

    await cocotb.start(Clock(dut.clk, 10, 'ns').start())
    await reset()

    await cocotb.start(bus.start())
    await cocotb.start(controller.start())
    
    return bus, controller

@cocotb.test
async def reset_state(dut):
    await cocotb.start(Clock(dut.clk, 10, 'ns').start())

    await reset()

    assert dut.holding_valid.value == 0
    assert dut.holding_data.message.meta.address.value == 0
    assert dut.holding_data.message.meta.tag.value == 0
    assert dut.holding_data.message.data.value == 0

@cocotb.test
async def flush_test(dut):
    bus, controller = await setup(dut)
    
    controller.recv_queue = Queue(maxsize=1)
    
    await controller.send(0, 0, 0) # Will clog the receive queue
    await controller.send(0, 0, 0) # Will stay in the holding register
    
    await RisingEdges(20)
    assert dut.holding_valid.value == 1
    
    await flush()
    
    assert dut.holding_valid.value == 0 # Should be gone
    await controller.receive() # Free up space in the receive queue
    await RisingEdges(20)
    assert controller.recv_queue.empty() # Should not receive the second element
    

@cocotb.test
async def echo_test(dut):
    bus, controller = await setup(dut)

    await controller.send(0, 42, 55)
    await controller.send(0, 55, 42)
    await controller.send(0, 0, 0)

    [source, tag, message] = await controller.receive()
    assert source == 0
    assert tag == 42
    assert message == 55

    [source, tag, message] = await controller.receive()
    assert source == 0
    assert tag == 55
    assert message == 42

    [source, tag, message] = await controller.receive()
    assert source == 0
    assert tag == 0
    assert message == 0
