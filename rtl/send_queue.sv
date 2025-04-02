import xctcmsg_pkg::*;

module send_queue #(
  parameter SIZE = 4
) (
  input  logic clk,
  input  logic rst_n,
  input  logic flush,

  // Request decoder
  input  logic request_decoder_send_queue_valid,
  output logic send_queue_request_decoder_ready,
  input  send_queue_data_t request_decoder_send_queue_data,

  // Post office
  output logic send_queue_postoffice_valid,
  input  logic postoffice_send_queue_ready,
  output send_queue_data_t send_queue_postoffice_data
);

  logic full;
  logic empty;

  always_comb begin : request_decoder_protocol
    send_queue_request_decoder_ready = ~full;
  end

  fifo_v3 #(
    .FALL_THROUGH(1),
    .DEPTH(SIZE),
    .dtype(send_queue_data_t)
  ) fifo_v3 (
    .clk_i(clk),
    .rst_ni(rst_n),
    .flush_i(flush),
    .testmode_i(0),
    .full_o(full),
    .empty_o(empty),
    .usage_o(),
    .data_i(request_decoder_send_queue_data),
    .push_i(~full & request_decoder_send_queue_valid),
    .data_o(send_queue_postoffice_data),
    .pop_i(~empty & postoffice_send_queue_ready)
  );

  always_comb begin : postoffice_protocol
    send_queue_postoffice_valid = ~empty;
  end

endmodule
