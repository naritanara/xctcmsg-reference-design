from asyncio.tasks import wait
import cocotb
from cocotb.handle import SimHandleBase
from cocotb.clock import Clock
from cocotb.queue import Queue

from cocotb_utils import reset, flush, RisingEdge, RisingEdges, SimulationUpdate

class RRStageEmulator:
    dut: SimHandleBase
    request_queue: Queue

    def __init__(self, dut):
        self.dut = dut
        self.request_queue = Queue()

    async def request(self, funct3, rs1, rs2, rd):
        await self.request_queue.put([funct3, rs1, rs2, rd])

    async def start(self):
        while True:
            await RisingEdge()
            await SimulationUpdate()
            
            if self.dut.rr_xctcmsg_valid.value == 1 and self.dut.xctcmsg_rr_ready.value == 0:
                continue
            
            self.dut.rr_xctcmsg_valid.value = 0

            if (not self.request_queue.empty()):
                [funct3, rs1, rs2, rd] = self.request_queue.get_nowait()
                self.dut.rr_xctcmsg_valid.value = 1
                self.dut.rr_xctcmsg_funct3.value = funct3
                self.dut.rr_xctcmsg_rs1.value = rs1
                self.dut.rr_xctcmsg_rs2.value = rs2
                self.dut.rr_xctcmsg_rd.value = rd
                self.dut._log.info(f"Request in: [{funct3=}, {rs1=}, {rs2=}, {rd=}]")

class WBStageEmulator:
    dut: SimHandleBase
    allow_writeback = True
    writeback_queue: Queue

    def __init__(self, dut):
        self.dut = dut
        self.writeback_queue = Queue()

    async def get_writeback(self):
        return await self.writeback_queue.get()

    async def start(self):
        while True:
            await RisingEdge()
            await SimulationUpdate()

            self.dut.wb_xctcmsg_ready.value = self.allow_writeback
            if (not self.allow_writeback):
                continue

            await SimulationUpdate()

            if (self.dut.xctcmsg_wb_valid.value == 0 or self.writeback_queue.full()):
                continue

            register = int(self.dut.xctcmsg_wb_register.value)
            value = int(self.dut.xctcmsg_wb_value.value)
            self.writeback_queue.put_nowait([register, value])
            self.dut._log.info(f"Writeback out: [{register=}, {value=}]")

class BusEmulator:
    dut: SimHandleBase
    send_queue: Queue
    allow_receive = True
    receive_queue: Queue

    def __init__(self, dut):
        self.dut = dut
        self.send_queue = Queue()
        self.receive_queue = Queue()

    async def send(self, source, tag, message):
        await self.send_queue.put([source, tag, message])

    async def receive(self):
        return await self.receive_queue.get()

    async def start(self):
        while True:
            await RisingEdge()
            await SimulationUpdate()

            self.dut.bus_ack_i.value = 0
            if (self.allow_receive):
                if (self.dut.bus_val_o.value == 1):
                    if (not self.receive_queue.full()):
                        self.dut.bus_ack_i.value = 1
                        destination = int(self.dut.bus_dst_o.value)
                        tag = int(self.dut.bus_tag_o.value)
                        message = int(self.dut.bus_msg_o.value)
                        self.receive_queue.put_nowait([destination, tag, message])
                        self.dut._log.info(f"Bus received: [{destination=}, {tag=}, {message=}]")

            await SimulationUpdate()

            self.dut.bus_val_i.value = 0
            if (self.dut.bus_rdy_o.value == 1):
                if (not self.send_queue.empty()):
                    [source, tag, message] = self.send_queue.get_nowait()
                    self.dut.bus_val_i.value = 1
                    self.dut.bus_src_i.value = source
                    self.dut.bus_tag_i.value = tag
                    self.dut.bus_msg_i.value = message
                    self.dut._log.info(f"Bus sent: [{source=}, {tag=}, {message=}]")

async def setup(dut):
    rr_stage = RRStageEmulator(dut)
    wb_stage = WBStageEmulator(dut)
    bus = BusEmulator(dut)

    dut.local_address.value = 0;
    await cocotb.start(Clock(dut.clk, 10, 'ns').start())
    await reset()

    await cocotb.start(rr_stage.start())
    await cocotb.start(wb_stage.start())
    await cocotb.start(bus.start())

    return [rr_stage, wb_stage, bus]

async def finish_test(dut, rr_stage, wb_stage, bus):
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
        for _ in range(4):
            await bus.send(0, 0, 0)
        await rr_stage.request(0b001, 1, 0, 13)
        
        await RisingEdges(20)
        
        assert dut.mbox.request_valid == 1
        assert dut.mbox.message_valid.value == 0b1111
        
        await flush()
        
        assert dut.mbox.request_valid == 0
        assert dut.mbox.message_valid.value == 0b1111
        
        # Cleanup messages left on buffers
        for i in range(4):
            await rr_stage.request(0b001, 0, -1, 0)
        for i in range(4):
            await wb_stage.get_writeback()
        
        ## postoffice
        wb_stage.writeback_queue = Queue()
        wb_stage.allow_writeback = False
        await rr_stage.request(0b000, 0, 0, 14)
        
        await RisingEdges(20)
        
        assert dut.postoffice.writeback_valid == 1
        
        await flush()
        
        assert dut.postoffice.writeback_valid == 0
        wb_stage.allow_writeback = True
        await RisingEdges(20)
        assert wb_stage.writeback_queue.empty()
        
        ## queues
        wb_stage.writeback_queue = Queue()
        wb_stage.allow_writeback = False
        await rr_stage.request(0b000, 0, 0, 15)
        await rr_stage.request(0b000, 0, 0, 16)
        await rr_stage.request(0b010, 0, 0, 17)
        await rr_stage.request(0b010, 0, 0, 18)
        
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
        await bus.send(10, 42, 5)

        await RisingEdges(2)

        await rr_stage.request(0b010, 10 | (42 << 32), 0, 1)
        await rr_stage.request(0b001, 10 | (42 << 32), 0, 2)
        await rr_stage.request(0b010, 10 | (42 << 32), 0, 3)

        [register, value] = await wb_stage.get_writeback()
        assert register == 1
        assert value == 1

        [register, value] = await wb_stage.get_writeback()
        assert register == 2
        assert value == 5
        
        [register, value] = await wb_stage.get_writeback()
        assert register == 3
        assert value == 0   
    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def receive_full_match_stream(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        for i in range(64):
            await bus.send(10, 42, i)
            await rr_stage.request(0b001, 10 | (42 << 32), 0, 1)

        received_values = set()
        for i in range(64):
            [register, value] = await wb_stage.get_writeback()
            assert register == 1
            assert value not in received_values

            received_values.add(value)

        for i in range(64):
            assert i in received_values
        
    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def send_single(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        await rr_stage.request(0b000, 5, 10 | (42 << 32), 1)

        [register, value] = await wb_stage.get_writeback()
        assert register == 1
        assert value == 1

        [destination, tag, message] = await bus.receive()
        assert destination == 10
        assert tag == 42
        assert message == 5
    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def send_stream(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        for i in range(64):
            await rr_stage.request(0b000, i, 10 | (42 << 32), 1)

        for i in range(64):
            [register, value] = await wb_stage.get_writeback()
            assert register == 1
            assert value == 1

            [destination, tag, message] = await bus.receive()
            assert destination == 10
            assert tag == 42
            assert message == i
    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def loopback_single(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        await rr_stage.request(0b000, 42, (42 << 32) | 0, 1)
        await rr_stage.request(0b001, (42 << 32) | 0, 0, 2)
        
        # ctc.send x1, 42, id:0+tag:42
        [register, value] = await wb_stage.get_writeback()
        assert register == 1
        assert value == 1

        # ctc.recv x2, id:0+tag:42
        [register, value] = await wb_stage.get_writeback()
        assert register == 2
        assert value == 42
    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def stream_loopback_spaced(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        for i in range(64):
            await rr_stage.request(0b000, i, 0 | (42 << 32), 1)
            [register, value] = await wb_stage.get_writeback()
            assert register == 1
            assert value == 1

            available = False
            while not available:
                await rr_stage.request(0b010, 0 | (42 << 32), 0, 2)
                [register, value] = await wb_stage.get_writeback()
                assert register == 2
                available = value == 1

            await rr_stage.request(0b001, 0 | (42 << 32), 0, 3)
            [register, value] = await wb_stage.get_writeback()
            assert register == 3
            assert value == i

            await rr_stage.request(0b010, 0 | (42 << 32), 0, 4)
            [register, value] = await wb_stage.get_writeback()
            assert register == 4
            assert value == 0
    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def stream_loopback_speed(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        for i in range(64):
            await rr_stage.request(0b000, i, 0 | (42 << 32), 1)
            await rr_stage.request(0b001, 0 | (42 << 32), 0, 3)

        sent = 0
        received = set()
        for i in range(128):
            [register, value] = await wb_stage.get_writeback()
            assert register == 1 or register == 3

            if register == 1:
                assert value == 1
                sent += 1
            else:
                received.add(value)

        assert sent == 64

        for i in range(64):
            assert i in received

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

async def echo_server(bus):
    while True:
        [destination, tag, message] = await bus.receive()
        await bus.send(destination, tag, message)

@cocotb.test
async def stream_echo_spaced(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        await cocotb.start(echo_server(bus))

        for i in range(64):
            await rr_stage.request(0b000, i, 10 | (42 << 32), 1)
            [register, value] = await wb_stage.get_writeback()
            assert register == 1
            assert value == 1

            available = False
            while not available:
                await rr_stage.request(0b010, 10 | (42 << 32), 0, 2)
                [register, value] = await wb_stage.get_writeback()
                assert register == 2
                available = value == 1

            await rr_stage.request(0b001, 10 | (42 << 32), 0, 3)
            [register, value] = await wb_stage.get_writeback()
            assert register == 3
            assert value == i

            await rr_stage.request(0b010, 10 | (42 << 32), 0, 4)
            [register, value] = await wb_stage.get_writeback()
            assert register == 4
            assert value == 0
    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def stream_echo_speed(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        await cocotb.start(echo_server(bus))

        for i in range(64):
            await rr_stage.request(0b000, i, 10 | (42 << 32), 1)
            await rr_stage.request(0b001, 10 | (42 << 32), 0, 3)

        sent = 0
        received = set()
        for i in range(128):
            [register, value] = await wb_stage.get_writeback()
            assert register == 1 or register == 3

            if register == 1:
                assert value == 1
                sent += 1
            else:
                received.add(value)

        assert sent == 64

        for i in range(64):
            assert i in received

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def stream_mixed_spaced(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        await cocotb.start(echo_server(bus))
        
        for i in range(64):
            await rr_stage.request(0b000, i, (i % 2) | (42 << 32), 1)
            [register, value] = await wb_stage.get_writeback()
            assert register == 1
            assert value == 1

            available = False
            while not available:
                await rr_stage.request(0b010, (i % 2) | (42 << 32), 0, 2)
                [register, value] = await wb_stage.get_writeback()
                assert register == 2
                available = value == 1

            await rr_stage.request(0b001, (i % 2) | (42 << 32), 0, 3)
            [register, value] = await wb_stage.get_writeback()
            assert register == 3
            assert value == i

            await rr_stage.request(0b010, (i % 2) | (42 << 32), 0, 4)
            [register, value] = await wb_stage.get_writeback()
            assert register == 4
            assert value == 0
    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def stream_mixed_speed(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        await cocotb.start(echo_server(bus))
        
        for i in range(64):
            await rr_stage.request(0b000, i, (i % 2) | (42 << 32), 1)
            await rr_stage.request(0b001, (i % 2) | (42 << 32), 0, 3)

        sent = 0
        received = set()
        for i in range(128):
            [register, value] = await wb_stage.get_writeback()
            assert register == 1 or register == 3

            if register == 1:
                assert value == 1
                sent += 1
            else:
                received.add(value)

        assert sent == 64

        for i in range(64):
            assert i in received

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def avoid_send_stall(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        bus.allow_receive = False

        # This request gets to stay in the holding registers
        await rr_stage.request(0b000, 5, 10 | (42 << 32), 1)
        [register, value] = await wb_stage.get_writeback()
        assert register == 1
        assert value == 1

        # This request will stall
        await rr_stage.request(0b000, 5, 10 | (42 << 32), 2)

        for i in range(5):
            await rr_stage.request(0b010, 10 | (42 << 32), 0, i+2)

        for i in range(5):
            [register, value] = await wb_stage.get_writeback()
            assert register == i+2
            assert value == 0

        # Here we unstall
        bus.allow_receive = True
        [register, value] = await wb_stage.get_writeback()
        assert register == 2
        assert value == 1

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)

@cocotb.test
async def avoid_receive_stall(dut):
    [rr_stage, wb_stage, bus] = await setup(dut)
    try:
        await cocotb.start(echo_server(bus))

        # This request will stall
        await rr_stage.request(0b001, 10 | (3 << 32), 0, 1)

        for i in range(4):
            await rr_stage.request(0b000, 5, 10 | (i << 32), i+1)

        for i in range(4):
            [register, value] = await wb_stage.get_writeback()
            assert register == i+1
            assert value == 1

        # The last send should unstall the receive (matching tag)
        [register, value] = await wb_stage.get_writeback()
        assert register == 1
        assert value == 5

    finally:
        await finish_test(dut, rr_stage, wb_stage, bus)