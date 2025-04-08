import xctcmsg_pkg::*;

module receive_queue #(
  parameter SIZE = 4
) (
  input  logic clk,
  input  logic rst_n,
  input  logic flush,

  // Request decoder
  input  logic request_decoder_receive_queue_valid,
  output logic receive_queue_request_decoder_ready,
  input  receive_queue_data_t request_decoder_receive_queue_data,

  // Mailbox
  output logic receive_queue_mailbox_valid,
  input  logic mailbox_receive_queue_ready,
  output receive_queue_data_t receive_queue_mailbox_data
);

  logic full;
  logic empty;

  always_comb begin : request_decoder_protocol
    receive_queue_request_decoder_ready = ~full;
  end

  fifo_v3 #(
    .FALL_THROUGH(1),
    .DEPTH(SIZE),
    .dtype(receive_queue_data_t)
  ) fifo_v3 (
    .clk_i(clk),
    .rst_ni(rst_n),
    .flush_i(flush),
    .testmode_i(1'b0),
    .full_o(full),
    .empty_o(empty),
    .usage_o(),
    .data_i(request_decoder_receive_queue_data),
    .push_i(~full & request_decoder_receive_queue_valid),
    .data_o(receive_queue_mailbox_data),
    .pop_i(~empty & mailbox_receive_queue_ready)
  );

  always_comb begin : mailbox_protocol
    receive_queue_mailbox_valid = ~empty;
  end

endmodule
