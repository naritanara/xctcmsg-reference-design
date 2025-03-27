`include "xctcmsg_defs.svh"

module bus_communication_interface (
  input  logic clk,
  input  logic rst_n,
  input  logic flush,

  // Post office
  input  logic postoffice_interface_valid,
  output logic interface_postoffice_ready,
  input  interface_send_data_t postoffice_interface_data,

  // Mailbox
  output logic interface_mailbox_valid,
  input  logic mailbox_interface_ready,
  output interface_receive_data_t interface_mailbox_data,

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
  input  logic [63:0] bus_msg_i
);

  // Registers to hold the message until accepted by the bus
  logic holding_valid;
  interface_send_data_t holding_data;

  // Holding registers operations
  logic holding_allocate_valid;
  logic holding_deallocate_valid;

  // Message sending
  always_ff @ (posedge clk, negedge rst_n) begin : holding_registers
    if (!rst_n | flush) begin
      holding_valid <= 0;
      holding_data <= 0;
    end else begin
      if (holding_allocate_valid & (!holding_valid | holding_deallocate_valid)) begin
        holding_valid <= 1;
        holding_data <= postoffice_interface_data;
      end
      else if (holding_deallocate_valid) begin
        holding_valid <= 0;
      end
    end
  end

  always_comb begin : holding_requests
    holding_deallocate_valid = bus_ack_i;
    holding_allocate_valid = postoffice_interface_valid & interface_postoffice_ready;
  end

  always_comb begin : postoffice_protocol
    interface_postoffice_ready = !holding_valid | holding_deallocate_valid;
  end

  always_comb begin : bus_send
    bus_val_o = holding_valid;
    bus_dst_o = holding_data.message.meta.address;
    bus_tag_o = holding_data.message.meta.tag;
    bus_msg_o = holding_data.message.data;
  end

  // Message reception
  always_comb begin : bus_receive
    interface_mailbox_valid = bus_val_i;
    interface_mailbox_data.message.meta.address = bus_src_i;
    interface_mailbox_data.message.meta.tag = bus_tag_i;
    interface_mailbox_data.message.data = bus_msg_i;
  end

  always_comb begin : bus_receive_protocol
    bus_rdy_o = mailbox_interface_ready;
  end

endmodule;
