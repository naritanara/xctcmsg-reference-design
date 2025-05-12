from enum import Enum
import cocotb
from cocotb.regression import TestFactory
from cocotb.triggers import Timer
from cocotb.types import LogicArray, Range

from cocotb_utils import SimulationUpdate
from xctcmsg_pkg import MessageMetadata, RequestData, RequestType, SendQueueData, UnitTestPassthrough, Message, ReceiveQueueData


class TargetQueue(Enum):
    SEND_QUEUE = 0
    RECEIVE_QUEUE = 1


async def decode_test(dut, request_data, expected_queue_data):
    if isinstance(expected_queue_data, SendQueueData):
        target_queue = TargetQueue.SEND_QUEUE
    elif isinstance(expected_queue_data, ReceiveQueueData):
        target_queue = TargetQueue.RECEIVE_QUEUE
    else:
        raise ValueError("Invalid expected queue data")

    dut.rr_request_decoder_valid.value = 1
    request_data.write_to_signal(dut.rr_request_decoder_data)
    
    dut.send_queue_request_decoder_ready.value = 0
    dut.receive_queue_request_decoder_ready.value = 0

    await SimulationUpdate()

    assert int(dut.request_decoder_rr_ready.value) == 0

    assert int(dut.request_decoder_send_queue_valid.value) == (target_queue == TargetQueue.SEND_QUEUE)
    assert int(dut.request_decoder_receive_queue_valid.value) == (target_queue == TargetQueue.RECEIVE_QUEUE)
    
    if target_queue == TargetQueue.SEND_QUEUE:
        queue_data = SendQueueData.from_signal(dut.request_decoder_send_queue_data)
    elif target_queue == TargetQueue.RECEIVE_QUEUE:
        queue_data = ReceiveQueueData.from_signal(dut.request_decoder_receive_queue_data)
    else:
        raise ValueError("Invalid target queue")

    assert queue_data == expected_queue_data
    
    dut.send_queue_request_decoder_ready.value = (target_queue == TargetQueue.SEND_QUEUE)
    dut.receive_queue_request_decoder_ready.value = (target_queue == TargetQueue.RECEIVE_QUEUE)
    
    await SimulationUpdate()
    
    assert int(dut.request_decoder_rr_ready.value) == 1


tf = TestFactory(test_function=decode_test)
tf.add_option(('request_data', 'expected_queue_data'), [
    (
        RequestData(RequestType.SEND, 255, (42 << 32) | 10, UnitTestPassthrough(23)),
        SendQueueData(Message(MessageMetadata(42, 10), 255), UnitTestPassthrough(23)),
    ),
    (
        RequestData(RequestType.RECV, (42 << 32) | 10, (1 << 32) | 2, UnitTestPassthrough(23)),
        ReceiveQueueData(False, MessageMetadata(42, 10), MessageMetadata(~1, ~2), UnitTestPassthrough(23)),
    ),
    (
        RequestData(RequestType.AVAIL, (42 << 32) | 10, (1 << 32) | 2, UnitTestPassthrough(23)),
        ReceiveQueueData(True, MessageMetadata(42, 10), MessageMetadata(~1, ~2), UnitTestPassthrough(23)),
    )
])
tf.generate_tests()