import cocotb
from cocotb.handle import SimHandleBase
from cocotb.clock import Clock
from cocotb.queue import Queue

from cocotb_utils import SimulationUpdate, reset, flush, RisingEdge, RisingEdges

class CommunicationInterfaceEmulator:
    dut: SimHandleBase
    receive_queue: Queue

    def __init__(self, dut):
        self.dut = dut
        self.receive_queue = Queue()

    async def receive(self, source, tag, message):
        await self.receive_queue.put([source, tag, message])

    async def start(self):
        while True:
            await RisingEdge()
            await SimulationUpdate()

            self.dut.loopback_mailbox_valid.value = 0

            if (self.dut.mailbox_loopback_ready.value == 0):
                continue

            if (not self.receive_queue.empty()):
                [source, tag, message] = self.receive_queue.get_nowait()
                self.dut.loopback_mailbox_valid.value = 1
                self.dut.loopback_mailbox_data.message.meta.address.value = source
                self.dut.loopback_mailbox_data.message.meta.tag.value = tag
                self.dut.loopback_mailbox_data.message.data.value = message
                self.dut._log.info(f"Received: [{source=}, {tag=}, {message=}]")

class PipelineEmulator:
    dut: SimHandleBase
    request_queue: Queue
    allow_writeback = True
    writeback_queue: Queue

    def __init__(self, dut):
        self.dut = dut
        self.request_queue = Queue()
        self.writeback_queue = Queue()

    async def request(self, source, tag, source_mask, tag_mask, register, is_avail):
        await self.request_queue.put([source, tag, source_mask, tag_mask, register, is_avail])

    async def get_writeback(self):
        return await self.writeback_queue.get()

    async def start(self):
        while True:
            await RisingEdge()
            await SimulationUpdate()

            if (self.allow_writeback):
                self.dut.writeback_arbiter_mailbox_acknowledge.value = 0

                if (self.dut.mailbox_writeback_arbiter_valid.value == 1):
                    if (not self.writeback_queue.full()):
                        self.dut.writeback_arbiter_mailbox_acknowledge.value = 1
                        register = int(self.dut.mailbox_writeback_arbiter_data.register.value)
                        value = int(self.dut.mailbox_writeback_arbiter_data.value.value)
                        self.writeback_queue.put_nowait([register, value])
                        self.dut._log.info(f"Writeback sent: [{register=}, {value=}]")

            await SimulationUpdate()

            self.dut.receive_queue_mailbox_valid.value = 0

            if (self.dut.mailbox_receive_queue_ready.value == 1):
                if (not self.request_queue.empty()):
                    [source, tag, source_mask, tag_mask, register, is_avail] = self.request_queue.get_nowait()
                    self.dut.receive_queue_mailbox_valid.value = 1
                    self.dut.receive_queue_mailbox_data.meta.address.value = source
                    self.dut.receive_queue_mailbox_data.meta.tag.value = tag
                    self.dut.receive_queue_mailbox_data.meta_mask.address.value = source_mask
                    self.dut.receive_queue_mailbox_data.meta_mask.tag.value = tag_mask
                    self.dut.receive_queue_mailbox_data.register.value = register
                    self.dut.receive_queue_mailbox_data.is_avail.value = is_avail
                    self.dut._log.info(f"Received request: [{source=}, {tag=}, {source_mask=}, {tag_mask=}, {register=}, {is_avail=}]")

async def finish_test(dut, communication_interface, pipeline):
    dut._log.info(f"Cleaning up")

    dut.receive_queue_mailbox_valid.value = 0
    dut.loopback_mailbox_valid.value = 0
    dut.writeback_arbiter_mailbox_acknowledge.value = 0
    await SimulationUpdate()

    while not communication_interface.receive_queue.empty():
        communication_interface.receive_queue.get_nowait()

    while not pipeline.request_queue.empty():
        pipeline.request_queue.get_nowait()

async def setup(dut):
    communication_interface = CommunicationInterfaceEmulator(dut)
    pipeline = PipelineEmulator(dut)
    dut.csu_mailbox_grant.value = 1

    await cocotb.start(Clock(dut.clk, 10, 'ns').start())
    await reset()

    await cocotb.start(communication_interface.start())
    await cocotb.start(pipeline.start())

    return [communication_interface, pipeline]

@cocotb.test
async def reset_state(dut):
    await cocotb.start(Clock(dut.clk, 10, 'ns').start())

    await reset()

    assert dut.message_valid.value == 0
    assert dut.request_valid.value == 0

@cocotb.test
async def flush_test(dut):
    communication_interface, pipeline = await setup(dut)
    try:
        for _ in range(4):
            await communication_interface.receive(0, 0, 0)
        await pipeline.request(10, 1, -1, -1, 1, False) # Should stall
        
        await RisingEdges(6)
        
        assert dut.request_valid.value == 1
        for i in range(4):
            assert dut.message_valid[i].value == 1
        
        await flush()
        
        assert dut.request_valid.value == 0
        for i in range(4):
            assert dut.message_valid[i].value == 0
    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def message_storage(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        pipeline.allow_writeback = False

        await communication_interface.receive(1, 2, 3)
        await communication_interface.receive(10, 20, 30)
        await communication_interface.receive(0, 0, 0)
        await communication_interface.receive(42, 42, 42)
        await communication_interface.receive(13, 13, 13) # This one will be blocked

        for i in range(20):
            await RisingEdge()

        assert dut.message_valid[0].value == 1
        assert dut.message_data[0].meta.address.value == 1
        assert dut.message_data[0].meta.tag.value == 2
        assert dut.message_data[0].data.value == 3

        assert dut.message_valid[1].value == 1
        assert dut.message_data[1].meta.address.value == 10
        assert dut.message_data[1].meta.tag.value == 20
        assert dut.message_data[1].data.value == 30

        assert dut.message_valid[2].value == 1
        assert dut.message_data[2].meta.address.value == 0
        assert dut.message_data[2].meta.tag.value == 0
        assert dut.message_data[2].data.value == 0

        assert dut.message_valid[3].value == 1
        assert dut.message_data[3].meta.address.value == 42
        assert dut.message_data[3].meta.tag.value == 42
        assert dut.message_data[3].data.value == 42

        assert dut.mailbox_loopback_ready.value == 0
    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def request_storage(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        pipeline.allow_writeback = False

        await pipeline.request(10, 42, 1, 2, 4, True)
        await pipeline.request(42, 10, 4, 3, 1, False) # This one will be blocked

        for i in range(20):
            await RisingEdge()

        assert dut.request_valid.value == True
        assert dut.request_data.is_avail.value == True
        assert dut.request_data.meta.address.value == 10
        assert dut.request_data.meta.tag.value == 42
        assert dut.request_data.meta_mask.address.value == 1
        assert dut.request_data.meta_mask.tag.value == 2
        assert dut.request_data.register.value == 4

        assert dut.mailbox_receive_queue_ready.value == 0

    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def full_match_single(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        await communication_interface.receive(10, 42, 5)
        await RisingEdges(2)
        await pipeline.request(10, 42, -1, -1, 1, True)
        await pipeline.request(10, 42, -1, -1, 2, False)
        await pipeline.request(10, 42, -1, -1, 3, True)

        [register, value] = await pipeline.get_writeback()
        assert register == 1
        assert value == 1


        [register, value] = await pipeline.get_writeback()
        assert register == 2
        assert value == 5


        [register, value] = await pipeline.get_writeback()
        assert register == 3
        assert value == 0

    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def full_match_stream(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        for i in range(64):
            await communication_interface.receive(10, 42, i)
            await pipeline.request(10, 42, -1, -1, 1, False)

        received_values = set()
        for i in range(64):
            [register, value] = await pipeline.get_writeback()
            assert register == 1
            assert value not in received_values

            received_values.add(value)

        for i in range(64):
            assert i in received_values

    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def partial_match_single(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        await communication_interface.receive(0b111, 0b1010, 42)
        await RisingEdges(2)
        await pipeline.request(0b101, 0b0000, -1, -1, 1, True)
        await pipeline.request(0b101, 0b0000, 0b101, 0b0101, 1, True)
        await pipeline.request(0b101, 0b0000, 0b101, 0b0101, 2, False)
        await pipeline.request(0b101, 0b0000, 0b101, 0b0101, 3, True)

        [register, value] = await pipeline.get_writeback()
        assert register == 1
        assert value == 0

        [register, value] = await pipeline.get_writeback()
        assert register == 1
        assert value >= 1

        [register, value] = await pipeline.get_writeback()
        assert register == 2
        assert value == 42

        [register, value] = await pipeline.get_writeback()
        assert register == 3
        assert value == 0

    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def partial_match_stream(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        for i in range(64):
            await communication_interface.receive(-1, -1, i)
            await pipeline.request(0, 0, 0, 0, 1, False)

        received_values = set()
        for i in range(64):
            [register, value] = await pipeline.get_writeback()
            assert register == 1
            assert value not in received_values

            received_values.add(value)

        for i in range(64):
            assert i in received_values

    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def stall_until_receive(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        await pipeline.request(0, 0, 0, 0, 1, False)

        for i in range(64):
            await RisingEdge()
            assert dut.mailbox_writeback_arbiter_valid.value == 0

        await communication_interface.receive(0, 0, 42)
        [register, value] = await pipeline.get_writeback()

        assert register == 1
        assert value == 42

    finally:
        await finish_test(dut, communication_interface, pipeline)
