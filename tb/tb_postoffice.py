from typing import Tuple
import cocotb
from cocotb.handle import SimHandleBase
from cocotb.clock import Clock
from cocotb.queue import Queue

from cocotb_utils import reset, flush, RisingEdges, RisingEdge, SimulationUpdate
from xctcmsg_pkg import InterfaceSendData, Message, MessageMetadata, ReceiveQueueData, SendQueueData, UnitTestPassthrough, WritebackArbiterData

class SendQueueEmulator:
    dut: SimHandleBase
    send_queue: Queue[SendQueueData]

    def __init__(self, dut: SimHandleBase):
        self.dut = dut
        self.send_queue = Queue()

    async def request(self, data: SendQueueData):
        await self.send_queue.put(data)

    async def start(self):
        while True:
            await RisingEdge()
            await SimulationUpdate()

            self.dut.send_queue_postoffice_valid.value = 0

            if (self.dut.postoffice_send_queue_ready.value == 0):
                continue

            if (not self.send_queue.empty()):
                data = self.send_queue.get_nowait()
                self.dut.send_queue_postoffice_valid.value = 1
                data.write_to_signal(self.dut.send_queue_postoffice_data)
                self.dut._log.info(f"Request in: {data}")

class WritebackArbiterEmulator:
    dut: SimHandleBase
    allow_writeback: bool = True
    writeback_queue: Queue[WritebackArbiterData]

    def __init__(self, dut: SimHandleBase):
        self.dut = dut
        self.writeback_queue = Queue()

    async def get_writeback(self) -> WritebackArbiterData:
        return await self.writeback_queue.get()

    async def start(self):
        while True:
            await RisingEdge()
            await SimulationUpdate()

            self.dut.writeback_arbiter_postoffice_acknowledge.value = 0

            if (not self.allow_writeback):
                continue

            if (self.dut.postoffice_writeback_arbiter_valid.value == 1):
                self.dut.writeback_arbiter_postoffice_acknowledge.value = 1
                data = WritebackArbiterData.from_signal(self.dut.postoffice_writeback_arbiter_data)
                self.writeback_queue.put_nowait(data)
                self.dut._log.info(f"Writeback sent: {data}")

class CommunicationInterfaceEmulator:
    dut: SimHandleBase
    allow_receive: bool = True
    receive_queue: Queue[InterfaceSendData]

    def __init__(self, dut: SimHandleBase):
        self.dut = dut
        self.receive_queue = Queue()

    async def receive(self) -> InterfaceSendData:
        return await self.receive_queue.get()

    async def start(self):
        while True:
            await RisingEdge()
            await SimulationUpdate()

            self.dut.loopback_postoffice_ready.value = self.allow_receive

            if (not self.allow_receive):
                continue

            await SimulationUpdate()

            if (self.dut.postoffice_loopback_valid.value == 1):
                data = InterfaceSendData.from_signal(self.dut.postoffice_loopback_data)
                self.receive_queue.put_nowait(data)
                self.dut._log.info(f"Sent: {data}")

async def setup(dut: SimHandleBase) -> Tuple[SendQueueEmulator, WritebackArbiterEmulator, CommunicationInterfaceEmulator]:
    send_queue = SendQueueEmulator(dut)
    writeback_arbiter = WritebackArbiterEmulator(dut)
    communication_interface = CommunicationInterfaceEmulator(dut)
    dut.csu_postoffice_grant.value = 1

    await cocotb.start(Clock(dut.clk, 10, 'ns').start())
    await reset()

    await cocotb.start(send_queue.start())
    await cocotb.start(writeback_arbiter.start())
    await cocotb.start(communication_interface.start())

    return (send_queue, writeback_arbiter, communication_interface)

async def finish_test(dut: SimHandleBase, send_queue: SendQueueEmulator, writeback_arbiter: WritebackArbiterEmulator, communication_interface: CommunicationInterfaceEmulator):
    dut._log.info(f"Cleaning up")

    dut.send_queue_postoffice_valid.value = 0
    dut.loopback_postoffice_ready.value = 0
    dut.writeback_arbiter_postoffice_acknowledge.value = 0
    await SimulationUpdate()

    while not send_queue.send_queue.empty():
        send_queue.send_queue.get_nowait()

    while not writeback_arbiter.writeback_queue.empty():
        writeback_arbiter.writeback_queue.get_nowait()

    while not communication_interface.receive_queue.empty():
        communication_interface.receive_queue.get_nowait()

@cocotb.test
async def reset_state(dut):
    await setup(dut)
    await RisingEdges(2)

    assert int(dut.postoffice_loopback_valid.value) == 0
    assert int(dut.postoffice_writeback_arbiter_valid.value) == 0

@cocotb.test
async def flush_test(dut):
    send_queue, writeback_arbiter, communication_interface = await setup(dut)
    try:
        writeback_arbiter.allow_writeback = False
        await send_queue.request(SendQueueData.quick(0, 0, 0, 1))
        
        await RisingEdges(20)
        
        assert dut.writeback_valid.value == 1
        
        await flush()
        
        assert dut.writeback_valid.value == 0
        
        writeback_arbiter.allow_writeback = True
        
        await RisingEdges(20)
        
        assert writeback_arbiter.writeback_queue.empty()
        
    finally:
        await finish_test(dut, send_queue, writeback_arbiter, communication_interface)

@cocotb.test
async def writeback_storage(dut):
    [send_queue, writeback_arbiter, communication_interface] = await setup(dut)
    try:
        writeback_arbiter.allow_writeback = False

        requests = [
            SendQueueData.quick(10, 42, 5, 1),
            SendQueueData.quick(20, 24, 6, 2), # This one will be blocked
        ]
        
        expected_writeback_data_registers = WritebackArbiterData.quick(1, 1)

        for request in requests:
            await send_queue.request(request)

        await RisingEdges(20)

        assert int(dut.writeback_valid.value) == 1
        writeback_data_registers = WritebackArbiterData.from_signal(dut.writeback_data)
        assert writeback_data_registers == expected_writeback_data_registers

        assert int(dut.postoffice_send_queue_ready.value) == 0
    finally:
        await finish_test(dut, send_queue, writeback_arbiter, communication_interface)

@cocotb.test
async def send_single(dut):
    [send_queue, writeback_arbiter, communication_interface] = await setup(dut)
    try:
        send_queue_data = SendQueueData.quick(10, 42, 5, 1)
        expected_writeback_data = WritebackArbiterData.quick(1, 1)
        expected_interface_send_data = InterfaceSendData.quick(10, 42, 5)
        
        await send_queue.request(send_queue_data)

        writeback_data = await writeback_arbiter.get_writeback()
        assert writeback_data == expected_writeback_data

        interface_send_data = await communication_interface.receive()
        assert interface_send_data == expected_interface_send_data
    finally:
        await finish_test(dut, send_queue, writeback_arbiter, communication_interface)

@cocotb.test
async def send_stream(dut):
    [send_queue, writeback_arbiter, communication_interface] = await setup(dut)
    try:
        requests = [SendQueueData.quick(10, 42, x, 1) for x in range(64)]
        expected_writeback_data = WritebackArbiterData.quick(1, 1)
        expected_interface_send_data = [InterfaceSendData.quick(10, 42, x) for x in range(64)]
        
        for request in requests:
            await send_queue.request(request)

        for i in range(64):
            writeback_data = await writeback_arbiter.get_writeback()
            assert writeback_data == expected_writeback_data
            
            interface_send_data = await communication_interface.receive()
            assert interface_send_data == expected_interface_send_data[i]
    finally:
        await finish_test(dut, send_queue, writeback_arbiter, communication_interface)

@cocotb.test
async def send_invalid(dut):
    [send_queue, writeback_arbiter, communication_interface] = await setup(dut)
    try:
        send_queue_data = SendQueueData.quick(65, 42, 5, 1)
        expected_writeback_data = WritebackArbiterData.quick(1, 0)
        
        await send_queue.request(send_queue_data)

        writeback_data = await writeback_arbiter.get_writeback()
        assert writeback_data == expected_writeback_data

        await RisingEdges(20)

        assert communication_interface.receive_queue.empty()
    finally:
        await finish_test(dut, send_queue, writeback_arbiter, communication_interface)
