import cocotb
from cocotb.clock import Clock
from cocotb.queue import Queue
from cocotb.handle import SimHandleBase

from cocotb_utils import reset, flush, RisingEdge, RisingEdges, SimulationUpdate
from xctcmsg_pkg import InterfaceReceiveData, InterfaceSendData, Message, MessageMetadata, ReceiveQueueData

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
    send_queue: Queue[InterfaceSendData]
    recv_queue: Queue[InterfaceReceiveData]

    def __init__(self, dut):
        self.dut = dut
        self.send_queue = Queue()
        self.recv_queue = Queue()

    async def send(self, send_data: Message | InterfaceSendData):
        if isinstance(send_data, Message):
            send_data = InterfaceSendData(send_data)
        
        await self.send_queue.put(send_data)

    async def receive(self) -> Message:
        return (await self.recv_queue.get()).message

    async def start(self):
        self.dut.loopback_interface_valid.value = 0
        while True:
            await RisingEdge()

            if self.dut.loopback_interface_valid.value == 1:
                self.dut.loopback_interface_valid.value = not self.dut.interface_loopback_ready.value

            if self.dut.loopback_interface_valid.value == 0 and not self.send_queue.empty():
                send_data = self.send_queue.get_nowait()
                self.dut.loopback_interface_valid.value = 1
                send_data.write_to_signal(self.dut.loopback_interface_data)
                self.dut._log.info(f"Sent: {send_data}")

            if self.dut.interface_loopback_valid.value and not self.recv_queue.full():
                receive_data = InterfaceReceiveData.from_signal(self.dut.interface_loopback_data)
                self.recv_queue.put_nowait(receive_data)
                self.dut._log.info(f"Received: {receive_data}")

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

@cocotb.test
async def echo_test(dut):
    bus, controller = await setup(dut)
    
    messages = [
        Message(MessageMetadata(42, 0), 55),
        Message(MessageMetadata(55, 0), 42),
        Message(MessageMetadata(0, 0), 0)
    ]
    
    for message in messages:
        await controller.send(message)

    for message in messages:
        received_message = await controller.receive()
        assert received_message == message
