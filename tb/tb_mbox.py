from typing import Tuple
import cocotb
from cocotb.handle import SimHandleBase
from cocotb.clock import Clock
from cocotb.queue import Queue
from cocotb.regression import Iterable

from cocotb_utils import RisingEdgesHoldingAssertion, SimulationUpdate, reset, flush, RisingEdge, RisingEdges
from xctcmsg_pkg import InterfaceReceiveData, ReceiveQueueData, Message, WritebackArbiterData

MESSAGE_BUFFER_SIZE = 4

class CommunicationInterfaceEmulator:
    dut: SimHandleBase
    receive_queue: Queue[InterfaceReceiveData]

    def __init__(self, dut: SimHandleBase):
        self.dut = dut
        self.receive_queue = Queue()

    async def receive(self, *items: Message | InterfaceReceiveData):
        for item in items:
            if isinstance(item, Message):
                item = InterfaceReceiveData(item)
            await self.receive_queue.put(item)

    async def start(self):
        while True:
            await RisingEdge()
            await SimulationUpdate()

            self.dut.loopback_mailbox_valid.value = 0

            if (self.dut.mailbox_loopback_ready.value == 0):
                continue

            if (not self.receive_queue.empty()):
                data = self.receive_queue.get_nowait()
                self.dut.loopback_mailbox_valid.value = 1
                data.write_to_signal(self.dut.loopback_mailbox_data)
                self.dut._log.info(f"Received: {data}")

class PipelineEmulator:
    dut: SimHandleBase
    request_queue: Queue[ReceiveQueueData]
    allow_writeback = True
    writeback_queue: Queue[WritebackArbiterData]

    def __init__(self, dut: SimHandleBase):
        self.dut = dut
        self.request_queue = Queue()
        self.writeback_queue = Queue()

    async def request(self, *items: ReceiveQueueData):
        for item in items:
            await self.request_queue.put(item)

    async def get_writeback(self) -> WritebackArbiterData:
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
                        data = WritebackArbiterData.from_signal(self.dut.mailbox_writeback_arbiter_data)
                        self.writeback_queue.put_nowait(data)
                        self.dut._log.info(f"Writeback sent: {data}")

            await SimulationUpdate()

            self.dut.receive_queue_mailbox_valid.value = 0

            if (self.dut.mailbox_receive_queue_ready.value == 1):
                if (not self.request_queue.empty()):
                    data = self.request_queue.get_nowait()
                    self.dut.receive_queue_mailbox_valid.value = 1
                    data.write_to_signal(self.dut.receive_queue_mailbox_data)
                    self.dut._log.info(f"Received request: {data}")

async def finish_test(dut: SimHandleBase, communication_interface: CommunicationInterfaceEmulator, pipeline: PipelineEmulator):
    dut._log.info(f"Cleaning up")

    dut.receive_queue_mailbox_valid.value = 0
    dut.loopback_mailbox_valid.value = 0
    dut.writeback_arbiter_mailbox_acknowledge.value = 0
    await SimulationUpdate()

    while not communication_interface.receive_queue.empty():
        communication_interface.receive_queue.get_nowait()

    while not pipeline.request_queue.empty():
        pipeline.request_queue.get_nowait()

async def setup(dut: SimHandleBase) -> Tuple[CommunicationInterfaceEmulator, PipelineEmulator]:
    communication_interface = CommunicationInterfaceEmulator(dut)
    pipeline = PipelineEmulator(dut)
    dut.csu_mailbox_grant.value = 1

    await cocotb.start(Clock(dut.clk, 10, 'ns').start())
    await reset()

    await cocotb.start(communication_interface.start())
    await cocotb.start(pipeline.start())

    return (communication_interface, pipeline)

@cocotb.test
async def reset_state(dut):
    await setup(dut)
    await RisingEdges(2)

    assert dut.message_valid.value == 0
    assert dut.request_valid.value == 0

@cocotb.test
async def flush_test(dut):
    communication_interface, pipeline = await setup(dut)
    try:
        await communication_interface.receive(*([Message.quick(0, 0, 0)] * MESSAGE_BUFFER_SIZE))
        await pipeline.request(ReceiveQueueData.quick(10, 1, -1, -1, 1, False)) # Should stall

        await RisingEdges(2 + MESSAGE_BUFFER_SIZE)

        assert dut.request_valid.value == 1
        assert dut.message_valid.value.binstr == '1' * MESSAGE_BUFFER_SIZE

        await flush()

        assert dut.request_valid.value == 0
        assert dut.message_valid.value.binstr == '1' * MESSAGE_BUFFER_SIZE

        assert dut.mailbox_receive_queue_ready == '1'
    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def message_storage(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        pipeline.allow_writeback = False

        messages = [
            Message.quick(1, 2, 3),
            Message.quick(10, 20, 30),
            Message.quick(0, 0, 0),
            Message.quick(42, 42, 42),
            Message.quick(13, 13, 13), # This one will be blocked
        ]

        assert len(messages) == MESSAGE_BUFFER_SIZE + 1, "there should be just enough messages to overflow the buffers"

        await communication_interface.receive(*messages)
        
        await RisingEdges(20)

        for i, (message, buffered_message) in enumerate(zip(messages[:-1], Message.from_array_signal(dut.message_data))):
            assert dut.message_valid.value[i] == 1
            assert buffered_message == message

        assert dut.mailbox_loopback_ready.value == 0
        assert not communication_interface.receive_queue.empty()
    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def request_storage(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        pipeline.allow_writeback = False
        
        requests = [
            ReceiveQueueData.quick(10, 42, 1, 2, 4, True),
            ReceiveQueueData.quick(42, 10, 4, 3, 1, False), # This one will be blocked
        ]
        
        await pipeline.request(*requests)

        await RisingEdges(20)

        assert dut.request_valid.value == 1
        buffered_request_data = ReceiveQueueData.from_signal(dut.request_data)
        assert buffered_request_data == requests[0]

        assert dut.mailbox_receive_queue_ready.value == 0

    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def full_match_single(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        message = Message.quick(10, 42, 5)
        requests = [
            ReceiveQueueData.quick(10, 42, -1, -1, 1, True),
            ReceiveQueueData.quick(10, 42, -1, -1, 2, False),
            ReceiveQueueData.quick(10, 42, -1, -1, 3, True),
        ]
        expected_writebacks = [
            WritebackArbiterData.quick(1, 1),
            WritebackArbiterData.quick(2, 5),
            WritebackArbiterData.quick(3, 0),
        ]
        
        await communication_interface.receive(message)
        await RisingEdges(2)
        await pipeline.request(*requests)

        for expected_writeback in expected_writebacks:
            writeback = await pipeline.get_writeback()
            assert writeback == expected_writeback

    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def full_match_stream(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        STREAM_LENGTH = 64
        messages = [Message.quick(10, 42, x) for x in range(STREAM_LENGTH)]
        requests = [ReceiveQueueData.quick(10, 42, -1, -1, 1, False)] * STREAM_LENGTH
        
        await communication_interface.receive(*messages)
        await pipeline.request(*requests)

        received_values = set()
        for _ in range(64):
            writeback = await pipeline.get_writeback()
            assert writeback.passthrough.rd.integer == 1
            assert writeback.value.integer not in received_values

            received_values.add(writeback.value.integer)

        assert received_values == set(range(64))

    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def partial_match_single(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        message = Message.quick(0b111, 0b1010, 42)
        requests = [
            ReceiveQueueData.quick(0b101, 0b0000, -1, -1, 1, True),
            ReceiveQueueData.quick(0b101, 0b0000, 0b101, 0b0101, 2, True),
            ReceiveQueueData.quick(0b101, 0b0000, 0b101, 0b0101, 3, False),
            ReceiveQueueData.quick(0b101, 0b0000, 0b101, 0b0101, 4, True),
        ]
        expected_writebacks = [
            WritebackArbiterData.quick(1, 0),
            WritebackArbiterData.quick(2, None), # value >= 1
            WritebackArbiterData.quick(3, 42),
            WritebackArbiterData.quick(4, 0),
        ]
        
        await communication_interface.receive(message)
        await RisingEdges(2)
        await pipeline.request(*requests)

        for expected_writeback in expected_writebacks:
            writeback = await pipeline.get_writeback()
            
            if expected_writeback.value.is_resolvable:
                assert writeback == expected_writeback
            else: # Handle value >= 1 (marked with value == None)
                assert writeback.passthrough.rd == expected_writeback.passthrough.rd
                assert writeback.value.integer >= 1

    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def partial_match_stream(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        STREAM_LENGTH = 64
        messages = [Message.quick(-1, -1, x) for x in range(STREAM_LENGTH)]
        requests = [ReceiveQueueData.quick(0, 0, 0, 0, 1, False)] * STREAM_LENGTH
        
        await communication_interface.receive(*messages)
        await pipeline.request(*requests)

        received_values = set()
        for _ in range(64):
            writeback = await pipeline.get_writeback()
            assert writeback.passthrough.rd.integer == 1
            assert writeback.value.integer not in received_values

            received_values.add(writeback.value.integer)

        assert received_values == set(range(64))

    finally:
        await finish_test(dut, communication_interface, pipeline)

@cocotb.test
async def stall_until_receive(dut):
    [communication_interface, pipeline] = await setup(dut)
    try:
        message = Message.quick(0, 0, 42)
        request = ReceiveQueueData.quick(0, 0, 0, 0, 1, False)
        expected_writeback = WritebackArbiterData.quick(1, 42)
        
        await pipeline.request(request)

        await RisingEdgesHoldingAssertion(64, lambda: dut.mailbox_writeback_arbiter_valid.value == 0)

        await communication_interface.receive(message)
        writeback = await pipeline.get_writeback()
        assert writeback == expected_writeback

    finally:
        await finish_test(dut, communication_interface, pipeline)
