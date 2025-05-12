from enum import IntEnum

from cocotb.types.logic_array import LogicArray

from cocotb_utils import SVStruct, CheckedLogicArray

class UnitTestPassthrough(SVStruct):
    rd: CheckedLogicArray = CheckedLogicArray(5)

class RequestData(SVStruct, quick_args=['funct3', 'rs1', 'rs2', 'passthrough-rd']):
    funct3: CheckedLogicArray = CheckedLogicArray(3)
    rs1: CheckedLogicArray = CheckedLogicArray(64)
    rs2: CheckedLogicArray = CheckedLogicArray(64)
    passthrough: UnitTestPassthrough

class RequestType(IntEnum):
    SEND = 0
    RECV = 1
    AVAIL = 2

MessageAddress = CheckedLogicArray(32)
MessageTag = CheckedLogicArray(32)
MessageData = CheckedLogicArray(64)

class MessageMetadata(SVStruct):
    tag: CheckedLogicArray = MessageTag
    address: CheckedLogicArray = MessageAddress

class Message(SVStruct, quick_args=['meta-address', 'meta-tag', 'data']):
    meta: MessageMetadata
    data: CheckedLogicArray = MessageData

class SendQueueData(SVStruct, quick_args=['message-meta-address', 'message-meta-tag', 'message-data', 'passthrough-rd']):
    message: Message
    passthrough: UnitTestPassthrough

class ReceiveQueueData(SVStruct, quick_args=['meta-address', 'meta-tag', 'meta_mask-address', 'meta_mask-tag', 'passthrough-rd', 'is_avail']):
    is_avail: CheckedLogicArray = CheckedLogicArray(1)
    meta: MessageMetadata
    meta_mask: MessageMetadata
    passthrough: UnitTestPassthrough

class WritebackArbiterData(SVStruct, quick_args=['passthrough-rd', 'value']):
    value: CheckedLogicArray = CheckedLogicArray(64)
    passthrough: UnitTestPassthrough

class InterfaceSendData(SVStruct, quick_args=['message-meta-address', 'message-meta-tag', 'message-data']):
    message: Message

class InterfaceReceiveData(SVStruct):
    message: Message

class CommitSafetyRequest(SVStruct):
    payload: CheckedLogicArray = CheckedLogicArray(1)