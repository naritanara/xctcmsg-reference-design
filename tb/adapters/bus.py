from typing import AsyncGenerator, Self
from cocotb import triggers
from cocotb.triggers import Combine, First
from typing_extensions import override
import cocotb
from cocotb.handle import SimHandleBase

from adapters import ValRdyNetworkInterfaceDriver
from cocotb_utils import AbstractClock, AbstractTB, PseudoSignal, RisingEdge, TBTask, ValRdyConsumer, ValRdyInterface, ValRdyProducer
from xctcmsg_pkg import InterfaceReceiveData, InterfaceSendData, Message


class BusInterfaceDriver(ValRdyNetworkInterfaceDriver[Message, Message]):
    def __init__(self, dut: SimHandleBase):
        send_interface_pseudo = PseudoSignal(dut,
            {
                'meta': {
                    'tag': 'bus_tag_o',
                    'address': 'bus_dst_o',
                },
                'data': 'bus_msg_o',
            }
        )
        recv_interface_pseudo = PseudoSignal(dut,
            {
                'meta': {
                    'tag': 'bus_tag_i',
                    'address': 'bus_src_i',
                },
                'data': 'bus_msg_i',
            }
        )
        
        send_interface = ValRdyInterface(
            val=dut.bus_val_o,
            rdy=dut.bus_ack_i,
            rdy_is_ack=True,
            data=send_interface_pseudo,
            consumer_name="C2C Network",
        )
        recv_interface = ValRdyInterface(
            val=dut.bus_val_i,
            rdy=dut.bus_rdy_o,
            data=recv_interface_pseudo,
            producer_name="C2C Network",
        )
        
        send_port = ValRdyConsumer(send_interface, Message)
        recv_port = ValRdyProducer(recv_interface, Message)
        
        super().__init__(dut, send_port, recv_port)
    
    @override
    @staticmethod
    def _send_data_to_message(data: Message) -> Message:
        return data
    
    @override
    @staticmethod
    def _message_to_recv_data(message: Message) -> Message:
        return message