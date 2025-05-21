from abc import abstractmethod
from collections.abc import AsyncGenerator
from typing import AsyncIterable, Callable, ContextManager, Iterable, List, override
import random

from cocotb import triggers
from cocotb.handle import SimHandleBase
from cocotb.queue import Queue
from cocotb.regression import TestFactory
from cocotb.triggers import First

from xctcmsg_pkg import InterfaceReceiveData, InterfaceSendData, Message
from cocotb_utils import AbstractTB, AbstractClock, NeedsClock, SVStruct, TBTask, ValRdyConsumer, ValRdyInterface, ValRdyProducer

class NetworkInterfaceDriver(TBTask):
    captured_sends: Queue[Message]
    pending_receives: Queue[Message]
    
    def __init__(self, *, use_kill: bool = False, subtasks: Iterable[TBTask]=[]):
        super().__init__(use_kill=use_kill, subtasks=subtasks)
        
        self.captured_sends = Queue()
        self.pending_receives = Queue()
    
    async def get_single_sent(self) -> Message:
        return await self.captured_sends.get()
    
    async def get_sent(self, n: int=-1) -> AsyncGenerator[Message]:
        count = 0
        
        while count != n:
            next = await self.get_single_sent()
            count += 1
            yield next
    
    async def receive(self, *messages: Message):
        for message in messages:
            await self.pending_receives.put(message)
    
    @abstractmethod
    def disable_sends(self) -> ContextManager:
        pass
    
    @abstractmethod
    def disable_recvs(self) -> ContextManager:
        pass

class ValRdyNetworkInterfaceDriver[SendData: SVStruct, RecvData: SVStruct](NetworkInterfaceDriver, NeedsClock):
    clock: AbstractClock
    
    def __init__(self, dut: SimHandleBase, send_port: ValRdyConsumer[SendData], recv_port: ValRdyProducer[RecvData]):
        self.dut = dut
        self.send_port = send_port
        self.recv_port = recv_port
        
        super().__init__(subtasks=[self.send_port, self.recv_port])
    
    @override
    async def _task_coroutine(self):
        next_iteration_trigger = First(self._stop_event.wait(), self.clock.rising_edge())
        
        while not self._stop_event.is_set():
            if not self.send_port.queue.empty():
                send_data = self.send_port.queue.get_nowait()
                message = self._send_data_to_message(send_data)
                await self.captured_sends.put(message)
                
            if not self.pending_receives.empty():
                message = self.pending_receives.get_nowait()
                recv_data = self._message_to_recv_data(message)
                await self.recv_port.enqueue_values(recv_data)

            await next_iteration_trigger
    
    @staticmethod
    @abstractmethod
    def _send_data_to_message(data: SendData) -> Message:
        pass
    
    @staticmethod
    @abstractmethod
    def _message_to_recv_data(message: Message) -> RecvData:
        pass
    
    def disable_sends(self) -> ContextManager:
        return self.send_port.disabled()
    
    def disable_recvs(self) -> ContextManager:
        return self.recv_port.disabled()