`include "xctcmsg_defs.svh"

module postoffice #(
  parameter HARTID = 0,
  parameter MAX_HARTID = 64
) (
  input clk,
  input rst_n,
  input flush,

  // Send queue
  input  logic send_queue_postoffice_valid,
  output logic postoffice_send_queue_ready,
  input  send_queue_data_t send_queue_postoffice_data,

  // Writeback arbiter
  output logic postoffice_writeback_arbiter_valid,
  input  logic writeback_arbiter_postoffice_acknowledge,
  output writeback_arbiter_data_t postoffice_writeback_arbiter_data,

  // Communication interface
  output logic postoffice_interface_valid,
  input  logic interface_postoffice_ready,
  output interface_send_data_t postoffice_interface_data,

  // Commit safety unit
  output commit_safety_request_t postoffice_csu_request,
  input  logic csu_postoffice_grant
);

  // Writeback holding registers
  logic writeback_valid;
  writeback_arbiter_data_t writeback_data;

  // Writeback holding registers operations
  logic writeback_allocate_valid;
  logic writeback_deallocate_valid;

  // Writeback holding registers status
  logic writeback_allocatable;
  assign writeback_allocatable = !writeback_valid | writeback_deallocate_valid;

  // Destination validation signals
  logic destination_valid;
  logic destination_is_self;
  logic destination_is_out_of_range;

  always_ff @ (posedge clk, negedge rst_n) begin
    if (!rst_n | flush) begin
      writeback_valid <= 0;
    end else begin
      if (writeback_allocate_valid & writeback_allocatable) begin
        writeback_valid <= 1;
        writeback_data.register <= send_queue_postoffice_data.register;
        writeback_data.value <= destination_valid ? 1 : 0;
      end else if (writeback_deallocate_valid) begin
        writeback_valid <= 0;
      end
    end
  end

  always_comb begin : destination_validation
    destination_is_self = send_queue_postoffice_data.message.meta.address == HARTID;
    destination_is_out_of_range = send_queue_postoffice_data.message.meta.address > MAX_HARTID;
    destination_valid = !destination_is_self && !destination_is_out_of_range;
  end

  logic would_send;
  logic can_send;

  always_comb begin : interface_communication_predicates
    would_send = destination_valid;
    can_send = interface_postoffice_ready & csu_postoffice_grant;
  end

  always_comb begin : request_acceptance
    postoffice_send_queue_ready = (can_send | !would_send) & writeback_allocatable;
    writeback_allocate_valid = postoffice_send_queue_ready & send_queue_postoffice_valid;
  end

  always_comb begin : interface_communication
    postoffice_interface_valid = writeback_allocate_valid & destination_valid;
    postoffice_interface_data.message = send_queue_postoffice_data.message;
  end

  always_comb begin : writeback_holding_registers_popping
    postoffice_writeback_arbiter_valid = writeback_valid;
    postoffice_writeback_arbiter_data = writeback_data;

    writeback_deallocate_valid = writeback_arbiter_postoffice_acknowledge;
  end

endmodule
