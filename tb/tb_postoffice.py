import cocotb
from cocotb.handle import SimHandleBase
from cocotb.clock import Clock
from cocotb.queue import Queue

from cocotb_utils import reset, flush, RisingEdges, RisingEdge, SimulationUpdate

class SendQueueEmulator:
    dut: SimHandleBase
    send_queue: Queue

    def __init__(self, dut):
        self.dut = dut
        self.send_queue = Queue()

    async def request(self, destination, tag, message, register):
        await self.send_queue.put([destination, tag, message, register])

    async def start(self):
        while True:
            await RisingEdge()
            await SimulationUpdate()

            self.dut.send_queue_postoffice_valid.value = 0

            if (self.dut.postoffice_send_queue_ready.value == 0):
                continue

            if (not self.send_queue.empty()):
                [destination, tag, message, register] = self.send_queue.get_nowait()
                self.dut.send_queue_postoffice_valid.value = 1
                self.dut.send_queue_postoffice_data.message.meta.address.value = destination
                self.dut.send_queue_postoffice_data.message.meta.tag.value = tag
                self.dut.send_queue_postoffice_data.message.data.value = message
                self.dut.send_queue_postoffice_data.register.value = register
                self.dut._log.info(f"Request in: [{destination=}, {tag=}, {message=}, {register=}]")

class WritebackArbiterEmulator:
    dut: SimHandleBase
    allow_writeback = True
    writeback_queue: Queue

    def __init__(self, dut):
        self.dut = dut
        self.writeback_queue = Queue()

    async def get_writeback(self):
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
                register = int(self.dut.postoffice_writeback_arbiter_data.register.value)
                value = int(self.dut.postoffice_writeback_arbiter_data.value.value)
                self.writeback_queue.put_nowait([register, value])
                self.dut._log.info(f"Writeback sent: [{register=}, {value=}]")

class CommunicationInterfaceEmulator:
    dut: SimHandleBase
    allow_receive = True
    receive_queue: Queue

    def __init__(self, dut):
        self.dut = dut
        self.receive_queue = Queue()

    async def receive(self):
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
                destination = int(self.dut.postoffice_loopback_data.message.meta.address)
                tag = int(self.dut.postoffice_loopback_data.message.meta.tag)
                message = int(self.dut.postoffice_loopback_data.message.data)
                self.receive_queue.put_nowait([destination, tag, message])
                self.dut._log.info(f"Sent: [{destination=}, {tag=}, {message=}]")

async def setup(dut):
    send_queue = SendQueueEmulator(dut)
    writeback_arbiter = WritebackArbiterEmulator(dut)
    communication_interface = CommunicationInterfaceEmulator(dut)
    dut.csu_postoffice_grant.value = 1

    await cocotb.start(Clock(dut.clk, 10, 'ns').start())
    await reset()

    await cocotb.start(send_queue.start())
    await cocotb.start(writeback_arbiter.start())
    await cocotb.start(communication_interface.start())

    return [send_queue, writeback_arbiter, communication_interface]

async def finish_test(dut, send_queue, writeback_arbiter, communication_interface):
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
        await send_queue.request(0, 0, 0, 1)
        
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

        await send_queue.request(10, 42, 5, 1)
        await send_queue.request(20, 24, 6, 2) # This one will be blocked

        await RisingEdges(20)

        assert int(dut.writeback_valid.value) == 1
        assert int(dut.writeback_data.register.value) == 1
        assert int(dut.writeback_data.value.value) == 1

        assert int(dut.postoffice_send_queue_ready.value == 0)
    finally:
        await finish_test(dut, send_queue, writeback_arbiter, communication_interface)

@cocotb.test
async def send_single(dut):
    [send_queue, writeback_arbiter, communication_interface] = await setup(dut)
    try:
        await send_queue.request(10, 42, 5, 1)

        [register, value] = await writeback_arbiter.get_writeback()
        assert register == 1
        assert value == 1

        [destination, tag, message] = await communication_interface.receive()
        assert destination == 10
        assert tag == 42
        assert message == 5
    finally:
        await finish_test(dut, send_queue, writeback_arbiter, communication_interface)

@cocotb.test
async def send_stream(dut):
    [send_queue, writeback_arbiter, communication_interface] = await setup(dut)
    try:
        for i in range(64):
            await send_queue.request(10, 42, i, 1)

        for i in range(64):
            [register, value] = await writeback_arbiter.get_writeback()
            assert register == 1
            assert value == 1

            [destination, tag, message] = await communication_interface.receive()
            assert destination == 10
            assert tag == 42
            assert message == i
    finally:
        await finish_test(dut, send_queue, writeback_arbiter, communication_interface)

@cocotb.test
async def send_invalid(dut):
    [send_queue, writeback_arbiter, communication_interface] = await setup(dut)
    try:
        await send_queue.request(65, 42, 5, 1)

        [register, value] = await writeback_arbiter.get_writeback()
        assert register == 1
        assert value == 0

        await RisingEdges(20)

        assert communication_interface.receive_queue.empty()
    finally:
        await finish_test(dut, send_queue, writeback_arbiter, communication_interface)
