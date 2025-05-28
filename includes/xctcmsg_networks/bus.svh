`ifndef XCTCMSG_NETWORKS__BUS_SVH
`define XCTCMSG_NETWORKS__BUS_SVH

`define XCTCMSG_NETWORK_BUS_INTERFACE \
  // Bus send                   \
  output logic bus_val_o        \
, input  logic bus_ack_i        \
, output logic [31:0] bus_dst_o \
, output logic [31:0] bus_tag_o \
, output logic [63:0] bus_msg_o \
                                \
  // Bus receive                \
, output logic bus_rdy_o        \
, input  logic bus_val_i        \
, input  logic [31:0] bus_src_i \
, input  logic [31:0] bus_tag_i \
, input  logic [63:0] bus_msg_i

`define XCTCMSG_NETWORK_BUS_ADAPTER bus_adapter

`endif // XCTCMSG_NETWORKS__BUS_SVH
