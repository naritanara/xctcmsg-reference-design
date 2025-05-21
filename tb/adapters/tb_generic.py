from abc import abstractmethod
from collections.abc import AsyncGenerator
from typing import AsyncIterable, Callable, ContextManager, Iterable, List, override
import random

from cocotb import triggers
from cocotb.handle import SimHandleBase
from cocotb.queue import Queue
from cocotb.regression import TestFactory
from cocotb.triggers import First

from adapters import NetworkInterfaceDriver
from xctcmsg_pkg import InterfaceReceiveData, InterfaceSendData, Message
from cocotb_utils import AbstractTB, AbstractClock, NeedsClock, SVStruct, TBTask, ValRdyConsumer, ValRdyInterface, ValRdyProducer


class AbstractAdapterTB[NID: NetworkInterfaceDriver](AbstractTB):
    send_port: ValRdyProducer[InterfaceSendData]
    recv_port: ValRdyConsumer[InterfaceReceiveData]
    network_interface_driver: NID
    
    def __init__(self, dut: SimHandleBase, network_interface_driver: NID):
        send_port_interface = ValRdyInterface(
            val=dut.loopback_interface_valid,
            rdy=dut.interface_loopback_ready,
            data=dut.loopback_interface_data,
            producer_name="Loopback Interceptor",
        )
        recv_port_interface = ValRdyInterface(
            val=dut.interface_loopback_valid,
            rdy=dut.loopback_interface_ready,
            data=dut.interface_loopback_data,
            consumer_name="Loopback Interceptor",
        )
        
        tasks = dict(
            send_port=ValRdyProducer(send_port_interface, InterfaceSendData),
            recv_port=ValRdyConsumer(recv_port_interface, InterfaceReceiveData),
            network_interface_driver=network_interface_driver,
        )
        
        super().__init__(dut, tasks)
    
    async def send(self, *messages: Message):
        await self.send_port.enqueue_values(*map(InterfaceSendData, messages))
    
    async def get_single_received(self) -> Message:
        return (await self.recv_port.dequeue_value()).message
    
    async def get_received(self, n: int=-1) -> AsyncIterable[Message]:
        async for data in self.recv_port.dequeue_values(n):
            yield data.message
        
    async def receive(self, *messages: Message):
        await self.network_interface_driver.receive(*messages)
        
    async def get_single_sent(self) -> Message:
        return await self.network_interface_driver.get_single_sent()
        
    def get_sent(self, n: int=-1) -> AsyncIterable[Message]:
        return self.network_interface_driver.get_sent(n)
    
    @classmethod
    def test_factory(cls, *, max_addr_bits: int=32) -> TestFactory:
        STREAM_LENGTH = 64
        
        tf = TestFactory(adapter_test, tb_builder=cls)
        tf.add_option(('sent_messages', 'received_messages'), [
            ([], []),
            (random_message_stream(STREAM_LENGTH, max_addr_bits), []),
            ([], random_message_stream(STREAM_LENGTH, max_addr_bits)),
            (random_message_stream(STREAM_LENGTH, max_addr_bits), random_message_stream(STREAM_LENGTH, max_addr_bits)),
        ])
        
        return tf

def random_message(max_addr_bits: int) -> Message:
    return Message.quick(random.randint(1, 2**max_addr_bits-1), random.randint(0, 2**32-1), random.randint(0, 2**64-1))

def random_message_stream(length: int, max_addr_bits: int) -> List[Message]:
    return [random_message(max_addr_bits) for _ in range(length)]

async def adapter_test(dut: SimHandleBase, tb_builder: Callable[[SimHandleBase], AbstractAdapterTB], sent_messages: List[Message]=[], received_messages: List[Message]=[]):
    async with tb_builder(dut) as tb:
        await tb.send(*sent_messages)
        await tb.receive(*received_messages)
        
        got_sent_messages = [x async for x in tb.get_sent(len(sent_messages))]
        got_received_messages = [x async for x in tb.get_received(len(received_messages))]
        
        assert got_sent_messages == sent_messages
        assert got_received_messages == received_messages