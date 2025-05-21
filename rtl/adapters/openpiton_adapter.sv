`ifdef NETWORK_IMPLEMENTATION_OPENPITON

import xctcmsg_pkg::*;
`include "define.tmp.h"

`define NETWORK_ADAPTER openpiton_adapter

`define NETWORK_INTERFACE                                  \
  // NoC send                                              \
  output logic                                noc_out_val  \
, input  logic                                noc_out_rdy  \
, output logic [`PITON_XCTCMSG_NOC_WIDTH-1:0] noc_out_data \
                                                           \
  // NoC receive                                           \
, input  logic                                noc_in_val   \
, output logic                                noc_in_rdy   \
, input  logic [`PITON_XCTCMSG_NOC_WIDTH-1:0] noc_in_data

module openpiton_adapter (
  input  message_addr_t local_address,

  // Loopback interceptor (send)
  input  logic loopback_interface_valid,
  output logic interface_loopback_ready,
  input  interface_send_data_t loopback_interface_data,

  // Loopback interceptor (receive)
  output logic interface_loopback_valid,
  input  logic loopback_interface_ready,
  output interface_receive_data_t interface_loopback_data,

  `NETWORK_INTERFACE
);

  logic [`XCTCMSG_MSG_HEADER_WIDTH-1:0] msg_out_header, msg_in_header;
  logic [`XCTCMSG_MSG_PAYLOAD_WIDTH-1:0] msg_out_payload, msg_in_payload;
  
  function automatic logic [`NOC_X_WIDTH-1:0] get_x_coordinate(input message_addr_t address);
    message_addr_t tmp = address % `PITON_X_TILES;
    return tmp[`NOC_X_WIDTH-1:0];
  endfunction
  
  function automatic logic [`NOC_Y_WIDTH-1:0] get_y_coordinate(input message_addr_t address);
    message_addr_t tmp = address / `PITON_X_TILES;
    return tmp[`NOC_Y_WIDTH-1:0];
  endfunction
  
  always_comb begin : encode_out_message
    msg_out_header[`XCTCMSG_MSG_RESERVED] = 0;
    msg_out_header[`XCTCMSG_MSG_LENGTH] = `XCTCMSG_MSG_PAYLOAD_LENGTH;
    msg_out_header[`XCTCMSG_MSG_DST_FBITS] = 0;
    msg_out_header[`XCTCMSG_MSG_DST_Y] = get_y_coordinate(loopback_interface_data.message.meta.address);
    msg_out_header[`XCTCMSG_MSG_DST_X] = get_x_coordinate(loopback_interface_data.message.meta.address);
    msg_out_header[`XCTCMSG_MSG_DST_CHIPID] = 0;
    
    msg_out_payload[`XCTCMSG_MSG_SRC] = local_address;
    msg_out_payload[`XCTCMSG_MSG_TAG] = loopback_interface_data.message.meta.tag;
    msg_out_payload[`XCTCMSG_MSG_DATA] = loopback_interface_data.message.data;
  end
  
  always_comb begin : valrdy_out_message
    noc_out_val = loopback_interface_valid;
    interface_loopback_ready = noc_out_rdy;
    noc_out_data = {msg_out_payload, msg_out_header};
  end
  
  always_comb begin : decode_in_message
    interface_loopback_data.message.meta.address = msg_in_payload[`XCTCMSG_MSG_SRC];
    interface_loopback_data.message.meta.tag = msg_in_payload[`XCTCMSG_MSG_TAG];
    interface_loopback_data.message.data = msg_in_payload[`XCTCMSG_MSG_DATA];
  end
  
  always_comb begin : valrdy_in_message
    interface_loopback_valid = noc_in_val;
    noc_in_rdy = loopback_interface_ready;
    msg_in_header = noc_in_data[`XCTCMSG_MSG_HEADER_WIDTH-1:0];
    msg_in_payload = noc_in_data[`PITON_XCTCMSG_NOC_WIDTH-1:`XCTCMSG_MSG_HEADER_WIDTH];
  end

endmodule

`endif