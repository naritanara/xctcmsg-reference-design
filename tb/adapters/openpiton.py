from typing import override

from cocotb.handle import SimHandleBase
from cocotb.types import LogicArray, Range, concat

from adapters import ValRdyNetworkInterfaceDriver
from cocotb_utils import PseudoSignal, ValRdyConsumer, ValRdyInterface, ValRdyProducer
from xctcmsg_pkg import Message, OpenpitonData


class OpenpitonInterfaceDriver(ValRdyNetworkInterfaceDriver[OpenpitonData, OpenpitonData]):
    def __init__(self, dut: SimHandleBase):
        send_interface_pseudo = PseudoSignal(dut, {
            'raw': 'noc_out_data',
        })
        recv_interface_pseudo = PseudoSignal(dut, {
            'raw': 'noc_in_data',
        })
        
        send_interface = ValRdyInterface(
            val=dut.noc_out_val,
            rdy=dut.noc_out_rdy,
            data=send_interface_pseudo,
            consumer_name="Xctcmsg NoC",
        )
        recv_interface = ValRdyInterface(
            val=dut.noc_in_val,
            rdy=dut.noc_in_rdy,
            data=recv_interface_pseudo,
            producer_name="Xctcmsg NoC",
        )
        
        send_port = ValRdyConsumer(send_interface, OpenpitonData)
        recv_port = ValRdyProducer(recv_interface, OpenpitonData)

        super().__init__(dut, send_port, recv_port)
    
    @override
    @staticmethod
    def _send_data_to_message(data: OpenpitonData) -> Message:
        message = Message.zeroed()
        
        message.meta.address = concat(LogicArray('0'*24), LogicArray(data.raw[41:34]))
        message.meta.tag = LogicArray(data.raw[127:96])
        message.data = LogicArray(data.raw[191:128])
        
        return message
    
    @override
    @staticmethod
    def _message_to_recv_data(message: Message) -> OpenpitonData:
        raw = LogicArray(0, Range(191, 'downto', 0))
        
        raw[95:64] = message.meta.address
        raw[127:96] = message.meta.tag
        raw[191:128] = message.data
        
        return OpenpitonData.quick(raw)