import itertools
from os import environ
from typing import AsyncGenerator, ContextManager, Tuple, override
import cocotb
from cocotb.handle import SimHandleBase
from cocotb.clock import Clock
from cocotb.queue import Queue

from cocotb_utils import AbstractTB, PseudoSignal, QueueState, RisingEdgesHoldingAssertion, TBTask, ValRdyConsumer, ValRdyInterface, ValRdyProducer, reset, flush, RisingEdge, RisingEdges, SimulationUpdate
from adapters import NetworkInterfaceDriver, ValRdyNetworkInterfaceDriver
from adapters.bus import BusInterfaceDriver
from adapters.openpiton import OpenpitonInterfaceDriver
from xctcmsg_pkg import RequestData, RequestType, WritebackArbiterData, Message

MESSAGE_BUFFER_SIZE = 4

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
        dut_rr_xctcmsg_data = PseudoSignal(self.dut, {
            'funct3': 'rr_xctcmsg_funct3',
            'rs1': 'rr_xctcmsg_rs1',
            'rs2': 'rr_xctcmsg_rs2',
            'passthrough': 'rr_xctcmsg_passthrough',
        })

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
        dut_xctcmsg_wb_data = PseudoSignal(self.dut, {
            'value': 'xctcmsg_wb_value',
            'passthrough': 'xctcmsg_wb_passthrough',
        })

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

class EchoingBusDriver(TBTask):
    network_interface_driver: NetworkInterfaceDriver
    
    def __init__(self, network_interface_driver: NetworkInterfaceDriver):
        super().__init__(use_kill=True)

        self.network_interface_driver = network_interface_driver
    
    @override
    async def _task_coroutine(self):
        async for message in self.network_interface_driver.get_sent():
            await self.network_interface_driver.receive(message)

class XctcmsgTB(AbstractTB):
    rr_stage: ValRdyProducer[RequestData]
    wb_stage: ValRdyConsumer[WritebackArbiterData]
    network_interface_driver: NetworkInterfaceDriver
    echoing_bus_driver: EchoingBusDriver
    
    def __init__(self, dut: SimHandleBase, *, with_echoing_bus_driver: bool=False):
        rr_stage_pseudo = PseudoSignal(dut, {
            'funct3': 'rr_xctcmsg_funct3',
            'rs1': 'rr_xctcmsg_rs1',
            'rs2': 'rr_xctcmsg_rs2',
            'passthrough': 'rr_xctcmsg_passthrough',
        })
        wb_stage_pseudo = PseudoSignal(dut, {
            'value': 'xctcmsg_wb_value',
            'passthrough': 'xctcmsg_wb_passthrough',
        })
        
        rr_stage_interface = ValRdyInterface(
            val=dut.rr_xctcmsg_valid,
            rdy=dut.xctcmsg_rr_ready,
            data=rr_stage_pseudo,
            producer_name='RR Stage',
        )
        wb_stage_interface = ValRdyInterface(
            val=dut.xctcmsg_wb_valid,
            rdy=dut.wb_xctcmsg_ready,
            data=wb_stage_pseudo,
            consumer_name='WB Stage',
        )
        
        match environ['XCTCMSG_NETWORK_IMPLEMENTATION']:
            case 'bus':
                network_interface_driver = BusInterfaceDriver(dut)
            case 'openpiton':
                network_interface_driver = OpenpitonInterfaceDriver(dut)
            case x:
                raise ValueError(f"Unknown network implementation: {x}")
        
        tasks = dict[str,TBTask](
            rr_stage=ValRdyProducer(rr_stage_interface, RequestData),
            wb_stage=ValRdyConsumer(wb_stage_interface, WritebackArbiterData),
            network_interface_driver=network_interface_driver,
        )
        
        if with_echoing_bus_driver:
            tasks['echoing_bus_driver'] = EchoingBusDriver(network_interface_driver)
        
        super().__init__(dut, tasks)
        
        dut.local_address.value = 0; # TODO: Driver for this?
    
    def no_writebacks(self) -> ContextManager:
        return self.wb_stage.disabled()
    
    def no_messages_out(self) -> ContextManager:
        return self.network_interface_driver.disable_sends()
    
    @property
    def wb_stage_queue_state(self) -> QueueState:
        return self.wb_stage.queue_state
    
    async def request(self, *data: RequestData):
        await self.rr_stage.enqueue_values(*data)
        
    async def get_writeback(self) -> WritebackArbiterData:
        return await self.wb_stage.dequeue_value()
    
    def get_writebacks(self, n: int=-1) -> AsyncGenerator[WritebackArbiterData]:
        return self.wb_stage.dequeue_values(n)
    
    async def send(self, *message: Message):
        await self.network_interface_driver.receive(*message)
    
    async def receive_single(self) -> Message:
        return await self.network_interface_driver.get_single_sent()
    
    def receive(self, n: int=-1) -> AsyncGenerator[Message]:
        return self.network_interface_driver.get_sent(n)

    async def poll_until_available(self, source: int, tag: int, source_mask: int, tag_mask: int, rd: int):
        request = RequestData.quick(RequestType.AVAIL, source | (tag << 32), source_mask | (tag_mask << 32), rd)
        again_writeback = WritebackArbiterData.quick(rd, 0)
        available_writeback = WritebackArbiterData.quick(rd, 1)
        
        await self.request(request)
        
        async for writeback in self.get_writebacks():
            if writeback == available_writeback:
                return
            
            assert writeback == again_writeback
            await self.request(request)

@cocotb.test
async def reset_state(dut):
    async with XctcmsgTB(dut) as tb:
        # Ready signal could be unasserted if a request type is not given
        dut.rr_xctcmsg_funct3.value = 0b000;
        await SimulationUpdate()
    
        assert dut.xctcmsg_rr_ready.value == 1
        assert dut.xctcmsg_wb_valid.value == 0
        
        if isinstance(tb.network_interface_driver, ValRdyNetworkInterfaceDriver):
            assert tb.network_interface_driver.send_port.interface.val.value == 0
            assert tb.network_interface_driver.recv_port.interface.rdy.value == 1

@cocotb.test
async def flush_test(dut):
    async with XctcmsgTB(dut) as tb:
        ## mailbox
        await tb.send(*([Message.quick(0, 0, 0)] * MESSAGE_BUFFER_SIZE))
        await tb.request(RequestData.quick(RequestType.RECV, 1, 0, 13))

        await RisingEdges(2 * MESSAGE_BUFFER_SIZE)

        assert tb.dut.mbox.request_valid.value == 1
        assert tb.dut.mbox.message_valid.value.binstr == '1' * MESSAGE_BUFFER_SIZE

        await flush()

        assert tb.dut.mbox.request_valid.value == 0
        assert tb.dut.mbox.message_valid.value.binstr == '1' * MESSAGE_BUFFER_SIZE

        # Cleanup messages left on buffers
        await tb.request(*([RequestData.quick(RequestType.RECV, 0, -1, 0)] * MESSAGE_BUFFER_SIZE))
        async for _ in tb.get_writebacks(MESSAGE_BUFFER_SIZE):
            pass

        ## postoffice
        with tb.no_writebacks():
            await tb.request(RequestData.quick(RequestType.SEND, 0, 0, 14))
    
            await RisingEdges(20)
    
            assert tb.dut.postoffice.writeback_valid.value == 1
    
            await flush()
    
            assert tb.dut.postoffice.writeback_valid.value == 0

        await RisingEdges(20)
        assert tb.wb_stage_queue_state == QueueState.EMPTY

        ## queues
        with tb.no_writebacks():
            await tb.request(
                RequestData.quick(RequestType.SEND, 0, 0, 15),
                RequestData.quick(RequestType.SEND, 0, 0, 16),
                RequestData.quick(RequestType.AVAIL, 0, 0, 17),
                RequestData.quick(RequestType.AVAIL, 0, 0, 18),
            )
    
            await RisingEdges(20)
    
            assert tb.dut.send_queue.empty.value == 0
            assert tb.dut.receive_queue.empty.value == 0
    
            await flush()
    
            assert tb.dut.send_queue.empty.value == 1
            assert tb.dut.receive_queue.empty.value == 1

        await RisingEdges(20)
        assert tb.wb_stage_queue_state == QueueState.EMPTY


@cocotb.test
async def receive_full_match_single(dut):
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
    
    async with XctcmsgTB(dut) as tb:
        await tb.send(message)
        await RisingEdges(2)
        await tb.request(*requests)
        
        writebacks = [x async for x in tb.get_writebacks(len(expected_writebacks))]
        assert writebacks == expected_writebacks

@cocotb.test
async def receive_full_match_stream(dut):
    STREAM_LENGTH = 64
    messages = [Message.quick(10, 42, x) for x in range(STREAM_LENGTH)]
    requests = [RequestData.quick(RequestType.RECV, 10 | (42 << 32), 0, 1)] * STREAM_LENGTH
    expected_writebacks = [WritebackArbiterData.quick(1, x) for x in range(STREAM_LENGTH)]

    async with XctcmsgTB(dut) as tb:
        await tb.send(*messages)
        await tb.request(*requests)

        writebacks = [x async for x in tb.get_writebacks(STREAM_LENGTH)]
        assert writebacks == expected_writebacks

@cocotb.test
async def send_single(dut):
    request = RequestData.quick(RequestType.SEND, 5, 10 | (42 << 32), 1)
    expected_writeback = WritebackArbiterData.quick(1, 1)
    expected_message = Message.quick(10, 42, 5)

    async with XctcmsgTB(dut) as tb:
        await tb.request(request)

        writeback = await tb.get_writeback()
        assert writeback == expected_writeback

        message = await tb.receive_single()
        assert message == expected_message

@cocotb.test
async def send_stream(dut):
    STREAM_LENGTH = 64
    requests = [RequestData.quick(RequestType.SEND, x, 10 | (42 << 32), 1) for x in range(STREAM_LENGTH)]
    expected_writebacks = [WritebackArbiterData.quick(1, 1) for _ in range(STREAM_LENGTH)]
    expected_messages = [Message.quick(10, 42, x) for x in range(STREAM_LENGTH)]

    async with XctcmsgTB(dut) as tb:
        await tb.request(*requests)

        writebacks = [x async for x in tb.get_writebacks(STREAM_LENGTH)]
        assert writebacks == expected_writebacks

        messages = [x async for x in tb.receive(STREAM_LENGTH)]
        assert messages == expected_messages

@cocotb.test
async def loopback_single(dut):
    requests = [
        RequestData.quick(RequestType.SEND, 42, (42 << 32) | 0, 1), # ctc.send x1, 42, id:0+tag:42
        RequestData.quick(RequestType.RECV, (42 << 32) | 0, 0, 2),  # ctc.recv x2, id:0+tag:42
    ]
    expected_writebacks = [
        WritebackArbiterData.quick(1, 1),
        WritebackArbiterData.quick(2, 42),
    ]
    
    async with XctcmsgTB(dut) as tb:
        await tb.request(*requests)

        writebacks = [x async for x in tb.get_writebacks(len(expected_writebacks))]
        assert writebacks == expected_writebacks

@cocotb.test
async def stream_loopback_spaced(dut):
    async with XctcmsgTB(dut) as tb:
        STREAM_LENGTH = 64
        send_requests = [RequestData.quick(RequestType.SEND, x, 0 | (42 << 32), 1) for x in range(STREAM_LENGTH)]
        expected_send_writeback = WritebackArbiterData.quick(1, 1)

        recv_request = RequestData.quick(RequestType.RECV, 0 | (42 << 32), 0, 3)
        expected_recv_writebacks = [WritebackArbiterData.quick(3, x) for x in range(STREAM_LENGTH)]
        
        final_avail_request = RequestData.quick(RequestType.AVAIL, 0 | (42 << 32), 0, 4)
        expected_final_avail_writeback = WritebackArbiterData.quick(4, 0)
        
        for i in range(STREAM_LENGTH):
            await tb.request(send_requests[i])
            send_writeback = await tb.get_writeback()
            assert send_writeback == expected_send_writeback
            
            await tb.poll_until_available(0, 42, 0, 0, 2)

            await tb.request(recv_request)
            recv_writeback = await tb.get_writeback()
            assert recv_writeback == expected_recv_writebacks[i]

            await tb.request(final_avail_request)
            polling_avail_writeback = await tb.get_writeback()
            assert polling_avail_writeback == expected_final_avail_writeback

@cocotb.test
async def stream_loopback_speed(dut):
    STREAM_LENGTH = 64
    send_requests = [RequestData.quick(RequestType.SEND, x, 0 | (42 << 32), 1) for x in range(STREAM_LENGTH)]
    recv_requests = [RequestData.quick(RequestType.RECV, 0 | (42 << 32), 0, 3) for _ in range(STREAM_LENGTH)]
    requests = itertools.chain(*zip(send_requests, recv_requests))
    expected_send_writeback = WritebackArbiterData.quick(1, 1)
    expected_recv_writebacks = [WritebackArbiterData.quick(3, x) for x in range(STREAM_LENGTH)]
    
    async with XctcmsgTB(dut) as tb:
        await tb.request(*requests)
        
        writebacks = [x async for x in tb.get_writebacks(2 * STREAM_LENGTH)]
        
        send_writebacks = [x for x in writebacks if x == expected_send_writeback]
        assert len(send_writebacks) == STREAM_LENGTH
        
        recv_writebacks = [x for x in writebacks if x in expected_recv_writebacks]
        assert all(map(lambda x: x in recv_writebacks, expected_recv_writebacks))

@cocotb.test
async def stream_echo_spaced(dut):
    async with XctcmsgTB(dut, with_echoing_bus_driver=True) as tb:
        STREAM_LENGTH = 64
        send_requests = [RequestData.quick(RequestType.SEND, x, 10 | (42 << 32), 1) for x in range(STREAM_LENGTH)]
        expected_send_writeback = WritebackArbiterData.quick(1, 1)

        recv_request = RequestData.quick(RequestType.RECV, 10 | (42 << 32), 0, 3)
        expected_recv_writebacks = [WritebackArbiterData.quick(3, x) for x in range(STREAM_LENGTH)]
        
        final_avail_request = RequestData.quick(RequestType.AVAIL, 10 | (42 << 32), 0, 4)
        expected_final_avail_writeback = WritebackArbiterData.quick(4, 0)
        
        for i in range(STREAM_LENGTH):
            await tb.request(send_requests[i])
            send_writeback = await tb.get_writeback()
            assert send_writeback == expected_send_writeback
            
            await tb.poll_until_available(10, 42, 0, 0, 2)

            await tb.request(recv_request)
            recv_writeback = await tb.get_writeback()
            assert recv_writeback == expected_recv_writebacks[i]

            await tb.request(final_avail_request)
            polling_avail_writeback = await tb.get_writeback()
            assert polling_avail_writeback == expected_final_avail_writeback

@cocotb.test
async def stream_echo_speed(dut):
    STREAM_LENGTH = 64
    send_requests = [RequestData.quick(RequestType.SEND, x, 10 | (42 << 32), 1) for x in range(STREAM_LENGTH)]
    recv_requests = [RequestData.quick(RequestType.RECV, 10 | (42 << 32), 0, 3) for _ in range(STREAM_LENGTH)]
    requests = itertools.chain(*zip(send_requests, recv_requests))
    expected_send_writeback = WritebackArbiterData.quick(1, 1)
    expected_recv_writebacks = [WritebackArbiterData.quick(3, x) for x in range(STREAM_LENGTH)]
    
    async with XctcmsgTB(dut, with_echoing_bus_driver=True) as tb:
        await tb.request(*requests)
        
        writebacks = [x async for x in tb.get_writebacks(2 * STREAM_LENGTH)]
        
        send_writebacks = [x for x in writebacks if x == expected_send_writeback]
        assert len(send_writebacks) == STREAM_LENGTH
        
        recv_writebacks = [x for x in writebacks if x in expected_recv_writebacks]
        assert all(map(lambda x: x in recv_writebacks, expected_recv_writebacks))

@cocotb.test
async def stream_mixed_spaced(dut):
    async with XctcmsgTB(dut, with_echoing_bus_driver=True) as tb:
        STREAM_LENGTH = 64
        send_requests = [RequestData.quick(RequestType.SEND, x, (x % 2) | (42 << 32), 1) for x in range(STREAM_LENGTH)]
        expected_send_writeback = WritebackArbiterData.quick(1, 1)

        recv_requests = [RequestData.quick(RequestType.RECV, (x % 2) | (42 << 32), 0, 3) for x in range(STREAM_LENGTH)]
        expected_recv_writebacks = [WritebackArbiterData.quick(3, x) for x in range(STREAM_LENGTH)]
        
        final_avail_requests = [RequestData.quick(RequestType.AVAIL, (x % 2) | (42 << 32), 0, 4) for x in range(STREAM_LENGTH)]
        expected_final_avail_writeback = WritebackArbiterData.quick(4, 0)
        
        for i in range(STREAM_LENGTH):
            await tb.request(send_requests[i])
            send_writeback = await tb.get_writeback()
            assert send_writeback == expected_send_writeback
            
            await tb.poll_until_available(i % 2, 42, 0, 0, 2)

            await tb.request(recv_requests[i])
            recv_writeback = await tb.get_writeback()
            assert recv_writeback == expected_recv_writebacks[i]

            await tb.request(final_avail_requests[i])
            polling_avail_writeback = await tb.get_writeback()
            assert polling_avail_writeback == expected_final_avail_writeback

@cocotb.test
async def stream_mixed_speed(dut):
    STREAM_LENGTH = 64
    send_requests = [RequestData.quick(RequestType.SEND, x, (x % 2) | (42 << 32), 1) for x in range(STREAM_LENGTH)]
    recv_requests = [RequestData.quick(RequestType.RECV, (x % 2) | (42 << 32), 0, 3) for x in range(STREAM_LENGTH)]
    requests = itertools.chain(*zip(send_requests, recv_requests))
    expected_send_writeback = WritebackArbiterData.quick(1, 1)
    expected_recv_writebacks = [WritebackArbiterData.quick(3, x) for x in range(STREAM_LENGTH)]

    async with XctcmsgTB(dut, with_echoing_bus_driver=True) as tb:
        await tb.request(*requests)
        
        writebacks = [x async for x in tb.get_writebacks(2 * STREAM_LENGTH)]
        
        send_writebacks = [x for x in writebacks if x == expected_send_writeback]
        assert len(send_writebacks) == STREAM_LENGTH
        
        recv_writebacks = [x for x in writebacks if x in expected_recv_writebacks]
        assert all(map(lambda x: x in recv_writebacks, expected_recv_writebacks))

@cocotb.test
async def avoid_send_stall(dut):
    AVAIL_REQUESTS = 5

    if environ['XCTCMSG_NETWORK_IMPLEMENTATION'] == 'bus':
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
    else:
        send_requests = [
            # This request will stall
            RequestData.quick(RequestType.SEND, 5, 10 | (42 << 32), 2),
        ]
        send_requests_expected_writebacks = [
            WritebackArbiterData.quick(2, 1),
        ]

    avail_requests = [RequestData.quick(RequestType.AVAIL, 10 | (42 << 32), 0, x+2) for x in range(AVAIL_REQUESTS)]
    avail_requests_expected_writebacks = [WritebackArbiterData.quick(x+2, 0) for x in range(AVAIL_REQUESTS)]
    
    requests = itertools.chain(send_requests, avail_requests)
    expected_writebacks = list(itertools.chain(
        send_requests_expected_writebacks[-2:-1],
        avail_requests_expected_writebacks,
        send_requests_expected_writebacks[-1:],
    ))
    
    async with XctcmsgTB(dut, with_echoing_bus_driver=True) as tb:
        with tb.no_messages_out():
            await tb.request(*requests)
            
            # Get all writebacks but the last one
            writebacks = [x async for x in tb.get_writebacks(len(expected_writebacks) - 1)]
            assert writebacks == expected_writebacks[:-1]

            await RisingEdgesHoldingAssertion(20, lambda: tb.wb_stage_queue_state == QueueState.EMPTY)

        writeback = await tb.get_writeback()
        assert writeback == expected_writebacks[-1]

@cocotb.test
async def avoid_receive_stall(dut):
    SEND_REQUESTS = 4
    
    # This request will stall
    receive_request = RequestData.quick(RequestType.RECV, 10 | ((SEND_REQUESTS - 1) << 32), 0, 1)
    receive_request_expected_writeback = WritebackArbiterData.quick(1, 5)
    send_requests = [RequestData.quick(0b000, 5, 10 | (x << 32), x+1) for x in range(SEND_REQUESTS)]
    send_requests_expected_writebacks = [WritebackArbiterData.quick(x+1, 1) for x in range(SEND_REQUESTS)]
    
    requests = [receive_request] + send_requests
    # The last send should unstall the receive (matching tag)
    expected_writebacks = send_requests_expected_writebacks + [receive_request_expected_writeback]

    async with XctcmsgTB(dut, with_echoing_bus_driver=True) as tb:
        await tb.request(*requests)
        
        writebacks = [x async for x in tb.get_writebacks(len(expected_writebacks))]
        assert writebacks == expected_writebacks
