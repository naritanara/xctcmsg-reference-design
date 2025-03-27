`include "xctcmsg_defs.svh"

module writeback_arbiter (
  input  logic clk,
  input  logic rst_n,
  input  logic flush,

  // Post office
  input  logic postoffice_writeback_arbiter_valid,
  output logic writeback_arbiter_postoffice_acknowledge,
  input  writeback_arbiter_data_t postoffice_writeback_arbiter_data,

  // Mailbox
  input  logic mailbox_writeback_arbiter_valid,
  output logic writeback_arbiter_mailbox_acknowledge,
  input  writeback_arbiter_data_t mailbox_writeback_arbiter_data,

  // WB-stage
  output logic writeback_arbiter_wb_valid,
  input  logic wb_writeback_arbiter_ready,
  output writeback_arbiter_data_t writeback_arbiter_wb_data
);

  rr_arb_tree #(
    .NumIn(2),
    .DataType(writeback_arbiter_data_t),
    .FairArb(0)
  ) writeback_arbiter (
    .clk_i(clk),
    .rst_ni(rst_n),
    .flush_i(flush),
    .rr_i(0),
    .req_i({postoffice_writeback_arbiter_valid, mailbox_writeback_arbiter_valid}),
    .gnt_o({writeback_arbiter_postoffice_acknowledge, writeback_arbiter_mailbox_acknowledge}),
    .data_i({postoffice_writeback_arbiter_data, mailbox_writeback_arbiter_data}),
    .req_o(writeback_arbiter_wb_valid),
    .gnt_i(wb_writeback_arbiter_ready),
    .data_o(writeback_arbiter_wb_data),
    .idx_o()
  );

endmodule
