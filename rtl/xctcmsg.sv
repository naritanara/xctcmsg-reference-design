`include "xctcmsg_defs.svh"

module xctcmsg #(
  parameter HARTID = 0,
  parameter MAX_HARTID = 64,
  parameter SEND_QUEUE_SIZE = 4,
  parameter RECEIVE_QUEUE_SIZE = 4,
  parameter MAILBOX_SIZE = 4
) (
  input clk,
  input rst_n,
  input flush,

  // RR-stage
  input  logic rr_xctcmsg_valid,
  output logic xctcmsg_rr_ready,
  input  logic [2:0] rr_xctcmsg_funct3,
  input  logic [63:0] rr_xctcmsg_rs1,
  input  logic [63:0] rr_xctcmsg_rs2,
  input  logic [4:0] rr_xctcmsg_rd,

  // Bus send
  output logic bus_val_o,
  input  logic bus_ack_i,
  output logic [31:0] bus_dst_o,
  output logic [31:0] bus_tag_o,
  output logic [63:0] bus_msg_o,

  // Bus receive
  output logic bus_rdy_o,
  input  logic bus_val_i,
  input  logic [31:0] bus_src_i,
  input  logic [31:0] bus_tag_i,
  input  logic [63:0] bus_msg_i,

  // WB-stage
  output logic xctcmsg_wb_valid,
  input  logic wb_xctcmsg_ready,
  output logic [4:0] xctcmsg_wb_register,
  output logic [63:0] xctcmsg_wb_value
);

  // RR stage <-> Request decoder
  logic rr_request_decoder_valid;
  logic request_decoder_rr_ready;
  request_data_t rr_request_decoder_data;

  // Request decoder <-> Send queue
  logic request_decoder_send_queue_valid;
  logic send_queue_request_decoder_ready;
  send_queue_data_t request_decoder_send_queue_data;

  // Send queue <-> Post office
  logic send_queue_postoffice_valid;
  logic postoffice_send_queue_ready;
  send_queue_data_t send_queue_postoffice_data;

  // Post office <-> Writeback arbiter
  logic postoffice_writeback_arbiter_valid;
  logic writeback_arbiter_postoffice_acknowledge;
  writeback_arbiter_data_t postoffice_writeback_arbiter_data;

  // Request decoder <-> Receive queue
  logic request_decoder_receive_queue_valid;
  logic receive_queue_request_decoder_ready;
  receive_queue_data_t request_decoder_receive_queue_data;

  // Receive queue <-> Mailbox
  logic receive_queue_mailbox_valid;
  logic mailbox_receive_queue_ready;
  receive_queue_data_t receive_queue_mailbox_data;

  // Mailbox <-> Writeback arbiter
  logic mailbox_writeback_arbiter_valid;
  logic writeback_arbiter_mailbox_acknowledge;
  writeback_arbiter_data_t mailbox_writeback_arbiter_data;

  // Post office <-> Commit safety unit
  commit_safety_request_t postoffice_csu_request;
  logic csu_postoffice_grant;

  // Mailbox <-> Commit safety unit
  commit_safety_request_t mailbox_csu_request;
  logic csu_mailbox_grant;

  // Post office <-> Communication interface
  logic postoffice_interface_valid;
  logic interface_postoffice_ready;
  interface_send_data_t postoffice_interface_data;

  // Mailbox <-> Communication interface
  logic interface_mailbox_valid;
  logic mailbox_interface_ready;
  interface_receive_data_t interface_mailbox_data;

  // Writeback arbiter <-> WB stage
  logic writeback_arbiter_wb_valid;
  logic wb_writeback_arbiter_ready;
  writeback_arbiter_data_t writeback_arbiter_wb_data;


  always_comb begin : rr_to_internal
    rr_request_decoder_valid = rr_xctcmsg_valid;
    xctcmsg_rr_ready = request_decoder_rr_ready;

    rr_request_decoder_data.funct3 = rr_xctcmsg_funct3;
    rr_request_decoder_data.rs1 = rr_xctcmsg_rs1;
    rr_request_decoder_data.rs2 = rr_xctcmsg_rs2;
    rr_request_decoder_data.rd = rr_xctcmsg_rd;
  end


  // Modules
  request_decoder request_decoder (.*);

  send_queue #(.SIZE(SEND_QUEUE_SIZE)) send_queue (.*);
  postoffice #(.HARTID(HARTID), .MAX_HARTID(MAX_HARTID)) postoffice (.*);

  receive_queue #(.SIZE(RECEIVE_QUEUE_SIZE)) receive_queue (.*);
  mbox #(.SIZE(MAILBOX_SIZE)) mbox (.*);

  commit_safety_unit commit_safety_unit (.*);

  bus_communication_interface bus_communication_interface (.*);

  writeback_arbiter writeback_arbiter (.*);


  always_comb begin : internal_to_wb
    xctcmsg_wb_valid = writeback_arbiter_wb_valid;
    wb_writeback_arbiter_ready = wb_xctcmsg_ready;

    xctcmsg_wb_register = writeback_arbiter_wb_data.register;
    xctcmsg_wb_value = writeback_arbiter_wb_data.value;
  end

endmodule
