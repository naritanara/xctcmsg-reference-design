from typing import AsyncGenerator, ContextManager

import cocotb
from cocotb.handle import SimHandleBase

from cocotb_utils import AbstractTB, QueueState, ValRdyConsumer, ValRdyInterface, ValRdyProducer, flush, RisingEdges
from xctcmsg_pkg import InterfaceSendData, Message, SendQueueData, WritebackArbiterData


class PostofficeTB(AbstractTB):
    send_queue: ValRdyProducer[SendQueueData]
    writeback_arbiter: ValRdyConsumer[WritebackArbiterData]
    loopback_interceptor: ValRdyConsumer[InterfaceSendData]
    
    def __init__(self, dut: SimHandleBase):
        send_queue_interface = ValRdyInterface(
            val=dut.send_queue_postoffice_valid,
            rdy=dut.postoffice_send_queue_ready,
            data=dut.send_queue_postoffice_data,
            producer_name = "Send Queue",
        )
        writeback_arbiter_interface = ValRdyInterface(
            val=dut.postoffice_writeback_arbiter_valid,
            rdy=dut.writeback_arbiter_postoffice_acknowledge,
            data=dut.postoffice_writeback_arbiter_data,
            rdy_is_ack=True,
            consumer_name = "Writeback Arbiter",
        )
        loopback_interceptor_interface = ValRdyInterface(
            val=dut.postoffice_loopback_valid,
            rdy=dut.loopback_postoffice_ready,
            data=dut.postoffice_loopback_data,
            consumer_name = "Loopback Interceptor",
        )
        
        tasks = dict(
            send_queue=ValRdyProducer(send_queue_interface, SendQueueData),
            writeback_arbiter=ValRdyConsumer(writeback_arbiter_interface, WritebackArbiterData),
            loopback_interceptor=ValRdyConsumer(loopback_interceptor_interface, InterfaceSendData),
        )
        
        super().__init__(dut, tasks)
        
        dut.csu_postoffice_grant.value = 1 # TODO: Implement a driver
    
    def no_writebacks(self) -> ContextManager:
        return self.writeback_arbiter.disabled()
    
    @property
    def writeback_queue_state(self):
        return self.writeback_arbiter.queue_state
    
    @property
    def loopback_queue_state(self):
        return self.loopback_interceptor.queue_state
    
    async def request(self, *data: SendQueueData):
        await self.send_queue.enqueue_values(*data)
    
    async def get_writeback(self) -> WritebackArbiterData:
        return await self.writeback_arbiter.dequeue_value()
    
    def get_writebacks(self, n: int=-1) -> AsyncGenerator[WritebackArbiterData]:
        return self.writeback_arbiter.dequeue_values(n)
    
    async def get_sent_message(self) -> Message:
        interface_send_data = await self.loopback_interceptor.dequeue_value()
        return interface_send_data.message
    
    async def get_sent_messages(self, n: int=-1) -> AsyncGenerator[Message]:
        async for interface_send_data in self.loopback_interceptor.dequeue_values(n):
            yield interface_send_data.message


@cocotb.test
async def reset_state(dut):
    async with PostofficeTB(dut):
        assert dut.postoffice_loopback_valid.value == 0
        assert dut.postoffice_writeback_arbiter_valid.value == 0

@cocotb.test
async def flush_test(dut):
    request = SendQueueData.quick(0, 0, 0, 1)
    expected_sent_message = Message.quick(0, 0, 0)
    
    async with PostofficeTB(dut) as tb:
        with tb.no_writebacks():
            await tb.request(request)
            
            await RisingEdges(20)
            
            assert dut.writeback_valid.value == 1
            
            await flush()
            
            assert dut.writeback_valid.value == 0
        
        await RisingEdges(20)
        
        assert tb.writeback_queue_state == QueueState.EMPTY
        
        sent_message = await tb.get_sent_message()
        assert sent_message == expected_sent_message
        
@cocotb.test
async def writeback_storage(dut):
    requests = [
        SendQueueData.quick(10, 42, 5, 1),
        SendQueueData.quick(20, 24, 6, 2), # This one will be blocked
    ]
    expected_writebacks = [
        WritebackArbiterData.quick(1, 1),
        WritebackArbiterData.quick(2, 1)
    ]
    expected_sent_messages = [
        Message.quick(10, 42, 5),
        Message.quick(20, 24, 6)
    ]

    async with PostofficeTB(dut) as tb:
        with tb.no_writebacks():
            await tb.request(*requests)
    
            await RisingEdges(20)
    
            assert dut.writeback_valid.value == 1

        writeback = await tb.get_writeback()
        assert writeback == expected_writebacks[0]

        await RisingEdges(20)

        writeback = await tb.get_writeback()
        assert writeback == expected_writebacks[1]
        
        sent_messages = [x async for x in tb.get_sent_messages(2)]
        assert sent_messages == expected_sent_messages

@cocotb.test
async def send_single(dut):
    requests = SendQueueData.quick(10, 42, 5, 1)
    expected_writeback = WritebackArbiterData.quick(1, 1)
    expected_sent_message = Message.quick(10, 42, 5)
    
    async with PostofficeTB(dut) as tb:
        await tb.request(requests)

        writeback = await tb.get_writeback()
        assert writeback == expected_writeback

        sent_message = await tb.get_sent_message()
        assert sent_message == expected_sent_message

@cocotb.test
async def send_stream(dut):
    STREAM_LENGTH = 64
    requests = [SendQueueData.quick(10, 42, x, 1) for x in range(STREAM_LENGTH)]
    expected_writeback = WritebackArbiterData.quick(1, 1)
    expected_sent_messages = [Message.quick(10, 42, x) for x in range(STREAM_LENGTH)]
    
    async with PostofficeTB(dut) as tb:
        await tb.request(*requests)
        
        writebacks = [x async for x in tb.get_writebacks(STREAM_LENGTH)]
        sent_messages = [x async for x in tb.get_sent_messages(STREAM_LENGTH)]

        assert writebacks == [expected_writeback] * STREAM_LENGTH
        assert sent_messages == expected_sent_messages

@cocotb.test
async def send_invalid(dut):
    request = SendQueueData.quick(65, 42, 5, 1)
    expected_writeback = WritebackArbiterData.quick(1, 0)
    
    async with PostofficeTB(dut) as tb:
        await tb.request(request)

        writeback = await tb.get_writeback()
        assert writeback == expected_writeback

        await RisingEdges(20)

        assert tb.loopback_queue_state == QueueState.EMPTY
