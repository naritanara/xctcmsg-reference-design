import xctcmsg_pkg::*;

interface bus_interface ();
  // Bus send
  logic bus_val_o;
  logic bus_ack_i;
  message_addr_t bus_dst_o;
  message_tag_t bus_tag_o;
  message_data_t bus_msg_o;

  // Bus receive
  logic bus_rdy_o;
  logic bus_val_i;
  message_addr_t bus_src_i;
  message_tag_t bus_tag_i;
  message_data_t bus_msg_i;

  modport FU (
    output bus_val_o,
    input bus_ack_i,
    output bus_dst_o,
    output bus_tag_o,
    output bus_msg_o,
    output bus_rdy_o,
    input bus_val_i,
    input bus_src_i,
    input bus_tag_i,
    input bus_msg_i
  );

  modport NET (
    input bus_val_o,
    output bus_ack_i,
    input bus_dst_o,
    input bus_tag_o,
    input bus_msg_o,
    input bus_rdy_o,
    output bus_val_i,
    output bus_src_i,
    output bus_tag_i,
    output bus_msg_i
  );
endinterface
