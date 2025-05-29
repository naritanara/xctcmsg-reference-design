from typing import AsyncGenerator, ContextManager
import cocotb
from cocotb.handle import SimHandleBase

from cocotb_utils import AbstractTB, QueueState, RisingEdge, RisingEdgesHoldingAssertion, ValRdyConsumer, ValRdyInterface, ValRdyProducer, flush, RisingEdges
from xctcmsg_pkg import InterfaceReceiveData, ReceiveQueueData, Message, WritebackArbiterData

MESSAGE_BUFFER_SIZE = 4

class MBoxTB(AbstractTB):
    receive_queue: ValRdyProducer[ReceiveQueueData]
    writeback_arbiter: ValRdyConsumer[WritebackArbiterData]
    loopback_interceptor: ValRdyProducer[InterfaceReceiveData]
    
    def __init__(self, dut: SimHandleBase):
        receive_queue_interface = ValRdyInterface(
            val=dut.receive_queue_mailbox_valid,
            rdy=dut.mailbox_receive_queue_ready,
            data=dut.receive_queue_mailbox_data,
            producer_name = "Receive Queue",
        )
        writeback_arbiter_interface = ValRdyInterface(
            val=dut.mailbox_writeback_arbiter_valid,
            rdy=dut.writeback_arbiter_mailbox_acknowledge,
            data=dut.mailbox_writeback_arbiter_data,
            rdy_is_ack=True,
            consumer_name = "Writeback Arbiter",
        )
        loopback_interceptor_interface = ValRdyInterface(
            val=dut.loopback_mailbox_valid,
            rdy=dut.mailbox_loopback_ready,
            data=dut.loopback_mailbox_data,
            producer_name = "Loopback Interceptor",
        )
        
        tasks = dict(
            receive_queue=ValRdyProducer(receive_queue_interface, ReceiveQueueData),
            writeback_arbiter=ValRdyConsumer(writeback_arbiter_interface, WritebackArbiterData),
            loopback_interceptor=ValRdyProducer(loopback_interceptor_interface, InterfaceReceiveData),
        )
        
        super().__init__(dut, tasks)
        
        dut.csu_mailbox_grant.value = 1 # TODO: Implement a driver

    def no_writebacks(self) -> ContextManager:
        return self.writeback_arbiter.disabled()

    @property
    def receive_queue_state(self):
        return self.loopback_interceptor.queue_state

    async def request(self, *items: ReceiveQueueData):
        await self.receive_queue.enqueue_values(*items)

    async def get_writeback(self) -> WritebackArbiterData:
        return await self.writeback_arbiter.dequeue_value()
    
    def get_writebacks(self, n: int=-1) -> AsyncGenerator[WritebackArbiterData]:
        return self.writeback_arbiter.dequeue_values(n)
        
    async def receive(self, *items: Message):
        await self.loopback_interceptor.enqueue_values(*map(InterfaceReceiveData, items))

@cocotb.test
async def reset_state(dut):
    async with MBoxTB(dut) as tb:
        assert tb.dut.message_valid.value == 0
        assert tb.dut.request_valid.value == 0

@cocotb.test
async def flush_test(dut):
    messages = [Message.quick(0, 0, 0)] * MESSAGE_BUFFER_SIZE
    request = ReceiveQueueData.quick(10, 1, -1, -1, 1, False)
    
    async with MBoxTB(dut) as tb:
        await tb.receive(*messages)
        await tb.request(request) # Should stall

        await RisingEdges(2 + MESSAGE_BUFFER_SIZE)

        assert tb.dut.request_valid.value == 1
        assert tb.dut.message_valid.value.binstr == '1' * MESSAGE_BUFFER_SIZE

        await flush()

        assert tb.dut.request_valid.value == 0
        assert tb.dut.message_valid.value.binstr == '1' * MESSAGE_BUFFER_SIZE

        assert tb.dut.mailbox_receive_queue_ready == '1'

@cocotb.test
async def message_storage(dut):
    messages = [
        Message.quick(1, 2, 3),
        Message.quick(10, 20, 30),
        Message.quick(0, 0, 0),
        Message.quick(42, 42, 42),
        Message.quick(13, 13, 13), # This one will be blocked
    ]
    
    assert len(messages) == MESSAGE_BUFFER_SIZE + 1, "there should be just enough messages to overflow the buffers"
    
    async with MBoxTB(dut) as tb:
        with tb.no_writebacks():
            await tb.receive(*messages)
            
            await RisingEdges(20)
    
            buffered_messages = list(Message.from_array_signal(tb.dut.message_data))
            
            assert tb.dut.message_valid.value.binstr == '1' * MESSAGE_BUFFER_SIZE
            assert buffered_messages == messages[:-1]
    
            assert tb.dut.mailbox_loopback_ready.value == 0
            assert tb.receive_queue_state != QueueState.EMPTY
            
            # Invalidate every message to absorb the stalled one
            tb.dut.message_valid.value = 0
            await RisingEdge()

@cocotb.test
async def request_storage(dut):
    requests = [
        ReceiveQueueData.quick(10, 42, 1, 2, 4, True),
        ReceiveQueueData.quick(42, 10, 4, 3, 1, False), # This one will be blocked
    ]
    
    async with MBoxTB(dut) as tb:
        with tb.no_writebacks():
            await tb.request(*requests)
    
            await RisingEdges(20)
    
            assert tb.dut.request_valid.value == 1
            buffered_request_data = ReceiveQueueData.from_signal(tb.dut.request_data)
            assert buffered_request_data == requests[0]
    
            assert tb.dut.mailbox_receive_queue_ready.value == 0
            
            # Invalidate the request to absorb the stalled one
            tb.dut.request_valid.value = 0
            await RisingEdges(2)

@cocotb.test
async def full_match_single(dut):
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
    
    async with MBoxTB(dut) as tb:
        await tb.receive(message)
        await RisingEdges(2)
        await tb.request(*requests)
        
        writebacks = [x async for x in tb.get_writebacks(len(expected_writebacks))]
        assert writebacks == expected_writebacks

@cocotb.test
async def full_match_stream(dut):
    STREAM_LENGTH = 64
    messages = [Message.quick(10, 42, x) for x in range(STREAM_LENGTH)]
    requests = [ReceiveQueueData.quick(10, 42, -1, -1, 1, False)] * STREAM_LENGTH
    expected_writebacks = [WritebackArbiterData.quick(1, x) for x in range(STREAM_LENGTH)]
    
    async with MBoxTB(dut) as tb:
        await tb.receive(*messages)
        await tb.request(*requests)

        writebacks = [x async for x in tb.get_writebacks(STREAM_LENGTH)]
        assert writebacks == expected_writebacks

@cocotb.test
async def partial_match_single(dut):
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
    
    async with MBoxTB(dut) as tb:
        await tb.receive(message)
        await RisingEdges(2)
        await tb.request(*requests)

        # TODO: Custom __eq__?
        for expected_writeback in expected_writebacks:
            writeback = await tb.get_writeback()
            
            if expected_writeback.value.is_resolvable:
                assert writeback == expected_writeback
            else: # Handle value >= 1 (marked with value == None)
                assert writeback.passthrough.rd == expected_writeback.passthrough.rd
                assert writeback.value.integer >= 1

@cocotb.test
async def partial_match_stream(dut):
    STREAM_LENGTH = 64
    messages = [Message.quick(-1, -1, x) for x in range(STREAM_LENGTH)]
    requests = [ReceiveQueueData.quick(0, 0, 0, 0, 1, False)] * STREAM_LENGTH
    expected_writebacks = [WritebackArbiterData.quick(1, x) for x in range(STREAM_LENGTH)]

    async with MBoxTB(dut) as tb:
        await tb.receive(*messages)
        await tb.request(*requests)

        writebacks = [x async for x in tb.get_writebacks(STREAM_LENGTH)]
        
        assert writebacks == expected_writebacks

@cocotb.test
async def stall_until_receive(dut):
    message = Message.quick(0, 0, 42)
    request = ReceiveQueueData.quick(0, 0, 0, 0, 1, False)
    expected_writeback = WritebackArbiterData.quick(1, 42)
    
    async with MBoxTB(dut) as tb:
        await tb.request(request)

        await RisingEdgesHoldingAssertion(64, lambda: dut.mailbox_writeback_arbiter_valid.value == 0)

        await tb.receive(message)
        writeback = await tb.get_writeback()
        assert writeback == expected_writeback
