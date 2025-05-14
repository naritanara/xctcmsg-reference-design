from typing import AsyncGenerator, Self
from typing_extensions import override
import cocotb
from cocotb.handle import SimHandleBase

from cocotb_utils import AbstractTB, PseudoSignal, TBTask, ValRdyConsumer, ValRdyInterface, ValRdyProducer
from xctcmsg_pkg import InterfaceReceiveData, InterfaceSendData, Message

class LoopbackBusEmulator(TBTask):
    dut_output_consumer: ValRdyConsumer[Message]
    dut_input_producer: ValRdyProducer[Message]
    
    def __init__(self, dut: SimHandleBase):
        dut_output_pseudo = PseudoSignal(dut,
            {
                'meta': {
                    'tag': 'bus_tag_o',
                    'address': 'bus_dst_o',
                },
                'data': 'bus_msg_o',
            }
        )
        dut_input_pseudo = PseudoSignal(dut,
            {
                'meta': {
                    'tag': 'bus_tag_i',
                    'address': 'bus_src_i',
                },
                'data': 'bus_msg_i',
            }
        )
        
        dut_output_interface = ValRdyInterface(
            val=dut.bus_val_o,
            rdy=dut.bus_ack_i,
            rdy_is_ack=True,
            data=dut_output_pseudo,
            consumer_name="Loopback Bus",
        )
        dut_input_interface = ValRdyInterface(
            val=dut.bus_val_i,
            rdy=dut.bus_rdy_o,
            data=dut_input_pseudo,
            producer_name="Loopback Bus",
        )
        
        self.dut_output_consumer = ValRdyConsumer(dut_output_interface, Message)
        self.dut_input_producer = ValRdyProducer(dut_input_interface, Message)
        
        super().__init__(use_kill=True, subtasks=[self.dut_output_consumer, self.dut_input_producer])
    
    async def _task_coroutine(self):
        async for message in self.dut_output_consumer.dequeue_values():
            await self.dut_input_producer.enqueue_values(message)

class BusCommunicationInterfaceTB(AbstractTB):
    send_port: ValRdyProducer[InterfaceSendData]
    recv_port: ValRdyConsumer[InterfaceReceiveData]
    bus: LoopbackBusEmulator
    
    def __init__(self, dut: SimHandleBase):
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
        )
        
        super().__init__(dut, tasks)
        
        self.bus = LoopbackBusEmulator(dut)
    
    @override
    async def __aenter__(self) -> Self:
        await self.bus.start()
        return await super().__aenter__()
    
    @override
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.bus.stop()
        return await super().__aexit__(exc_type, exc_val, exc_tb)
    
    async def send(self, *messages: Message):
        await self.send_port.enqueue_values(*map(InterfaceSendData, messages))
    
    async def receive(self, n: int=-1) -> AsyncGenerator[Message, None]:
        async for data in self.recv_port.dequeue_values(n):
            yield data.message

@cocotb.test
async def reset_state(dut):
    async with BusCommunicationInterfaceTB(dut):
        assert dut.holding_valid.value == 0

@cocotb.test
async def echo_test(dut):
    messages = [
        Message.quick(0, 42, 55),
        Message.quick(0, 55, 42),
        Message.quick(0, 0, 0),
    ]
    
    async with BusCommunicationInterfaceTB(dut) as tb:
        await tb.send(*messages)
        
        received_messages = [x async for x in tb.receive(len(messages))]
        assert received_messages == messages
