import cocotb
from cocotb.triggers import Timer
from cocotb.types import LogicArray, Range

from cocotb_utils import SimulationUpdate

@cocotb.test
async def decode_send(dut):
    dut.rr_request_decoder_valid.value = 1
    dut.rr_request_decoder_data.funct3.value = 0
    dut.rr_request_decoder_data.rs1.value = 255
    dut.rr_request_decoder_data.rs2.value = (42 << 32) | 10
    dut.rr_request_decoder_data.passthrough.rd.value = 23

    dut.send_queue_request_decoder_ready.value = 0

    await SimulationUpdate()

    assert int(dut.request_decoder_rr_ready.value) == 0
    assert int(dut.request_decoder_send_queue_valid.value) == 1
    assert int(dut.request_decoder_send_queue_data.message.meta.address.value) == 10
    assert int(dut.request_decoder_send_queue_data.message.meta.tag.value) == 42
    assert int(dut.request_decoder_send_queue_data.message.data.value) == 255
    assert int(dut.request_decoder_send_queue_data.passthrough.rd.value) == 23

    assert int(dut.request_decoder_receive_queue_valid.value) == 0

    dut.send_queue_request_decoder_ready.value = 1
    await SimulationUpdate()
    assert int(dut.request_decoder_rr_ready.value) == 1

@cocotb.test
async def decode_recv(dut):
    dut.rr_request_decoder_valid.value = 1
    dut.rr_request_decoder_data.funct3.value = 1
    dut.rr_request_decoder_data.rs1.value = (42 << 32) | 10
    dut.rr_request_decoder_data.rs2.value = (1 << 32) | 2
    dut.rr_request_decoder_data.passthrough.rd.value = 23

    dut.receive_queue_request_decoder_ready.value = 0

    await SimulationUpdate()

    assert int(dut.request_decoder_rr_ready.value) == 0

    assert int(dut.request_decoder_send_queue_valid.value) == 0

    assert int(dut.request_decoder_receive_queue_valid.value) == 1
    assert int(dut.request_decoder_receive_queue_data.is_avail.value) == 0
    assert int(dut.request_decoder_receive_queue_data.meta.address.value) == 10
    assert int(dut.request_decoder_receive_queue_data.meta.tag.value) == 42
    assert str(dut.request_decoder_receive_queue_data.meta_mask.address.value) == "11111111111111111111111111111101"
    assert str(dut.request_decoder_receive_queue_data.meta_mask.tag.value) == "11111111111111111111111111111110"
    assert int(dut.request_decoder_receive_queue_data.passthrough.rd.value) == 23

    dut.receive_queue_request_decoder_ready.value = 1
    await SimulationUpdate()
    assert int(dut.request_decoder_rr_ready.value) == 1

@cocotb.test
async def decode_avail(dut):
    dut.rr_request_decoder_valid.value = 1
    dut.rr_request_decoder_data.funct3.value = 2
    dut.rr_request_decoder_data.rs1.value = (42 << 32) | 10
    dut.rr_request_decoder_data.rs2.value = (1 << 32) | 2
    dut.rr_request_decoder_data.passthrough.rd.value = 23

    dut.receive_queue_request_decoder_ready.value = 0

    await SimulationUpdate()

    assert int(dut.request_decoder_rr_ready.value) == 0

    assert int(dut.request_decoder_send_queue_valid.value) == 0

    assert int(dut.request_decoder_receive_queue_valid.value) == 1
    assert int(dut.request_decoder_receive_queue_data.is_avail.value) == 1
    assert int(dut.request_decoder_receive_queue_data.meta.address.value) == 10
    assert int(dut.request_decoder_receive_queue_data.meta.tag.value) == 42
    assert str(dut.request_decoder_receive_queue_data.meta_mask.address.value) == "11111111111111111111111111111101"
    assert str(dut.request_decoder_receive_queue_data.meta_mask.tag.value) == "11111111111111111111111111111110"
    assert int(dut.request_decoder_receive_queue_data.passthrough.rd.value) == 23

    dut.receive_queue_request_decoder_ready.value = 1
    await SimulationUpdate()
    assert int(dut.request_decoder_rr_ready.value) == 1
