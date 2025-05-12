from asyncio.tasks import wait
import itertools
from typing import Tuple
import cocotb
from cocotb.handle import SimHandleBase
from cocotb.clock import Clock
from cocotb.queue import Queue

from cocotb_utils import RisingEdgesHoldingAssertion, reset, flush, RisingEdge, RisingEdges, SimulationUpdate
from xctcmsg_pkg import RequestData, RequestType, WritebackArbiterData, Message

MESSAGE_BUFFER_SIZE = 4

# Structs need for compatibility with SVStruct signal methods

class RRStageInputPseudoSignal:
    def __init__(self, dut: SimHandleBase):
        self.funct3 = dut.rr_xctcmsg_funct3
        self.rs1 = dut.rr_xctcmsg_rs1
        self.rs2 = dut.rr_xctcmsg_rs2
        self.passthrough = dut.rr_xctcmsg_passthrough

class WBStageOutputPseudoSignal:
    def __init__(self, dut: SimHandleBase):
        self.value = dut.xctcmsg_wb_value
        self.passthrough = dut.xctcmsg_wb_passthrough

class PseudoMessageMetadataSignal:
    def __init__(self, tag_signal: SimHandleBase, address_signal: SimHandleBase):
        self.tag = tag_signal
        self.address = address_signal

class BusInputPseudoSignal:
    def __init__(self, dut: SimHandleBase):
        self.meta = PseudoMessageMetadataSignal(dut.bus_tag_i, dut.bus_src_i)
        self.data = dut.bus_msg_i

class BusOutputPseudoSignal:
    def __init__(self, dut: SimHandleBase):
        self.meta = PseudoMessageMetadataSignal(dut.bus_tag_o, dut.bus_dst_o)
        self.data = dut.bus_msg_o

# Emulators

class RRStageEmulator:
    dut: SimHandleBase
    request_queue: Queue[RequestData]

    def __init__(self, dut: SimHandleBase):
        self.dut = dut
        self.request_queue = Queue()

    async def request(self, *items: RequestData):
        for item in items:
            await self.request_queue.put(item)

    async def start(self):
        dut_rr_xctcmsg_data = RRStageInputPseudoSignal(self.dut)

        while True:
            await RisingEdge()
            await SimulationUpdate()

            if self.dut.rr_xctcmsg_valid.value == 1 and self.dut.xctcmsg_rr_ready.value == 0:
                continue

            self.dut.rr_xctcmsg_valid.value = 0

            if (not self.request_queue.empty()):
                data = self.request_queue.get_nowait()
                self.dut.rr_xctcmsg_valid.value = 1
                data.write_to_signal(dut_rr_xctcmsg_data)
                self.dut._log.info(f"Request in: {data}")

class WBStageEmulator:
    dut: SimHandleBase
    allow_writeback: bool = True
    writeback_queue: Queue[WritebackArbiterData]

    def __init__(self, dut: SimHandleBase):
        self.dut = dut
        self.writeback_queue = Queue()

    async def get_writeback(self) -> WritebackArbiterData:
        return await self.writeback_queue.get()

    async def start(self):
        dut_xctcmsg_wb_data = WBStageOutputPseudoSignal(self.dut)

        while True:
            await RisingEdge()
            await SimulationUpdate()

            self.dut.wb_xctcmsg_ready.value = self.allow_writeback
            if (not self.allow_writeback):
                continue

            await SimulationUpdate()

            if (self.dut.xctcmsg_wb_valid.value == 0 or self.writeback_queue.full()):
                continue

            data = WritebackArbiterData.from_signal(dut_xctcmsg_wb_data)
            self.writeback_queue.put_nowait(data)
            self.dut._log.info(f"Writeback out: {data}")

class BusEmulator:
    dut: SimHandleBase
    send_queue: Queue[Message]
    allow_receive: bool = True
    receive_queue: Queue[Message]

    def __init__(self, dut: SimHandleBase):
        self.dut = dut
        self.send_queue = Queue()
        self.receive_queue = Queue()

    async def send(self, *items: Message):
        for item in items:
            await self.send_queue.put(item)

    async def receive(self) -> Message:
        return await self.receive_queue.get()

    async def start(self):
        dut_bus_i = BusInputPseudoSignal(self.dut)
        dut_bus_o = BusOutputPseudoSignal(self.dut)

        while True:
            await RisingEdge()
            await SimulationUpdate()

            self.dut.bus_ack_i.value = 0
            if (self.allow_receive):
                if (self.dut.bus_val_o.value == 1):
                    if (not self.receive_queue.full()):
                        self.dut.bus_ack_i.value = 1
                        data = Message.from_signal(dut_bus_o)
                        self.receive_queue.put_nowait(data)
                        self.dut._log.info(f"Bus out: {data}")

            await SimulationUpdate()

            self.dut.bus_val_i.value = 0
            if (self.dut.bus_rdy_o.value == 1):
                if (not self.send_queue.empty()):
                    data = self.send_queue.get_nowait()
                    self.dut.bus_val_i.value = 1
                    data.write_to_signal(dut_bus_i)
                    self.dut._log.info(f"Bus in: {data}")

async def setup(dut: SimHandleBase) -> Tuple[RRStageEmulator, WBStageEmulator, BusEmulator]:
    rr_stage = RRStageEmulator(dut)
    wb_stage = WBStageEmulator(dut)
    bus = BusEmulator(dut)

    dut.local_address.value = 0;
    await cocotb.start(Clock(dut.clk, 10, 'ns').start())
    await reset()

    await cocotb.start(rr_stage.start())
    await cocotb.start(wb_stage.start())
    await cocotb.start(bus.start())

    return (rr_stage, wb_stage, bus)

async def finish_test(dut: SimHandleBase, rr_stage: RRStageEmulator, wb_stage: WBStageEmulator, bus: BusEmulator):
    dut._log.info("Cleaning up")

    dut.rr_xctcmsg_valid.value = 0
    dut.bus_ack_i.value = 0
    dut.bus_val_i.value = 0
    dut.wb_xctcmsg_ready.value = 0

    await SimulationUpdate()

    while not rr_stage.request_queue.empty():
        rr_stage.request_queue.get_nowait()

    while not wb_stage.writeback_queue.empty():
        wb_stage.writeback_queue.get_nowait()

    while not bus.send_queue.empty():
        bus.send_queue.get_nowait()

    while not bus.receive_queue.empty():
        bus.receive_queue.get_nowait()

@cocotb.test
async def reset_state(dut):
    await cocotb.start(Clock(dut.clk, 10, 'ns').start())
    await reset()

    # Ready signal could be unasserted if a request type is not given
    dut.rr_xctcmsg_funct3.value = 0b000;
    await SimulationUpdate()

    assert int(dut.xctcmsg_rr_ready.value) == 1
    assert int(dut.bus_val_o.value) == 0
    assert int(dut.bus_rdy_o.value) == 1
    assert int(dut.xctcmsg_wb_valid.value) == 0

@cocotb.test
async def flush_test(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        ## mailbox
        bus.receive_queue = Queue()
        await bus.send(*([Message.quick(0, 0, 0)] * MESSAGE_BUFFER_SIZE))
        await rr_stage.request(RequestData.quick(RequestType.RECV, 1, 0, 13))

        await RisingEdges(2 * MESSAGE_BUFFER_SIZE)

        assert dut.mbox.request_valid.value == 1
        assert dut.mbox.message_valid.value.binstr == '1' * MESSAGE_BUFFER_SIZE

        await flush()

        assert dut.mbox.request_valid.value == 0
        assert dut.mbox.message_valid.value.binstr == '1' * MESSAGE_BUFFER_SIZE

        # Cleanup messages left on buffers
        await rr_stage.request(*([RequestData.quick(RequestType.RECV, 0, -1, 0)] * MESSAGE_BUFFER_SIZE))
        for i in range(MESSAGE_BUFFER_SIZE):
            await wb_stage.get_writeback()

        ## postoffice
        wb_stage.writeback_queue = Queue()
        wb_stage.allow_writeback = False
        await rr_stage.request(RequestData.quick(RequestType.SEND, 0, 0, 14))

        await RisingEdges(20)

        assert dut.postoffice.writeback_valid.value == 1

        await flush()

        assert dut.postoffice.writeback_valid.value == 0
        wb_stage.allow_writeback = True
        await RisingEdges(20)
        assert wb_stage.writeback_queue.empty()

        ## queues
        wb_stage.writeback_queue = Queue()
        wb_stage.allow_writeback = False

        await rr_stage.request(
            RequestData.quick(RequestType.SEND, 0, 0, 15),
            RequestData.quick(RequestType.SEND, 0, 0, 16),
            RequestData.quick(RequestType.AVAIL, 0, 0, 17),
            RequestData.quick(RequestType.AVAIL, 0, 0, 18),
        )

        await RisingEdges(20)

        assert dut.send_queue.empty.value == 0
        assert dut.receive_queue.empty.value == 0

        await flush()

        assert dut.send_queue.empty.value == 1
        assert dut.receive_queue.empty.value == 1
        wb_stage.allow_writeback = True
        await RisingEdges(20)
        assert wb_stage.writeback_queue.empty()
    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)


@cocotb.test
async def receive_full_match_single(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        message = Message.quick(10, 42, 5)
        requests = [
            RequestData.quick(RequestType.AVAIL, 10 | (42 << 32), 0, 1),
            RequestData.quick(RequestType.RECV, 10 | (42 << 32), 0, 2),
            RequestData.quick(RequestType.AVAIL, 10 | (42 << 32), 0, 3),
        ]
        expected_writebacks = [
            WritebackArbiterData.quick(1, 1),
            WritebackArbiterData.quick(2, 5),
            WritebackArbiterData.quick(3, 0),
        ]

        await bus.send(message)

        await RisingEdges(2)

        await rr_stage.request(*requests)

        for expected_writeback in expected_writebacks:
            writeback = await wb_stage.get_writeback()
            assert writeback == expected_writeback

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def receive_full_match_stream(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        STREAM_LENGTH = 64
        messages = [Message.quick(10, 42, x) for x in range(STREAM_LENGTH)]
        requests = [RequestData.quick(RequestType.RECV, 10 | (42 << 32), 0, 1)] * STREAM_LENGTH

        await bus.send(*messages)
        await rr_stage.request(*requests)

        received_values = set()
        for i in range(64):
            writeback = await wb_stage.get_writeback()
            assert writeback.passthrough.rd.integer == 1
            assert writeback.value.integer not in received_values

            received_values.add(writeback.value.integer)

        assert received_values == set(range(64))

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def send_single(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        request = RequestData.quick(RequestType.SEND, 5, 10 | (42 << 32), 1)
        expected_writeback = WritebackArbiterData.quick(1, 1)
        expected_message = Message.quick(10, 42, 5)

        await rr_stage.request(request)

        writeback = await wb_stage.get_writeback()
        assert writeback == expected_writeback

        message = await bus.receive()
        assert message == expected_message

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def send_stream(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        STREAM_LENGTH = 64
        requests = [RequestData.quick(RequestType.SEND, x, 10 | (42 << 32), 1) for x in range(STREAM_LENGTH)]
        expected_writebacks = [WritebackArbiterData.quick(1, 1) for _ in range(STREAM_LENGTH)]
        expected_messages = [Message.quick(10, 42, x) for x in range(STREAM_LENGTH)]

        await rr_stage.request(*requests)

        for expected_writeback in expected_writebacks:
            writeback = await wb_stage.get_writeback()
            assert writeback == expected_writeback

        for expected_message in expected_messages:
            message = await bus.receive()
            assert message == expected_message

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def loopback_single(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        requests = [
            RequestData.quick(RequestType.SEND, 42, (42 << 32) | 0, 1), # ctc.send x1, 42, id:0+tag:42
            RequestData.quick(RequestType.RECV, (42 << 32) | 0, 0, 2),  # ctc.recv x2, id:0+tag:42
        ]
        expected_writebacks = [
            WritebackArbiterData.quick(1, 1),
            WritebackArbiterData.quick(2, 42),
        ]

        await rr_stage.request(*requests)

        for expected_writeback in expected_writebacks:
            writeback = await wb_stage.get_writeback()
            assert writeback == expected_writeback

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def stream_loopback_spaced(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        STREAM_LENGTH = 64
        
        for i in range(STREAM_LENGTH):
            await rr_stage.request(RequestData.quick(RequestType.SEND, i, 0 | (42 << 32), 1))
            send_writeback = await wb_stage.get_writeback()
            assert send_writeback == WritebackArbiterData.quick(1, 1)

            available = False
            while not available:
                await rr_stage.request(RequestData.quick(RequestType.AVAIL, 0 | (42 << 32), 0, 2))
                avail_writeback = await wb_stage.get_writeback()
                assert avail_writeback.passthrough.rd.integer == 2
                available = (avail_writeback.value.integer == 1)

            await rr_stage.request(RequestData.quick(RequestType.RECV, 0 | (42 << 32), 0, 3))
            recv_writeback = await wb_stage.get_writeback()
            assert recv_writeback == WritebackArbiterData.quick(3, i)

            await rr_stage.request(RequestData.quick(RequestType.AVAIL, 0 | (42 << 32), 0, 4))
            avail_writeback = await wb_stage.get_writeback()
            assert avail_writeback == WritebackArbiterData.quick(4, 0)

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def stream_loopback_speed(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        STREAM_LENGTH = 64
        send_requests = [RequestData.quick(RequestType.SEND, x, 0 | (42 << 32), 1) for x in range(STREAM_LENGTH)]
        recv_requests = [RequestData.quick(RequestType.RECV, 0 | (42 << 32), 0, 3) for _ in range(STREAM_LENGTH)]
        requests = itertools.chain(*zip(send_requests, recv_requests))
        
        await rr_stage.request(*requests)

        sent = 0
        received = set()
        for i in range(2 * STREAM_LENGTH):
            writeback = await wb_stage.get_writeback()
            
            if writeback.passthrough.rd.integer == 1:
                assert writeback.value.integer == 1
                sent += 1
            elif writeback.passthrough.rd.integer == 3:
                received.add(writeback.value.integer)
            else:
                assert False, f"Unexpected writeback rd: {writeback.passthrough.rd.integer}, expected 1 or 3"

        assert sent == STREAM_LENGTH
        assert received == set(range(STREAM_LENGTH))

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

async def echo_server(bus: BusEmulator):
    while True:
        message = await bus.receive()
        await bus.send(message)

@cocotb.test
async def stream_echo_spaced(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        STREAM_LENGTH = 64
        
        await cocotb.start(echo_server(bus))
        
        for i in range(STREAM_LENGTH):
            await rr_stage.request(RequestData.quick(RequestType.SEND, i, 10 | (42 << 32), 1))
            send_writeback = await wb_stage.get_writeback()
            assert send_writeback == WritebackArbiterData.quick(1, 1)

            available = False
            while not available:
                await rr_stage.request(RequestData.quick(RequestType.AVAIL, 10 | (42 << 32), 0, 2))
                avail_writeback = await wb_stage.get_writeback()
                assert avail_writeback.passthrough.rd.integer == 2
                available = (avail_writeback.value.integer == 1)

            await rr_stage.request(RequestData.quick(RequestType.RECV, 10 | (42 << 32), 0, 3))
            recv_writeback = await wb_stage.get_writeback()
            assert recv_writeback == WritebackArbiterData.quick(3, i)

            await rr_stage.request(RequestData.quick(RequestType.AVAIL, 10 | (42 << 32), 0, 4))
            avail_writeback = await wb_stage.get_writeback()
            assert avail_writeback == WritebackArbiterData.quick(4, 0)

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def stream_echo_speed(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        STREAM_LENGTH = 64
        send_requests = [RequestData.quick(RequestType.SEND, x, 10 | (42 << 32), 1) for x in range(STREAM_LENGTH)]
        recv_requests = [RequestData.quick(RequestType.RECV, 10 | (42 << 32), 0, 3) for _ in range(STREAM_LENGTH)]
        requests = itertools.chain(*zip(send_requests, recv_requests))
        
        await cocotb.start(echo_server(bus))
        
        await rr_stage.request(*requests)

        sent = 0
        received = set()
        for i in range(2 * STREAM_LENGTH):
            writeback = await wb_stage.get_writeback()
            
            if writeback.passthrough.rd.integer == 1:
                assert writeback.value.integer == 1
                sent += 1
            elif writeback.passthrough.rd.integer == 3:
                received.add(writeback.value.integer)
            else:
                assert False, f"Unexpected writeback rd: {writeback.passthrough.rd.integer}, expected 1 or 3"

        assert sent == STREAM_LENGTH
        assert received == set(range(STREAM_LENGTH))

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def stream_mixed_spaced(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        STREAM_LENGTH = 64
        
        await cocotb.start(echo_server(bus))
        
        for i in range(STREAM_LENGTH):
            await rr_stage.request(RequestData.quick(RequestType.SEND, i, (i % 2) | (42 << 32), 1))
            send_writeback = await wb_stage.get_writeback()
            assert send_writeback == WritebackArbiterData.quick(1, 1)

            available = False
            while not available:
                await rr_stage.request(RequestData.quick(RequestType.AVAIL, (i % 2) | (42 << 32), 0, 2))
                avail_writeback = await wb_stage.get_writeback()
                assert avail_writeback.passthrough.rd.integer == 2
                available = (avail_writeback.value.integer == 1)

            await rr_stage.request(RequestData.quick(RequestType.RECV, (i % 2) | (42 << 32), 0, 3))
            recv_writeback = await wb_stage.get_writeback()
            assert recv_writeback == WritebackArbiterData.quick(3, i)

            await rr_stage.request(RequestData.quick(RequestType.AVAIL, (i % 2) | (42 << 32), 0, 4))
            avail_writeback = await wb_stage.get_writeback()
            assert avail_writeback == WritebackArbiterData.quick(4, 0)

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def stream_mixed_speed(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        STREAM_LENGTH = 64
        send_requests = [RequestData.quick(RequestType.SEND, x, (x % 2) | (42 << 32), 1) for x in range(STREAM_LENGTH)]
        recv_requests = [RequestData.quick(RequestType.RECV, (x % 2) | (42 << 32), 0, 3) for x in range(STREAM_LENGTH)]
        requests = itertools.chain(*zip(send_requests, recv_requests))
        
        await cocotb.start(echo_server(bus))
        
        await rr_stage.request(*requests)

        sent = 0
        received = set()
        for i in range(2 * STREAM_LENGTH):
            writeback = await wb_stage.get_writeback()
            
            if writeback.passthrough.rd.integer == 1:
                assert writeback.value.integer == 1
                sent += 1
            elif writeback.passthrough.rd.integer == 3:
                received.add(writeback.value.integer)
            else:
                assert False, f"Unexpected writeback rd: {writeback.passthrough.rd.integer}, expected 1 or 3"

        assert sent == STREAM_LENGTH
        assert received == set(range(STREAM_LENGTH))

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def avoid_send_stall(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        bus.allow_receive = False
        
        AVAIL_REQUESTS = 5

        send_requests = [
            # This request gets to stay in the holding registers
            RequestData.quick(RequestType.SEND, 5, 10 | (42 << 32), 1),
            # This request will stall
            RequestData.quick(RequestType.SEND, 5, 10 | (42 << 32), 2),
        ]
        send_requests_expected_writebacks = [
            WritebackArbiterData.quick(1, 1),
            WritebackArbiterData.quick(2, 1),
        ]
        avail_requests = [RequestData.quick(RequestType.AVAIL, 10 | (42 << 32), 0, x+2) for x in range(AVAIL_REQUESTS)]
        avail_requests_expected_writebacks = [WritebackArbiterData.quick(x+2, 0) for x in range(AVAIL_REQUESTS)]
        
        requests = itertools.chain(send_requests, avail_requests)
        expected_writebacks = list(itertools.chain(
            send_requests_expected_writebacks[0:1],
            avail_requests_expected_writebacks,
            send_requests_expected_writebacks[1:2],
        ))
        
        await rr_stage.request(*requests)
        
        # Get all writebacks but the last one
        for expected_writeback in expected_writebacks[:-1]:
            writeback = await wb_stage.get_writeback()
            assert writeback == expected_writeback
        
        RisingEdgesHoldingAssertion(20, lambda: wb_stage.writeback_queue.empty())
        
        # Here we unstall
        bus.allow_receive = True
        writeback = await wb_stage.get_writeback()
        assert writeback == expected_writebacks[-1]

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def avoid_receive_stall(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        await cocotb.start(echo_server(bus))
        
        SEND_REQUESTS = 4
        
        # This request will stall
        receive_request = RequestData.quick(RequestType.RECV, 10 | ((SEND_REQUESTS - 1) << 32), 0, 1)
        receive_request_expected_writeback = WritebackArbiterData.quick(1, 5)
        send_requests = [RequestData.quick(0b000, 5, 10 | (x << 32), x+1) for x in range(SEND_REQUESTS)]
        send_requests_expected_writebacks = [WritebackArbiterData.quick(x+1, 1) for x in range(SEND_REQUESTS)]
        
        requests = [receive_request] + send_requests
        # The last send should unstall the receive (matching tag)
        expected_writebacks = send_requests_expected_writebacks + [receive_request_expected_writeback]
        
        await rr_stage.request(*requests)
        
        for expected_writeback in expected_writebacks:
            writeback = await wb_stage.get_writeback()
            assert writeback == expected_writeback

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)
